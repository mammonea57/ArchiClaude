"""Pydantic schemas for the full semantic BuildingModel.

This is the source-of-truth structure consumed by all rendering pipelines
(2D plans, 3D CADQuery, IFC, Blender, SDXL).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# ---------- Enums ----------

class RoomType(str, Enum):
    ENTREE = "entree"
    SEJOUR = "sejour"
    SEJOUR_CUISINE = "sejour_cuisine"
    CUISINE = "cuisine"
    SDB = "sdb"
    SALLE_DE_DOUCHE = "salle_de_douche"
    WC = "wc"
    WC_SDB = "wc_sdb"
    CHAMBRE_PARENTS = "chambre_parents"
    CHAMBRE_ENFANT = "chambre_enfant"
    CHAMBRE_SUPP = "chambre_supp"
    CELLIER = "cellier"
    PLACARD_TECHNIQUE = "placard_technique"
    LOGGIA = "loggia"


class WallType(str, Enum):
    PORTEUR = "porteur"
    CLOISON_70 = "cloison_70"
    CLOISON_100 = "cloison_100"
    DOUBLAGE_ISOLANT = "doublage_isolant"
    FENETRE_BAIE = "fenetre_baie"


class OpeningType(str, Enum):
    PORTE_ENTREE = "porte_entree"
    PORTE_INTERIEURE = "porte_interieure"
    FENETRE = "fenetre"
    PORTE_FENETRE = "porte_fenetre"
    BAIE_COULISSANTE = "baie_coulissante"


class CelluleType(str, Enum):
    LOGEMENT = "logement"
    COMMERCE = "commerce"
    TERTIAIRE = "tertiaire"
    PARKING = "parking"
    LOCAL_COMMUN = "local_commun"


class Typologie(str, Enum):
    STUDIO = "studio"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"


class Orientation(str, Enum):
    NORD = "nord"
    SUD = "sud"
    EST = "est"
    OUEST = "ouest"
    NORD_EST = "nord-est"
    NORD_OUEST = "nord-ouest"
    SUD_EST = "sud-est"
    SUD_OUEST = "sud-ouest"


class ToitureType(str, Enum):
    TERRASSE = "terrasse"
    DEUX_PANS = "2pans"
    QUATRE_PANS = "4pans"
    MANSARDE = "mansarde"


# ---------- Small leaves ----------

class ToitureConfig(BaseModel):
    type: ToitureType
    accessible: bool = False
    vegetalisee: bool = False


class Escalier(BaseModel):
    type: Literal["droit", "quart_tournant", "demi_tournant", "helicoidal"]
    giron_cm: int = Field(ge=25, le=35)
    hauteur_marche_cm: int = Field(ge=15, le=20)
    nb_marches_par_niveau: int = Field(ge=12, le=22)


class Ascenseur(BaseModel):
    type: str
    cabine_l_cm: int = Field(ge=100, le=200)
    cabine_p_cm: int = Field(ge=110, le=210)
    norme_pmr: bool = True


class GaineTechnique(BaseModel):
    type: Literal["eau", "elec", "vmc", "gaz", "fibres"]
    position_xy: tuple[float, float]


class Core(BaseModel):
    """Noyau commun : escalier + ascenseur + gaines."""
    position_xy: tuple[float, float]
    surface_m2: float = Field(gt=0)
    escalier: Escalier
    ascenseur: Ascenseur | None = None
    gaines_techniques: list[GaineTechnique] = Field(default_factory=list)
    # Actual rectangular polygon of the core (4 corner tuples). Present
    # when the core was computed by a topology-aware handler (e.g. the
    # L-layout dispatcher which places the core at the right half of a
    # landlocked slot). Absent for legacy heuristic placements — the
    # frontend then falls back to a `sqrt(surface_m2)` square.
    polygon_xy: list[tuple[float, float]] | None = None


class Wall(BaseModel):
    id: str
    type: WallType
    thickness_cm: int = Field(ge=5, le=50)
    geometry: dict[str, Any]  # GeoJSON LineString
    hauteur_cm: int = Field(ge=200, le=400)
    materiau: str


class Opening(BaseModel):
    id: str
    type: OpeningType
    wall_id: str
    position_along_wall_cm: int
    width_cm: int = Field(ge=60, le=400)
    height_cm: int = Field(ge=180, le=350)
    allege_cm: int | None = None
    swing: Literal["interior_left", "interior_right", "exterior_left", "exterior_right", "slide", "double"] | None = None
    has_vitrage: bool = False
    type_menuiserie: str | None = None
    vitrage: str | None = None


class Furniture(BaseModel):
    type: str
    position_xy: tuple[float, float]
    rotation_deg: float = 0.0


class Room(BaseModel):
    id: str
    type: RoomType
    surface_m2: float = Field(gt=0)
    polygon_xy: list[tuple[float, float]]
    orientation: list[str] | None = None
    label_fr: str
    furniture: list[Furniture] = Field(default_factory=list)


class Loggia(BaseModel):
    surface_m2: float
    polygon_xy: list[tuple[float, float]]


class Cellule(BaseModel):
    id: str
    type: CelluleType
    typologie: Typologie | None = None  # required if type=logement
    surface_m2: float = Field(gt=0)
    surface_shab_m2: float | None = None
    surface_sdp_m2: float | None = None
    polygon_xy: list[tuple[float, float]]
    orientation: list[str] = Field(default_factory=list)
    template_id: str | None = None
    loggia: Loggia | None = None
    rooms: list[Room] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)

    @field_validator("typologie")
    @classmethod
    def _logement_requires_typologie(cls, v, info):
        if info.data.get("type") == CelluleType.LOGEMENT and v is None:
            raise ValueError("cellule type=logement requires typologie")
        return v


class Circulation(BaseModel):
    id: str
    polygon_xy: list[tuple[float, float]]
    surface_m2: float
    largeur_min_cm: int = Field(ge=90)


class Niveau(BaseModel):
    index: int = Field(ge=-5, le=15)  # -1/-2 parkings, 0=RDC, up to R+15
    code: str  # "R+0", "R-1"
    usage_principal: Literal["commerce", "logements", "mixte", "parking", "tertiaire"]
    hauteur_sous_plafond_m: float = Field(ge=2.2, le=4.5)
    surface_plancher_m2: float = Field(gt=0)
    cellules: list[Cellule] = Field(default_factory=list)
    circulations_communes: list[Circulation] = Field(default_factory=list)


class Envelope(BaseModel):
    footprint_geojson: dict[str, Any]
    emprise_m2: float = Field(gt=0)
    niveaux: int = Field(ge=1, le=20)
    hauteur_totale_m: float = Field(gt=0)
    hauteur_rdc_m: float = Field(ge=2.5, le=5.0)
    hauteur_etage_courant_m: float = Field(ge=2.5, le=3.5)
    toiture: ToitureConfig


class Site(BaseModel):
    parcelle_geojson: dict[str, Any]
    parcelle_surface_m2: float = Field(gt=0)
    voirie_orientations: list[str]
    north_angle_deg: float = 0.0


class Metadata(BaseModel):
    id: UUID
    project_id: UUID
    address: str
    zone_plu: str
    created_at: datetime
    updated_at: datetime
    version: int = 1
    locked: bool = False


class Facade(BaseModel):
    style: str
    composition: list[dict[str, Any]] = Field(default_factory=list)
    rgb_main: str


class ConformiteAlert(BaseModel):
    level: Literal["info", "warning", "error"]
    category: Literal["pmr", "incendie", "plu", "surface", "ventilation", "lumiere"]
    message: str
    affected_element_id: str | None = None


class ConformiteCheck(BaseModel):
    pmr_ascenseur_ok: bool = True
    pmr_rotation_cercles_ok: bool = True
    incendie_distance_sorties_ok: bool = True
    plu_emprise_ok: bool = True
    plu_hauteur_ok: bool = True
    plu_retraits_ok: bool = True
    ventilation_ok: bool = True
    lumiere_ok: bool = True
    alerts: list[ConformiteAlert] = Field(default_factory=list)


class BuildingModel(BaseModel):
    """Full semantic representation of a building project."""
    metadata: Metadata
    site: Site
    envelope: Envelope
    core: Core
    niveaux: list[Niveau]
    facades: dict[Literal["nord", "sud", "est", "ouest"], Facade]
    materiaux_rendu: dict[str, Any] = Field(default_factory=dict)
    conformite_check: ConformiteCheck | None = None
