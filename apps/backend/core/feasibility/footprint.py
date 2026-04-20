"""Footprint calculation — maximum constructible ground-floor area.

All geometries must be in Lambert-93 (EPSG:2154, metric CRS).
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.affinity import scale
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class FootprintResult:
    """Result of footprint computation."""

    footprint_geom: BaseGeometry
    surface_emprise_m2: float
    surface_pleine_terre_m2: float
    surface_terrain_m2: float


def compute_footprint(
    *,
    terrain: Polygon | MultiPolygon,
    recul_voirie_m: float = 0.0,
    recul_lat_m: float = 0.0,
    recul_fond_m: float = 0.0,
    emprise_max_pct: float = 100.0,
    ebc_geom: BaseGeometry | None = None,
) -> FootprintResult:
    """Compute the maximum constructible footprint given terrain and PLU constraints.

    All input geometries must be in Lambert-93 (EPSG:2154, metres).

    Args:
        terrain: Parcel polygon(s) in Lambert-93.
        recul_voirie_m: Setback from road alignment, in metres.
        recul_lat_m: Setback from lateral property boundaries, in metres.
        recul_fond_m: Setback from rear boundary, in metres.
        emprise_max_pct: Maximum emprise au sol as a percentage of terrain area (0–100).
        ebc_geom: Espace Boisé Classé or other no-build zone to subtract (Lambert-93).

    Returns:
        FootprintResult with footprint geometry and key surface figures.
    """
    terrain_area = terrain.area

    # Step 1: Uniform inward buffer using the maximum of the three setbacks
    # v1 simplification: a single isotropic buffer approximates the real
    # three-sided setback adequately for early-stage feasibility.
    buffer_m = max(recul_voirie_m, recul_lat_m, recul_fond_m)
    if buffer_m > 0.0:
        footprint: BaseGeometry = terrain.buffer(-buffer_m)
    else:
        footprint = terrain

    # Step 2: Handle degenerate result after buffer
    if footprint.is_empty or footprint.area <= 0.0:
        return FootprintResult(
            footprint_geom=footprint,
            surface_emprise_m2=0.0,
            surface_pleine_terre_m2=terrain_area,
            surface_terrain_m2=terrain_area,
        )

    # Step 3: Subtract EBC geometry
    if ebc_geom is not None and not ebc_geom.is_empty:
        footprint = footprint.difference(ebc_geom)

    if footprint.is_empty or footprint.area <= 0.0:
        return FootprintResult(
            footprint_geom=footprint,
            surface_emprise_m2=0.0,
            surface_pleine_terre_m2=terrain_area,
            surface_terrain_m2=terrain_area,
        )

    # Step 4: Cap to emprise_max_pct using centroid-based scaling
    emprise_max_m2 = terrain_area * emprise_max_pct / 100.0
    if footprint.area > emprise_max_m2:
        # Scale factor = sqrt(target_area / current_area)
        scale_factor = (emprise_max_m2 / footprint.area) ** 0.5
        centroid = footprint.centroid
        footprint = scale(footprint, xfact=scale_factor, yfact=scale_factor, origin=centroid)

    surface_emprise = footprint.area
    surface_pleine_terre = terrain_area - surface_emprise

    return FootprintResult(
        footprint_geom=footprint,
        surface_emprise_m2=surface_emprise,
        surface_pleine_terre_m2=surface_pleine_terre,
        surface_terrain_m2=terrain_area,
    )
