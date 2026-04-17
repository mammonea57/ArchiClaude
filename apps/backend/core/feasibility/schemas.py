"""Pydantic schemas for feasibility engine — Brief, FeasibilityResult, and supporting types."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from core.plu.schemas import NumericRules


class Brief(BaseModel):
    """User programme targets — what the developer wants to build."""

    destination: Literal["logement_collectif", "residence_service", "bureaux", "commerce", "mixte"]
    cible_nb_logements: int | None = None
    mix_typologique: dict[str, float] = Field(
        default_factory=lambda: {"T2": 0.3, "T3": 0.4, "T4": 0.3}
    )
    cible_sdp_m2: float | None = None
    hauteur_cible_niveaux: int | None = None  # total incl. RDC (R+3 → 4)
    emprise_cible_pct: float | None = None
    stationnement_cible_par_logement: float | None = None
    espaces_verts_pleine_terre_cible_pct: float | None = None


class ZoneApplicableInfo(BaseModel):
    """PLU zone that intersects the terrain, with its rules."""

    zone_id: UUID | None = None
    code: str
    libelle: str
    surface_intersectee_m2: float
    pct_of_terrain: float
    rules_numeric: NumericRules


class EcartItem(BaseModel):
    """Gap analysis between a brief target and the regulatory maximum."""

    target: str
    brief_value: float
    max_value: float
    ratio: float
    classification: Literal[
        "tres_sous_exploite", "sous_exploite", "coherent", "limite", "infaisable"
    ]
    commentaire: str


class Alert(BaseModel):
    """Blocking or advisory alert raised during feasibility computation."""

    level: Literal["info", "warning", "critical"]
    type: str
    message: str
    source: str


class VigilancePoint(BaseModel):
    """Non-blocking vigilance point that the developer should be aware of."""

    category: Literal["insertion", "recours", "patrimoine", "environnement", "technique"]
    message: str


class ComplianceResult(BaseModel):
    """Regulatory compliance outcomes (incendie, PMR, RE2020, SRU, RSDU)."""

    incendie_classement: str = "2eme"
    incendie_coef_reduction_sdp: float = 1.0
    pmr_ascenseur_obligatoire: bool = False
    pmr_surface_circulations_m2: float = 0.0
    pmr_nb_places_pmr: int = 0
    re2020_ic_construction_estime: float | None = None
    re2020_ic_energie_estime: float | None = None
    re2020_seuil_applicable: str = "2025"
    lls_commune_statut: str = "non_soumise"
    lls_obligation_pct: float | None = None
    lls_bonus_constructibilite_pct: float | None = None
    rsdu_applicable: bool = True
    rsdu_obligations: list[str] = Field(default_factory=list)


class FeasibilityResult(BaseModel):
    """Full feasibility result — geometry, capacity, compliance, and analysis."""

    surface_terrain_m2: float
    zones_applicables: list[ZoneApplicableInfo] = Field(default_factory=list)
    footprint_geojson: dict[str, Any] = Field(default_factory=dict)
    surface_emprise_m2: float = 0.0
    surface_pleine_terre_m2: float = 0.0
    hauteur_retenue_m: float = 0.0
    nb_niveaux: int = 0
    sdp_max_m2: float = 0.0
    sdp_max_m2_avant_compliance: float = 0.0
    nb_logements_max: int = 0
    nb_par_typologie: dict[str, int] = Field(default_factory=dict)
    nb_places_stationnement: int = 0
    nb_places_pmr: int = 0
    compliance: ComplianceResult | None = None
    ecart_brief: dict[str, EcartItem] = Field(default_factory=dict)
    servitudes_actives: list[dict] = Field(default_factory=list)
    alertes_dures: list[Alert] = Field(default_factory=list)
    points_vigilance: list[VigilancePoint] = Field(default_factory=list)
    confidence_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)
