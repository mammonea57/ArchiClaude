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
    # Dégagement NUIT (T4/T5 uniquement) : petit couloir desservant TOUTES les
    # chambres + SdB, pour que le séjour redevienne un rectangle net (pas gonflé
    # de circulation). Distinct de l'entrée/hall fermé interdit en open-plan.
    DEGAGEMENT_NUIT = "degagement_nuit"


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
    # kind : "balcon" = saillie projetée (autorisée SEULEMENT côté cour/jardin,
    # survol de terrain privé) ; "loggia" = creusée EN RETRAIT dans le volume
    # (obligatoire côté RUE — jamais de saillie au-dessus du trottoir, UA.6). Au
    # RDC : jamais de balcon saillant (on est au sol) → au mieux une loggia.
    kind: Literal["balcon", "loggia"] = "balcon"


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
    # Explicit axis-aligned jardin polygon for RDC logements. When set,
    # the frontend renders this polygon directly instead of extruding the
    # jardin from the apt's exterior walls. Needed to correctly tile
    # exterior "pocket" zones (e.g. an L-notch shared between two apts)
    # where the naive per-wall extrusion overlaps or misses the zone.
    jardin_polygon_xy: list[tuple[float, float]] | None = None

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
    # COUR INTÉRIEURE OUVERTE (2026-07-06) : trou traversant à ciel ouvert au
    # centre d'un immeuble sur cour (L / U). Ce polygone est un VIDE dans le
    # plancher (retiré de surface_plancher_m2), rendu comme un espace planté à
    # ciel ouvert (pas une dalle de circulation). Présent à TOUS les niveaux (la
    # cour est un vide vertical traversant R+0..R+N). None = pas de cour.
    cour_polygon_xy: list[tuple[float, float]] | None = None
    # ESPACE VERT COMMUN au RDC (2026-07-07) : le RÉSIDU de la cour arrière que
    # personne ne peut atteindre proprement en restant devant SA façade (fond de
    # coin profond) est un jardin PARTAGÉ planté, distinct des jardins privatifs
    # (rendu vert avec hachure/teinte différente + label « jardin commun »). Les
    # jardins privatifs vivent sur chaque Cellule (jardin_polygon_xy) ; celui-ci
    # est unique par niveau. None = pas de résidu commun (privatifs couvrent tout).
    jardin_commun_polygon_xy: list[tuple[float, float]] | None = None
    # PARTI ATRIUM PLANTÉ (2026-07-09) : quand True, la cour (``cour_polygon_xy``)
    # n'est PAS un patio ouvert bordant la cage, mais un ATRIUM sous VERRIÈRE avec
    # le noyau esc+ASC PLANTÉ EN SON CENTRE — on monte à travers un jardin. La cage
    # touche le couloir sur UNE face ; l'anneau vert planté entoure les 3 autres.
    # Aménité marquée pour le rendu 3D (verrière/puits de lumière + label ATRIUM +
    # socle planté autour du noyau au RDC). None/False = cour ouverte simple (v23).
    atrium_verriere: bool = False
    # PARTI v23 FINANÇABLE (2026-07-09, défaut) : escalier ENCLOISONNÉ (conforme
    # évacuation R+5) adossé à un ANGLE de la cour, sa PAROI côté cour étant VITRÉE
    # (on voit le vert en montant). La cour reste À CIEL OUVERT, plantée (cœur
    # d'îlot). Marqué pour le rendu 2D (liseré vitré + label COUR PLANTÉE) et la
    # base 3D (paroi vitrée sur cour plantée + paliers plantés). Exclusif d'atrium.
    cage_vitree_cour: bool = False


class Envelope(BaseModel):
    footprint_geojson: dict[str, Any]
    emprise_m2: float = Field(gt=0)
    niveaux: int = Field(ge=1, le=20)
    hauteur_totale_m: float = Field(gt=0)
    hauteur_rdc_m: float = Field(ge=2.5, le=5.0)
    hauteur_etage_courant_m: float = Field(ge=2.5, le=3.5)
    toiture: ToitureConfig


class EnvelopeMaxPLU(BaseModel):
    """Maximum PLU envelope — what the parcelle COULD sustain if optimised
    against the PLU rules, independent of the actual designed project.

    Stored alongside the designed ``Envelope`` so investors / lenders can
    see the gap between the proposed programme and the legal ceiling.
    """
    footprint_max_plu_geojson: dict[str, Any]
    emprise_max_m2: float = Field(gt=0)
    emprise_max_pct: float = Field(ge=0.0, le=100.0)
    niveaux_max_plu: int = Field(ge=0, le=20)
    hauteur_max_plu_m: float = Field(ge=0.0)
    sdp_max_plu_m2: float = Field(ge=0.0)
    # Bookkeeping: which retrait was the binding constraint
    retrait_applique_m: float = Field(ge=0.0)
    notes: list[str] = Field(default_factory=list)


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
    category: Literal[
        "pmr", "incendie", "plu", "surface", "ventilation", "lumiere",
        "business", "r111_18", "typologie",
        # TOP 20 conformite V2 categories — see
        # refs/plu/taxonomy/FR_urbanism_documents_exhaustive_v1.md
        "oap", "abf", "ppri", "pprt", "sru_sms", "sup_canalisation",
        "rga", "pollution", "ebc", "l151_19", "natura2000", "cdpenaf",
        "cdac", "re2020", "stationnement", "lineaire_commercial",
    ]
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
    # Pre-render gate booleans (default True = unchecked / no violation).
    business_marge_ok: bool = True
    business_lls_quota_ok: bool = True
    business_typologie_ok: bool = True
    r111_18_chambres_ok: bool = True
    alerts: list[ConformiteAlert] = Field(default_factory=list)
    # Blocking errors emitted by the conformite validator (PLU + R.111-18
    # + business). Non-blocking warnings live in ``warnings``. Kept
    # separate from ``alerts`` so the pre-render gate can fail fast
    # without re-walking the legacy alert list.
    errors: list[ConformiteAlert] = Field(default_factory=list)
    warnings: list[ConformiteAlert] = Field(default_factory=list)

    def has_blocking_errors(self) -> bool:
        """True if any error-level alert (errors or legacy alerts) blocks rendering."""
        if any(a.level == "error" for a in self.errors):
            return True
        return any(a.level == "error" for a in self.alerts)

    def blocking_summary(self) -> list[dict]:
        """Return a JSON-friendly list of blocking violations for HTTP detail."""
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for a in list(self.errors) + list(self.alerts):
            if a.level != "error":
                continue
            key = (a.category, a.message)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "category": a.category,
                "message": a.message,
                "affected_element_id": a.affected_element_id,
            })
        return out


class BuildingModel(BaseModel):
    """Full semantic representation of a building project."""
    metadata: Metadata
    site: Site
    envelope: Envelope
    envelope_max_plu: EnvelopeMaxPLU | None = None
    core: Core
    niveaux: list[Niveau]
    facades: dict[Literal["nord", "sud", "est", "ouest"], Facade]
    materiaux_rendu: dict[str, Any] = Field(default_factory=dict)
    conformite_check: ConformiteCheck | None = None
    # Optional bundle of every urbanism overlay (PLU/PLUi, SUP, risque,
    # patrimoine, mixité, environnement, règles bâtiment, supra) that
    # constrains the project. Kept as ``Any`` to avoid a hard import
    # cycle with :mod:`core.urbanism_overlays.schemas`. Callers attach
    # an :class:`UrbanismOverlayBundle` instance directly.
    urbanism_overlays: Any | None = None
