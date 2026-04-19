from shapely.geometry import Polygon

from core.building_model.schemas import Typologie
from core.building_model.solver import build_modular_grid, compute_apartment_slots, place_core


def test_compute_slots_for_simple_mix():
    footprint = Polygon([(0,0),(18,0),(18,12),(0,12)])  # 18×12 = 216m²
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=20.0)
    mix = {Typologie.T2: 0.4, Typologie.T3: 0.4, Typologie.T4: 0.2}  # 40% T2, 40% T3, 20% T4
    slots = compute_apartment_slots(grid, core, mix_typologique=mix, voirie_side="sud")
    # Expect at least some slots; typologies may be re-labelled by
    # _reclassify_by_surface (so mix membership is not guaranteed).
    assert len(slots) >= 2
    assert all(s.target_typologie is not None for s in slots)
    # Slots tile the footprint minus the circulation network. Corridor +
    # core + connectors typically eat 30-60 m² on this 18×12 = 216 m²
    # footprint, leaving ~150-180 m² for apts. Some slots may be dropped
    # when they get clipped below the 20 m² minimum.
    total = sum(s.surface_m2 for s in slots)
    assert 50 < total < 220


def test_slots_have_orientation():
    footprint = Polygon([(0,0),(18,0),(18,12),(0,12)])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=20.0)
    mix = {Typologie.T2: 0.5, Typologie.T3: 0.5}
    slots = compute_apartment_slots(grid, core, mix_typologique=mix, voirie_side="sud")
    # At least some slots face sud (voirie)
    sud_facing = [s for s in slots if "sud" in s.orientations]
    assert len(sud_facing) >= 1
