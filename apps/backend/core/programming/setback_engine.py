"""Setback engine — half-plane intersection approach.

Computes the constructible footprint by intersecting the parcelle with
a half-plane per boundary segment, each offset inward by the required
setback distance.

This gives accurate, per-segment asymmetric setbacks unlike the
isotropic buffer used in the legacy footprint module.

All geometries must be in Lambert-93 (EPSG:2154, metric CRS).
"""

from __future__ import annotations

import math

from shapely.affinity import scale
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from core.programming.schemas import ClassifiedSegment

# Half-plane is constructed as a very large rectangle orthogonal to the
# segment and positioned at the offset distance from the segment line.
_HALF_PLANE_EXTENT = 1_000_000.0  # metres — effectively infinite


def _inward_normal(
    start: tuple[float, float],
    end: tuple[float, float],
    parcelle: Polygon,
) -> tuple[float, float]:
    """Return the unit inward normal for a boundary segment.

    The inward normal points from the segment toward the interior of the
    parcelle.  We pick the direction such that the parcelle centroid lies
    on the positive side.

    Args:
        start: Segment start coordinates (x, y).
        end: Segment end coordinates (x, y).
        parcelle: The parent parcel polygon.

    Returns:
        Unit normal vector (nx, ny) pointing inward.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-10:
        return (0.0, 1.0)

    # Two candidate normals (perpendiculars)
    nx1, ny1 = -dy / length, dx / length
    nx2, ny2 = dy / length, -dx / length

    cx, cy = parcelle.centroid.coords[0]
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2

    # Choose the normal that points toward the centroid
    dot1 = (cx - mx) * nx1 + (cy - my) * ny1
    if dot1 >= 0:
        return (nx1, ny1)
    return (nx2, ny2)


def _half_plane(
    start: tuple[float, float],
    end: tuple[float, float],
    recul_m: float,
    parcelle: Polygon,
) -> Polygon:
    """Build a half-plane polygon offset inward by recul_m from the segment.

    The half-plane is a very large rectangle on the inward side of the
    offset line.  Intersecting it with the parcelle removes the strip
    between the segment and the offset line.

    Args:
        start: Segment start (x, y).
        end: Segment end (x, y).
        recul_m: Setback distance in metres.
        parcelle: Parent parcel (used to determine inward direction).

    Returns:
        A large Polygon representing the allowed half-plane.
    """
    nx, ny = _inward_normal(start, end, parcelle)

    # Offset base point along the normal by recul_m
    ox = (start[0] + end[0]) / 2 + nx * recul_m
    oy = (start[1] + end[1]) / 2 + ny * recul_m

    # Direction along the segment
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-10:
        tx, ty = 1.0, 0.0
    else:
        tx, ty = dx / length, dy / length

    E = _HALF_PLANE_EXTENT

    # Corners of the half-plane rectangle (extends "behind" the offset line)
    p1 = (ox + tx * E + nx * E, oy + ty * E + ny * E)
    p2 = (ox - tx * E + nx * E, oy - ty * E + ny * E)
    p3 = (ox - tx * E, oy - ty * E)
    p4 = (ox + tx * E, oy + ty * E)

    return Polygon([p1, p2, p3, p4])


def compute_footprint_by_segments(
    *,
    parcelle: Polygon,
    segments: list[ClassifiedSegment],
    emprise_max_pct: float = 100.0,
    ebc_geom: BaseGeometry | None = None,
) -> Polygon:
    """Compute the constructible footprint using per-segment half-plane intersection.

    For each boundary segment the setback is applied by intersecting the
    parcelle with a half-plane offset inward by the segment's recul_m.
    The result is the polygon that satisfies all setback constraints simultaneously.

    Args:
        parcelle: The parcel polygon in Lambert-93 (EPSG:2154).
        segments: Classified segments with their setback distances.
        emprise_max_pct: Maximum emprise au sol as a percentage of parcel area.
            100 means no cap.
        ebc_geom: Espace Boisé Classé or other no-build zone to subtract.

    Returns:
        Shapely Polygon (may be empty if setbacks consume the entire parcel).
    """
    footprint: BaseGeometry = parcelle

    for seg in segments:
        if seg.recul_m <= 0.0:
            continue
        hp = _half_plane(seg.start, seg.end, seg.recul_m, parcelle)
        footprint = footprint.intersection(hp)
        if footprint.is_empty:
            return Polygon()

    # Subtract EBC if provided
    if ebc_geom is not None and not ebc_geom.is_empty:
        footprint = footprint.difference(ebc_geom)
        if footprint.is_empty:
            return Polygon()

    # Apply emprise cap if needed (scale from centroid)
    if emprise_max_pct < 100.0 and not footprint.is_empty:
        emprise_max_m2 = parcelle.area * emprise_max_pct / 100.0
        if footprint.area > emprise_max_m2:
            scale_factor = (emprise_max_m2 / footprint.area) ** 0.5
            centroid = footprint.centroid
            footprint = scale(footprint, xfact=scale_factor, yfact=scale_factor, origin=centroid)

    if isinstance(footprint, Polygon):
        return footprint

    # Handle MultiPolygon or other geometry types — return largest part
    if hasattr(footprint, "geoms"):
        parts = list(footprint.geoms)
        if not parts:
            return Polygon()
        return max(parts, key=lambda g: g.area)

    return Polygon()
