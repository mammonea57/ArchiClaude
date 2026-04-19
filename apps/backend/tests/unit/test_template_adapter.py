# apps/backend/tests/unit/test_template_adapter.py
import json
import pytest
from core.templates_library.adapter import TemplateAdapter, FitResult
from core.templates_library.schemas import Template
from core.building_model.solver import ApartmentSlot
from core.building_model.schemas import Typologie
from shapely.geometry import Polygon


def _load(name: str) -> Template:
    with open(f"core/templates_library/seed/{name}.json") as f:
        return Template.model_validate(json.load(f))


def test_fit_t2_to_compatible_slot():
    template = _load("T2_bi_oriente")
    slot = ApartmentSlot(
        id="s1", polygon=Polygon([(0,0),(6.5,0),(6.5,7.8),(0,7.8)]),
        surface_m2=50.7, target_typologie=Typologie.T2,
        orientations=["sud", "nord"], position_in_floor="milieu",
    )
    result = TemplateAdapter().fit_to_slot(template, slot)
    assert result.success is True
    assert result.apartment is not None
    # All rooms placed
    assert len(result.apartment.rooms) == len(template.topologie["rooms"])
    # Surface total close to slot surface
    total_room_surface = sum(r.surface_m2 for r in result.apartment.rooms)
    assert abs(total_room_surface - slot.surface_m2) / slot.surface_m2 < 0.1  # ±10%


def test_fit_fails_if_slot_too_small():
    template = _load("T4_traversant")  # requires ≥8.5m × 9m
    slot = ApartmentSlot(
        id="s1", polygon=Polygon([(0,0),(5,0),(5,6),(0,6)]),  # 5×6 too small
        surface_m2=30.0, target_typologie=Typologie.T4,
        orientations=["sud"], position_in_floor="milieu",
    )
    result = TemplateAdapter().fit_to_slot(template, slot)
    assert result.success is False
    assert "dimensions" in (result.rejection_reason or "").lower() or \
           "small" in (result.rejection_reason or "").lower()


def test_fit_respects_stretch_tolerance():
    template = _load("T2_bi_oriente")
    # Slot width 8.0 while template max width is 7.5 — stretch = 8/7.5 = 1.067, OK <1.15
    slot = ApartmentSlot(
        id="s1", polygon=Polygon([(0,0),(8.0,0),(8.0,7.5),(0,7.5)]),
        surface_m2=60.0, target_typologie=Typologie.T2,
        orientations=["sud"], position_in_floor="milieu",
    )
    result = TemplateAdapter().fit_to_slot(template, slot)
    assert result.success is True

    # Slot width 9.5 while template max is 7.5 — stretch = 9.5/7.5 = 1.27 > 1.15 → fail
    too_wide = ApartmentSlot(
        id="s2", polygon=Polygon([(0,0),(9.5,0),(9.5,7.5),(0,7.5)]),
        surface_m2=71.0, target_typologie=Typologie.T2,
        orientations=["sud"], position_in_floor="milieu",
    )
    result2 = TemplateAdapter().fit_to_slot(template, too_wide)
    assert result2.success is False
