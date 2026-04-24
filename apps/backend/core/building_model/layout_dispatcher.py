"""Topology-aware dispatcher for building layout generation.

Classifies a footprint by its shape (rect / L / T / U / other) and
routes to the appropriate layout handler. Handlers are self-contained:
each produces (core, corridor, slots) atomically so solver and pipeline
cannot disagree about geometry.
"""
from __future__ import annotations

from typing import Literal

from shapely.geometry import Polygon as ShapelyPolygon

from core.building_model.layout_l import LLayoutResult, compute_l_layout
from core.building_model.schemas import Typologie

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
