"""BuildingModel validator package.

Re-exports the legacy flat validator (PMR, incendie, ventilation,
lumiere, basic PLU) under the same import path used across the
codebase: ``from core.building_model.validator import validate_all``.

The newer pre-render conformite gate (PLU retraits + R.111-18 + business
rules) lives in :mod:`core.building_model.validator.conformite`.
"""
from __future__ import annotations

# Re-export every symbol that any caller (pipeline, tests, scripts)
# imports from the old module so the move is transparent.
from core.building_model._validator_legacy import (  # noqa: F401
    validate_all,
    validate_pmr,
    validate_pmr_building,
    validate_ventilation,
    validate_lumiere_naturelle,
    validate_incendie_niveau,
    validate_plu,
)

from core.building_model.validator.conformite import (  # noqa: F401
    BusinessRules,
    validate_conformite,
)

from core.building_model.validator.conformite_v2 import (  # noqa: F401
    ConformiteCheckItem,
    ConformiteCheckV2,
    OverlayContext,
    validate_conformite_v2,
)

__all__ = [
    "validate_all",
    "validate_pmr",
    "validate_pmr_building",
    "validate_ventilation",
    "validate_lumiere_naturelle",
    "validate_incendie_niveau",
    "validate_plu",
    "BusinessRules",
    "validate_conformite",
    # V2 — TOP 20 conformite gate
    "ConformiteCheckItem",
    "ConformiteCheckV2",
    "OverlayContext",
    "validate_conformite_v2",
]
