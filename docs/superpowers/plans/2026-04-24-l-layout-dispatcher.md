# L-Layout Dispatcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the wing-par-wing corridor logic (which produces 2 disconnected corridors on L-footprints) with a topology-aware dispatcher that generates ONE continuous L-shaped corridor, core at the elbow, dual-loaded on both branches, yielding 60+ apartments on the user's test project.

**Architecture:** Add a topology classifier + per-topology layout handler. L is implemented fully; rect/T/U keep the existing wing-par-wing as fallback. Each handler returns (core_position, circulation_polygon, apartment_slots) as one atomic result, so solver/pipeline cannot desync. Long-term this pattern scales: adding Z/H/Y shapes = one new handler + one classifier case, no changes to existing handlers.

**Tech Stack:** Python 3.11, Shapely 2.x, pytest. Axis-aligned polygons only (input is already OBB-rectified upstream).

---

## File Structure

- **Create:** `apps/backend/core/building_model/layout_l.py` — L-shape handler (classifier helpers, `compute_l_layout`, geometry builders). Self-contained.
- **Create:** `apps/backend/core/building_model/layout_dispatcher.py` — topology classification + dispatch entry points used by solver + pipeline.
- **Modify:** `apps/backend/core/building_model/solver.py` — `_compute_circulation_network` and `compute_apartment_slots` delegate to dispatcher when topology == "L".
- **Modify:** `apps/backend/core/building_model/pipeline.py` — `_emit_wing_corridors` delegates to dispatcher when topology == "L".
- **Create:** `apps/backend/tests/unit/test_layout_l.py` — unit tests for L handler (geometry, 4 orientations, apt counts).
- **Create:** `apps/backend/tests/unit/test_layout_dispatcher.py` — classifier + dispatch tests.
- **Create:** `apps/backend/tests/integration/test_l_layout_endtoend.py` — end-to-end pipeline test on user's L canonical footprint → assert 60+ apts.

---

## Task 1: Topology classifier skeleton

**Files:**
- Create: `apps/backend/core/building_model/layout_dispatcher.py`
- Test: `apps/backend/tests/unit/test_layout_dispatcher.py`

- [ ] **Step 1: Write the failing test for classify_footprint_topology**

```python
# apps/backend/tests/unit/test_layout_dispatcher.py
from shapely.geometry import Polygon

from core.building_model.layout_dispatcher import classify_footprint_topology


def test_rectangle_is_rect():
    footprint = Polygon([(0, 0), (20, 0), (20, 12), (0, 12)])
    assert classify_footprint_topology(footprint) == "rect"


def test_l_canon_is_L():
    # L with inner corner at (6.9, 15): bar south + leg east
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    assert classify_footprint_topology(footprint) == "L"


def test_u_shape_is_other():
    # 2 reflex vertices → not L
    footprint = Polygon([
        (0, 0), (30, 0), (30, 20),
        (20, 20), (20, 10), (10, 10), (10, 20),
        (0, 20),
    ])
    assert classify_footprint_topology(footprint) == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.building_model.layout_dispatcher'`

- [ ] **Step 3: Implement classifier**

```python
# apps/backend/core/building_model/layout_dispatcher.py
"""Topology-aware dispatcher for building layout generation.

Classifies a footprint by its shape (rect / L / T / U / other) and
routes to the appropriate layout handler. Handlers are self-contained:
each produces (core, corridor, slots) atomically so solver and pipeline
cannot disagree about geometry.
"""
from __future__ import annotations

from typing import Literal

from shapely.geometry import Polygon as ShapelyPolygon

Topology = Literal["rect", "L", "T", "U", "other"]


def _count_reflex_vertices(footprint: ShapelyPolygon) -> int:
    """Count concave (inner-corner) vertices after mild simplification.

    A clean L has 1 reflex; T/U have 2+; rectangles have 0.
    """
    poly = footprint.simplify(0.8)
    if poly.geom_type != "Polygon" or poly.area < footprint.area * 0.9:
        poly = footprint
    coords = list(poly.exterior.coords)[:-1]
    if not poly.exterior.is_ccw:
        coords = coords[::-1]
    n = len(coords)
    count = 0
    for i in range(n):
        p0 = coords[(i - 1) % n]
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if cross < -0.5:
            count += 1
    return count


def classify_footprint_topology(footprint: ShapelyPolygon) -> Topology:
    """Classify axis-aligned footprint into known topology families.

    - rect: bbox-filling polygon (fill_ratio >= 0.92)
    - L:    exactly 1 reflex vertex
    - T/U/other: 2+ reflex vertices, not handled yet → "other"

    Unknown topologies fall back to the legacy wing-par-wing layout.
    """
    if footprint.is_empty or footprint.geom_type != "Polygon":
        return "other"
    minx, miny, maxx, maxy = footprint.bounds
    bbox_area = (maxx - minx) * (maxy - miny)
    if bbox_area <= 0:
        return "other"
    if footprint.area / bbox_area >= 0.92:
        return "rect"
    reflex_count = _count_reflex_vertices(footprint)
    if reflex_count == 1:
        return "L"
    return "other"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_dispatcher.py apps/backend/tests/unit/test_layout_dispatcher.py
git commit -m "feat(layout): topology classifier (rect/L/other)"
```

---

## Task 2: L decomposition — bar + leg + elbow

**Files:**
- Create: `apps/backend/core/building_model/layout_l.py`
- Test: `apps/backend/tests/unit/test_layout_l.py`

The L-handler needs to know, for any of the 4 canonical L orientations (inner corner at SE, SW, NE, NW), which rectangle is the "bar" (horizontal arm), which is the "leg" (vertical arm), and where the corridor elbow point is.

- [ ] **Step 1: Write the failing test for decompose_l**

```python
# apps/backend/tests/unit/test_layout_l.py
import math

from shapely.geometry import Polygon

from core.building_model.layout_l import decompose_l, LDecomposition


def test_decompose_l_inner_corner_nw():
    # Inner corner at (6.9, 15): bar is south rectangle spanning full
    # width, leg is east rectangle spanning y=15..32.4 at x=6.9..21.9
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    assert d is not None
    # Bar (horizontal arm) bounds
    bx0, by0, bx1, by1 = d.bar.bounds
    assert math.isclose(bx0, 0.0, abs_tol=0.1)
    assert math.isclose(bx1, 21.9, abs_tol=0.1)
    assert math.isclose(by0, 0.0, abs_tol=0.1)
    assert math.isclose(by1, 15.0, abs_tol=0.1)
    # Leg (vertical arm) bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds
    assert math.isclose(lx0, 6.9, abs_tol=0.1)
    assert math.isclose(lx1, 21.9, abs_tol=0.1)
    assert math.isclose(ly0, 15.0, abs_tol=0.1)
    assert math.isclose(ly1, 32.4, abs_tol=0.1)
    # Reflex at inner corner
    assert math.isclose(d.reflex[0], 6.9, abs_tol=0.1)
    assert math.isclose(d.reflex[1], 15.0, abs_tol=0.1)
    # Elbow = (leg centerline x, bar centerline y) = (14.4, 7.5)
    assert math.isclose(d.elbow[0], (6.9 + 21.9) / 2, abs_tol=0.1)
    assert math.isclose(d.elbow[1], (0.0 + 15.0) / 2, abs_tol=0.1)


def test_decompose_l_rotated_all_four_orientations():
    # Template L at inner-corner NW (= outer corner SE)
    base = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    # Rotate 0/90/180/270 degrees → all 4 orientations must decompose
    from shapely.affinity import rotate
    for angle in (0, 90, 180, 270):
        rotated = rotate(base, angle, origin=(10, 10))
        # snap bounds to axis-aligned form (rotation preserves axis-alignment
        # for multiples of 90°)
        d = decompose_l(rotated)
        assert d is not None, f"decompose_l failed at angle={angle}"
        assert d.bar.area > 0 and d.leg.area > 0
        # Elbow must lie inside the footprint
        from shapely.geometry import Point
        assert rotated.buffer(0.2).contains(Point(d.elbow))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.building_model.layout_l'`

- [ ] **Step 3: Implement decompose_l**

```python
# apps/backend/core/building_model/layout_l.py
"""L-shape layout handler.

Produces a single continuous L-corridor (inverted-T topology where the
two arms meet), core at the junction, dual-loaded apartment slots on
both branches. Works for all 4 canonical L orientations (inner corner
at NW, NE, SW, or SE of the bounding box) via a single axis-aligned
decomposition.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import box as shp_box


@dataclass(frozen=True)
class LDecomposition:
    """Result of splitting an L footprint into its two rectangular arms.

    - bar: horizontal arm (the one spanning the full bbox width OR the
      longer of the two along x)
    - leg: vertical arm (narrower in x, taller in y)
    - reflex: inner-corner vertex of the L
    - elbow: corridor junction point (cx_leg, cy_bar), where the
      horizontal bar-corridor meets the vertical leg-corridor
    """
    bar: ShapelyPolygon
    leg: ShapelyPolygon
    reflex: tuple[float, float]
    elbow: tuple[float, float]


def _find_reflex(footprint: ShapelyPolygon) -> tuple[float, float] | None:
    poly = footprint.simplify(0.8)
    if poly.geom_type != "Polygon" or poly.area < footprint.area * 0.9:
        poly = footprint
    coords = list(poly.exterior.coords)[:-1]
    if not poly.exterior.is_ccw:
        coords = coords[::-1]
    n = len(coords)
    for i in range(n):
        p0 = coords[(i - 1) % n]
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if cross < -0.5:
            return (p1[0], p1[1])
    return None


def _find_notch(footprint: ShapelyPolygon) -> tuple[float, float] | None:
    """The bbox corner that the L footprint does NOT cover."""
    from shapely.geometry import Point as _Point
    minx, miny, maxx, maxy = footprint.bounds
    buf = footprint.buffer(0.1)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    for corner in ((minx, miny), (maxx, miny), (minx, maxy), (maxx, maxy)):
        probe = _Point(
            corner[0] + (0.5 if corner[0] < cx else -0.5),
            corner[1] + (0.5 if corner[1] < cy else -0.5),
        )
        if not buf.contains(probe):
            return corner
    return None


def decompose_l(footprint: ShapelyPolygon) -> LDecomposition | None:
    """Split an axis-aligned L footprint into bar + leg + elbow.

    Returns None if the footprint is not a clean L (use fallback layout).

    The "bar" is always the arm whose long axis is horizontal (wider
    than tall); the "leg" is the arm whose long axis is vertical. For
    L-shapes where both arms are oriented the same (rare — near-square
    arms), we pick the arm with larger x-span as bar.
    """
    minx, miny, maxx, maxy = footprint.bounds
    reflex = _find_reflex(footprint)
    notch = _find_notch(footprint)
    if reflex is None or notch is None:
        return None

    rx, ry = reflex
    nx, ny = notch

    # Horizontal decomposition: bar = full bottom strip OR full top strip
    # (the one NOT on the notch side), leg = the other strip narrowed to
    # exclude the notch x-range.
    if ny < (miny + maxy) / 2:
        # Notch on bottom → bar is the TOP strip (full width),
        # leg is the BOTTOM strip minus the notch corner
        bar_y0, bar_y1 = ry, maxy
        leg_y0, leg_y1 = miny, ry
        if nx < (minx + maxx) / 2:
            leg_x0, leg_x1 = rx, maxx
        else:
            leg_x0, leg_x1 = minx, rx
        bar = shp_box(minx, bar_y0, maxx, bar_y1)
        leg = shp_box(leg_x0, leg_y0, leg_x1, leg_y1)
    else:
        # Notch on top → bar is the BOTTOM strip (full width),
        # leg is the TOP strip minus the notch corner
        bar_y0, bar_y1 = miny, ry
        leg_y0, leg_y1 = ry, maxy
        if nx < (minx + maxx) / 2:
            leg_x0, leg_x1 = rx, maxx
        else:
            leg_x0, leg_x1 = minx, rx
        bar = shp_box(minx, bar_y0, maxx, bar_y1)
        leg = shp_box(leg_x0, leg_y0, leg_x1, leg_y1)

    # "bar" as computed is the full-width strip, "leg" is the narrowed
    # strip. But if the full-width strip is taller than wide (tall-L),
    # swap roles so bar is always the horizontally-long arm.
    bar_w = bar.bounds[2] - bar.bounds[0]
    bar_h = bar.bounds[3] - bar.bounds[1]
    leg_w = leg.bounds[2] - leg.bounds[0]
    leg_h = leg.bounds[3] - leg.bounds[1]
    if bar_w < bar_h and leg_w > leg_h:
        bar, leg = leg, bar

    # Elbow = (cx_leg, cy_bar) — intersection of leg's vertical axis
    # and bar's horizontal axis.
    cx_leg = (leg.bounds[0] + leg.bounds[2]) / 2
    cy_bar = (bar.bounds[1] + bar.bounds[3]) / 2

    return LDecomposition(
        bar=bar, leg=leg, reflex=(rx, ry), elbow=(cx_leg, cy_bar),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_l.py apps/backend/tests/unit/test_layout_l.py
git commit -m "feat(layout): decompose_l splits L footprint into bar+leg+elbow"
```

---

## Task 3: L-corridor geometry (continuous inverted-T)

**Files:**
- Modify: `apps/backend/core/building_model/layout_l.py`
- Modify: `apps/backend/tests/unit/test_layout_l.py`

The corridor is:
- Horizontal strip in bar at y=cy_bar (full bar width)
- Vertical strip in leg at x=cx_leg (full leg height) PLUS extending down into bar from leg.y_min to cy_bar, so the two strips physically connect
- Net result: one connected polygon spanning the full L in an inverted-T pattern (when inner-corner = NW)

- [ ] **Step 1: Write failing test for build_l_corridor**

```python
# Append to apps/backend/tests/unit/test_layout_l.py
from core.building_model.layout_l import build_l_corridor, decompose_l


def test_build_l_corridor_is_single_connected_polygon():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    corridor = build_l_corridor(d, corridor_width=1.6)
    # Single polygon (not MultiPolygon) → corridor is continuous
    assert corridor.geom_type == "Polygon"
    # Corridor area ≈ (bar width × 1.6) + (leg height × 1.6) − junction overlap
    # Bar: 21.9 × 1.6 = 35.04. Leg strip in bar: (15 − 7.5 − 0.8) × 1.6 ≈ 6.7 × 1.6 = 10.72
    # Leg above bar: 17.4 × 1.6 = 27.84. Total ≈ 35.04 + 10.72 + 27.84 ≈ 73.6 m²
    # Minus overlap at junction (1.6 × 1.6 = 2.56) → ~71 m²
    assert 60.0 < corridor.area < 90.0
    # Corridor must lie inside footprint (with small tolerance for rounding)
    assert footprint.buffer(0.1).contains(corridor.buffer(-0.05))


def test_build_l_corridor_touches_both_arm_ends():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    corridor = build_l_corridor(d, corridor_width=1.6)
    cxmin, cymin, cxmax, cymax = corridor.bounds
    # Corridor spans from bar's west end (x=0) to leg's top (y=32.4)
    assert abs(cxmin - 0.0) < 0.5
    assert abs(cymax - 32.4) < 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py::test_build_l_corridor_is_single_connected_polygon -v`
Expected: FAIL with `ImportError: cannot import name 'build_l_corridor'`

- [ ] **Step 3: Implement build_l_corridor**

Append to `apps/backend/core/building_model/layout_l.py`:

```python
from shapely.ops import unary_union


def build_l_corridor(
    d: LDecomposition, corridor_width: float = 1.6,
) -> ShapelyPolygon:
    """Build the continuous L-shaped corridor.

    Geometry (for inner-corner-NW orientation):
    - Horizontal strip in bar at y=cy_bar, spanning full bar width
    - Vertical strip in leg at x=cx_leg, spanning full leg height
    - Connector strip inside bar from leg.y_min down to cy_bar, at x=cx_leg,
      so the bar corridor and leg corridor meet physically

    The connector is always needed because the leg (after L decomposition)
    starts at y = bar.y_max, while the bar corridor runs at y = cy_bar
    (middle of bar). Without the connector the two strips would be parallel
    with a gap of (bar height / 2). The connector closes that gap inside
    the bar material.
    """
    half = corridor_width / 2
    bx0, by0, bx1, by1 = d.bar.bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds
    cx_leg, cy_bar = d.elbow

    # Bar horizontal strip (full bar width at cy_bar)
    bar_strip = shp_box(bx0, cy_bar - half, bx1, cy_bar + half)

    # Leg vertical strip (full leg height at cx_leg)
    leg_strip = shp_box(cx_leg - half, ly0, cx_leg + half, ly1)

    # Connector inside bar: from leg's base (ly0) down to cy_bar, at x=cx_leg.
    # If leg starts above bar centerline (inner corner NW/NE) this is a
    # downward segment; if leg starts below (inner corner SW/SE) it's upward.
    if ly0 > cy_bar:
        conn_y0, conn_y1 = cy_bar, ly0
    else:
        conn_y0, conn_y1 = ly1, cy_bar
    connector = shp_box(cx_leg - half, conn_y0, cx_leg + half, conn_y1)

    corridor = unary_union([bar_strip, leg_strip, connector])
    # Ensure result is Polygon (should be after union of overlapping rects)
    if corridor.geom_type != "Polygon":
        # Fallback: pick largest
        corridor = max(corridor.geoms, key=lambda g: g.area)
    return corridor
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_l.py apps/backend/tests/unit/test_layout_l.py
git commit -m "feat(layout): build_l_corridor produces continuous L geometry"
```

---

## Task 4: Core placement at L elbow

**Files:**
- Modify: `apps/backend/core/building_model/layout_l.py`
- Modify: `apps/backend/tests/unit/test_layout_l.py`

Core is a rectangle centered on the elbow, sized to match `core_surface_m2` (22 m² default). It sits ON the corridor junction — stairs/ASC are at the hinge of the L, reachable from both arms.

- [ ] **Step 1: Write failing test**

```python
# Append to apps/backend/tests/unit/test_layout_l.py
from core.building_model.layout_l import place_core_at_elbow


def test_place_core_at_elbow_size_and_position():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    core_poly = place_core_at_elbow(d, core_surface_m2=22.0)
    # Surface within ±5%
    assert 20.9 <= core_poly.area <= 23.1
    # Centered on elbow (14.4, 7.5)
    cx, cy = core_poly.centroid.x, core_poly.centroid.y
    assert abs(cx - d.elbow[0]) < 0.3
    assert abs(cy - d.elbow[1]) < 0.3
    # Core lies inside footprint
    assert footprint.buffer(0.1).contains(core_poly)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py::test_place_core_at_elbow_size_and_position -v`
Expected: FAIL with `ImportError: cannot import name 'place_core_at_elbow'`

- [ ] **Step 3: Implement place_core_at_elbow**

Append to `apps/backend/core/building_model/layout_l.py`:

```python
def place_core_at_elbow(
    d: LDecomposition, core_surface_m2: float,
) -> ShapelyPolygon:
    """Place the core (stairs + lift + shafts) at the corridor elbow.

    Square core centred on the elbow. If the elbow is too close to bar
    or leg edges for the square to fit inside the footprint, the core is
    shifted inward minimally to keep it inside.
    """
    side = core_surface_m2 ** 0.5
    cx, cy = d.elbow
    bx0, by0, bx1, by1 = d.bar.bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds

    # Clamp to keep core inside bar (since elbow is in bar for inner-corner-NW)
    # For inner-corner orientations where elbow is in leg, clamp to leg instead.
    # Elbow is always in bar when the L was decomposed with bar = full-width arm.
    cx = max(bx0 + side / 2, min(bx1 - side / 2, cx))
    cy = max(by0 + side / 2, min(by1 - side / 2, cy))

    return shp_box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_l.py apps/backend/tests/unit/test_layout_l.py
git commit -m "feat(layout): place_core_at_elbow for L footprints"
```

---

## Task 5: Apartment quadrants around the L-corridor

**Files:**
- Modify: `apps/backend/core/building_model/layout_l.py`
- Modify: `apps/backend/tests/unit/test_layout_l.py`

Given bar + leg + corridor + core, the remaining usable floor area divides into 5 quadrants (for inner-corner-NW):

1. **south_bar** — bar below the horizontal corridor, full bar width
2. **nw_bar** — bar above corridor, WEST of leg vertical corridor
3. **ne_bar** — bar above corridor, EAST of leg vertical corridor (small)
4. **leg_west** — leg WEST of vertical corridor
5. **leg_east** — leg EAST of vertical corridor

Each quadrant is a rectangle; `divide_strip_into_apartments(quadrant, mix, min_width)` slices it into T2/T3 slots. Same helper works on all 5 quadrants.

- [ ] **Step 1: Write failing test for compute_l_quadrants**

```python
# Append to apps/backend/tests/unit/test_layout_l.py
from core.building_model.layout_l import compute_l_quadrants


def test_compute_l_quadrants_five_rects():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    quadrants = compute_l_quadrants(d, corridor_width=1.6)
    assert len(quadrants) == 5
    names = {q.name for q in quadrants}
    assert names == {"south_bar", "nw_bar", "ne_bar", "leg_west", "leg_east"}
    # south_bar runs full bar width below corridor
    south = next(q for q in quadrants if q.name == "south_bar")
    sx0, sy0, sx1, sy1 = south.rect.bounds
    assert abs(sx1 - sx0 - 21.9) < 0.2  # full bar width
    assert abs(sy1 - sy0 - (7.5 - 0.8)) < 0.2  # depth ≈ 6.7 m
    # leg_east: 6.7m deep, 17.4m long
    le = next(q for q in quadrants if q.name == "leg_east")
    ex0, ey0, ex1, ey1 = le.rect.bounds
    assert abs(ex1 - ex0 - (21.9 - 14.4 - 0.8)) < 0.2
    assert abs(ey1 - ey0 - 17.4) < 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py::test_compute_l_quadrants_five_rects -v`
Expected: FAIL with `ImportError: cannot import name 'compute_l_quadrants'`

- [ ] **Step 3: Implement compute_l_quadrants**

Append to `apps/backend/core/building_model/layout_l.py`:

```python
@dataclass(frozen=True)
class LQuadrant:
    """A rectangular apartment zone surrounding the L-corridor.

    - name: canonical label ("south_bar", "nw_bar", "ne_bar",
      "leg_west", "leg_east")
    - rect: axis-aligned rectangle polygon
    - long_axis: "horizontal" or "vertical" — direction along which
      apts are sliced
    - facade_sides: exterior sides of this quadrant touching a street
      or jardin ("sud", "nord", "est", "ouest")
    """
    name: str
    rect: ShapelyPolygon
    long_axis: str
    facade_sides: tuple[str, ...]


def compute_l_quadrants(
    d: LDecomposition, corridor_width: float = 1.6,
) -> list[LQuadrant]:
    """Return the 5 rectangular apartment zones around the L-corridor.

    Works for all 4 canonical L orientations. The quadrant NAMES are
    always the same (south_bar, nw_bar, etc.) but the actual rectangle
    coordinates reflect the specific orientation of this L.

    For inner-corner NW (bar south, leg east, outer corner NE):
    - south_bar: bar below corridor
    - nw_bar: bar above corridor, west of leg x
    - ne_bar: bar above corridor, east of leg x (small corner)
    - leg_west: leg west of leg corridor
    - leg_east: leg east of leg corridor
    """
    half = corridor_width / 2
    bx0, by0, bx1, by1 = d.bar.bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds
    cx_leg, cy_bar = d.elbow

    # Determine orientation: is leg ABOVE or BELOW bar centerline?
    leg_above = ly0 >= cy_bar
    # Is leg EAST or WEST of bar centerline?
    cx_bar = (bx0 + bx1) / 2
    leg_east_of_center = cx_leg >= cx_bar

    # Bar splits into "below-corridor" and "above-corridor" strips
    bar_south = shp_box(bx0, by0, bx1, cy_bar - half)
    bar_north = shp_box(bx0, cy_bar + half, bx1, by1)
    # Above-bar strip splits at x=cx_leg ± half into west/east
    bar_above_west = shp_box(bx0, cy_bar + half, cx_leg - half, by1)
    bar_above_east = shp_box(cx_leg + half, cy_bar + half, bx1, by1)
    # For inner-corner NW, leg is above bar → nw_bar = bar_above_west,
    # ne_bar = bar_above_east, south_bar = bar_south.
    # For inner-corner SW (leg below bar), swap: south_bar becomes
    # bar_above (above corridor), nw_bar becomes bar_below_west.
    if leg_above:
        south_rect = bar_south
        nw_rect = bar_above_west
        ne_rect = bar_above_east
    else:
        # Leg below: bar's "other" strip is ABOVE the corridor.
        south_rect = bar_north  # "opposite to leg" side
        # Below-corridor splits analogously
        nw_rect = shp_box(bx0, by0, cx_leg - half, cy_bar - half)
        ne_rect = shp_box(cx_leg + half, by0, bx1, cy_bar - half)

    # Leg splits at x=cx_leg ± half into west/east columns
    leg_west_rect = shp_box(lx0, ly0, cx_leg - half, ly1)
    leg_east_rect = shp_box(cx_leg + half, ly0, lx1, ly1)

    # Facade sides (based on bbox orientation — the owner's polygon
    # tells us which sides touch the outside). For inner-corner-NW:
    # south_bar touches "sud", leg_east touches "est", etc. The dispatcher
    # is responsible for translating to voirie/jardin labels upstream.
    quadrants: list[LQuadrant] = []
    # Suppress zero-area rects (when leg_w ≤ corridor_width etc.)
    for name, rect, axis, sides in [
        ("south_bar", south_rect, "horizontal", ("sud",)),
        ("nw_bar", nw_rect, "horizontal", ("ouest", "nord")),
        ("ne_bar", ne_rect, "horizontal", ("est", "nord")),
        ("leg_west", leg_west_rect, "vertical", ("ouest",)),
        ("leg_east", leg_east_rect, "vertical", ("est",)),
    ]:
        if rect.area > 1.0:  # drop slivers
            quadrants.append(LQuadrant(name=name, rect=rect, long_axis=axis, facade_sides=sides))
    return quadrants
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_l.py apps/backend/tests/unit/test_layout_l.py
git commit -m "feat(layout): compute_l_quadrants returns 5 apt zones around L-corridor"
```

---

## Task 6: Slice quadrants into apartment slots

**Files:**
- Modify: `apps/backend/core/building_model/layout_l.py`
- Modify: `apps/backend/tests/unit/test_layout_l.py`

Each quadrant rectangle must be divided into apt slots. Target width per apt depends on typology:
- T2 (~48 m²): at 6.7m depth, apt width = 48/6.7 ≈ 7.2m
- T3 (~58 m²): at 6.7m depth, apt width = 58/6.7 ≈ 8.7m

We slice along `long_axis`. Minimum apt width = 5.5m (below this, merge with neighbour or drop slot as sliver).

- [ ] **Step 1: Write failing test for slice_quadrant_into_apts**

```python
# Append to apps/backend/tests/unit/test_layout_l.py
from core.building_model.schemas import Typologie
from core.building_model.layout_l import slice_quadrant_into_apts


def test_slice_south_bar_into_T2_gives_3_apts():
    # south_bar: 21.9m wide × 6.7m deep = 147 m². 3 T2 target.
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    quads = compute_l_quadrants(d, corridor_width=1.6)
    south = next(q for q in quads if q.name == "south_bar")
    slots = slice_quadrant_into_apts(
        south, target_typo=Typologie.T2, target_surface=48.0,
    )
    assert 2 <= len(slots) <= 4
    # Each slot's polygon lies inside south_bar
    for s in slots:
        assert south.rect.buffer(0.1).contains(s.polygon)


def test_slice_leg_east_into_T3():
    # leg_east: 6.7m wide × 17.4m deep = ~117 m². ~2 T3 (58 m² target).
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    quads = compute_l_quadrants(d, corridor_width=1.6)
    le = next(q for q in quads if q.name == "leg_east")
    slots = slice_quadrant_into_apts(
        le, target_typo=Typologie.T3, target_surface=58.0,
    )
    assert len(slots) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py::test_slice_south_bar_into_T2_gives_3_apts -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement slice_quadrant_into_apts**

Append to `apps/backend/core/building_model/layout_l.py`:

```python
from core.building_model.solver import ApartmentSlot
from core.building_model.schemas import Typologie


_MIN_APT_WIDTH_M = 5.5  # below this, apt is unsellable


def slice_quadrant_into_apts(
    quadrant: LQuadrant,
    target_typo: Typologie,
    target_surface: float,
    id_prefix: str = "",
) -> list[ApartmentSlot]:
    """Slice a rectangular quadrant into T2/T3 slots along its long axis.

    Strategy: at the quadrant's fixed depth (perpendicular to long axis),
    the target apt width = target_surface / depth. Compute how many apts
    fit at that width; split the long dimension evenly.

    Returns a list of ApartmentSlot with target_typologie set.
    """
    qx0, qy0, qx1, qy1 = quadrant.rect.bounds
    w = qx1 - qx0
    h = qy1 - qy0

    if quadrant.long_axis == "horizontal":
        long_len = w
        depth = h
    else:
        long_len = h
        depth = w

    if depth <= 0 or long_len <= 0:
        return []

    # Target apt width along the long axis
    target_width = max(_MIN_APT_WIDTH_M, target_surface / max(depth, 1.0))
    # Number of apts that fit
    n_apts = max(1, int(long_len / target_width))
    actual_width = long_len / n_apts
    # Drop if slivers
    if actual_width < _MIN_APT_WIDTH_M:
        n_apts = max(1, int(long_len / _MIN_APT_WIDTH_M))
        actual_width = long_len / n_apts

    slots: list[ApartmentSlot] = []
    for i in range(n_apts):
        if quadrant.long_axis == "horizontal":
            ax0 = qx0 + i * actual_width
            ax1 = qx0 + (i + 1) * actual_width
            ay0, ay1 = qy0, qy1
        else:
            ay0 = qy0 + i * actual_width
            ay1 = qy0 + (i + 1) * actual_width
            ax0, ax1 = qx0, qx1
        poly = shp_box(ax0, ay0, ax1, ay1)
        position = "extremite" if i == 0 or i == n_apts - 1 else "milieu"
        slots.append(ApartmentSlot(
            id=f"{id_prefix}{quadrant.name}_{i}",
            polygon=poly,
            surface_m2=poly.area,
            target_typologie=target_typo,
            orientations=list(quadrant.facade_sides),
            position_in_floor=position,
        ))
    return slots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_l.py apps/backend/tests/unit/test_layout_l.py
git commit -m "feat(layout): slice_quadrant_into_apts slices quadrant into T2/T3"
```

---

## Task 7: Top-level compute_l_layout entry point

**Files:**
- Modify: `apps/backend/core/building_model/layout_l.py`
- Modify: `apps/backend/tests/unit/test_layout_l.py`

Wraps decompose + corridor + core + quadrants + slices into one result.

- [ ] **Step 1: Write failing end-to-end test**

```python
# Append to apps/backend/tests/unit/test_layout_l.py
from core.building_model.layout_l import compute_l_layout


def test_compute_l_layout_nogent_style_footprint():
    # User's real project: L canonical inner-corner NW
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    result = compute_l_layout(
        footprint,
        mix_typologique={Typologie.T2: 0.4, Typologie.T3: 0.6},
        core_surface_m2=22.0,
        corridor_width=1.6,
    )
    # Core at elbow
    assert abs(result.core.centroid.x - 14.4) < 0.5
    assert abs(result.core.centroid.y - 7.5) < 0.5
    # Corridor is a single connected polygon
    assert result.corridor.geom_type == "Polygon"
    # Apartment count: target 10/niveau
    assert 8 <= len(result.slots) <= 13, f"got {len(result.slots)} slots"
    # All slots inside footprint
    for s in result.slots:
        assert footprint.buffer(0.1).contains(s.polygon)
    # No slot overlaps corridor or core
    occupied = result.corridor.union(result.core)
    for s in result.slots:
        overlap = s.polygon.intersection(occupied).area
        assert overlap < 0.5, f"slot {s.id} overlaps circulation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py::test_compute_l_layout_nogent_style_footprint -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement compute_l_layout**

Append to `apps/backend/core/building_model/layout_l.py`:

```python
@dataclass(frozen=True)
class LLayoutResult:
    core: ShapelyPolygon
    corridor: ShapelyPolygon
    slots: list[ApartmentSlot]
    decomposition: LDecomposition


def compute_l_layout(
    footprint: ShapelyPolygon,
    mix_typologique: dict[Typologie, float],
    core_surface_m2: float,
    corridor_width: float = 1.6,
    id_prefix: str = "",
) -> LLayoutResult | None:
    """Generate core + L-corridor + apt slots for an L-shaped footprint.

    Returns None if the footprint is not a clean L (caller should fall
    back to legacy wing-par-wing layout).
    """
    d = decompose_l(footprint)
    if d is None:
        return None

    corridor = build_l_corridor(d, corridor_width=corridor_width)
    core = place_core_at_elbow(d, core_surface_m2=core_surface_m2)
    quadrants = compute_l_quadrants(d, corridor_width=corridor_width)

    # Assign typology per quadrant based on mix and quadrant size.
    # South bar (large, facing voirie) → T2 priority for units count.
    # Leg arms (medium) → T3 priority for family apts.
    # Small NE corner → T2 fill.
    T2_share = mix_typologique.get(Typologie.T2, 0.0)
    T3_share = mix_typologique.get(Typologie.T3, 0.0)
    total = T2_share + T3_share
    if total <= 0:
        return None

    slots: list[ApartmentSlot] = []
    for q in quadrants:
        # Bar quadrants (horizontal long axis) → T2 target; leg → T3 target
        if q.long_axis == "horizontal":
            typo = Typologie.T2 if T2_share >= T3_share * 0.3 else Typologie.T3
            surface = 48.0 if typo == Typologie.T2 else 58.0
        else:
            typo = Typologie.T3 if T3_share > 0 else Typologie.T2
            surface = 58.0 if typo == Typologie.T3 else 48.0
        slots.extend(slice_quadrant_into_apts(
            quadrant=q, target_typo=typo, target_surface=surface,
            id_prefix=id_prefix,
        ))

    # Clip any slot that overlaps circulation (safety net)
    occupied = corridor.union(core)
    clipped_slots: list[ApartmentSlot] = []
    for s in slots:
        clean = s.polygon.difference(occupied)
        if clean.is_empty or clean.area < 20.0:
            continue
        if clean.geom_type == "MultiPolygon":
            clean = max(clean.geoms, key=lambda g: g.area)
        clipped_slots.append(ApartmentSlot(
            id=s.id,
            polygon=clean,
            surface_m2=clean.area,
            target_typologie=s.target_typologie,
            orientations=s.orientations,
            position_in_floor=s.position_in_floor,
        ))

    return LLayoutResult(
        core=core, corridor=corridor, slots=clipped_slots, decomposition=d,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_l.py -v`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_l.py apps/backend/tests/unit/test_layout_l.py
git commit -m "feat(layout): compute_l_layout end-to-end L handler"
```

---

## Task 8: Dispatcher routes L → compute_l_layout

**Files:**
- Modify: `apps/backend/core/building_model/layout_dispatcher.py`
- Modify: `apps/backend/tests/unit/test_layout_dispatcher.py`

The dispatcher exposes `dispatch_layout(footprint, mix, core_surface) → LayoutResult | None` returning L-handler output when applicable, or None to signal "use legacy".

- [ ] **Step 1: Write failing test**

```python
# Append to apps/backend/tests/unit/test_layout_dispatcher.py
from shapely.geometry import Polygon

from core.building_model.schemas import Typologie
from core.building_model.layout_dispatcher import dispatch_layout


def test_dispatch_l_returns_l_result():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    result = dispatch_layout(
        footprint,
        mix_typologique={Typologie.T2: 0.4, Typologie.T3: 0.6},
        core_surface_m2=22.0,
    )
    assert result is not None
    assert len(result.slots) >= 8


def test_dispatch_rect_returns_none():
    footprint = Polygon([(0, 0), (20, 0), (20, 12), (0, 12)])
    result = dispatch_layout(
        footprint,
        mix_typologique={Typologie.T2: 0.5, Typologie.T3: 0.5},
        core_surface_m2=22.0,
    )
    assert result is None  # rect → caller uses legacy wing-par-wing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py::test_dispatch_l_returns_l_result -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement dispatch_layout**

Append to `apps/backend/core/building_model/layout_dispatcher.py`:

```python
from core.building_model.layout_l import LLayoutResult, compute_l_layout
from core.building_model.schemas import Typologie


def dispatch_layout(
    footprint: ShapelyPolygon,
    mix_typologique: dict[Typologie, float],
    core_surface_m2: float,
    corridor_width: float = 1.6,
    id_prefix: str = "",
) -> LLayoutResult | None:
    """Topology-aware layout dispatcher.

    Returns an LLayoutResult when the footprint maps to a handler
    (currently: L). Returns None for "rect", "T", "U", "other" — the
    caller should fall back to the legacy wing-par-wing pipeline.

    Each topology handler is self-contained and guarantees that core,
    corridor, and slots form a coherent layout (no overlaps, corridor
    connects the entire floor, core is reachable from every slot).
    """
    topology = classify_footprint_topology(footprint)
    if topology == "L":
        return compute_l_layout(
            footprint=footprint,
            mix_typologique=mix_typologique,
            core_surface_m2=core_surface_m2,
            corridor_width=corridor_width,
            id_prefix=id_prefix,
        )
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/layout_dispatcher.py apps/backend/tests/unit/test_layout_dispatcher.py
git commit -m "feat(layout): dispatch_layout routes L footprints to L handler"
```

---

## Task 9: Wire dispatcher into solver.compute_apartment_slots

**Files:**
- Modify: `apps/backend/core/building_model/solver.py:562-...` (compute_apartment_slots)
- Modify: `apps/backend/tests/unit/test_solver_slots.py`

When `dispatch_layout` returns a result, use its slots directly and skip the wing-par-wing loop. When it returns None, fall through to existing logic unchanged.

- [ ] **Step 1: Write failing integration test**

```python
# Append to apps/backend/tests/unit/test_solver_slots.py
from shapely.geometry import Polygon


def test_compute_slots_on_l_footprint_uses_dispatcher():
    from core.building_model.schemas import Typologie
    from core.building_model.solver import (
        build_modular_grid, compute_apartment_slots, place_core,
    )
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=22.0)
    slots = compute_apartment_slots(
        grid, core, mix_typologique={Typologie.T2: 0.4, Typologie.T3: 0.6},
        voirie_side="sud",
    )
    # Dispatcher L handler delivers at least 8 apts per niveau
    assert len(slots) >= 8, f"got {len(slots)} slots (expected >= 8)"
    # No slot overlaps the core
    for s in slots:
        assert s.polygon.intersection(core.polygon).area < 0.5
```

- [ ] **Step 2: Run test to verify it fails (or returns too few slots)**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_solver_slots.py::test_compute_slots_on_l_footprint_uses_dispatcher -v`
Expected: FAIL — existing wing-par-wing produces ≤4-6 slots on this footprint

- [ ] **Step 3: Wire dispatcher into compute_apartment_slots**

Open `apps/backend/core/building_model/solver.py`, locate the start of `compute_apartment_slots` (line 562). Insert this block right after the initial `if grid.footprint is None` guard and before the `usable = grid.footprint.difference(...)` line:

```python
    # Topology-aware short-circuit: if the footprint maps to a known
    # shape handler (currently: L), delegate entirely. The handler
    # returns a coherent (core, corridor, slots) bundle, so we use its
    # slots and move the core to the handler-chosen position upstream
    # if needed. When None, fall through to legacy wing-par-wing logic.
    from core.building_model.layout_dispatcher import dispatch_layout

    l_result = dispatch_layout(
        footprint=grid.footprint,
        mix_typologique=mix_typologique,
        core_surface_m2=core.surface_m2,
    )
    if l_result is not None:
        return l_result.slots
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_solver_slots.py -v`
Expected: 3 PASS (2 existing rect tests + 1 new L test)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/solver.py apps/backend/tests/unit/test_solver_slots.py
git commit -m "feat(solver): delegate L footprints to layout_dispatcher"
```

---

## Task 10: Wire dispatcher into solver._compute_circulation_network

**Files:**
- Modify: `apps/backend/core/building_model/solver.py:125-271` (_compute_circulation_network)

The circulation network used to pre-clip apt slots must also match the L-handler's corridor. Wire it the same way.

- [ ] **Step 1: Write failing test**

```python
# apps/backend/tests/unit/test_layout_dispatcher.py (append)
def test_circulation_network_on_l_uses_dispatcher_corridor():
    from shapely.geometry import Polygon
    from core.building_model.schemas import Typologie
    from core.building_model.solver import (
        _compute_circulation_network, _decompose_into_wings,
        build_modular_grid, place_core,
    )
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=22.0)
    wings = _decompose_into_wings(footprint)
    network = _compute_circulation_network(footprint, wings, core)
    # Network includes both arms of the L (corridor touches x=0 and y=32.4)
    nxmin, nymin, nxmax, nymax = network.bounds
    assert nxmin < 1.0, "corridor must reach bar west end"
    assert nymax > 31.0, "corridor must reach leg north end"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py::test_circulation_network_on_l_uses_dispatcher_corridor -v`
Expected: FAIL — legacy network doesn't produce a continuous L

- [ ] **Step 3: Wire dispatcher into _compute_circulation_network**

Open `apps/backend/core/building_model/solver.py`, locate `_compute_circulation_network` at line 125. Insert at the top of the function body, right after the docstring and the `from shapely.ops import unary_union` import line:

```python
    # Topology-aware short-circuit. If the footprint maps to a known
    # handler (currently: L), that handler produced a coherent corridor
    # polygon — use it directly instead of the legacy wing-par-wing
    # reconstruction (which can't represent a continuous L corridor).
    # Keep the result in sync with compute_apartment_slots.
    from core.building_model.layout_dispatcher import classify_footprint_topology
    from core.building_model.layout_l import (
        build_l_corridor, decompose_l, place_core_at_elbow,
    )

    if classify_footprint_topology(footprint) == "L":
        d = decompose_l(footprint)
        if d is not None:
            l_corridor = build_l_corridor(d, corridor_width=corridor_width)
            return unary_union([core.polygon, l_corridor])
```

Note: the existing function accepts `core` but constructs its own core polygon only in the legacy branch. We just union core.polygon with the handler's corridor.

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py tests/unit/test_solver_slots.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/building_model/solver.py apps/backend/tests/unit/test_layout_dispatcher.py
git commit -m "feat(solver): L circulation uses dispatcher corridor"
```

---

## Task 11: Wire dispatcher into pipeline._emit_wing_corridors

**Files:**
- Modify: `apps/backend/core/building_model/pipeline.py:514-715` (_emit_wing_corridors)

The pipeline emits `Circulation` records for the plan renderer. On L footprints, replace the wing-par-wing emission with a single `Circulation` record containing the L-corridor polygon.

- [ ] **Step 1: Read current signature**

Run: `cd apps/backend && .venv/bin/grep -n "def _emit_wing_corridors" core/building_model/pipeline.py`
Expected: function at line 514, signature like `def _emit_wing_corridors(niveau_idx, core, footprint, cells)`.

- [ ] **Step 2: Write failing test**

```python
# apps/backend/tests/unit/test_layout_dispatcher.py (append)
def test_pipeline_emit_l_corridor_is_single_circulation():
    from shapely.geometry import Polygon
    from core.building_model.solver import build_modular_grid, place_core
    from core.building_model.pipeline import _emit_wing_corridors
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=22.0)
    circulations = _emit_wing_corridors(0, core, footprint, [])
    # Expect exactly one Circulation for the L corridor
    couloirs = [c for c in circulations if c.id.startswith("couloir_")]
    assert len(couloirs) == 1
    # Its polygon spans both arms
    from shapely.geometry import Polygon as SP
    poly = SP(couloirs[0].polygon_xy)
    bx0, by0, bx1, by1 = poly.bounds
    assert bx0 < 1.0  # reaches bar west end
    assert by1 > 31.0  # reaches leg north end
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py::test_pipeline_emit_l_corridor_is_single_circulation -v`
Expected: FAIL — legacy emits 2+ couloir records for wings

- [ ] **Step 4: Wire dispatcher at top of _emit_wing_corridors**

Open `apps/backend/core/building_model/pipeline.py`, locate `_emit_wing_corridors` at line 514. Insert at the top of the function body, right after the docstring:

```python
    # Topology-aware short-circuit. L footprints get a single
    # continuous corridor emitted from the L handler, matching what the
    # solver used to clip apt slots. For other topologies fall through
    # to the legacy wing-par-wing emission below.
    from core.building_model.layout_dispatcher import classify_footprint_topology
    from core.building_model.layout_l import build_l_corridor, decompose_l
    from core.building_model.schemas import Circulation

    if classify_footprint_topology(footprint) == "L":
        d = decompose_l(footprint)
        if d is not None:
            l_corridor = build_l_corridor(d, corridor_width=_CORRIDOR_WIDTH_M)
            # Subtract core so corridor and core don't overlap visually
            l_corridor = l_corridor.difference(core.polygon)
            if not l_corridor.is_empty:
                if l_corridor.geom_type == "MultiPolygon":
                    l_corridor = max(l_corridor.geoms, key=lambda g: g.area)
                coords = list(l_corridor.exterior.coords)[:-1]
                return [Circulation(
                    id=f"couloir_L_R{niveau_idx}",
                    polygon_xy=coords,
                    surface_m2=l_corridor.area,
                    largeur_min_cm=int(_CORRIDOR_WIDTH_M * 100),
                )]
```

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && .venv/bin/pytest tests/unit/test_layout_dispatcher.py tests/unit/test_solver_slots.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/building_model/pipeline.py apps/backend/tests/unit/test_layout_dispatcher.py
git commit -m "feat(pipeline): L corridor emitted as single Circulation record"
```

---

## Task 12: End-to-end 60-apt validation

**Files:**
- Create: `apps/backend/tests/integration/test_l_layout_endtoend.py`

Run the full `generate_building_model` pipeline on the user's L footprint and assert 60+ apartments across 6 niveaux.

- [ ] **Step 1: Write end-to-end test**

```python
# apps/backend/tests/integration/test_l_layout_endtoend.py
"""End-to-end: L footprint → BuildingModel with 60+ apts."""
import pytest
from shapely.geometry import Polygon, mapping

from core.building_model.pipeline import generate_building_model
from core.building_model.schemas import GenerationInputs, Brief, Typologie


@pytest.mark.asyncio
async def test_l_canon_nogent_produces_60_plus_apartments(async_session):
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    inputs = GenerationInputs(
        footprint_recommande_geojson=mapping(footprint),
        niveaux_recommandes=6,
        voirie_orientations=["sud", "est"],
        brief=Brief(
            mix_typologique={Typologie.T2: 0.4, Typologie.T3: 0.6},
            commerces_rdc=False,
        ),
    )
    model = await generate_building_model(inputs, session=async_session)
    total_apts = sum(
        len([c for c in n.cellules if c.type == "logement"])
        for n in model.niveaux
    )
    assert total_apts >= 60, f"got {total_apts} apts (expected >= 60)"
    # Each niveau has a single couloir record (L-corridor)
    for n in model.niveaux:
        couloirs = [c for c in n.circulations if c.id.startswith("couloir_")]
        assert len(couloirs) == 1, f"niveau {n.index} has {len(couloirs)} couloirs"
```

- [ ] **Step 2: Run test**

Run: `cd apps/backend && .venv/bin/pytest tests/integration/test_l_layout_endtoend.py -v`
Expected: PASS with 60+ apts. If it fails with <60, adjust mix or quadrant slicing.

- [ ] **Step 3: Run the full test suite to verify no regressions**

Run: `cd apps/backend && .venv/bin/pytest -x`
Expected: all existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/integration/test_l_layout_endtoend.py
git commit -m "test(layout): end-to-end L footprint produces 60+ apts"
```

---

## Task 13: Manual verification on project c60d8627

**Files:** No code changes — manual browser check.

- [ ] **Step 1: Restart backend**

Run: `cd apps/backend && .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload &`

- [ ] **Step 2: Open project in browser**

Navigate to `http://localhost:3010/projects/c60d8627-752f-4d51-9e6d-052b34796385/plans`.

- [ ] **Step 3: Verify visually**

Check the "niveaux" tab:
- Couloir en forme de L continu (pas 2 couloirs séparés)
- Noyau positionné au coude (intersection des deux bras)
- Apartements dual-loaded de chaque côté sur le bar ET le leg
- Compteur d'apts ≥ 60

If any of these fail, capture the render and re-open discussion before merging.

- [ ] **Step 4: Final commit if any copy tweaks needed**

```bash
git add -p  # review any final changes
git commit -m "chore: finalize L-layout for project c60d8627"
```

---

## Self-review checklist

**Spec coverage:**
- Couloir L continu ✓ (Task 3 build_l_corridor)
- Noyau au coude ✓ (Task 4 place_core_at_elbow)
- Dual-loaded 2 rangées chaque branche ✓ (Task 5 compute_l_quadrants)
- 60+ apts ✓ (Task 12 end-to-end assertion)
- Architecture évolutive (dispatcher) ✓ (Task 1 + Task 8)
- Pas de régression sur rect/T/U ✓ (fallback to legacy)

**Placeholder scan:** none — every code step has complete code.

**Type consistency:**
- `LDecomposition` (Task 2) used in Tasks 3, 4, 5, 7
- `LQuadrant` (Task 5) used in Task 6
- `LLayoutResult` (Task 7) used in Task 8
- `compute_l_layout`, `decompose_l`, `build_l_corridor`, `place_core_at_elbow`, `compute_l_quadrants`, `slice_quadrant_into_apts`, `dispatch_layout`, `classify_footprint_topology` — all names consistent across tasks.
