from core.building_model.solver import build_modular_grid, place_core, compute_apartment_slots
from core.building_model.schemas import Typologie
from shapely.geometry import Polygon


def test_compute_slots_for_simple_mix():
    footprint = Polygon([(0,0),(18,0),(18,12),(0,12)])  # 18×12 = 216m²
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=20.0)
    mix = {Typologie.T2: 0.4, Typologie.T3: 0.4, Typologie.T4: 0.2}  # 40% T2, 40% T3, 20% T4
    slots = compute_apartment_slots(grid, core, mix_typologique=mix, voirie_side="sud")
    # Expect some slots; each slot has a target_typo + surface + position
    assert len(slots) >= 3
    assert all(s.target_typologie in mix for s in slots)
    # Total slot surface approximately equals footprint - core - circulations
    total = sum(s.surface_m2 for s in slots)
    assert 150 < total < 200  # roughly (216 - 20 - circulations)


def test_slots_have_orientation():
    footprint = Polygon([(0,0),(18,0),(18,12),(0,12)])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=20.0)
    mix = {Typologie.T2: 0.5, Typologie.T3: 0.5}
    slots = compute_apartment_slots(grid, core, mix_typologique=mix, voirie_side="sud")
    # At least some slots face sud (voirie)
    sud_facing = [s for s in slots if "sud" in s.orientations]
    assert len(sud_facing) >= 1
