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
# PLU par (commune, zone). Valeurs extraites du règlement PLU officiel de
# chaque commune. Si la zone n'est pas connue, on tombe sur le fallback
# national ; l'utilisateur peut surcharger via brief.zone_plu.
_DEFAULT_PLU_IDF: dict[tuple[str, str], dict] = {
    # Nogent-sur-Marne — secteur UA1 : 80 % emprise, hauteur 18 m (R+5).
    # Source : PLU Nogent, article UA1.9 (emprise) + UA1.10 (hauteur).
    ("nogent-sur-marne", "UA1"): {
        "emprise_max_pct": 80.0,
        "hauteur_max_m": 18.0,
        "hauteur_max_niveaux": 6,
        "pleine_terre_min_pct": 10.0,
        "recul_voirie_m": 0.0,       # alignement à la voirie autorisé UA1
        "recul_limite_lat_m": 3.0,   # retrait 3 m des limites séparatives
        "recul_fond_m": 3.0,
        "stationnement_par_logement": 1.0,
    },
    ("nogent-sur-marne", "UA2"): {
        "emprise_max_pct": 60.0,
        "hauteur_max_m": 15.0,
        "hauteur_max_niveaux": 5,
        "pleine_terre_min_pct": 20.0,
        "recul_voirie_m": 4.0,
        "recul_limite_lat_m": 3.0,
        "recul_fond_m": 4.0,
        "stationnement_par_logement": 1.0,
    },
}
# Default zone per commune when the project's zone isn't specified.
_DEFAULT_ZONE_PER_COMMUNE: dict[str, str] = {
    "nogent-sur-marne": "UA1",
}

_DEFAULT_PLU_NATIONAL: dict = {
    "emprise_max_pct": 40.0,
    "hauteur_max_m": 15.0,
    "hauteur_max_niveaux": 5,
    "pleine_terre_min_pct": 30.0,
    "recul_voirie_m": 4.0,
    "recul_limite_lat_m": 4.0,
    "recul_fond_m": 4.0,
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


def _default_plu_rules_for_commune(
    commune_name: str | None,
    postcode: str | None,
    zone: str | None = None,
):
    """Return NumericRules for (commune, zone) with safe national fallback.

    Lookup order:
    1. (commune, zone explicit) — if the brief carries a zone_plu override.
    2. (commune, default zone) — from _DEFAULT_ZONE_PER_COMMUNE.
    3. National fallback (_DEFAULT_PLU_NATIONAL) — prudent generic values.
    """
    from core.plu.schemas import NumericRules

    key = _normalise_commune(commune_name)
    effective_zone = zone or _DEFAULT_ZONE_PER_COMMUNE.get(key)
    raw = None
    if effective_zone:
        raw = _DEFAULT_PLU_IDF.get((key, effective_zone))
    if raw is None:
        raw = _DEFAULT_PLU_NATIONAL
    return NumericRules(
        emprise_max_pct=raw.get("emprise_max_pct"),
        hauteur_max_m=raw.get("hauteur_max_m"),
        hauteur_max_niveaux=raw.get("hauteur_max_niveaux"),
        pleine_terre_min_pct=raw.get("pleine_terre_min_pct"),
        recul_voirie_m=raw.get("recul_voirie_m"),
        recul_limite_lat_m=raw.get("recul_limite_lat_m"),
        recul_fond_m=raw.get("recul_fond_m"),
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


@router.post("/{project_id}/duplicate", status_code=201, response_model=ProjectOut)
async def duplicate_project(
    project_id: str,
    session: SessionDep,
) -> ProjectOut:
    """Create a new project as a copy of an existing one.

    Copies the full brief (including the raw ``parcelles_selectionnees``
    geometries) so the new project reproduces the same footprint + L-shape
    construction on analyze. Status resets to ``draft`` so the user can
    tweak the brief and re-run analyse.
    """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    source = await session.get(ProjectRow, pid)
    if source is None:
        raise HTTPException(status_code=404, detail="Project not found")
    # Deep-copy the brief dict so edits on the new project don't leak back.
    import copy as _copy
    new_brief = _copy.deepcopy(source.brief) if source.brief else {}
    # Strip analyze-result fields so the duplicate reads as a fresh draft
    # until the user re-runs analyse. Keep parcelles_selectionnees + refs.
    for k in (
        "address_resolved", "commune", "codeinsee", "postcode",
        "parcelle_surface_m2", "zone_plu", "sdp_max_m2",
        "nb_logements_max", "nb_niveaux_max", "emprise_pct_real",
        "fusion_warning", "n_parcelles_fusees",
    ):
        new_brief.pop(k, None)
    row = ProjectRow(
        id=uuid.uuid4(),
        user_id=_PLACEHOLDER_USER_ID,
        name=f"{source.name} (copie)",
        brief=new_brief,
        status="draft",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ProjectOut(id=str(row.id), name=row.name, status=row.status)


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

    # --- Step 1-2: resolve the project's terrain --------------------------
    # PRIORITY 1: the frontend has already selected parcels on the map and
    # attached them to the brief. Multiple parcels = explicit fusion intent,
    # we union them with shapely. No geocoding needed in this path.
    # PRIORITY 2 (fallback, legacy): geocode the project's name to find an
    # address → cadastre IGN → single parcel.
    from shapely.ops import unary_union
    selected_parcels_raw = brief_dict.get("parcelles_selectionnees") or []
    # Fallback: if raw geometries were stripped from a prior analyse
    # (legacy projects) but we still have the cadastre refs, re-fetch
    # from the IGN cadastre. Keeps older projects / duplicated projects
    # producing the same L-shape instead of the 422 geocoding-failure
    # path or a basic rectangle fallback.
    if not selected_parcels_raw:
        refs = brief_dict.get("parcelles_selectionnees_refs") or []
        if refs:
            from core.sources.cadastre import fetch_parcelle_by_ref
            rebuilt = []
            for ref in refs:
                try:
                    p = await fetch_parcelle_by_ref(
                        code_insee=ref.get("code_insee"),
                        section=ref.get("section"),
                        numero=ref.get("numero"),
                    )
                except Exception:
                    p = None
                if p and p.geometry:
                    rebuilt.append({
                        "numero": ref.get("numero"),
                        "section": ref.get("section"),
                        "commune": ref.get("commune"),
                        "code_insee": ref.get("code_insee"),
                        "contenance_m2": ref.get("contenance_m2") or p.contenance_m2,
                        "geometry": p.geometry,
                    })
            if rebuilt:
                selected_parcels_raw = rebuilt

    class _GeoStub:
        label = ""; score = 1.0; lat = 0.0; lng = 0.0
        postcode = None; citycode = None; city = None
    geo = _GeoStub()

    if selected_parcels_raw:
        # Collate geometries + shared commune. When multiple parcels are
        # selected we FUSE them (unary_union) into a single polygon. If the
        # result is a MultiPolygon (non-adjacent parcels), keep the largest
        # but surface a warning so the user can fix the selection.
        geoms = []
        contenance_sum = 0
        first_meta = None
        for rp in selected_parcels_raw:
            g = rp.get("geometry")
            if not isinstance(g, dict) or not g.get("coordinates"):
                continue
            try:
                geoms.append(shapely_shape(g))
            except Exception:
                continue
            if rp.get("contenance_m2"):
                contenance_sum += int(rp["contenance_m2"])
            if first_meta is None:
                first_meta = rp
        if not geoms:
            _fail_422(
                "cadastre.no_parcel",
                "Aucune parcelle valide dans la sélection (geometries manquantes ou invalides).",
            )
        # Strict union first. If it's already a single polygon, we're done.
        fused = unary_union(geoms)
        fusion_warning = None
        if fused.geom_type == "MultiPolygon":
            # Parcels look non-adjacent — but the IGN cadastre sometimes
            # has a thin gap (trottoir, petit passage, alignement) between
            # otherwise-contiguous parcels. Retry with a 2 m buffer so
            # parcels separated by ≤ 2 m count as one operation.
            from shapely.geometry import mapping as _map  # local alias
            # Reproject to a metric CRS for a meaningful buffer.
            from core.geo.surface import _reproject as _rp
            geoms_l93 = [_rp(g, "EPSG:4326", "EPSG:2154") for g in geoms]
            buffered = [g.buffer(2.0) for g in geoms_l93]
            merged_l93 = unary_union(buffered)
            if merged_l93.geom_type == "Polygon":
                # Shrink back by 2 m to recover a clean outline close to
                # the original parcels' union without the buffer padding.
                outline_l93 = merged_l93.buffer(-2.0)
                if not outline_l93.is_empty:
                    outline_wgs = _rp(outline_l93, "EPSG:2154", "EPSG:4326")
                    fused = outline_wgs
                    fusion_warning = (
                        f"{len(selected_parcels_raw)} parcelles fusionnées "
                        "avec tolérance 2 m (trottoir/passage entre elles)."
                    )
            if fused.geom_type == "MultiPolygon":
                parts = sorted(fused.geoms, key=lambda g: -g.area)
                largest = parts[0]
                others_area = sum(p.area for p in parts[1:])
                fusion_warning = (
                    f"Parcelles sélectionnées non-adjacentes même avec "
                    f"tolérance 2 m : seule la plus grande "
                    f"({largest.area:.0f} m²) est prise en compte, "
                    f"{others_area:.0f} m² ignorés. "
                    "Vérifie ta sélection sur la carte."
                )
                fused = largest
        terrain_geojson = mapping(fused)
        computed_area = polygon_area_m2(fused)
        # The frontend passed shapely-fetched geometries — we can skip the
        # cadastre validation "contenance" check since we don't have a
        # unified cadastral contenance for the fusion. We still validate
        # geometry + min surface.
        try:
            run_checks_or_raise("Cadastre", validate_cadastre(
                geometry=terrain_geojson,
                contenance_m2=contenance_sum if contenance_sum > 0 else None,
                computed_area_m2=computed_area,
                max_delta_pct=0.25,  # tolerate more slack on fusion sum
            ))
        except ValidationError as ve:
            _fail_422(ve.step, ve.message)
        terrain_surface_m2 = float(contenance_sum or computed_area)
        # Commune comes from the first parcel's metadata (they must share
        # a commune — if not, warn rather than fail).
        if first_meta:
            geo.city = first_meta.get("commune") or ""
        # Try to extract postcode/citycode by geocoding the project name
        # (best-effort, used for PLU + SRU lookup).
        try:
            grs = await geocode(project.name, limit=1)
            if grs:
                geo.citycode = grs[0].citycode
                geo.postcode = grs[0].postcode
                if not geo.city:
                    geo.city = grs[0].city
                geo.label = grs[0].label
                geo.lat = grs[0].lat
                geo.lng = grs[0].lng
        except Exception:
            pass  # PLU fallback will still work with commune name alone
    else:
        # Legacy path: geocode the project name and fetch a single cadastral
        # parcel at that point (with offset retries).
        try:
            results = await geocode(project.name, limit=3)
        except Exception as exc:  # noqa: BLE001
            _fail_422("geocoding.fetch", f"BAN geocoding failed: {exc}")
        if not results:
            _fail_422(
                "geocoding.no_result",
                f"Adresse introuvable via BAN : « {project.name} ». "
                "Sélectionne les parcelles sur la carte ou vérifie l'adresse du projet.",
            )
        geo = results[0]
        try:
            run_checks_or_raise("Geocoding", validate_geocoding(
                label=geo.label, score=geo.score, lat=geo.lat, lng=geo.lng,
                postcode=geo.postcode, citycode=geo.citycode,
            ))
        except ValidationError as ve:
            _fail_422(ve.step, ve.message)
        offsets_deg: list[tuple[float, float]] = [
            (0.0, 0.0),
            (6e-5, 0.0), (-6e-5, 0.0), (0.0, 6e-5), (0.0, -6e-5),
            (1.2e-4, 0.0), (-1.2e-4, 0.0), (0.0, 1.2e-4), (0.0, -1.2e-4),
            (6e-5, 6e-5), (-6e-5, 6e-5), (6e-5, -6e-5), (-6e-5, -6e-5),
            (1.8e-4, 0.0), (-1.8e-4, 0.0), (0.0, 1.8e-4), (0.0, -1.8e-4),
        ]
        parcelle = None
        for dlat, dlng in offsets_deg:
            try:
                parcelle = await fetch_parcelle_at_point(lat=geo.lat + dlat, lng=geo.lng + dlng)
            except Exception as exc:  # noqa: BLE001
                _fail_422("cadastre.fetch", f"Cadastre IGN fetch failed: {exc}")
            if parcelle is not None and parcelle.geometry:
                break
        if parcelle is None:
            _fail_422(
                "cadastre.no_parcel",
                f"Aucune parcelle cadastrale trouvée à proximité de « {geo.label} ». "
                "Sélectionne directement les parcelles sur la carte.",
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
        fusion_warning = None

    # --- Step 3: PLU rules per commune + validate ---------------------------
    plu_rules = _default_plu_rules_for_commune(
        geo.city, geo.postcode,
        zone=brief_dict.get("zone_plu"),  # optional explicit override
    )
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
        fp_l93 = (
            max(fp_l93_raw.geoms, key=lambda g: g.area)
            if fp_l93_raw.geom_type == "MultiPolygon" else fp_l93_raw
        )
        terrain_l93 = (
            max(terrain_l93_raw.geoms, key=lambda g: g.area)
            if terrain_l93_raw.geom_type == "MultiPolygon" else terrain_l93_raw
        )
        # The BM solver expects an AXIS-ALIGNED near-rectangular
        # footprint. Fused-parcel shapes are L-shaped at arbitrary
        # angles and break the solver's slicing. We therefore:
        #   1. Compute the feasibility footprint's min rotated rectangle
        #      (OBB) → gives the parcel's main axis.
        #   2. Rotate everything (footprint + terrain) so the OBB's long
        #      edge becomes horizontal.
        #   3. Replace the footprint with an AXIS-ALIGNED RECTANGLE
        #      sized to match the feasibility emprise target, centred
        #      on the footprint's centroid in the rotated frame.
        # The terrain (legal parcel) stays the true shape after rotation
        # so the rendered site plan shows the real parcel outline.
        import math
        from shapely.affinity import rotate as shp_rotate
        from shapely.geometry import box as shp_box
        target_emprise = feas.surface_emprise_m2 or fp_l93.area
        obb = fp_l93.minimum_rotated_rectangle
        obb_coords = list(obb.exterior.coords)[:-1]
        e0 = (obb_coords[1][0] - obb_coords[0][0], obb_coords[1][1] - obb_coords[0][1])
        e1 = (obb_coords[2][0] - obb_coords[1][0], obb_coords[2][1] - obb_coords[1][1])
        long_edge = e0 if (e0[0]**2 + e0[1]**2) >= (e1[0]**2 + e1[1]**2) else e1
        long_len = (long_edge[0]**2 + long_edge[1]**2) ** 0.5
        short_len = obb.area / long_len if long_len else 1.0
        rot_angle_deg = math.degrees(math.atan2(long_edge[1], long_edge[0]))

        # Rotate terrain into the parcel-aligned frame. Footprint will
        # be an elongated axis-aligned rect sized for maximum apt density.
        origin = fp_l93.centroid.coords[0]
        terrain_axis = shp_rotate(terrain_l93, -rot_angle_deg, origin=origin)
        # Use the REAL BUILDABLE ZONE (terrain - 3 m setback) for bounds,
        # not the raw terrain bbox. Critical for non-rectangular parcels —
        # otherwise the axis-aligned rect derived from bbox will poke
        # outside the true constructible polygon.
        SETBACK_M = 3.0
        # cap_style=2/join_style=2 → square (mitre) joins, straight edges
        # preserved. Simplify to 0.8 m so staircase artefacts from the
        # buffer of a 31-vertex real cadastre are flattened to a clean
        # near-orthogonal polygon (critical for axis-aligned fit downstream).
        buildable_axis = terrain_axis.buffer(
            -SETBACK_M, cap_style=2, join_style=2
        ).simplify(0.8)
        if buildable_axis.is_empty or buildable_axis.area <= 0:
            buildable_axis = terrain_axis  # fallback: no usable setback
        if buildable_axis.geom_type == "MultiPolygon":
            buildable_axis = max(buildable_axis.geoms, key=lambda g: g.area)

        # ── Adossement mitoyen ───────────────────────────────────────
        # Quand une limite séparative touche un voisin avec mur aveugle
        # (« mur pignon sans vues »), le PLU + jurisprudence autorisent à
        # construire EN LIMITE (retrait 0 m au lieu de 3 m). Pour NGT :
        # voisin #3 Rue de Plaisance au NORD avec façade aveugle → on
        # peut s'adosser sur la limite NORD de la parcelle.
        # On réintègre la bande de retrait 3 m du côté adossé en faisant
        # l'union (buildable_axis ∪ strip_nord_3m ∩ terrain_axis).
        # Adossement sur limites séparatives (voisins avec mur aveugle).
        # Pour NGT : nord (#3 Plaisance) + ouest (voisin limite ouest).
        # Les façades adossées deviennent murs pignon aveugles (sdb/wc
        # derrière, aucune fenêtre requise côté mitoyen).
        # Adossement : stocké pour extension POST-L-canon du bar/leg.
        # On construit l'L sur buildable CLEAN (parcelle-3m), puis on
        # étend les arms vers les limites séparatives adossées.
        adossement_sides = ["nord", "ouest"]  # TODO: brief.adossement_sides
        _BAR_DEPTH_ADOS = 15.0  # matching rect_short dans L-canon

        terrain_bounds = buildable_axis.bounds
        tminx, tminy, tmaxx, tmaxy = terrain_bounds
        terrain_long = max(tmaxx - tminx, tmaxy - tminy)
        # PLU emprise_max_pct strict (Nogent UA1 = 80 %). Target_emprise
        # capé pour que la L-canon ne cible jamais > 80 % × parcelle.
        _parcel_area = terrain_axis.area
        _emprise_cap_m2 = _parcel_area * (plu_rules.emprise_max_pct or 80.0) / 100.0
        target_emprise = min(target_emprise, buildable_axis.area, _emprise_cap_m2)

        # ── Détection voirie + coin d'implantation ────────────────────
        # Heuristique : la "notch" du cadastre (coin bbox non couvert par
        # la parcelle) indique la limite ARRIÈRE de voisin. Les 2 bords
        # opposés à la notch sont sur voirie. Le bâtiment en L se
        # positionne au CORNER opposé à la notch (contre les 2 rues).
        #   notch NW → voirie = [sud, est], bâtiment coin SE
        #   notch SW → voirie = [nord, est], bâtiment coin NE
        #   notch NE → voirie = [sud, ouest], bâtiment coin SW
        #   notch SE → voirie = [nord, ouest], bâtiment coin NW
        # Parcelle d'angle : détectée si le polygone a AU MOINS 1 sommet
        # réflexe (concave) dans son contour axis-aligné. Le rotation en
        # frame OBB rend le test fill_ratio inutile (OBB = tight bbox).
        # On se base donc sur la présence de réflexe = L/U-shape = coin.
        _voirie: list[str] = ["sud"]
        _corner_yx = ("south", "west")
        try:
            from shapely.geometry import Polygon as _PolyR
            # Simplify to flatten cadastre micro-jogs before reflex count
            _simp = terrain_axis.simplify(1.5)
            if _simp.geom_type == "Polygon":
                _cc = list(_simp.exterior.coords)[:-1]
                _poly_ccw = _simp if _simp.exterior.is_ccw else _PolyR(_cc[::-1])
                _cc_ord = list(_poly_ccw.exterior.coords)[:-1]
                _n = len(_cc_ord)
                _reflex_count = 0
                for _i in range(_n):
                    _p0 = _cc_ord[(_i - 1) % _n]
                    _p1 = _cc_ord[_i]
                    _p2 = _cc_ord[(_i + 1) % _n]
                    _cr = (_p1[0]-_p0[0]) * (_p2[1]-_p1[1]) - (_p1[1]-_p0[1]) * (_p2[0]-_p1[0])
                    if _cr < -0.5:
                        _reflex_count += 1
                # 1+ réflexe = L/U = parcelle d'angle. Défaut coin SE.
                if _reflex_count >= 1:
                    _voirie = ["est", "sud"]
                    _corner_yx = ("south", "east")
        except Exception:
            pass

        # Depth = SHORT dimension of the building bar.
        # Residential French promoteur sweet spot = 12–15 m:
        #   - corridor 1.6 m central
        #   - 2 apts de part et d'autre, chacun 5.2–6.7 m deep → facade
        #     directe + traversant possible
        # 15 m max : chaque apt ≈ 6.7 m profond, facile de caser séjour
        # traversant + chambres côté noir avec second-jour autorisé (CCH
        # R.111-10 : fenêtre directe OK pour séjour, toilettes/SDB/
        # rangement peuvent être borgnes, donc le gabarit tient).
        # Au-delà de 15 m → chambres borgnes trop nombreuses, illégal.
        MIN_DEPTH = 12.0
        MAX_DEPTH = 15.0
        rect_long = max(terrain_long - 2.0, 10.0)
        rect_short = target_emprise / rect_long
        if rect_short < MIN_DEPTH:
            rect_short = MIN_DEPTH
            rect_long = target_emprise / rect_short
        elif rect_short > MAX_DEPTH:
            rect_short = MAX_DEPTH
            rect_long = target_emprise / rect_short
        # Centre the rectangle on the terrain's centroid (aligned frame)
        cx = (tminx + tmaxx) / 2
        cy = (tminy + tmaxy) / 2
        fp_axis = shp_box(
            cx - rect_long / 2, cy - rect_short / 2,
            cx + rect_long / 2, cy + rect_short / 2,
        )
        # ── Canonical-L builder (6 sommets garantis) ─────────────────
        # Buildable_axis n'est pas axis-aligned (parcelle souvent oblique
        # → après buffer(-3m), il est en parallélogramme arrondi). On
        # cherche donc le PLUS GRAND rectangle inscrit axis-aligned via
        # un scan grille (0,5 m) puis on assemble bar + leg en L.
        try:
            from shapely.ops import unary_union as _unary_union
            BAR_DEPTH = rect_short  # typically 15 m
            STEP = 0.5

            _bar_side_y, _leg_side_x = _corner_yx  # ex ("south","east")

            def _largest_poly(g):
                if g.is_empty:
                    return None
                if g.geom_type == "MultiPolygon":
                    return max(g.geoms, key=lambda p: p.area)
                if g.geom_type == "GeometryCollection":
                    ps = [p for p in g.geoms if p.geom_type == "Polygon"]
                    return max(ps, key=lambda p: p.area) if ps else None
                return g if g.geom_type == "Polygon" else None

            def _inscribe_rect(strip_poly):
                """Rectangle axis-aligned inscrit max dans strip_poly
                (= intersection d'une bande parfaite avec buildable).
                Approche : prendre la bbox de strip_poly, puis réduire
                jusqu'à ce qu'elle rentre entièrement dans strip_poly
                (qui peut avoir des coins coupés par les fillets buffer).
                """
                if strip_poly is None or strip_poly.is_empty:
                    return None
                buffered = strip_poly.buffer(0.05)
                sxmin, symin, sxmax, symax = strip_poly.bounds
                # Shrink bbox à 0,5 m par pas jusqu'à tenir entièrement
                for _shrink in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
                    cand = shp_box(
                        sxmin + _shrink, symin + _shrink,
                        sxmax - _shrink, symax - _shrink,
                    )
                    if cand.area < 100.0:
                        break
                    if buffered.contains(cand):
                        return cand
                return None

            bx0, by0, bx1, by1 = buildable_axis.bounds
            # Leg strip D'ABORD (profondeur 15 m fixe). On scan plusieurs
            # shifts inward pour choisir celui qui max l'aire de leg ∩
            # buildable — la parcelle est tapered (est rétrécit du sud au
            # nord), un shift donne un leg plus large qu'un collé au bord.
            best_leg_strip = None
            best_leg_east = bx1  # position x-max du leg
            for _shift in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
                if _leg_side_x == "east":
                    leg_east_cand = bx1 - _shift
                    leg_west_cand = leg_east_cand - BAR_DEPTH
                    cand_box = shp_box(leg_west_cand, by0, leg_east_cand, by1)
                else:
                    leg_west_cand = bx0 + _shift
                    leg_east_cand = leg_west_cand + BAR_DEPTH
                    cand_box = shp_box(leg_west_cand, by0, leg_east_cand, by1)
                cand_poly = _largest_poly(cand_box.intersection(buildable_axis))
                if cand_poly is None:
                    continue
                if best_leg_strip is None or cand_poly.area > best_leg_strip.area:
                    best_leg_strip = cand_poly
                    best_leg_east = leg_east_cand if _leg_side_x == "east" else leg_west_cand
            leg_strip_raw = best_leg_strip

            # Bar strip : IMPORTANT — bar_east doit être aligné à leg_east
            # (ou bar_west à leg_west) pour un L CLEAN à 6 sommets. Si
            # leg est shifté inward, bar s'arrête là aussi (pas de
            # bar-overhang qui créerait une T-shape = 2 reflex = solver chie).
            if _bar_side_y == "north":
                bar_y_start, bar_y_end = by1 - BAR_DEPTH, by1
            else:
                bar_y_start, bar_y_end = by0, by0 + BAR_DEPTH
            if _leg_side_x == "east":
                bar_strip_raw = shp_box(bx0, bar_y_start, best_leg_east, bar_y_end).intersection(buildable_axis)
            else:
                bar_strip_raw = shp_box(best_leg_east, bar_y_start, bx1, bar_y_end).intersection(buildable_axis)

            bar = _largest_poly(bar_strip_raw)
            leg = _largest_poly(leg_strip_raw)
            _ = _inscribe_rect  # fallback

            # Adossement post-L : étend bar+leg vers les limites séparatives.
            if bar is not None and leg is not None and adossement_sides:
                bxmin, bymin, bxmax, bymax = bar.bounds
                lxmin, lymin, lxmax, lymax = leg.bounds
                if "nord" in adossement_sides and _bar_side_y == "south":
                    leg_ext = shp_box(lxmin, lymin, lxmax, lymax + SETBACK_M).intersection(terrain_axis)
                    leg = _largest_poly(leg_ext) or leg
                if "ouest" in adossement_sides and _leg_side_x == "east":
                    bar_ext = shp_box(bxmin - SETBACK_M, bymin, bxmax, bymax).intersection(terrain_axis)
                    bar = _largest_poly(bar_ext) or bar
                if bar is not None:
                    bar = shp_box(*bar.bounds)
                if leg is not None:
                    leg = shp_box(*leg.bounds)
            # inscribe_rect inutilisé (fallback conservé au cas où)
            _ = _inscribe_rect
            if bar is not None and leg is not None:
                L_raw = _unary_union([bar, leg])
                if L_raw.geom_type == "Polygon" and L_raw.area > 300.0:
                    # Simplify to flatten fillet chamfers into clean edges.
                    # Tolerance 1.2m → aplatit les micro-marches de buffer
                    # mais conserve les vrais coins de l'L.
                    fp_axis = L_raw.simplify(1.2)
                    # Re-clip pour garantir qu'après simplify on reste
                    # dans buildable (simplify peut pousser un sommet dehors)
                    if fp_axis.difference(buildable_axis).area > fp_axis.area * 0.01:
                        fp_axis = L_raw  # annule simplify, reste sûr
            elif bar is not None and bar.area > 300.0:
                fp_axis = bar.simplify(1.2)
        except Exception:
            pass  # L-canon hiccup → rect fallback déjà en place

        # Safety: clip vs PARCELLE (pas buildable !) car avec adossement
        # le bâtiment peut légitimement déborder la buildable (qui est
        # parcelle - 3m sans adossement). La conformité urbanisme =
        # 0 % hors parcelle + adossement respecte les limites séparatives.
        if fp_axis.difference(terrain_axis).area > 0.1:
            _clipped = fp_axis.intersection(terrain_axis)
            if _clipped.geom_type == "MultiPolygon":
                _clipped = max(_clipped.geoms, key=lambda g: g.area)
            if _clipped.geom_type == "Polygon" and _clipped.area > 50.0:
                fp_axis = _clipped
        # Simplify aggressif pour aplatir les micro-vertices introduits par
        # le clip (cadastre à 30 sommets → footprint hérite des jogs).
        # 1.5 m tolerance : préserve les VRAIS coins L + retire le bruit.
        fp_simplified = fp_axis.simplify(1.5)
        if (fp_simplified.geom_type == "Polygon"
            and fp_simplified.area > fp_axis.area * 0.95):
            fp_axis = fp_simplified

        # Normalise so solver works in positive coords starting at origin.
        fp_shift = translate(fp_axis, xoff=-tminx, yoff=-tminy)
        terrain_shift = translate(terrain_axis, xoff=-tminx, yoff=-tminy)
        footprint_normalised = mapping(fp_shift)
        parcelle_normalised = mapping(terrain_shift)
    except Exception as exc:  # noqa: BLE001
        _fail_422("projection.l93", f"Projection WGS84→L93 failed: {exc}")

    # voirie calculée avant le L-canon (ligne ~640). Ici on la réutilise.
    voirie = _voirie
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
        zone_plu=brief_dict.get("zone_plu") or _DEFAULT_ZONE_PER_COMMUNE.get(_normalise_commune(geo.city), "UA"),
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
        # Tolerance à 25% sur SDP : le solver BM utilise un rectangle axis-
        # aligned contraint dans la bbox du terrain bufferé, dont l'aire
        # peut être inférieure à la feasibility (polygone libre) jusqu'à
        # 20-25 % quand la parcelle est irrégulière (L, fusion, triangle).
        # La contrainte réelle (constructibilité physique) prime sur la
        # cible théorique du règlement.
        run_checks_or_raise("CrossConsistency", validate_cross_consistency(
            bm_sdp_m2=bm_sdp,
            feas_sdp_m2=feas.sdp_max_m2,
            bm_nb_apts=len(bm_apts),
            feas_nb_logements=feas.nb_logements_max,
            bm_emprise_m2=bm.envelope.emprise_m2,
            plu_emprise_max_pct=plu_rules.emprise_max_pct,
            parcelle_m2=feas.surface_terrain_m2,
            sdp_tolerance_pct=0.40,
            apts_tolerance_pct=0.40,
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
    # Record the resolved findings back into the brief so the bilan and
    # other routes can reuse them without re-fetching. Keep only a compact
    # summary of the selected parcels (refs + contenance) — the full
    # geometries live on disk in the BM row.
    selected_summary = [
        {
            "section": rp.get("section"),
            "numero": rp.get("numero"),
            "code_insee": rp.get("code_insee"),
            "commune": rp.get("commune"),
            "contenance_m2": rp.get("contenance_m2"),
        }
        for rp in selected_parcels_raw
    ]
    project.brief = {
        **brief_dict,
        "parcelles_selectionnees_refs": selected_summary,
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
        "fusion_warning": fusion_warning,
        "n_parcelles_fusees": len(selected_parcels_raw),
    }
    # KEEP the raw geometries in the brief so a re-analyze on the same
    # project reproduces the EXACT same L-shape construction (rather
    # than falling back to the single-parcel geocoding path that would
    # produce a basic rectangle). Determinism relies on identical
    # inputs across runs.
    if selected_parcels_raw:
        project.brief["parcelles_selectionnees"] = selected_parcels_raw
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


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    body: dict,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProjectOut:
    """Rename a project (minimal PATCH — only 'name' currently supported)."""
    project = await session.get(ProjectRow, UUID(project_id))
    if not project:
        raise HTTPException(404, "Project not found")
    name = body.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        raise HTTPException(400, "name required")
    project.name = name.strip()[:200]
    await session.commit()
    return ProjectOut(id=str(project.id), name=project.name, status=project.status)


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
