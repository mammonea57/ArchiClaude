"""
Lambert-93 (EPSG:2154) ↔ WGS84 (EPSG:4326) coordinate transformations.

Transformers are module-level singletons created once at import time.
pyproj.Transformer is thread-safe for concurrent reads once constructed.

Convention:
- WGS84 inputs/outputs use (lat, lng) order — latitude first.
- Lambert-93 inputs/outputs use (x, y) order — easting first.
"""

from pyproj import Transformer

# always_xy=True: inputs/outputs are always (easting, northing) / (lng, lat).
# We manage the convention flip ourselves so callers use intuitive (lat, lng).
_WGS84_TO_L93: Transformer = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:2154",
    always_xy=True,
)

_L93_TO_WGS84: Transformer = Transformer.from_crs(
    "EPSG:2154",
    "EPSG:4326",
    always_xy=True,
)


def wgs84_to_lambert93(*, lat: float, lng: float) -> tuple[float, float]:
    """Convert WGS84 geographic coordinates to Lambert-93 projected coordinates.

    Args:
        lat: Latitude in decimal degrees (EPSG:4326).
        lng: Longitude in decimal degrees (EPSG:4326).

    Returns:
        (x, y) tuple in meters (EPSG:2154). x is easting, y is northing.
    """
    x, y = _WGS84_TO_L93.transform(lng, lat)  # always_xy: lng first
    return float(x), float(y)


def lambert93_to_wgs84(*, x: float, y: float) -> tuple[float, float]:
    """Convert Lambert-93 projected coordinates to WGS84 geographic coordinates.

    Args:
        x: Easting in meters (EPSG:2154).
        y: Northing in meters (EPSG:2154).

    Returns:
        (lat, lng) tuple in decimal degrees (EPSG:4326).
    """
    lng, lat = _L93_TO_WGS84.transform(x, y)  # always_xy: x/easting first → returns lng
    return float(lat), float(lng)
