"""Multi-constraint MAX envelope solver — Phase 4.

Extends :func:`core.building_model.pipeline.compute_max_envelope` (which
only knows about base PLU rules) by chaining ALL exogenous constraints
from the nogentLayers data bundle (cadastre + GPU prescriptions + GPU
SUP + servitudes + risques + BD TOPO voisinage).

Each constraint is applied in a strict priority order so the binding
rule per axis (emprise / hauteur / niveaux / SDP) is reproducible and
auditable. Every step appends a :class:`ConstraintStepTrace` to the
output so investors / lenders / ABF can read exactly WHY the envelope
was reduced — no black-box collapse.

Priority order (most restrictive wins per axis)::

    1.  parcelle geometry (vertices from cadastre)            — start
    2.  EBC L.113-1                                            — soustrait
    3.  EVP L.151-23                                           — preserve %
    4.  ABF 500m → avis conforme trigger                       — warn / cap
    5.  Linéaire commercial L.151-16                           — RDC commerce
    6.  ER L.151-41 grevant la parcelle                        — full block
    7.  SUP I1 / I3 / I4 (bandes inconstructibles)             — soustrait
    8.  PPRI cote PHEC → Δ plancher RDC                        — height +Δ
    9.  PLU UA1 (emprise % × hauteur × bonus toiture/pignon)   — base
    10. Retrait latéral H/3 min 4m + retrait fond hauteur ≤ 3m — geometric
    11. R.111-18 6m chambres vue voisin (BD TOPO)              — geometric
    12. Code civil 675-680 vue droite 1.90m                    — info
    13. Gabarit prospect H = f(L) si PLU prescrit              — height cap

All geometries are processed in Lambert-93 (EPSG:2154). WGS84 GeoJSON
inputs are auto-reprojected via :func:`core.geo.surface._reproject`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core.building_model.schemas import EnvelopeMaxPLU
from core.geo.surface import _reproject
from core.plu.schemas import NumericRules

# ---------------------------------------------------------------------------
# Constants — defaults aligned with French PLU practice
# ---------------------------------------------------------------------------

#: Floor-to-floor height used to convert niveaux <-> metres.
_HAUTEUR_PAR_NIVEAU_M = 3.0

#: Half-floor allowance on the top niveau (toiture / acrotère).
_TOP_NIVEAU_ALLOWANCE_M = 0.5

#: R.111-18 default — 6m for habitable rooms with direct neighbour view.
_R111_18_CHAMBRE_VUE_M = 6.0

#: Code civil 675-680 — vue droite 1.90m from limite séparative.
_VUE_DROITE_CC_M = 1.90

#: PLU UA1 bonus toiture (corniche / lucarnes mansardées).
_UA1_BONUS_TOITURE_M = 2.0

#: PLU UA1 bonus pignon (niveau supplémentaire si pignon sur rue).
_UA1_BONUS_PIGNON_NIVEAUX = 1


# ---------------------------------------------------------------------------
# Input bundle — nogentLayers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EbcLayer:
    """Espace Boisé Classé (L.113-1) — strictly inconstructible."""

    geometry_geojson: dict[str, Any]
    source: str = "gpu"  # gpu | plu_graphique
    label: str | None = None


@dataclass(frozen=True)
class EvpLayer:
    """Espace Vert Protégé (L.151-23) — preserve a % non bâti."""

    geometry_geojson: dict[str, Any]
    pct_non_bati_min: float = 100.0  # 100% = full non-build; <100% allows partial
    label: str | None = None


@dataclass(frozen=True)
class AbfPerimetre:
    """ABF 500m perimeter around a Monument Historique."""

    monument_nom: str
    monument_ref: str | None  # e.g. "PA00079894"
    distance_m: float          # parcelle ↔ monument
    avis_conforme: bool = True  # True if MH classé (avis conforme), False if simple
    geometry_geojson: dict[str, Any] | None = None


@dataclass(frozen=True)
class LineaireCommercialLayer:
    """L.151-16 — linéaire commercial obligatoire en RDC."""

    geometry_geojson: dict[str, Any]   # line geometry traced along voirie
    hauteur_rdc_commerce_min_m: float = 3.0
    interdit_logement_rdc: bool = True
    label: str | None = None


@dataclass(frozen=True)
class EmplacementReserveLayer:
    """L.151-41 — Emplacement Réservé. If overlaps parcelle → full block."""

    geometry_geojson: dict[str, Any]
    numero: str
    beneficiaire: str | None = None
    motif: str | None = None  # voirie, equipement, etc.


@dataclass(frozen=True)
class SupBandeInconstructible:
    """SUP I1 / I3 / I4 — bandes inconstructibles (canalisations, hydrocarbures, gaz)."""

    geometry_geojson: dict[str, Any]
    categorie: Literal["I1", "I3", "I4"]
    label: str | None = None


@dataclass(frozen=True)
class PpriCote:
    """PPRI — cote PHEC oblige à surélever le plancher RDC."""

    cote_phec_ngf: float        # absolute reference (m NGF)
    cote_terrain_ngf: float     # parcelle ground level (m NGF)
    marge_securite_m: float = 0.20
    zone: Literal["bleue", "rouge", "blanche"] = "bleue"


@dataclass(frozen=True)
class NeighborBuilding:
    """A neighbour building (BD TOPO) — used for R.111-18 chambres vue."""

    geometry_geojson: dict[str, Any]
    hauteur_m: float | None = None
    is_principal: bool = True  # vs. annexe/abri


@dataclass(frozen=True)
class GabaritProspect:
    """PLU gabarit prospect — H = f(L) where L = distance to opposite alignment."""

    type: Literal["L_egal_H", "L_egal_H_demi", "L_egal_H_tiers", "constant"]
    constant_max_m: float | None = None  # only when type == "constant"


@dataclass
class NogentLayers:
    """Bundle of all exogenous layers a parcelle may be subject to.

    Every field is optional — the solver applies only the constraints
    that are populated. Empty list / None means "no such constraint
    applies to this parcelle".
    """

    ebc: list[EbcLayer] = field(default_factory=list)
    evp: list[EvpLayer] = field(default_factory=list)
    abf: AbfPerimetre | None = None
    lineaire_commercial: list[LineaireCommercialLayer] = field(default_factory=list)
    er: list[EmplacementReserveLayer] = field(default_factory=list)
    sup_bandes: list[SupBandeInconstructible] = field(default_factory=list)
    ppri: PpriCote | None = None
    neighbors: list[NeighborBuilding] = field(default_factory=list)
    gabarit_prospect: GabaritProspect | None = None
    # UA1-specific bonuses (toggle on if PLU allows them on this parcelle)
    ua1_bonus_toiture_eligible: bool = True
    ua1_bonus_pignon_eligible: bool = False


# ---------------------------------------------------------------------------
# Output — per-step trace
# ---------------------------------------------------------------------------


class ConstraintStepTrace(BaseModel):
    """One row of the constraint application trace."""

    step: int = Field(ge=1, le=13)
    name: str
    code_ref: str                     # e.g. "L.113-1", "R.111-18"
    applied: bool                     # False = layer absent / not applicable
    binding: bool                     # True if this step changed the result
    emprise_avant_m2: float
    emprise_apres_m2: float
    hauteur_avant_m: float
    hauteur_apres_m: float
    niveaux_avant: int
    niveaux_apres: int
    rationale: str
    geometry_after_geojson: dict[str, Any] | None = None


class MultiConstraintEnvelope(BaseModel):
    """Output of the multi-constraint solver.

    Wraps an :class:`EnvelopeMaxPLU` with the full per-step trace so the
    binding constraint per axis can be replayed and audited.
    """

    envelope: EnvelopeMaxPLU
    trace: list[ConstraintStepTrace] = Field(default_factory=list)
    binding_constraint_emprise: str | None = None
    binding_constraint_hauteur: str | None = None
    binding_constraint_sdp: str | None = None
    constraints_applied: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_metric(geom_geojson: dict[str, Any]) -> tuple[BaseGeometry, bool]:
    """Reproject a GeoJSON geometry to Lambert-93 if it looks like WGS84."""
    geom = shape(geom_geojson)
    minx, miny, maxx, maxy = geom.bounds
    if (maxx - minx) < 1.0 and (maxy - miny) < 1.0:
        return _reproject(geom, "EPSG:4326", "EPSG:2154"), True
    return geom, False


def _as_geojson(geom: BaseGeometry, was_wgs84: bool) -> dict[str, Any]:
    if geom.is_empty:
        return {}
    if was_wgs84:
        geom = _reproject(geom, "EPSG:2154", "EPSG:4326")
    return dict(mapping(geom))


def _safe_buffer(geom: BaseGeometry, distance_m: float) -> BaseGeometry:
    if distance_m <= 0:
        return geom
    out = geom.buffer(-distance_m)
    if out.is_empty:
        return out
    if isinstance(out, MultiPolygon):
        return max(out.geoms, key=lambda g: g.area)
    return out


def _niveaux_from_height(h_m: float) -> int:
    if h_m <= 0:
        return 0
    return math.floor(h_m / _HAUTEUR_PAR_NIVEAU_M)


def _height_from_niveaux(n: int) -> float:
    return n * _HAUTEUR_PAR_NIVEAU_M + _TOP_NIVEAU_ALLOWANCE_M


# ---------------------------------------------------------------------------
# Public solver
# ---------------------------------------------------------------------------


def solve_max_envelope_multi_constraint(  # noqa: PLR0912, PLR0915 - inherently sequential
    plu_rules: NumericRules,
    parcelle_geojson: dict[str, Any],
    layers: NogentLayers | None = None,
    *,
    zone_plu: str = "UA1",
) -> MultiConstraintEnvelope:
    """Chain all Phase-4 constraints and return the MAX envelope + trace.

    Args:
        plu_rules:     Base PLU numeric rules (UA1 default values).
        parcelle_geojson: Parcelle geometry (WGS84 or Lambert-93 GeoJSON).
        layers:        Bundle of nogentLayers (EBC, EVP, ABF, …). When
                       ``None`` only the base PLU rules apply.
        zone_plu:      PLU zone label (used to gate UA1-specific bonuses).

    Returns:
        :class:`MultiConstraintEnvelope` — envelope + per-step trace.
    """
    layers = layers or NogentLayers()
    trace: list[ConstraintStepTrace] = []
    applied: list[str] = []

    binding_emprise: str | None = None
    binding_hauteur: str | None = None
    binding_sdp: str | None = None

    # ------------------------------------------------------------------
    # Step 1 — parcelle geometry from cadastre
    # ------------------------------------------------------------------
    parcelle_metric, was_wgs84 = _to_metric(parcelle_geojson)
    terrain_area = parcelle_metric.area
    current = parcelle_metric
    current_emprise = terrain_area
    current_hauteur = 0.0
    current_niveaux = 0

    trace.append(
        ConstraintStepTrace(
            step=1,
            name="Parcelle cadastrale",
            code_ref="cadastre",
            applied=True,
            binding=False,
            emprise_avant_m2=terrain_area,
            emprise_apres_m2=terrain_area,
            hauteur_avant_m=0.0,
            hauteur_apres_m=0.0,
            niveaux_avant=0,
            niveaux_apres=0,
            rationale=f"Terrain {terrain_area:.1f} m² (Lambert-93).",
            geometry_after_geojson=_as_geojson(current, was_wgs84),
        )
    )

    # ------------------------------------------------------------------
    # Step 2 — EBC L.113-1 (soustrait)
    # ------------------------------------------------------------------
    avant = current_emprise
    if layers.ebc:
        ebc_union = unary_union(
            [_to_metric(e.geometry_geojson)[0] for e in layers.ebc]
        )
        current = current.difference(ebc_union)
        applied.append("EBC L.113-1")
        binding = current.area < avant - 1e-3
        if binding:
            binding_emprise = "EBC L.113-1"
        trace.append(
            ConstraintStepTrace(
                step=2, name="EBC L.113-1", code_ref="L.113-1",
                applied=True, binding=binding,
                emprise_avant_m2=avant, emprise_apres_m2=current.area,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale=f"EBC soustrait : -{avant - current.area:.1f} m².",
                geometry_after_geojson=_as_geojson(current, was_wgs84),
            )
        )
        current_emprise = current.area
    else:
        trace.append(
            ConstraintStepTrace(
                step=2, name="EBC L.113-1", code_ref="L.113-1",
                applied=False, binding=False,
                emprise_avant_m2=avant, emprise_apres_m2=avant,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Aucun EBC sur la parcelle.",
            )
        )

    # ------------------------------------------------------------------
    # Step 3 — EVP L.151-23 (preserve % non bâti)
    # ------------------------------------------------------------------
    avant = current_emprise
    if layers.evp:
        evp_union = unary_union(
            [_to_metric(e.geometry_geojson)[0] for e in layers.evp]
        )
        # Surface EVP qui doit rester non bâtie
        evp_in_parcelle = current.intersection(evp_union)
        # Soustrait la part interdite (pct_non_bati_min %)
        if not evp_in_parcelle.is_empty:
            preserve_pct = max(e.pct_non_bati_min for e in layers.evp) / 100.0
            # Approximation v1 : on retire intégralement la portion EVP × preserve_pct
            buildable_in_evp = evp_in_parcelle.buffer(0)  # ensure valid
            # Scale-down the EVP portion by (1 - preserve_pct) — keep only the
            # buildable fraction (centroid-based).
            from shapely.affinity import scale as _scale
            keep_factor = max(0.0, 1.0 - preserve_pct) ** 0.5
            if keep_factor > 0:
                buildable_in_evp = _scale(
                    buildable_in_evp,
                    xfact=keep_factor, yfact=keep_factor,
                    origin=buildable_in_evp.centroid,
                )
                current = current.difference(evp_in_parcelle).union(buildable_in_evp)
            else:
                current = current.difference(evp_in_parcelle)
        applied.append("EVP L.151-23")
        binding = current.area < avant - 1e-3
        if binding and binding_emprise is None:
            binding_emprise = "EVP L.151-23"
        trace.append(
            ConstraintStepTrace(
                step=3, name="EVP L.151-23", code_ref="L.151-23",
                applied=True, binding=binding,
                emprise_avant_m2=avant, emprise_apres_m2=current.area,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale=f"EVP préservé : -{avant - current.area:.1f} m² non bâti.",
                geometry_after_geojson=_as_geojson(current, was_wgs84),
            )
        )
        current_emprise = current.area
    else:
        trace.append(
            ConstraintStepTrace(
                step=3, name="EVP L.151-23", code_ref="L.151-23",
                applied=False, binding=False,
                emprise_avant_m2=avant, emprise_apres_m2=avant,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Aucun EVP sur la parcelle.",
            )
        )

    # ------------------------------------------------------------------
    # Step 4 — ABF 500m (avis conforme trigger — pas de cap géométrique)
    # ------------------------------------------------------------------
    avant_h = current_hauteur
    if layers.abf is not None and layers.abf.distance_m <= 500.0:
        applied.append("ABF 500m")
        # No geometric reduction; trigger avis conforme & flag for downstream.
        trace.append(
            ConstraintStepTrace(
                step=4, name="ABF 500m", code_ref="L.621-30/621-32 CP",
                applied=True, binding=False,  # avis = procedural, not geometric
                emprise_avant_m2=current_emprise, emprise_apres_m2=current_emprise,
                hauteur_avant_m=avant_h, hauteur_apres_m=avant_h,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale=(
                    f"MH '{layers.abf.monument_nom}' à {layers.abf.distance_m:.0f} m "
                    f"({'avis conforme' if layers.abf.avis_conforme else 'avis simple'}) — "
                    "matériaux/toiture à valider UDAP."
                ),
            )
        )
    else:
        trace.append(
            ConstraintStepTrace(
                step=4, name="ABF 500m", code_ref="L.621-30/621-32 CP",
                applied=False, binding=False,
                emprise_avant_m2=current_emprise, emprise_apres_m2=current_emprise,
                hauteur_avant_m=avant_h, hauteur_apres_m=avant_h,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Hors périmètre ABF (>500 m de tout MH).",
            )
        )

    # ------------------------------------------------------------------
    # Step 5 — Linéaire commercial L.151-16
    # ------------------------------------------------------------------
    # Geometric: RDC must keep H >= hauteur_rdc_commerce_min_m. We bump the
    # niveau-0 plancher; aggregate result = niveaux logement = niveaux - 1.
    rdc_commerce_active = False
    if layers.lineaire_commercial:
        applied.append("Linéaire commercial L.151-16")
        rdc_commerce_active = True
        trace.append(
            ConstraintStepTrace(
                step=5, name="Linéaire commercial L.151-16",
                code_ref="L.151-16",
                applied=True, binding=True,
                emprise_avant_m2=current_emprise, emprise_apres_m2=current_emprise,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale=(
                    "RDC commerce obligatoire (H ≥ "
                    f"{layers.lineaire_commercial[0].hauteur_rdc_commerce_min_m} m), "
                    "logement RDC interdit → -1 niveau logement."
                ),
            )
        )
    else:
        trace.append(
            ConstraintStepTrace(
                step=5, name="Linéaire commercial L.151-16",
                code_ref="L.151-16",
                applied=False, binding=False,
                emprise_avant_m2=current_emprise, emprise_apres_m2=current_emprise,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Pas de linéaire commercial sur cette rue.",
            )
        )

    # ------------------------------------------------------------------
    # Step 6 — ER L.151-41 grevant la parcelle (full block)
    # ------------------------------------------------------------------
    avant = current_emprise
    if layers.er:
        er_union = unary_union(
            [_to_metric(e.geometry_geojson)[0] for e in layers.er]
        )
        # If ER fully covers the parcelle → emprise = 0, return empty envelope.
        intersection = current.intersection(er_union)
        if intersection.area / max(current.area, 1e-9) > 0.95:
            current = Polygon()  # empty
            binding_emprise = "ER L.151-41 (intégral)"
            applied.append("ER L.151-41")
            trace.append(
                ConstraintStepTrace(
                    step=6, name="ER L.151-41", code_ref="L.151-41",
                    applied=True, binding=True,
                    emprise_avant_m2=avant, emprise_apres_m2=0.0,
                    hauteur_avant_m=current_hauteur, hauteur_apres_m=0.0,
                    niveaux_avant=current_niveaux, niveaux_apres=0,
                    rationale="ER intégral sur parcelle → construction interdite.",
                )
            )
            current_emprise = 0.0
        elif intersection.area > 0:
            current = current.difference(er_union)
            applied.append("ER L.151-41 (partiel)")
            if binding_emprise is None:
                binding_emprise = "ER L.151-41 (partiel)"
            trace.append(
                ConstraintStepTrace(
                    step=6, name="ER L.151-41 (partiel)", code_ref="L.151-41",
                    applied=True, binding=True,
                    emprise_avant_m2=avant, emprise_apres_m2=current.area,
                    hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale=(
                        f"ER soustrait : -{avant - current.area:.1f} m² "
                        f"(N° {layers.er[0].numero})."
                    ),
                    geometry_after_geojson=_as_geojson(current, was_wgs84),
                )
            )
            current_emprise = current.area
        else:
            trace.append(
                ConstraintStepTrace(
                    step=6, name="ER L.151-41", code_ref="L.151-41",
                    applied=False, binding=False,
                    emprise_avant_m2=avant, emprise_apres_m2=avant,
                    hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale="ER référencé mais sans intersection avec la parcelle.",
                )
            )
    else:
        trace.append(
            ConstraintStepTrace(
                step=6, name="ER L.151-41", code_ref="L.151-41",
                applied=False, binding=False,
                emprise_avant_m2=avant, emprise_apres_m2=avant,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Aucun ER grevant la parcelle.",
            )
        )

    # ------------------------------------------------------------------
    # Step 7 — SUP I1 / I3 / I4 (bandes inconstructibles)
    # ------------------------------------------------------------------
    avant = current_emprise
    if layers.sup_bandes and not current.is_empty:
        sup_union = unary_union(
            [_to_metric(b.geometry_geojson)[0] for b in layers.sup_bandes]
        )
        current = current.difference(sup_union)
        cats = ", ".join(sorted({b.categorie for b in layers.sup_bandes}))
        applied.append(f"SUP {cats}")
        binding = current.area < avant - 1e-3
        if binding and binding_emprise is None:
            binding_emprise = f"SUP {cats}"
        trace.append(
            ConstraintStepTrace(
                step=7, name=f"SUP {cats}", code_ref="L.151-43",
                applied=True, binding=binding,
                emprise_avant_m2=avant, emprise_apres_m2=current.area,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale=(
                    f"Bandes SUP soustraites : -{avant - current.area:.1f} m²."
                ),
                geometry_after_geojson=_as_geojson(current, was_wgs84),
            )
        )
        current_emprise = current.area
    else:
        trace.append(
            ConstraintStepTrace(
                step=7, name="SUP I1/I3/I4", code_ref="L.151-43",
                applied=False, binding=False,
                emprise_avant_m2=avant, emprise_apres_m2=avant,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Aucune bande inconstructible SUP I1/I3/I4.",
            )
        )

    # ------------------------------------------------------------------
    # Step 8 — PPRI cote PHEC → Δ plancher RDC
    # ------------------------------------------------------------------
    ppri_delta_m = 0.0
    if layers.ppri is not None:
        target_ngf = layers.ppri.cote_phec_ngf + layers.ppri.marge_securite_m
        if target_ngf > layers.ppri.cote_terrain_ngf:
            ppri_delta_m = target_ngf - layers.ppri.cote_terrain_ngf
            applied.append("PPRI")
            trace.append(
                ConstraintStepTrace(
                    step=8, name="PPRI cote PHEC", code_ref="L.562-1 CE",
                    applied=True, binding=True,
                    emprise_avant_m2=current_emprise,
                    emprise_apres_m2=current_emprise,
                    hauteur_avant_m=current_hauteur,
                    hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale=(
                        f"Plancher RDC ≥ PHEC+{layers.ppri.marge_securite_m} m "
                        f"= {target_ngf:.2f} NGF → surélever +{ppri_delta_m:.2f} m."
                    ),
                )
            )
        else:
            trace.append(
                ConstraintStepTrace(
                    step=8, name="PPRI cote PHEC", code_ref="L.562-1 CE",
                    applied=True, binding=False,
                    emprise_avant_m2=current_emprise,
                    emprise_apres_m2=current_emprise,
                    hauteur_avant_m=current_hauteur,
                    hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale=(
                        f"PPRI {layers.ppri.zone} mais terrain "
                        f"{layers.ppri.cote_terrain_ngf:.2f} NGF déjà > "
                        f"PHEC {layers.ppri.cote_phec_ngf:.2f} NGF."
                    ),
                )
            )
    else:
        trace.append(
            ConstraintStepTrace(
                step=8, name="PPRI cote PHEC", code_ref="L.562-1 CE",
                applied=False, binding=False,
                emprise_avant_m2=current_emprise, emprise_apres_m2=current_emprise,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Pas de PPRI applicable.",
            )
        )

    # ------------------------------------------------------------------
    # Step 9 — PLU UA1 : emprise % × hauteur 18m + bonus toiture/pignon
    # ------------------------------------------------------------------
    emprise_max_pct = min(80.0, plu_rules.emprise_max_pct or 100.0) \
        if zone_plu.upper().startswith("UA1") else (plu_rules.emprise_max_pct or 100.0)

    # Geometric cap by emprise %
    emprise_cap_m2 = terrain_area * emprise_max_pct / 100.0
    avant = current_emprise
    if not current.is_empty and current.area > emprise_cap_m2:
        from shapely.affinity import scale as _scale
        sf = (emprise_cap_m2 / current.area) ** 0.5
        current = _scale(current, xfact=sf, yfact=sf, origin=current.centroid)
        if binding_emprise is None:
            binding_emprise = "Emprise PLU UA1"
        current_emprise = current.area
        emprise_capped = True
    else:
        emprise_capped = False

    # Height : min(hauteur_max_m, niveaux_max * 3 + 0.5) + bonuses
    h_candidates: list[float] = []
    if plu_rules.hauteur_max_m is not None:
        h_candidates.append(plu_rules.hauteur_max_m)
    if plu_rules.hauteur_max_niveaux is not None:
        h_candidates.append(_height_from_niveaux(plu_rules.hauteur_max_niveaux))
    if not h_candidates:
        h_candidates.append(_HAUTEUR_PAR_NIVEAU_M)

    hauteur_base = min(h_candidates)
    hauteur_with_bonus = hauteur_base
    bonus_notes: list[str] = []
    if zone_plu.upper().startswith("UA1") and layers.ua1_bonus_toiture_eligible:
        hauteur_with_bonus += _UA1_BONUS_TOITURE_M
        bonus_notes.append(f"+{_UA1_BONUS_TOITURE_M} m toiture")
    niveaux_with_bonus = _niveaux_from_height(hauteur_with_bonus)
    if zone_plu.upper().startswith("UA1") and layers.ua1_bonus_pignon_eligible:
        niveaux_with_bonus += _UA1_BONUS_PIGNON_NIVEAUX
        hauteur_with_bonus = max(
            hauteur_with_bonus,
            _height_from_niveaux(niveaux_with_bonus),
        )
        bonus_notes.append(f"+{_UA1_BONUS_PIGNON_NIVEAUX} niveau pignon")

    # PPRI delta: surélever le plancher RDC = grignote la hauteur utile
    if ppri_delta_m > 0:
        hauteur_with_bonus = max(0.0, hauteur_with_bonus - ppri_delta_m)
        niveaux_with_bonus = _niveaux_from_height(hauteur_with_bonus)
        bonus_notes.append(f"-{ppri_delta_m:.2f} m PPRI surélévation")

    current_hauteur = hauteur_with_bonus
    current_niveaux = niveaux_with_bonus
    binding_hauteur = "PLU UA1 hauteur"
    applied.append(f"PLU {zone_plu} ({emprise_max_pct:.0f}%, {hauteur_base:.1f} m)")
    bonus_str = " | ".join(bonus_notes) if bonus_notes else "aucun bonus"
    trace.append(
        ConstraintStepTrace(
            step=9, name=f"PLU {zone_plu}", code_ref=f"{zone_plu} règlement",
            applied=True, binding=True,
            emprise_avant_m2=avant, emprise_apres_m2=current_emprise,
            hauteur_avant_m=0.0, hauteur_apres_m=current_hauteur,
            niveaux_avant=0, niveaux_apres=current_niveaux,
            rationale=(
                f"Emprise max {emprise_max_pct:.0f}% × {terrain_area:.0f} = "
                f"{emprise_cap_m2:.1f} m² "
                f"({'cap appliqué' if emprise_capped else 'cap inactif'}) ; "
                f"H base {hauteur_base:.2f} m → R+{current_niveaux} ({bonus_str})."
            ),
            geometry_after_geojson=_as_geojson(current, was_wgs84),
        )
    )

    # ------------------------------------------------------------------
    # Step 10 — Retrait latéral H/3 min 4m + retrait fond H ≤ 3m
    # ------------------------------------------------------------------
    avant = current_emprise
    retrait_lat = max(current_hauteur / 3.0, 4.0)
    retrait_fond = max(plu_rules.recul_fond_m or 0.0, 3.0)
    retrait = max(retrait_lat, retrait_fond)
    if not current.is_empty:
        new_geom = _safe_buffer(current, retrait)
        if not new_geom.is_empty:
            current = new_geom
            current_emprise = current.area
            if binding_emprise is None or current_emprise < avant:
                binding_emprise = "Retrait latéral H/3 min 4m"
            trace.append(
                ConstraintStepTrace(
                    step=10, name="Retrait latéral H/3 min 4m + fond ≥ 3m",
                    code_ref=f"{zone_plu}.7-8",
                    applied=True, binding=True,
                    emprise_avant_m2=avant, emprise_apres_m2=current_emprise,
                    hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale=(
                        f"Retrait isotrope max({retrait_lat:.2f}, {retrait_fond:.2f}) = "
                        f"{retrait:.2f} m → -{avant - current_emprise:.1f} m²."
                    ),
                    geometry_after_geojson=_as_geojson(current, was_wgs84),
                )
            )
        else:
            current = new_geom  # empty
            current_emprise = 0.0
            binding_emprise = "Retrait latéral H/3 min 4m"
            trace.append(
                ConstraintStepTrace(
                    step=10, name="Retrait latéral H/3 min 4m",
                    code_ref=f"{zone_plu}.7-8",
                    applied=True, binding=True,
                    emprise_avant_m2=avant, emprise_apres_m2=0.0,
                    hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale=(
                        f"Retrait {retrait:.2f} m fait disparaître l'emprise "
                        f"(parcelle trop étroite vs hauteur)."
                    ),
                )
            )
    else:
        trace.append(
            ConstraintStepTrace(
                step=10, name="Retrait latéral H/3 min 4m",
                code_ref=f"{zone_plu}.7-8",
                applied=False, binding=False,
                emprise_avant_m2=avant, emprise_apres_m2=avant,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Emprise déjà vide — retrait sans effet.",
            )
        )

    # ------------------------------------------------------------------
    # Step 11 — R.111-18 6m chambres vue voisin (BD TOPO neighbors)
    # ------------------------------------------------------------------
    avant = current_emprise
    if layers.neighbors and not current.is_empty:
        # For every neighbour with hauteur > 0, the buildable footprint must
        # leave a 6 m clearance for habitable rooms. We approximate by
        # subtracting a 6m buffer around the neighbours' footprint.
        neighbor_geoms = [
            _to_metric(n.geometry_geojson)[0]
            for n in layers.neighbors
            if n.is_principal
        ]
        if neighbor_geoms:
            neighbor_union = unary_union(neighbor_geoms)
            no_build_zone = neighbor_union.buffer(_R111_18_CHAMBRE_VUE_M)
            new_geom = current.difference(no_build_zone)
            if isinstance(new_geom, MultiPolygon):
                new_geom = max(new_geom.geoms, key=lambda g: g.area)
            current = new_geom
            current_emprise = current.area if not current.is_empty else 0.0
            binding = current_emprise < avant - 1e-3
            if binding and binding_emprise is None:
                binding_emprise = "R.111-18 chambres vue voisin"
            applied.append("R.111-18")
            trace.append(
                ConstraintStepTrace(
                    step=11, name="R.111-18 chambres vue voisin",
                    code_ref="R.111-18 CCH",
                    applied=True, binding=binding,
                    emprise_avant_m2=avant, emprise_apres_m2=current_emprise,
                    hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale=(
                        f"{len(neighbor_geoms)} voisin(s) BD TOPO → "
                        f"buffer {_R111_18_CHAMBRE_VUE_M} m : "
                        f"-{avant - current_emprise:.1f} m²."
                    ),
                    geometry_after_geojson=_as_geojson(current, was_wgs84),
                )
            )
        else:
            trace.append(
                ConstraintStepTrace(
                    step=11, name="R.111-18 chambres vue voisin",
                    code_ref="R.111-18 CCH",
                    applied=False, binding=False,
                    emprise_avant_m2=avant, emprise_apres_m2=avant,
                    hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale="Voisins déclarés mais aucun principal.",
                )
            )
    else:
        trace.append(
            ConstraintStepTrace(
                step=11, name="R.111-18 chambres vue voisin",
                code_ref="R.111-18 CCH",
                applied=False, binding=False,
                emprise_avant_m2=avant, emprise_apres_m2=avant,
                hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Aucun voisin BD TOPO ou emprise déjà vide.",
            )
        )

    # ------------------------------------------------------------------
    # Step 12 — Code civil 675-680 vue droite 1.90m (informatif)
    # ------------------------------------------------------------------
    trace.append(
        ConstraintStepTrace(
            step=12, name="Vue droite Code civil 675-680",
            code_ref="art. 675-680 CC",
            applied=True, binding=False,
            emprise_avant_m2=current_emprise, emprise_apres_m2=current_emprise,
            hauteur_avant_m=current_hauteur, hauteur_apres_m=current_hauteur,
            niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
            rationale=(
                f"Toute ouverture vue droite doit être à ≥ {_VUE_DROITE_CC_M} m "
                "de la limite séparative (contrainte sur la composition, pas l'enveloppe)."
            ),
        )
    )
    applied.append("Vue droite CC 675")

    # ------------------------------------------------------------------
    # Step 13 — Gabarit prospect H = f(L) si PLU prescrit
    # ------------------------------------------------------------------
    avant_h = current_hauteur
    if layers.gabarit_prospect is not None:
        gp = layers.gabarit_prospect
        # Estimate L = parcelle width along voirie axis = sqrt(area / ratio).
        # Conservative: take the shorter side of the OBB.
        bounds = parcelle_metric.minimum_rotated_rectangle.bounds
        bbx = bounds[2] - bounds[0]
        bby = bounds[3] - bounds[1]
        L = min(bbx, bby)
        if gp.type == "L_egal_H":
            h_cap = L
        elif gp.type == "L_egal_H_demi":
            h_cap = 2 * L
        elif gp.type == "L_egal_H_tiers":
            h_cap = 3 * L
        elif gp.type == "constant":
            h_cap = gp.constant_max_m or current_hauteur
        else:
            h_cap = current_hauteur
        if h_cap < current_hauteur:
            current_hauteur = h_cap
            current_niveaux = _niveaux_from_height(current_hauteur)
            binding_hauteur = "Gabarit prospect"
            applied.append(f"Gabarit prospect ({gp.type})")
            trace.append(
                ConstraintStepTrace(
                    step=13, name="Gabarit prospect", code_ref=f"{zone_plu}.10",
                    applied=True, binding=True,
                    emprise_avant_m2=current_emprise,
                    emprise_apres_m2=current_emprise,
                    hauteur_avant_m=avant_h, hauteur_apres_m=current_hauteur,
                    niveaux_avant=_niveaux_from_height(avant_h),
                    niveaux_apres=current_niveaux,
                    rationale=(
                        f"L={L:.2f} m × {gp.type} → H_max {h_cap:.2f} m "
                        f"(était {avant_h:.2f})."
                    ),
                )
            )
        else:
            trace.append(
                ConstraintStepTrace(
                    step=13, name="Gabarit prospect", code_ref=f"{zone_plu}.10",
                    applied=True, binding=False,
                    emprise_avant_m2=current_emprise,
                    emprise_apres_m2=current_emprise,
                    hauteur_avant_m=avant_h, hauteur_apres_m=avant_h,
                    niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                    rationale=(
                        f"Gabarit prospect L={L:.2f} m autorise H {h_cap:.2f} m, "
                        "non binding."
                    ),
                )
            )
    else:
        trace.append(
            ConstraintStepTrace(
                step=13, name="Gabarit prospect", code_ref=f"{zone_plu}.10",
                applied=False, binding=False,
                emprise_avant_m2=current_emprise, emprise_apres_m2=current_emprise,
                hauteur_avant_m=avant_h, hauteur_apres_m=avant_h,
                niveaux_avant=current_niveaux, niveaux_apres=current_niveaux,
                rationale="Aucun gabarit prospect prescrit par le PLU.",
            )
        )

    # ------------------------------------------------------------------
    # Final SDP — niveaux × emprise, capped by SDP / COS
    # ------------------------------------------------------------------
    niveaux_logement = current_niveaux - 1 if rdc_commerce_active else current_niveaux
    niveaux_logement = max(0, niveaux_logement)

    sdp_candidates: list[float] = [current_emprise * current_niveaux]
    sdp_source = "geometric"
    if plu_rules.sdp_max_m2 is not None:
        if plu_rules.sdp_max_m2 < sdp_candidates[0]:
            sdp_source = "SDP max PLU"
        sdp_candidates.append(plu_rules.sdp_max_m2)
    if plu_rules.cos is not None:
        cos_cap = plu_rules.cos * terrain_area
        if cos_cap < min(sdp_candidates):
            sdp_source = "COS × terrain"
        sdp_candidates.append(cos_cap)
    sdp_max_plu_m2 = min(sdp_candidates) if sdp_candidates else 0.0
    binding_sdp = sdp_source

    # Build the final EnvelopeMaxPLU
    envelope = EnvelopeMaxPLU(
        footprint_max_plu_geojson=_as_geojson(current, was_wgs84) if not current.is_empty else {},
        emprise_max_m2=max(current_emprise, 1e-9),
        emprise_max_pct=emprise_max_pct,
        niveaux_max_plu=current_niveaux,
        hauteur_max_plu_m=current_hauteur,
        sdp_max_plu_m2=sdp_max_plu_m2,
        retrait_applique_m=max(
            plu_rules.recul_voirie_m or 0.0,
            plu_rules.recul_limite_lat_m or 0.0,
            plu_rules.recul_fond_m or 0.0,
            retrait if 'retrait' in locals() else 0.0,
        ),
        notes=[t.rationale for t in trace if t.binding],
    )

    return MultiConstraintEnvelope(
        envelope=envelope,
        trace=trace,
        binding_constraint_emprise=binding_emprise,
        binding_constraint_hauteur=binding_hauteur,
        binding_constraint_sdp=binding_sdp,
        constraints_applied=applied,
    )
