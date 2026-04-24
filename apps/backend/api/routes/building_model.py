# apps/backend/api/routes/building_model.py
"""API routes for BuildingModel resource."""
from __future__ import annotations

import uuid
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from api.deps import CurrentUserDep
from core.building_model.pipeline import GenerationInputs, generate_building_model
from core.feasibility.schemas import Brief
from core.plu.schemas import NumericRules
from db.models.building_models import BuildingModelRow
from db.models.projects import ProjectRow
from db.session import SessionDep
from schemas.building_model_api import BuildingModelCreate, BuildingModelOut, BuildingModelVersionsOut

router = APIRouter(prefix="/projects/{project_id}/building_model", tags=["building_model"])


def _to_out(row: BuildingModelRow) -> BuildingModelOut:
    return BuildingModelOut(
        id=row.id, project_id=row.project_id, version=row.version,
        model_json=row.model_json, conformite_check=row.conformite_check,
        generated_at=row.generated_at, source=row.source, dirty=row.dirty,
    )


@router.get("", response_model=BuildingModelOut)
async def get_current_building_model(
    project_id: UUID,
    session: SessionDep,
    response: Response,
) -> BuildingModelOut:
    # Read-only — public like GET /projects/{id} in v1 MVP. Auth is enforced
    # on mutating endpoints (generate, restore).
    # Force no-cache so UI always sees the latest version after edits/fixes.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    row = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No building model for this project")
    return _to_out(row)


@router.post("/generate", response_model=BuildingModelOut, status_code=status.HTTP_201_CREATED)
async def generate_endpoint(
    project_id: UUID,
    body: BuildingModelCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> BuildingModelOut:
    project = await session.get(ProjectRow, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch latest feasibility + PLU — MVP: use placeholder from project.brief
    brief_dict = project.brief or {}

    # For v1: hardcode simple parcelle geometry from project (real wiring in Sprint 2)
    # The brief should contain these, but for now we use fallbacks if missing.
    inputs = GenerationInputs(
        project_id=project_id,
        parcelle_geojson=brief_dict.get("parcelle_geojson",
            {"type": "Polygon", "coordinates": [[[0,0],[20,0],[20,18],[0,18],[0,0]]]}),
        parcelle_surface_m2=brief_dict.get("parcelle_surface_m2", 360.0),
        voirie_orientations=brief_dict.get("voirie_orientations", ["sud"]),
        north_angle_deg=0.0,
        plu_rules=NumericRules(
            emprise_max_pct=brief_dict.get("emprise_max_pct", 40.0),
            hauteur_max_m=brief_dict.get("hauteur_max_m", 18.0),
            pleine_terre_min_pct=30.0, retrait_voirie_m=None,
            retrait_limite_m=4.0, stationnement_pct=100.0,
            hauteur_max_niveaux=brief_dict.get("hauteur_max_niveaux", 5),
        ),
        zone_plu=brief_dict.get("zone_plu", "UA"),
        brief=Brief(
            destination=brief_dict.get("destination", "logement_collectif"),
            cible_nb_logements=brief_dict.get("cible_nb_logements", 12),
            cible_sdp_m2=brief_dict.get("cible_sdp_m2", 900),
            mix_typologique=brief_dict.get("mix_typologique", {"T2": 0.4, "T3": 0.4, "T4": 0.2}),
        ),
        footprint_recommande_geojson=brief_dict.get("footprint_recommande_geojson",
            {"type": "Polygon", "coordinates": [[[2,2],[16,2],[16,14],[2,14],[2,2]]]}),
        niveaux_recommandes=brief_dict.get("niveaux_recommandes", 4),
        hauteur_recommandee_m=brief_dict.get("hauteur_recommandee_m", 12.0),
        emprise_pct_recommandee=brief_dict.get("emprise_pct_recommandee", 40.0),
        style_architectural_preference=body.style_architectural_preference,
        facade_style_preference=body.facade_style_preference,
    )

    bm = await generate_building_model(inputs, session=session)

    # Persist
    next_version = ((await session.execute(
        select(BuildingModelRow.version)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none() or 0) + 1

    row = BuildingModelRow(
        project_id=project_id,
        version=next_version,
        model_json=bm.model_dump(mode="json"),
        conformite_check=bm.conformite_check.model_dump(mode="json") if bm.conformite_check else None,
        generated_by=current_user.id,
        source="auto",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_out(row)


@router.get("/versions", response_model=BuildingModelVersionsOut)
async def list_versions(
    project_id: UUID,
    session: SessionDep,
) -> BuildingModelVersionsOut:
    rows = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
    )).scalars().all()
    return BuildingModelVersionsOut(items=[_to_out(r) for r in rows])


@router.post("/restore/{version}", response_model=BuildingModelOut)
async def restore_version(
    project_id: UUID, version: int,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> BuildingModelOut:
    src = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id, BuildingModelRow.version == version)
    )).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="Version not found")

    next_version = ((await session.execute(
        select(BuildingModelRow.version)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none() or 0) + 1

    new_row = BuildingModelRow(
        project_id=project_id,
        version=next_version,
        model_json=src.model_json,
        conformite_check=src.conformite_check,
        generated_by=current_user.id,
        source="regen",
        parent_version_id=src.id,
    )
    session.add(new_row)
    await session.commit()
    await session.refresh(new_row)
    return _to_out(new_row)


class _RoomPatch(dict):
    pass


@router.patch("", response_model=BuildingModelOut)
async def patch_building_model(
    project_id: UUID,
    session: SessionDep,
    body: dict,
) -> BuildingModelOut:
    """Apply a manual delta to the current BM and save as a new version.

    Accepted edits (one apt at a time):
      - ``apt_id`` (required): ``"R+1.07"``
      - ``typologie``: ``"T3"`` — reclassifies the apt.
      - ``room_labels``: ``{ "slot_3_r_entree": "Hall", ... }`` — renames
        room labels (label_fr) by room id.
      - ``delete``: ``true`` — removes the apt from its floor.

    Returns the newly-created BM version (source="manual").
    """
    # Load the latest BM row
    src = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="No building model to patch")

    apt_id = body.get("apt_id")
    # apt_id is optional now — building-level edits (core, circulations)
    # can be sent without an apt_id.
    has_building_edit = bool(
        body.get("core") or body.get("circulations") or body.get("delete_circulations")
    )
    if not apt_id and not has_building_edit:
        raise HTTPException(
            status_code=400,
            detail="apt_id required (or send core/circulations for building-level edits)",
        )

    import copy as _copy
    model = _copy.deepcopy(src.model_json or {})

    changed = False
    delete = bool(body.get("delete"))
    new_typo = body.get("typologie")
    room_labels = body.get("room_labels") or {}
    walls_patch = {w["wall_id"]: w for w in (body.get("walls") or []) if w.get("wall_id")}
    openings_patch = {o["opening_id"]: o for o in (body.get("openings") or []) if o.get("opening_id")}
    rooms_patch = {r["room_id"]: r for r in (body.get("rooms") or []) if r.get("room_id")}
    delete_openings: set[str] = set(body.get("delete_openings") or [])
    delete_walls: set[str] = set(body.get("delete_walls") or [])
    add_openings: list[dict] = list(body.get("add_openings") or [])
    add_walls: list[dict] = list(body.get("add_walls") or [])
    # Building-level edits (not per-cellule)
    core_patch = body.get("core") or {}
    circulation_patch = {c["id"]: c for c in (body.get("circulations") or []) if c.get("id")}
    delete_circulations: set[str] = set(body.get("delete_circulations") or [])

    for niveau in model.get("niveaux", []):
        cells = niveau.get("cellules") or []
        if delete:
            before = len(cells)
            niveau["cellules"] = [c for c in cells if c.get("id") != apt_id]
            if len(niveau["cellules"]) != before:
                changed = True
            continue
        for cell in cells:
            if cell.get("id") != apt_id:
                continue
            if new_typo and new_typo != cell.get("typologie"):
                cell["typologie"] = new_typo
                changed = True
            if room_labels:
                for rm in cell.get("rooms", []):
                    new_label = room_labels.get(rm.get("id"))
                    if new_label is not None and new_label != rm.get("label_fr"):
                        rm["label_fr"] = new_label
                        changed = True
            # Geometry patches (drag-and-drop edits from the canvas editor)
            if delete_openings:
                before = len(cell.get("openings", []))
                cell["openings"] = [op for op in cell.get("openings", []) if op.get("id") not in delete_openings]
                if len(cell["openings"]) != before:
                    changed = True
            if delete_walls:
                before = len(cell.get("walls", []))
                cell["walls"] = [w for w in cell.get("walls", []) if w.get("id") not in delete_walls]
                if len(cell["walls"]) != before:
                    changed = True
                # Also drop any opening referencing a deleted wall
                cell["openings"] = [op for op in cell.get("openings", []) if op.get("wall_id") not in delete_walls]
            if walls_patch:
                for w in cell.get("walls", []):
                    delta = walls_patch.get(w.get("id"))
                    if delta and delta.get("geometry"):
                        w["geometry"] = delta["geometry"]
                        changed = True
            if openings_patch:
                for op in cell.get("openings", []):
                    delta = openings_patch.get(op.get("id"))
                    if delta is None:
                        continue
                    if "position_along_wall_cm" in delta:
                        op["position_along_wall_cm"] = int(delta["position_along_wall_cm"])
                        changed = True
                    if "wall_id" in delta and delta["wall_id"]:
                        op["wall_id"] = delta["wall_id"]
                        changed = True
            if rooms_patch:
                for rm in cell.get("rooms", []):
                    delta = rooms_patch.get(rm.get("id"))
                    if delta and delta.get("polygon_xy"):
                        rm["polygon_xy"] = delta["polygon_xy"]
                        # Recompute surface from polygon (shoelace)
                        pts = delta["polygon_xy"]
                        area = 0.0
                        n = len(pts)
                        for i in range(n):
                            x1, y1 = pts[i]
                            x2, y2 = pts[(i + 1) % n]
                            area += x1 * y2 - x2 * y1
                        rm["surface_m2"] = abs(area) / 2.0
                        changed = True
            if add_walls:
                existing_wall_ids = {w.get("id") for w in cell.get("walls", [])}
                counter = sum(1 for i in existing_wall_ids if i and "w_user_" in i)
                for new_w in add_walls:
                    if not new_w.get("geometry"):
                        continue
                    counter += 1
                    new_id = f"{apt_id}_w_user_{counter:02d}"
                    while new_id in existing_wall_ids:
                        counter += 1
                        new_id = f"{apt_id}_w_user_{counter:02d}"
                    wtype = new_w.get("type", "cloison_70")
                    thickness = int(new_w.get("thickness_cm", 10 if wtype != "porteur" else 20))
                    cell.setdefault("walls", []).append({
                        "id": new_id,
                        "type": wtype,
                        "thickness_cm": thickness,
                        "geometry": new_w["geometry"],
                        "hauteur_cm": int(new_w.get("hauteur_cm", 260)),
                        "materiau": new_w.get("materiau", "placo" if wtype != "porteur" else "beton_banche"),
                    })
                    existing_wall_ids.add(new_id)
                    changed = True
            if add_openings:
                # Generate ids like {apt}_op_user_{n} starting after existing
                existing_ids = {op.get("id") for op in cell.get("openings", [])}
                counter = sum(1 for i in existing_ids if i and "op_user_" in i)
                for new_op in add_openings:
                    if not new_op.get("wall_id") or not new_op.get("type"):
                        continue
                    counter += 1
                    new_id = f"{apt_id}_op_user_{counter:02d}"
                    while new_id in existing_ids:
                        counter += 1
                        new_id = f"{apt_id}_op_user_{counter:02d}"
                    typ = new_op["type"]
                    if typ == "fenetre":
                        w, h, allege = 140, 200, 95
                    elif typ == "porte_fenetre":
                        w, h, allege = 240, 220, None
                    elif typ == "porte_interieure":
                        w, h, allege = 83, 210, None
                    else:
                        w, h, allege = int(new_op.get("width_cm", 93)), int(new_op.get("height_cm", 210)), None
                    cell.setdefault("openings", []).append({
                        "id": new_id,
                        "type": typ,
                        "wall_id": new_op["wall_id"],
                        "position_along_wall_cm": int(new_op.get("position_along_wall_cm", 100)),
                        "width_cm": int(new_op.get("width_cm", w)),
                        "height_cm": int(new_op.get("height_cm", h)),
                        "allege_cm": allege,
                        "swing": new_op.get("swing") or ("interior_right" if typ.startswith("porte") else None),
                        "vitrage": None,
                        "has_vitrage": False,
                        "type_menuiserie": None,
                    })
                    existing_ids.add(new_id)
                    changed = True

    # ─── Building-level edits (core + circulations, not tied to one apt) ───
    if core_patch:
        core_obj = model.get("core") or {}
        if "position_xy" in core_patch:
            core_obj["position_xy"] = core_patch["position_xy"]
            changed = True
        if "surface_m2" in core_patch:
            core_obj["surface_m2"] = float(core_patch["surface_m2"])
            changed = True
        if "polygon_xy" in core_patch:
            core_obj["polygon_xy"] = core_patch["polygon_xy"]
            changed = True
        # Per-element overrides: escalier / ascenseur / palier can each be
        # repositioned independently. Stored as {"position_xy": [x,y],
        # "size_m": [w,h]} on the existing nested object.
        for key in ("escalier", "ascenseur", "palier"):
            if key in core_patch:
                sub = core_obj.get(key) or {}
                if isinstance(core_patch[key], dict):
                    # `removed: true` hides the sub-element from render without
                    # deleting its stored geometry (toggle-friendly).
                    if "removed" in core_patch[key]:
                        sub["removed"] = bool(core_patch[key]["removed"])
                        changed = True
                    for k2 in ("position_xy", "size_m", "polygon_xy", "hidden_sides"):
                        if k2 in core_patch[key]:
                            sub[k2] = core_patch[key][k2]
                            changed = True
                    core_obj[key] = sub
        model["core"] = core_obj

    if circulation_patch or delete_circulations:
        for niveau in model.get("niveaux", []):
            circs = niveau.get("circulations_communes") or []
            if delete_circulations:
                before = len(circs)
                circs = [c for c in circs if c.get("id") not in delete_circulations]
                if len(circs) != before:
                    changed = True
            for circ in circs:
                delta = circulation_patch.get(circ.get("id"))
                if not delta:
                    continue
                if delta.get("polygon_xy"):
                    circ["polygon_xy"] = delta["polygon_xy"]
                    pts = delta["polygon_xy"]
                    area = 0.0
                    n = len(pts)
                    for i in range(n):
                        x1, y1 = pts[i]
                        x2, y2 = pts[(i + 1) % n]
                        area += x1 * y2 - x2 * y1
                    circ["surface_m2"] = abs(area) / 2.0
                    changed = True
                if "hidden_edges" in delta:
                    # List of edge indices (int) whose stroke should not
                    # render (lets the user remove a face of the couloir
                    # without changing its walkable geometry).
                    circ["hidden_edges"] = list(delta["hidden_edges"])
                    changed = True
            niveau["circulations_communes"] = circs

    if not changed:
        raise HTTPException(status_code=400, detail="No change applied (check apt_id + fields)")

    # In-place update on the latest row — avoid cluttering the DB with one
    # new version per edit. Keeps a single project = single building_model
    # row, matching the user's mental model.
    src.model_json = model
    await session.commit()
    await session.refresh(src)
    return _to_out(src)
