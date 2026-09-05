"""Urbanism overlays — exhaustive Pydantic schemas for 100+ French urbanism
documents that constrain a building project (PLU/PLUi, SUP, Risques,
Patrimoine, Mixité, Environnement, Règles Bâtiment, documents supra-PLU).

The taxonomy is canonical to
``refs/plu/taxonomy/FR_urbanism_documents_exhaustive_v1.md`` and is grouped
into 8 categories (A..H). Every overlay exposes the same minimal API:

* ``applies: bool``     — does this overlay apply to the parcelle?
* ``source_url``        — URL to the official source (DDT, géoportail, etc.)
* ``last_updated``      — date of the latest publication / révision
* ``geometry_geojson``  — optional GeoJSON polygon of the prescription
* ``validate(project)`` — returns a list of :class:`OverlayViolation`
* ``to_buildable_impact()`` — concise FR text summary for the dossier
"""

from core.urbanism_overlays.schemas import (  # noqa: F401
    # Base
    BaseUrbanismOverlay,
    OverlayViolation,
    ProjectContext,
    # A. PLU / PLUi
    PLUZonage,
    PLUReglement,
    OAPSectorielle,
    OAPThematique,
    OAPBioclim,
    Prescription44,
    Patrimoine43,
    ER45,
    # B. SUP (22 types CNIG)
    SUP_AC1, SUP_AC2, SUP_AC3, SUP_AC4,
    SUP_AS1,
    SUP_EL3, SUP_EL7, SUP_EL9, SUP_EL11,
    SUP_I1, SUP_I3, SUP_I4, SUP_I5, SUP_I6,
    SUP_PM1, SUP_PM2, SUP_PM3,
    SUP_PT1, SUP_PT2, SUP_PT3,
    SUP_T1, SUP_T4, SUP_T5, SUP_T7,
    SUP_INT1,
    # C. Risque
    PPRI, RGA, Radon, Sismique, ICPE,
    BASIAS, BASOL, SIS, Cavites, TRI, AZI, ERP,
    # D. Patrimoine
    L_151_19, PSMV, SPR, AtlasPatrimoineMH,
    # E. Mixité
    L_151_16_Lineaire, L_151_15_SMS, SRU_Art55, PLH_Mixite, T3PlusQuota,
    # F. Environnement
    ZNIEFF, Natura2000, PNR, EBC, EVP, TVB, SDAGE, ZonesHumides,
    IOTA, EvaluationEnvironnementale, EspecesProtegees, Defrichement,
    # G. Règles bâtiment
    RNU_R_111, R_111_18_Vues, RE2020, PMR,
    SecuriteIncendie, Acoustique, Stationnement_PDU, CodeCivil_675_680,
    # H. Supra
    SCoT, SRADDET_SDRIF, ZAN, PLH_Supra, PCAET, PDU,
    PGRI, CDAC_CDPENAF, DTA, Loi_Littoral, Loi_Montagne, DUP, PIG,
    # Aggregator
    UrbanismOverlayBundle,
)
