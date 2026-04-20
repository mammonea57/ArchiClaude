"""Projects API routes — CRUD and feasibility analysis trigger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from api.deps import CurrentUserDep
from db.models.project_status_history import ProjectStatusHistoryRow
from db.models.projects import ProjectRow
from db.session import SessionDep
from schemas.project import (
    AnalyzeJobResponse,
    AnalyzeStatusResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectStatusChange,
    ProjectStatusHistoryItem,
    ProjectStatusHistoryResponse,
    ProjectStatusResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])

# Placeholder user ID for v1 (auth integration deferred)
_PLACEHOLDER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------
# PLU + SRU lookup tables. Designed to grow per-commune; every commune
# that isn't in the table gets a conservative NATIONAL default rather
# than a fabricated 20×18 m rectangle. The keys are normalised lowercase
# commune names (as returned by BAN).
# ---------------------------------------------------------------------
_DEFAULT_PLU_IDF: dict[str, dict] = {
    # Per-commune overrides. Add progressively as they're surveyed.
    "nogent-sur-marne": {
        "emprise_max_pct": 50.0,
        "hauteur_max_m": 18.0,
        "hauteur_max_niveaux": 6,
        "pleine_terre_min_pct": 30.0,
        "retrait_limite_m": 4.0,
        "stationnement_par_logement": 1.0,
        "zone": "UA",
    },
}

_DEFAULT_PLU_NATIONAL: dict = {
    "emprise_max_pct": 40.0,
    "hauteur_max_m": 15.0,
    "hauteur_max_niveaux": 5,
    "pleine_terre_min_pct": 30.0,
    "retrait_limite_m": 4.0,
    "stationnement_par_logement": 1.0,
    "zone": "UA",
}

# Communes soumises à la SRU (loi 2013). Table à enrichir. Code INSEE key
# lets us lookup reliably via the geocoder's ``citycode`` output.
_SRU_COMMUNES_APPLIQUEES: set[str] = {
    "94052",  # Nogent-sur-Marne
    "94041",  # Fontenay-sous-Bois
    "94046",  # Maisons-Alfort
    # La liste officielle doit être synchronisée avec core.compliance.lls_sru ;
    # à terme, consommer la table SRU via core/sources/insee_sru.
}


def _normalise_commune(name: str | None) -> str:
    return (name or "").strip().lower().replace("'", "-").replace(" ", "-")


def _default_plu_rules_for_commune(commune_name: str | None, postcode: str | None):
    """Return NumericRules for the commune with safe national fallback."""
    from core.plu.schemas import NumericRules

    key = _normalise_commune(commune_name)
    raw = _DEFAULT_PLU_IDF.get(key, _DEFAULT_PLU_NATIONAL)
    return NumericRules(
        emprise_max_pct=raw.get("emprise_max_pct"),
        hauteur_max_m=raw.get("hauteur_max_m"),
        hauteur_max_niveaux=raw.get("hauteur_max_niveaux"),
        pleine_terre_min_pct=raw.get("pleine_terre_min_pct"),
        retrait_voirie_m=raw.get("retrait_voirie_m"),
        retrait_limite_m=raw.get("retrait_limite_m"),
        stationnement_par_logement=raw.get("stationnement_par_logement"),
    )


def _sru_statut_for_commune(citycode: str | None) -> str:
    """Return "applicable" / "non_soumise" — default non_soumise."""
    if citycode and citycode in _SRU_COMMUNES_APPLIQUEES:
        return "applicable"
    return "non_soumise"


@router.post("", status_code=201, response_model=ProjectOut)
async def create_project(
    body: ProjectCreate,
    session: SessionDep,
) -> ProjectOut:
    """Create a new feasibility project.

    Returns the created project id, name, and status.
    """
    row = ProjectRow(
        id=uuid.uuid4(),
        user_id=_PLACEHOLDER_USER_ID,
        name=body.name,
        brief=body.brief,
        status="draft",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ProjectOut(id=str(row.id), name=row.name, status=row.status)


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    session: SessionDep,
) -> list[ProjectOut]:
    """List all projects (v1: unscoped, returns all projects)."""
    result = await session.execute(select(ProjectRow).order_by(ProjectRow.created_at.desc()))
    rows = result.scalars().all()
    return [ProjectOut(id=str(r.id), name=r.name, status=r.status) for r in rows]


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str,
    session: SessionDep,
) -> ProjectDetail:
    """Get a project by ID, including the brief."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None

    result = await session.execute(select(ProjectRow).where(ProjectRow.id == pid))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectDetail(
        id=str(row.id),
        name=row.name,
        brief=row.brief,
        status=row.status,
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    session: SessionDep,
) -> Response:
    """Permanently delete a project and all its related rows.

    FKs on dependent tables (building_models, pcmi_dossiers, pcmi6_renders,
    project_status_history, project_versions) use ``ondelete="CASCADE"``
    so deleting the parent row cascades automatically.
    """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    project = await session.get(ProjectRow, pid)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(project)
    await session.commit()
    return Response(status_code=204)


@router.post("/{project_id}/analyze", status_code=202, response_model=AnalyzeJobResponse)
async def analyze_project(
    project_id: str,
    session: SessionDep,
) -> AnalyzeJobResponse:
    """Trigger feasibility analysis for a project.

    Real pipeline (no hardcoded fallbacks):
      1. Geocode the project's address (BAN API).
      2. Fetch the cadastral parcel at that point (IGN API Carto).
      3. Load default PLU numeric rules for the commune (hardcoded
         per-commune table for now, until the PLU RAG is wired).
      4. Run ``run_feasibility`` to compute the recommended footprint,
         number of floors, SDP, number of apartments, and compliance.
      5. Feed those REAL values to ``generate_building_model`` so the
         resulting BM matches the parcel + regulation, not a default
         20×18 m rectangle.

    Any step can fail (address not found, parcel not found, PLU
    unavailable) — the error is surfaced to the user with a 422.
    """
    if not project_id:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None

    project = await session.get(ProjectRow, pid)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Defer heavy imports so this route stays cheap to import at startup.
    from shapely.geometry import mapping, shape as shapely_shape
    from shapely.affinity import translate

    from core.analysis.validation import (
        ValidationError,
        run_checks_or_raise,
        validate_building_model,
        validate_cadastre,
        validate_cross_consistency,
        validate_feasibility,
        validate_geocoding,
        validate_plu,
    )
    from core.building_model.pipeline import (
        GenerationInputs,
        generate_building_model,
    )
    from core.building_model.schemas import CelluleType
    from core.feasibility.engine import run_feasibility
    from core.feasibility.schemas import Brief
    from core.geo.surface import _reproject, polygon_area_m2
    from core.sources.ban import geocode
    from core.sources.cadastre import fetch_parcelle_at_point
    from db.models.building_models import BuildingModelRow

    brief_dict = project.brief or {}

    def _fail_422(step: str, message: str):
        raise HTTPException(
            status_code=422,
            detail={"step": step, "message": message},
        )

    # --- Step 1: geocode the project address + validate ---------------------
    address = project.name
    try:
        results = await geocode(address, limit=3)
    except Exception as exc:  # noqa: BLE001
        _fail_422("geocoding.fetch", f"BAN geocoding failed: {exc}")
    if not results:
        _fail_422(
            "geocoding.no_result",
            f"Adresse introuvable via BAN : « {address} ». "
            "Vérifie le nom du projet — il doit être une adresse postale complète.",
        )
    geo = results[0]
    try:
        run_checks_or_raise("Geocoding", validate_geocoding(
            label=geo.label, score=geo.score, lat=geo.lat, lng=geo.lng,
            postcode=geo.postcode, citycode=geo.citycode,
        ))
    except ValidationError as ve:
        _fail_422(ve.step, ve.message)

    # --- Step 2: fetch the cadastral parcel + validate ----------------------
    # BAN typically returns a point on the street — not always inside the
    # parcel. Try the geocoded point first, then progressively offset 5, 10,
    # 15 m in the 4 cardinals, then the diagonals. ≈ 1 deg lat ≈ 111 km so
    # 5 m ≈ 4.5e-5 deg; we use ±6e-5 as our first offset (~7 m).
    offsets_deg: list[tuple[float, float]] = [
        (0.0, 0.0),
        (6e-5, 0.0), (-6e-5, 0.0), (0.0, 6e-5), (0.0, -6e-5),
        (1.2e-4, 0.0), (-1.2e-4, 0.0), (0.0, 1.2e-4), (0.0, -1.2e-4),
        (6e-5, 6e-5), (-6e-5, 6e-5), (6e-5, -6e-5), (-6e-5, -6e-5),
        (1.8e-4, 0.0), (-1.8e-4, 0.0), (0.0, 1.8e-4), (0.0, -1.8e-4),
    ]
    parcelle = None
    tried_points: list[tuple[float, float]] = []
    for dlat, dlng in offsets_deg:
        try_lat = geo.lat + dlat
        try_lng = geo.lng + dlng
        tried_points.append((try_lat, try_lng))
        try:
            parcelle = await fetch_parcelle_at_point(lat=try_lat, lng=try_lng)
        except Exception as exc:  # noqa: BLE001
            _fail_422("cadastre.fetch", f"Cadastre IGN fetch failed: {exc}")
        if parcelle is not None and parcelle.geometry:
            break
    if parcelle is None:
        _fail_422(
            "cadastre.no_parcel",
            f"Aucune parcelle cadastrale trouvée à proximité de "
            f"({geo.lat:.5f}, {geo.lng:.5f}) pour « {geo.label} » "
            f"(essayé {len(tried_points)} points dans un rayon de ~20 m).",
        )
    terrain_geojson = parcelle.geometry
    computed_area = polygon_area_m2(shapely_shape(terrain_geojson))
    try:
        run_checks_or_raise("Cadastre", validate_cadastre(
            geometry=terrain_geojson,
            contenance_m2=parcelle.contenance_m2,
            computed_area_m2=computed_area,
        ))
    except ValidationError as ve:
        _fail_422(ve.step, ve.message)
    terrain_surface_m2 = float(parcelle.contenance_m2 or computed_area)

    # --- Step 3: PLU rules per commune + validate ---------------------------
    plu_rules = _default_plu_rules_for_commune(geo.city, geo.postcode)
    commune_sru = _sru_statut_for_commune(geo.citycode)
    try:
        run_checks_or_raise("PLU", validate_plu(
            emprise_max_pct=plu_rules.emprise_max_pct,
            hauteur_max_m=plu_rules.hauteur_max_m,
            hauteur_max_niveaux=plu_rules.hauteur_max_niveaux,
        ))
    except ValidationError as ve:
        _fail_422(ve.step, ve.message)

    # --- Step 4: run_feasibility + validate ---------------------------------
    mix_raw = brief_dict.get("mix_typologique") or {"T2": 0.25, "T3": 0.35, "T4": 0.25, "T5": 0.15}
    brief_obj = Brief(
        destination=brief_dict.get("destination", "logement_collectif"),
        cible_nb_logements=brief_dict.get("cible_nb_logements"),
        cible_sdp_m2=brief_dict.get("cible_sdp_m2"),
        mix_typologique=mix_raw,
    )
    try:
        feas = run_feasibility(
            terrain_geojson=terrain_geojson,
            numeric_rules=plu_rules,
            brief=brief_obj,
            commune_sru_statut=commune_sru,
        )
    except Exception as exc:  # noqa: BLE001
        _fail_422("feasibility.engine", f"Feasibility engine failed: {exc}")
    try:
        run_checks_or_raise("Feasibility", validate_feasibility(
            sdp_max_m2=feas.sdp_max_m2,
            nb_niveaux=feas.nb_niveaux,
            nb_logements_max=feas.nb_logements_max,
            surface_emprise_m2=feas.surface_emprise_m2,
            footprint_geojson=feas.footprint_geojson,
        ))
    except ValidationError as ve:
        _fail_422(ve.step, ve.message)

    # --- Step 5: reproject to Lambert-93 + generate BM ----------------------
    footprint_geojson = feas.footprint_geojson or terrain_geojson
    try:
        fp_l93_raw = _reproject(shapely_shape(footprint_geojson), "EPSG:4326", "EPSG:2154")
        terrain_l93_raw = _reproject(shapely_shape(terrain_geojson), "EPSG:4326", "EPSG:2154")
        # The BM solver expects a single Polygon (not MultiPolygon). If the
        # reprojection / PLU carving produced multi-parts, keep only the
        # largest connected component so the solver has a clean footprint.
        fp_l93 = (
            max(fp_l93_raw.geoms, key=lambda g: g.area)
            if fp_l93_raw.geom_type == "MultiPolygon" else fp_l93_raw
        )
        terrain_l93 = (
            max(terrain_l93_raw.geoms, key=lambda g: g.area)
            if terrain_l93_raw.geom_type == "MultiPolygon" else terrain_l93_raw
        )
        minx, miny, _, _ = terrain_l93.bounds
        fp_shift = translate(fp_l93, xoff=-minx, yoff=-miny)
        terrain_shift = translate(terrain_l93, xoff=-minx, yoff=-miny)
        footprint_normalised = mapping(fp_shift)
        parcelle_normalised = mapping(terrain_shift)
    except Exception as exc:  # noqa: BLE001
        _fail_422("projection.l93", f"Projection WGS84→L93 failed: {exc}")

    voirie = ["sud"]
    emprise_pct_real = (
        100.0 * feas.surface_emprise_m2 / feas.surface_terrain_m2
        if feas.surface_terrain_m2 > 0 else plu_rules.emprise_max_pct or 50.0
    )
    inputs = GenerationInputs(
        project_id=pid,
        parcelle_geojson=parcelle_normalised,
        parcelle_surface_m2=feas.surface_terrain_m2,
        voirie_orientations=voirie,
        north_angle_deg=0.0,
        plu_rules=plu_rules,
        zone_plu=brief_dict.get("zone_plu", "UA"),
        brief=brief_obj,
        footprint_recommande_geojson=footprint_normalised,
        niveaux_recommandes=feas.nb_niveaux or 4,
        hauteur_recommandee_m=feas.hauteur_retenue_m or 12.0,
        emprise_pct_recommandee=emprise_pct_real,
    )
    try:
        bm = await generate_building_model(inputs, session=session)
    except Exception as exc:  # noqa: BLE001
        _fail_422("bm.generation", f"BM generation failed: {exc}")
    try:
        run_checks_or_raise("BuildingModel", validate_building_model(bm))
    except ValidationError as ve:
        _fail_422(ve.step, ve.message)

    # --- Step 6: cross-consistency checks -----------------------------------
    bm_apts = [
        c for niv in bm.niveaux if niv.index >= 0
        for c in niv.cellules if c.type == CelluleType.LOGEMENT
    ]
    bm_sdp = sum(n.surface_plancher_m2 for n in bm.niveaux if n.index >= 0)
    try:
        run_checks_or_raise("CrossConsistency", validate_cross_consistency(
            bm_sdp_m2=bm_sdp,
            feas_sdp_m2=feas.sdp_max_m2,
            bm_nb_apts=len(bm_apts),
            feas_nb_logements=feas.nb_logements_max,
            bm_emprise_m2=bm.envelope.emprise_m2,
            plu_emprise_max_pct=plu_rules.emprise_max_pct,
            parcelle_m2=feas.surface_terrain_m2,
        ))
    except ValidationError as ve:
        _fail_422(ve.step, ve.message)

    # Persist a new BM version and flip project status.
    next_version = ((
        await session.execute(
            select(BuildingModelRow.version)
            .where(BuildingModelRow.project_id == pid)
            .order_by(BuildingModelRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or 0) + 1
    bm_row = BuildingModelRow(
        project_id=pid,
        version=next_version,
        model_json=bm.model_dump(mode="json"),
        conformite_check=(
            bm.conformite_check.model_dump(mode="json")
            if bm.conformite_check
            else None
        ),
        source="auto",
    )
    session.add(bm_row)
    project.status = "analyzed"
    project.updated_at = datetime.now(UTC)
    # Record the geocoded / cadastral findings back into the brief so the
    # bilan and other routes can reuse them without re-fetching.
    project.brief = {
        **brief_dict,
        "address_resolved": geo.label,
        "commune": geo.city,
        "codeinsee": geo.citycode,
        "postcode": geo.postcode,
        "parcelle_surface_m2": feas.surface_terrain_m2,
        "zone_plu": inputs.zone_plu,
        "sdp_max_m2": feas.sdp_max_m2,
        "nb_logements_max": feas.nb_logements_max,
        "nb_niveaux_max": feas.nb_niveaux,
        "emprise_pct_real": emprise_pct_real,
    }
    await session.commit()

    job_id = str(uuid.uuid4())
    return AnalyzeJobResponse(job_id=job_id, status="completed")


@router.get("/{project_id}/analyze/status", response_model=AnalyzeStatusResponse)
async def analyze_status(
    project_id: str,
    session: SessionDep,
) -> AnalyzeStatusResponse:
    """Get the analysis job status for a project.

    v1: Returns a static pending status. Real status tracking will query
    the ARQ job store when Redis integration is complete.
    """
    if not project_id:
        raise HTTPException(status_code=404, detail="Project not found")

    # Placeholder job ID derived from project ID (deterministic for v1)
    job_id = f"job-{project_id}"
    return AnalyzeStatusResponse(job_id=job_id, status="pending", progress=None)


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"analyzed", "archived"},
    "analyzed": {"reviewed", "archived"},
    "reviewed": {"ready_for_pc", "archived"},
    "ready_for_pc": {"archived"},
    "archived": {"draft"},
}


@router.patch("/{project_id}/status", response_model=ProjectStatusResponse)
async def update_project_status(
    project_id: str,
    body: ProjectStatusChange,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProjectStatusResponse:
    project = await session.get(ProjectRow, UUID(project_id))
    if not project:
        raise HTTPException(404, "Project not found")

    from_status = project.status
    to_status = body.status

    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise HTTPException(
            400, f"Transition {from_status} -> {to_status} not allowed"
        )

    project.status = to_status
    project.status_changed_at = datetime.now(UTC)
    project.status_changed_by = current_user.id

    session.add(
        ProjectStatusHistoryRow(
            project_id=project.id,
            from_status=from_status,
            to_status=to_status,
            changed_by=current_user.id,
            notes=body.notes,
        )
    )
    await session.commit()
    return ProjectStatusResponse(status=to_status)


@router.get(
    "/{project_id}/status_history", response_model=ProjectStatusHistoryResponse
)
async def get_status_history(
    project_id: str,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProjectStatusHistoryResponse:
    rows = (
        await session.execute(
            select(ProjectStatusHistoryRow)
            .where(ProjectStatusHistoryRow.project_id == UUID(project_id))
            .order_by(ProjectStatusHistoryRow.changed_at.desc())
        )
    ).scalars().all()
    return ProjectStatusHistoryResponse(
        items=[
            ProjectStatusHistoryItem(
                id=str(r.id),
                from_status=r.from_status,
                to_status=r.to_status,
                changed_by=str(r.changed_by) if r.changed_by else None,
                changed_at=r.changed_at.isoformat() if r.changed_at else None,
                notes=r.notes,
            )
            for r in rows
        ]
    )
