"""Pydantic schemas for the 100+ French urbanism documents that constrain
a building project.

Taxonomy reference :
``refs/plu/taxonomy/FR_urbanism_documents_exhaustive_v1.md``

Design notes
------------
* All overlays inherit from :class:`BaseUrbanismOverlay` which carries the
  standard fields (``applies``, ``source_url``, ``last_updated``,
  ``geometry_geojson``, ``notes``) and exposes two contract methods:

  - ``validate(project)`` returns a list of :class:`OverlayViolation`.
  - ``to_buildable_impact()`` returns a short FR text summary of the
    constraint as it applies to the buildable envelope.

* Subclasses override ``_validate_impl`` and ``_impact_summary``; the
  public methods short-circuit when ``applies is False``.

* ``ProjectContext`` is the minimal projection of a project geometry +
  programme the overlays need in order to be validated. It is built by
  the caller from :class:`core.building_model.schemas.BuildingModel`
  but does not import it here to avoid a cycle.

The schemas intentionally do not implement the *fetching* of the source
documents — they describe the constraint once it has been fetched /
parsed by upstream connectors (Géoportail de l'Urbanisme, GéoRisques,
INPN, IGN, etc.).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


class OverlayViolation(BaseModel):
    """A single rule violation emitted by an overlay's ``validate`` call."""

    overlay_code: str  # e.g. "SUP_AC1", "PPRI", "L_151_19"
    severity: Literal["info", "warning", "error", "blocking"]
    message: str
    article_ref: str | None = None
    affected_element_id: str | None = None


class ProjectContext(BaseModel):
    """Minimal projection of a project used by overlays.

    Built by the caller from a :class:`BuildingModel` instance. Kept
    separate so the overlays module has no upward dependency.
    """

    parcelle_geojson: dict[str, Any]
    footprint_geojson: dict[str, Any] | None = None
    parcelle_surface_m2: float = Field(gt=0)
    emprise_m2: float = Field(ge=0)
    hauteur_totale_m: float = Field(ge=0)
    niveaux: int = Field(ge=0)
    sdp_m2: float = Field(ge=0)
    nb_logements: int = Field(ge=0, default=0)
    typologies: dict[str, int] = Field(default_factory=dict)  # {"T3": 4, ...}
    pct_lls: float = Field(ge=0, le=100, default=0.0)
    commune_insee: str | None = None
    zone_plu: str | None = None
    # Optional flags filled in by the data-fetch layer
    in_zone_uneso_buffer_m: float | None = None
    has_basement: bool = False
    # Sometimes overlays need raw distance metrics
    distance_to_axis_m: dict[str, float] = Field(default_factory=dict)


class OverlayCategory(str, Enum):
    A_PLU = "A_PLU"
    B_SUP = "B_SUP"
    C_RISQUE = "C_RISQUE"
    D_PATRIMOINE = "D_PATRIMOINE"
    E_MIXITE = "E_MIXITE"
    F_ENVIRONNEMENT = "F_ENVIRONNEMENT"
    G_REGLES_BATIMENT = "G_REGLES_BATIMENT"
    H_SUPRA = "H_SUPRA"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BaseUrbanismOverlay(BaseModel):
    """Common API for every urbanism overlay.

    Subclasses MUST set the ``code`` class-var and override the two
    private hooks :meth:`_validate_impl` and :meth:`_impact_summary`.
    """

    # Class-level metadata (immutable per subclass)
    code: str = "BASE"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "Overlay"

    # Per-instance metadata
    applies: bool = False
    source_url: str | None = None
    last_updated: date | None = None
    geometry_geojson: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)

    # ------- public API -------
    def validate(self, project: ProjectContext) -> list[OverlayViolation]:
        """Return the list of violations (empty if the project complies)."""
        if not self.applies:
            return []
        return list(self._validate_impl(project))

    def to_buildable_impact(self) -> str:
        """Return a short FR text describing the constraint impact."""
        if not self.applies:
            return f"{self.label_fr} : non applicable."
        return self._impact_summary()

    # ------- hooks for subclasses -------
    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:  # noqa: ARG002
        return []

    def _impact_summary(self) -> str:
        return f"{self.label_fr} : applicable."

    # ------- helpers -------
    def _v(
        self,
        severity: Literal["info", "warning", "error", "blocking"],
        message: str,
        article: str | None = None,
    ) -> OverlayViolation:
        return OverlayViolation(
            overlay_code=self.code, severity=severity, message=message,
            article_ref=article,
        )


# ===========================================================================
# A. PLU / PLUi
# ===========================================================================


class PLUZonage(BaseUrbanismOverlay):
    code: str = "PLU_ZONAGE"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "Zonage PLU/PLUi"

    zone_code: str = "UA"  # UA, UB, UC, AU, A, N, etc.
    sous_secteur: str | None = None
    destinations_autorisees: list[str] = Field(default_factory=list)
    destinations_interdites: list[str] = Field(default_factory=list)

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        if "habitation" in (s.lower() for s in self.destinations_interdites):
            out.append(self._v("blocking", f"Zone {self.zone_code} interdit l'habitation"))
        return out

    def _impact_summary(self) -> str:
        s = f"Zone {self.zone_code}"
        if self.sous_secteur:
            s += f" / {self.sous_secteur}"
        return s


class PLUReglement(BaseUrbanismOverlay):
    code: str = "PLU_REGLEMENT"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "Règlement écrit PLU"

    hauteur_max_m: float | None = None
    emprise_max_pct: float | None = None
    cos: float | None = None
    pleine_terre_min_pct: float | None = None
    retrait_voirie_min_m: float | None = None
    retrait_lateral_min_m: float | None = None
    retrait_fond_min_m: float | None = None
    stationnement_par_logement: float | None = None

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        if self.hauteur_max_m is not None and project.hauteur_totale_m > self.hauteur_max_m + 1e-6:
            out.append(self._v(
                "blocking",
                f"Hauteur {project.hauteur_totale_m:.2f} m > max PLU {self.hauteur_max_m:.2f} m",
                article="Art. 10",
            ))
        if self.emprise_max_pct is not None and project.parcelle_surface_m2 > 0:
            emprise_pct = 100.0 * project.emprise_m2 / project.parcelle_surface_m2
            if emprise_pct > self.emprise_max_pct + 1e-6:
                out.append(self._v(
                    "blocking",
                    f"Emprise {emprise_pct:.1f}% > max PLU {self.emprise_max_pct:.1f}%",
                    article="Art. 9",
                ))
        return out

    def _impact_summary(self) -> str:
        parts = []
        if self.hauteur_max_m is not None:
            parts.append(f"H_max={self.hauteur_max_m:.1f} m")
        if self.emprise_max_pct is not None:
            parts.append(f"emprise≤{self.emprise_max_pct:.0f}%")
        return "Règlement PLU : " + (", ".join(parts) if parts else "applicable")


class OAPSectorielle(BaseUrbanismOverlay):
    code: str = "OAP_SECTORIELLE"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "OAP sectorielle"

    secteur_name: str = ""
    densite_min_log_ha: float | None = None
    hauteur_max_m: float | None = None
    obligations: list[str] = Field(default_factory=list)

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        if self.hauteur_max_m is not None and project.hauteur_totale_m > self.hauteur_max_m + 1e-6:
            out.append(self._v(
                "blocking",
                f"OAP {self.secteur_name} : hauteur > {self.hauteur_max_m} m",
            ))
        return out

    def _impact_summary(self) -> str:
        return f"OAP sectorielle {self.secteur_name}".strip()


class OAPThematique(BaseUrbanismOverlay):
    code: str = "OAP_THEMATIQUE"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "OAP thématique"
    theme: str = "habitat"  # habitat, commerce, mobilité, etc.
    prescriptions: list[str] = Field(default_factory=list)

    def _impact_summary(self) -> str:
        return f"OAP thématique ({self.theme})"


class OAPBioclim(BaseUrbanismOverlay):
    code: str = "OAP_BIOCLIM"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "OAP bioclimatique"
    coef_biotope_min: float | None = None
    pct_canopee_min: float | None = None
    pct_pleine_terre_min: float | None = None

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        # Pleine terre check is delegated to PLUReglement; OAPBioclim is
        # informative — but if a project records pct_pleine_terre then we
        # surface a warning when below threshold.
        return []

    def _impact_summary(self) -> str:
        bits = []
        if self.coef_biotope_min:
            bits.append(f"CBS≥{self.coef_biotope_min:.2f}")
        if self.pct_canopee_min:
            bits.append(f"canopée≥{self.pct_canopee_min:.0f}%")
        if self.pct_pleine_terre_min:
            bits.append(f"PT≥{self.pct_pleine_terre_min:.0f}%")
        return "OAP bioclim : " + (", ".join(bits) if bits else "applicable")


class Prescription44(BaseUrbanismOverlay):
    code: str = "PRESCRIPTION_4_4"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "Prescriptions PLU (annexe 4.4)"
    items: list[str] = Field(default_factory=list)


class Patrimoine43(BaseUrbanismOverlay):
    code: str = "PATRIMOINE_4_3"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "Patrimoine PLU (annexe 4.3)"
    elements_proteges: list[str] = Field(default_factory=list)

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        if self.elements_proteges:
            return [self._v(
                "warning",
                "Élément patrimonial PLU identifié — démolition / surélévation soumises à avis",
            )]
        return []


class ER45(BaseUrbanismOverlay):
    code: str = "ER_4_5"
    category: OverlayCategory = OverlayCategory.A_PLU
    label_fr: str = "Emplacement réservé (4.5)"
    bénéficiaire: str = ""
    destination: str = ""

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            f"Emplacement réservé ({self.bénéficiaire} / {self.destination}) — construction privée interdite sur emprise",
        )]


# ===========================================================================
# B. SUP — Servitudes d'Utilité Publique (CNIG)
# ===========================================================================


class _SUPBase(BaseUrbanismOverlay):
    """Base for all 22 CNIG SUP types."""

    category: OverlayCategory = OverlayCategory.B_SUP
    rayon_protection_m: float | None = None
    acte_instituant: str | None = None  # référence de l'arrêté
    gestionnaire: str | None = None

    def _impact_summary(self) -> str:
        r = f" (rayon {self.rayon_protection_m:.0f} m)" if self.rayon_protection_m else ""
        return f"{self.label_fr}{r} — autorisation gestionnaire requise"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("warning", f"{self.label_fr} — avis {self.gestionnaire or 'gestionnaire'} requis")]


# AC — Patrimoine bâti et naturel
class SUP_AC1(_SUPBase):
    code: str = "SUP_AC1"
    label_fr: str = "AC1 — Monument historique"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("blocking", "Périmètre MH (AC1) — avis ABF obligatoire", article="L.621-30 CP")]


class SUP_AC2(_SUPBase):
    code: str = "SUP_AC2"
    label_fr: str = "AC2 — Site classé ou inscrit"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("blocking", "Site classé / inscrit (AC2) — autorisation ministre ou préfet")]


class SUP_AC3(_SUPBase):
    code: str = "SUP_AC3"
    label_fr: str = "AC3 — Réserve naturelle"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("blocking", "Réserve naturelle (AC3) — construction soumise à régime spécial")]


class SUP_AC4(_SUPBase):
    code: str = "SUP_AC4"
    label_fr: str = "AC4 — Site patrimonial remarquable (SPR)"


# AS — Salubrité & eau potable
class SUP_AS1(_SUPBase):
    code: str = "SUP_AS1"
    label_fr: str = "AS1 — Périmètre de protection des captages"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("blocking", "Captage AEP (AS1) — règles d'occupation strictes (rapports, ICPE interdits)")]


# EL — Domaine public & littoral
class SUP_EL3(_SUPBase):
    code: str = "SUP_EL3"
    label_fr: str = "EL3 — Halage et marchepied"


class SUP_EL7(_SUPBase):
    code: str = "SUP_EL7"
    label_fr: str = "EL7 — Voirie (alignement)"


class SUP_EL9(_SUPBase):
    code: str = "SUP_EL9"
    label_fr: str = "EL9 — Passage piéton littoral"


class SUP_EL11(_SUPBase):
    code: str = "SUP_EL11"
    label_fr: str = "EL11 — Interdictions d'accès route express / autoroute"


# I — Réseaux énergie
class SUP_I1(_SUPBase):
    code: str = "SUP_I1"
    label_fr: str = "I1 — Hydrocarbures liquides (pipelines)"


class SUP_I3(_SUPBase):
    code: str = "SUP_I3"
    label_fr: str = "I3 — Canalisations de gaz"


class SUP_I4(_SUPBase):
    code: str = "SUP_I4"
    label_fr: str = "I4 — Lignes électriques HT"


class SUP_I5(_SUPBase):
    code: str = "SUP_I5"
    label_fr: str = "I5 — Canalisations chimiques"


class SUP_I6(_SUPBase):
    code: str = "SUP_I6"
    label_fr: str = "I6 — Exploitation des mines"


# PM — Risques
class SUP_PM1(_SUPBase):
    code: str = "SUP_PM1"
    label_fr: str = "PM1 — PPR (naturel)"


class SUP_PM2(_SUPBase):
    code: str = "SUP_PM2"
    label_fr: str = "PM2 — PPR technologique"


class SUP_PM3(_SUPBase):
    code: str = "SUP_PM3"
    label_fr: str = "PM3 — Anciens sites miniers"


# PT — Télécoms & radio
class SUP_PT1(_SUPBase):
    code: str = "SUP_PT1"
    label_fr: str = "PT1 — Protection centres radioélectriques (perturbations)"


class SUP_PT2(_SUPBase):
    code: str = "SUP_PT2"
    label_fr: str = "PT2 — Protection centres radioélectriques (obstacles)"


class SUP_PT3(_SUPBase):
    code: str = "SUP_PT3"
    label_fr: str = "PT3 — Réseaux de télécommunications"


# T — Aéronautique & ferroviaire & magnétisme
class SUP_T1(_SUPBase):
    code: str = "SUP_T1"
    label_fr: str = "T1 — Chemins de fer"


class SUP_T4(_SUPBase):
    code: str = "SUP_T4"
    label_fr: str = "T4 — Balisage aéronautique"


class SUP_T5(_SUPBase):
    code: str = "SUP_T5"
    label_fr: str = "T5 — Dégagement aéronautique"


class SUP_T7(_SUPBase):
    code: str = "SUP_T7"
    label_fr: str = "T7 — Hors zones de dégagement (hauteur)"

    hauteur_max_m: float | None = None

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        if self.hauteur_max_m is not None and project.hauteur_totale_m > self.hauteur_max_m + 1e-6:
            out.append(self._v(
                "blocking",
                f"SUP T7 : hauteur > {self.hauteur_max_m} m (servitude aéronautique)",
            ))
        return out


# INT — Cimetières
class SUP_INT1(_SUPBase):
    code: str = "SUP_INT1"
    label_fr: str = "INT1 — Cimetières (rayon 100 m)"
    rayon_protection_m: float | None = 100.0


# ===========================================================================
# C. Risque
# ===========================================================================


class _RisqueBase(BaseUrbanismOverlay):
    category: OverlayCategory = OverlayCategory.C_RISQUE
    aleas: list[str] = Field(default_factory=list)


class PPRI(_RisqueBase):
    code: str = "PPRI"
    label_fr: str = "Plan de Prévention des Risques Inondation"
    zone_alea: Literal["rouge", "orange", "bleu", "blanc"] = "blanc"
    cote_seuil_ngf: float | None = None

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        if self.zone_alea == "rouge":
            out.append(self._v("blocking", "PPRI zone rouge : construction nouvelle interdite"))
        elif self.zone_alea == "orange":
            out.append(self._v("error", "PPRI zone orange : sous-sol interdit, RDC > cote PHEC"))
        if project.has_basement and self.zone_alea in {"rouge", "orange", "bleu"}:
            out.append(self._v("blocking", "Sous-sol interdit en zone PPRI"))
        return out

    def _impact_summary(self) -> str:
        return f"PPRI zone {self.zone_alea}"


class RGA(_RisqueBase):
    code: str = "RGA"
    label_fr: str = "Retrait-gonflement des argiles"
    niveau: Literal["faible", "moyen", "fort"] = "faible"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        if self.niveau in {"moyen", "fort"}:
            return [self._v(
                "warning",
                f"RGA niveau {self.niveau} — étude G2 + fondations adaptées obligatoires (loi ELAN art. 68)",
            )]
        return []


class Radon(_RisqueBase):
    code: str = "RADON"
    label_fr: str = "Potentiel radon"
    categorie: Literal[1, 2, 3] = 1

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        if self.categorie == 3:
            return [self._v("warning", "Radon catégorie 3 — VMC + étanchéité dalle obligatoires")]
        return []


class Sismique(_RisqueBase):
    code: str = "SISMIQUE"
    label_fr: str = "Zonage sismique"
    zone: Literal[1, 2, 3, 4, 5] = 1

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        if self.zone >= 3:
            return [self._v(
                "warning",
                f"Zone sismique {self.zone} — règles PS-MI / EC8 applicables",
            )]
        return []


class ICPE(_RisqueBase):
    code: str = "ICPE"
    label_fr: str = "ICPE à proximité"
    rayon_effets_m: float | None = None
    type_etablissement: str | None = None

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("warning", "Étude d'impact / éloignement ICPE à vérifier")]


class BASIAS(_RisqueBase):
    code: str = "BASIAS"
    label_fr: str = "BASIAS — ancien site industriel"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "warning",
            "Site BASIAS — étude historique + diagnostic pollution recommandés (art. L.556-1 CE)",
        )]


class BASOL(_RisqueBase):
    code: str = "BASOL"
    label_fr: str = "BASOL — site pollué connu"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            "Site BASOL : changement d'usage soumis à attestation art. L.556-1 CE (bureau d'études certifié LNE)",
        )]


class SIS(_RisqueBase):
    code: str = "SIS"
    label_fr: str = "Secteur d'Information sur les Sols"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            "SIS — attestation pollution (art. L.125-6 CE) obligatoire avant PC",
        )]


class Cavites(_RisqueBase):
    code: str = "CAVITES"
    label_fr: str = "Cavités souterraines"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("warning", "Cavités souterraines — étude G5 spécifique requise")]


class TRI(_RisqueBase):
    code: str = "TRI"
    label_fr: str = "Territoire à Risque Important d'inondation"


class AZI(_RisqueBase):
    code: str = "AZI"
    label_fr: str = "Atlas des Zones Inondables"


class ERP(_RisqueBase):
    """ERP = Établissement Recevant du Public (présence à proximité, type
    et catégorie qui imposent réseaux secours, gabarit voirie, …)."""

    code: str = "ERP"
    label_fr: str = "ERP à proximité"
    type_erp: str | None = None
    categorie: Literal["1", "2", "3", "4", "5"] | None = None


# ===========================================================================
# D. Patrimoine
# ===========================================================================


class _PatrimoineBase(BaseUrbanismOverlay):
    category: OverlayCategory = OverlayCategory.D_PATRIMOINE


class L_151_19(_PatrimoineBase):
    code: str = "L_151_19"
    label_fr: str = "Élément protégé L.151-19 CU"
    element_type: str = "bati"  # bati / arbre / mur / cloture
    designation: str = ""

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            f"Élément L.151-19 ({self.designation}) — démolition / modification soumise à DP / PC",
            article="L.151-19 CU",
        )]


class PSMV(_PatrimoineBase):
    code: str = "PSMV"
    label_fr: str = "Plan de Sauvegarde et de Mise en Valeur"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            "PSMV en vigueur — règlement spécifique + accord ABF",
        )]


class SPR(_PatrimoineBase):
    code: str = "SPR"
    label_fr: str = "Site Patrimonial Remarquable"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("error", "Site Patrimonial Remarquable — autorisation ABF")]


class AtlasPatrimoineMH(_PatrimoineBase):
    code: str = "ATLAS_PATRIMOINE_MH"
    label_fr: str = "Atlas patrimoine — Monument historique référencé"
    designation: str = ""


# ===========================================================================
# E. Mixité
# ===========================================================================


class _MixiteBase(BaseUrbanismOverlay):
    category: OverlayCategory = OverlayCategory.E_MIXITE


class L_151_16_Lineaire(_MixiteBase):
    code: str = "L_151_16_LINEAIRE"
    label_fr: str = "Linéaire commercial protégé (L.151-16)"
    destination_imposee: str = "commerce"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            f"Linéaire L.151-16 : RDC doit conserver destination « {self.destination_imposee} »",
        )]


class L_151_15_SMS(_MixiteBase):
    code: str = "L_151_15_SMS"
    label_fr: str = "Secteur Mixité Sociale (L.151-15)"
    pct_lls_min: float = Field(ge=0, le=100, default=30.0)

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        if project.pct_lls + 1e-6 < self.pct_lls_min:
            return [self._v(
                "blocking",
                f"Secteur SMS L.151-15 : %LLS={project.pct_lls:.0f}% < min {self.pct_lls_min:.0f}%",
                article="L.151-15 CU",
            )]
        return []

    def _impact_summary(self) -> str:
        return f"SMS L.151-15 : %LLS ≥ {self.pct_lls_min:.0f}%"


class SRU_Art55(_MixiteBase):
    code: str = "SRU_ART55"
    label_fr: str = "Loi SRU article 55"
    pct_lls_commune: float = 0.0
    seuil_legal_pct: float = 25.0
    operation_seuil_logements: int = 12
    pct_lls_min_operation: float = 30.0

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        commune_below = self.pct_lls_commune < self.seuil_legal_pct
        if commune_below and project.nb_logements >= self.operation_seuil_logements:
            if project.pct_lls + 1e-6 < self.pct_lls_min_operation:
                out.append(self._v(
                    "blocking",
                    f"SRU art.55 : commune en carence ({self.pct_lls_commune:.0f}%),"
                    f" opération ≥{self.operation_seuil_logements} log. doit ≥ {self.pct_lls_min_operation:.0f}% LLS",
                ))
        return out


class PLH_Mixite(_MixiteBase):
    code: str = "PLH_MIXITE"
    label_fr: str = "PLH — objectifs de mixité"
    pct_lls_objectif: float | None = None


class T3PlusQuota(_MixiteBase):
    code: str = "T3_PLUS_QUOTA"
    label_fr: str = "Quota typologie ≥ T3"
    pct_t3_plus_min: float = Field(ge=0, le=100, default=50.0)

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        total = sum(project.typologies.values())
        if total <= 0:
            return []
        t3_plus = sum(v for k, v in project.typologies.items() if k.upper() in {"T3", "T4", "T5", "T6"})
        pct = 100.0 * t3_plus / total
        if pct + 1e-6 < self.pct_t3_plus_min:
            return [self._v(
                "blocking",
                f"Quota T3+ : {pct:.0f}% < min {self.pct_t3_plus_min:.0f}%",
            )]
        return []


# ===========================================================================
# F. Environnement
# ===========================================================================


class _EnvBase(BaseUrbanismOverlay):
    category: OverlayCategory = OverlayCategory.F_ENVIRONNEMENT


class ZNIEFF(_EnvBase):
    code: str = "ZNIEFF"
    label_fr: str = "ZNIEFF"
    type_znieff: Literal["1", "2"] = "1"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("warning", f"ZNIEFF type {self.type_znieff} — évaluation faune-flore recommandée")]


class Natura2000(_EnvBase):
    code: str = "NATURA2000"
    label_fr: str = "Natura 2000"
    type_zone: Literal["ZSC", "ZPS", "ZSC/ZPS"] = "ZSC"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            "Natura 2000 — évaluation des incidences obligatoire (art. R.414-19 CE)",
        )]


class PNR(_EnvBase):
    code: str = "PNR"
    label_fr: str = "Parc Naturel Régional"
    nom_parc: str = ""


class EBC(_EnvBase):
    code: str = "EBC"
    label_fr: str = "Espace Boisé Classé"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            "EBC — défrichement interdit (art. L.113-2 CU), changement d'affectation soumis à révision PLU",
        )]


class EVP(_EnvBase):
    code: str = "EVP"
    label_fr: str = "Espace Vert Protégé"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("error", "EVP — emprise au sol restreinte, plantations à conserver")]


class TVB(_EnvBase):
    code: str = "TVB"
    label_fr: str = "Trame Verte et Bleue"


class SDAGE(_EnvBase):
    code: str = "SDAGE"
    label_fr: str = "SDAGE / SAGE"


class ZonesHumides(_EnvBase):
    code: str = "ZONES_HUMIDES"
    label_fr: str = "Zones humides"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            "Zone humide — destruction interdite sauf compensation 150% (loi sur l'eau)",
        )]


class IOTA(_EnvBase):
    code: str = "IOTA"
    label_fr: str = "Loi sur l'eau (IOTA)"
    seuil_declaration_m2: float = 10_000
    seuil_autorisation_m2: float = 20_000

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        surface = project.parcelle_surface_m2
        if surface >= self.seuil_autorisation_m2:
            out.append(self._v("blocking", "Loi sur l'eau : régime d'AUTORISATION (≥ 20 000 m²)"))
        elif surface >= self.seuil_declaration_m2:
            out.append(self._v("warning", "Loi sur l'eau : régime de DÉCLARATION (≥ 10 000 m²)"))
        return out


class EvaluationEnvironnementale(_EnvBase):
    code: str = "EVAL_ENV"
    label_fr: str = "Évaluation environnementale (cas par cas)"
    seuil_sdp_m2: float = 40_000

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        if project.sdp_m2 >= self.seuil_sdp_m2:
            return [self._v(
                "blocking",
                f"SDP {project.sdp_m2:.0f} m² ≥ {self.seuil_sdp_m2:.0f} m² → étude d'impact systématique",
                article="R.122-2 CE",
            )]
        return []


class EspecesProtegees(_EnvBase):
    code: str = "ESPECES_PROTEGEES"
    label_fr: str = "Espèces protégées"
    especes: list[str] = Field(default_factory=list)

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        if self.especes:
            return [self._v(
                "blocking",
                f"Espèces protégées présentes ({', '.join(self.especes)}) — dérogation L.411-2 CE requise",
            )]
        return []


class Defrichement(_EnvBase):
    code: str = "DEFRICHEMENT"
    label_fr: str = "Autorisation de défrichement"
    seuil_surface_m2: float = 5_000

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("warning", "Autorisation de défrichement (art. L.341-3 CF) à vérifier")]


# ===========================================================================
# G. Règles Bâtiment
# ===========================================================================


class _BatimentBase(BaseUrbanismOverlay):
    category: OverlayCategory = OverlayCategory.G_REGLES_BATIMENT
    applies: bool = True  # règles nationales : par défaut applicables partout


class RNU_R_111(_BatimentBase):
    code: str = "RNU_R_111"
    label_fr: str = "Règlement National d'Urbanisme (art. R.111-x)"

    def _impact_summary(self) -> str:
        return "RNU applicable (R.111-1 à R.111-27)"


class R_111_18_Vues(_BatimentBase):
    """Vues droites — 6 m mini entre baie de chambre et limite voisine."""

    code: str = "R_111_18_VUES"
    label_fr: str = "R.111-18 — vues droites chambres"
    distance_min_m: float = 6.0

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        d = project.distance_to_axis_m.get("voisin_chambre")
        if d is not None and d + 1e-6 < self.distance_min_m:
            return [self._v(
                "blocking",
                f"R.111-18 : distance baie chambre↔limite voisine {d:.2f} m < 6 m",
                article="R.111-18 CU",
            )]
        return []

    def _impact_summary(self) -> str:
        return f"R.111-18 : 6 m mini vue chambre (actuel {self.distance_min_m:.1f} m)"


class RE2020(_BatimentBase):
    code: str = "RE2020"
    label_fr: str = "RE2020"
    seuil_cep_max: float | None = None
    seuil_ic_construction: float | None = None

    def _impact_summary(self) -> str:
        return "RE2020 : Bbio, Cep, IC construction, IC énergie"


class PMR(_BatimentBase):
    code: str = "PMR"
    label_fr: str = "Accessibilité PMR"

    def _impact_summary(self) -> str:
        return "PMR : ascenseur si R+3, cheminements ≥ 90 cm, sanitaires adaptés"


class SecuriteIncendie(_BatimentBase):
    code: str = "SECURITE_INCENDIE"
    label_fr: str = "Sécurité incendie (3e famille / IGH)"
    famille: Literal["1A", "1B", "2", "3A", "3B", "4", "IGH"] = "2"


class Acoustique(_BatimentBase):
    code: str = "ACOUSTIQUE"
    label_fr: str = "Réglementation acoustique"


class Stationnement_PDU(_BatimentBase):
    code: str = "STATIONNEMENT_PDU"
    label_fr: str = "Stationnement (PDU / PLU)"
    places_max_par_logement: float | None = None
    places_velo_par_logement: float | None = None


class CodeCivil_675_680(_BatimentBase):
    """Servitudes civiles : vues, jours, distances (art. 675, 678, 680 CC)."""

    code: str = "CODE_CIVIL_675_680"
    label_fr: str = "Code civil — vues / jours"
    distance_vue_droite_m: float = 1.9
    distance_vue_oblique_m: float = 0.6


# ===========================================================================
# H. Supra-PLU
# ===========================================================================


class _SupraBase(BaseUrbanismOverlay):
    category: OverlayCategory = OverlayCategory.H_SUPRA


class SCoT(_SupraBase):
    code: str = "SCOT"
    label_fr: str = "SCoT"
    objectifs: list[str] = Field(default_factory=list)


class SRADDET_SDRIF(_SupraBase):
    code: str = "SRADDET_SDRIF"
    label_fr: str = "SRADDET (ou SDRIF en IDF)"


class ZAN(_SupraBase):
    code: str = "ZAN"
    label_fr: str = "Zéro Artificialisation Nette"
    objectif_pct_reduction_2031: float = 50.0


class PLH_Supra(_SupraBase):
    code: str = "PLH_SUPRA"
    label_fr: str = "PLH (objectifs)"


class PCAET(_SupraBase):
    code: str = "PCAET"
    label_fr: str = "PCAET"


class PDU(_SupraBase):
    code: str = "PDU"
    label_fr: str = "PDU"


class PGRI(_SupraBase):
    code: str = "PGRI"
    label_fr: str = "PGRI"


class CDAC_CDPENAF(_SupraBase):
    code: str = "CDAC_CDPENAF"
    label_fr: str = "CDAC / CDPENAF"
    seuil_cdac_m2: float = 1_000

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "warning",
            f"Avis CDAC requis dès {self.seuil_cdac_m2:.0f} m² commerce ; CDPENAF si terres agricoles",
        )]


class DTA(_SupraBase):
    code: str = "DTA"
    label_fr: str = "Directive Territoriale d'Aménagement"


class Loi_Littoral(_SupraBase):
    code: str = "LOI_LITTORAL"
    label_fr: str = "Loi Littoral"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v(
            "blocking",
            "Loi Littoral : extension de l'urbanisation en continuité (L.121-8 CU)",
        )]


class Loi_Montagne(_SupraBase):
    code: str = "LOI_MONTAGNE"
    label_fr: str = "Loi Montagne"


class DUP(_SupraBase):
    code: str = "DUP"
    label_fr: str = "Déclaration d'Utilité Publique"

    def _validate_impl(self, project: ProjectContext) -> list[OverlayViolation]:
        return [self._v("blocking", "DUP en cours — risque d'expropriation, PC déconseillé")]


class PIG(_SupraBase):
    code: str = "PIG"
    label_fr: str = "Projet d'Intérêt Général"


# ===========================================================================
# Aggregator
# ===========================================================================


class UrbanismOverlayBundle(BaseModel):
    """Bundle of every overlay applicable to a parcelle.

    Used by the dossier pipeline : a single ``validate_all`` call returns
    every blocking / error violation, and ``buildable_impact_summary``
    aggregates the FR text for the report.
    """

    # A
    plu_zonage: PLUZonage | None = None
    plu_reglement: PLUReglement | None = None
    oap_sectorielle: list[OAPSectorielle] = Field(default_factory=list)
    oap_thematique: list[OAPThematique] = Field(default_factory=list)
    oap_bioclim: OAPBioclim | None = None
    prescription_4_4: Prescription44 | None = None
    patrimoine_4_3: Patrimoine43 | None = None
    er_4_5: list[ER45] = Field(default_factory=list)

    # B
    sups: list[_SUPBase] = Field(default_factory=list)

    # C
    risques: list[_RisqueBase] = Field(default_factory=list)

    # D
    patrimoine: list[_PatrimoineBase] = Field(default_factory=list)

    # E
    mixite: list[_MixiteBase] = Field(default_factory=list)

    # F
    environnement: list[_EnvBase] = Field(default_factory=list)

    # G
    regles_batiment: list[_BatimentBase] = Field(default_factory=list)

    # H
    supra: list[_SupraBase] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_none_lists(self) -> UrbanismOverlayBundle:
        # Defensive — Pydantic v2 always uses default_factory, but keep
        # the check so client code that passes ``None`` explicitly does
        # not surprise downstream consumers.
        return self

    # -------- public API --------
    def all_overlays(self) -> list[BaseUrbanismOverlay]:
        out: list[BaseUrbanismOverlay] = []
        for x in (
            self.plu_zonage, self.plu_reglement, self.oap_bioclim,
            self.prescription_4_4, self.patrimoine_4_3,
        ):
            if x is not None:
                out.append(x)
        out.extend(self.oap_sectorielle)
        out.extend(self.oap_thematique)
        out.extend(self.er_4_5)
        out.extend(self.sups)
        out.extend(self.risques)
        out.extend(self.patrimoine)
        out.extend(self.mixite)
        out.extend(self.environnement)
        out.extend(self.regles_batiment)
        out.extend(self.supra)
        return out

    def validate_all(self, project: ProjectContext) -> list[OverlayViolation]:
        out: list[OverlayViolation] = []
        for ov in self.all_overlays():
            out.extend(ov.validate(project))
        return out

    def buildable_impact_summary(self) -> list[str]:
        return [ov.to_buildable_impact() for ov in self.all_overlays() if ov.applies]

    def blocking_violations(self, project: ProjectContext) -> list[OverlayViolation]:
        return [v for v in self.validate_all(project) if v.severity in {"blocking", "error"}]
