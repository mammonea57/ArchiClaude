"""
CRS-aware geometric calculations: polygon area and point buffering.

All calculations are performed in Lambert-93 (EPSG:2154), which provides
accurate metric distances for metropolitan France. Input geometries may
be in any CRS supported by pyproj; they are reprojected before calculation.

Shapely coordinate order follows GIS convention: (x, y) = (lng, lat) for
geographic CRS, and (easting, northing) for projected CRS.
"""

from functools import lru_cache

import numpy as np
from pyproj import Transformer
from shapely import transform
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry

_TARGET_CRS = "EPSG:2154"  # Lambert-93


@lru_cache(maxsize=32)
def _get_transformer(source_crs: str, target_crs: str) -> Transformer:
    """Return a cached Transformer for the given CRS pair.

    lru_cache makes this effectively a singleton per (source, target) pair.
    Transformer is thread-safe once constructed.
    """
    return Transformer.from_crs(source_crs, target_crs, always_xy=True)


def _reproject(geom: BaseGeometry, source_crs: str, target_crs: str = _TARGET_CRS) -> BaseGeometry:
    """Reproject a Shapely geometry from source_crs to target_crs.

    Uses shapely.transform() which applies a coordinate-array transformation
    to a copy of the geometry, preserving its type.

    shapely.transform passes an (N, 2) float64 array of [x, y] pairs to the
    transformation callable and expects an (N, 2) array back.  pyproj's
    Transformer.transform() takes separate (xx, yy) arrays, so we unpack
    and repack inside the lambda.

    Args:
        geom: Any Shapely geometry. Coordinates must follow always_xy=True
              convention: (lng, lat) for geographic CRS, (x, y) for projected.
        source_crs: Source CRS string (e.g. "EPSG:4326").
        target_crs: Target CRS string (default: "EPSG:2154" Lambert-93).

    Returns:
        New geometry in target_crs coordinates.
    """
    if source_crs == target_crs:
        return geom
    transformer = _get_transformer(source_crs, target_crs)

    def _apply(coords: "np.ndarray") -> "np.ndarray":
        # coords shape: (N, 2) — columns are [x, y] (always_xy convention)
        xx, yy = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([xx, yy])

    return transform(geom, _apply)


def polygon_area_m2(geom: BaseGeometry, source_crs: str = "EPSG:4326") -> float:
    """Return the area of a polygon in square metres.

    The geometry is reprojected to Lambert-93 before computing area, which
    gives accurate metric results for metropolitan France.

    Args:
        geom: A Shapely Polygon (or MultiPolygon). Coordinates must follow
              always_xy convention for the given source_crs.
        source_crs: CRS of the input geometry (default: "EPSG:4326" WGS84).

    Returns:
        Area in square metres (always positive).
    """
    projected = _reproject(geom, source_crs)
    return abs(projected.area)


def buffer_point_m(
    point: Point,
    radius_m: float,
    source_crs: str = "EPSG:4326",
) -> Polygon:
    """Buffer a point by a given radius in metres, returning a Lambert-93 polygon.

    The point is first reprojected to Lambert-93 where distances are metric,
    then buffered. The returned polygon is in Lambert-93 coordinates.

    Args:
        point: A Shapely Point. Coordinates must follow always_xy convention
               for the given source_crs (i.e. (lng, lat) for WGS84).
        radius_m: Buffer radius in metres.
        source_crs: CRS of the input point (default: "EPSG:4326" WGS84).

    Returns:
        Shapely Polygon in Lambert-93 (EPSG:2154) coordinates.
    """
    projected_point = _reproject(point, source_crs)
    # shapely buffer with quad_segs=64 gives a close circular approximation
    return projected_point.buffer(radius_m, quad_segs=64)
