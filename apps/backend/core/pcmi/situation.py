"""PCMI1 — Plan de situation avec fond de carte IGN.

Generates an A4-portrait SVG containing:
- IGN WMTS base map tile (Scan25 or PlanIGNv2)
- Red circle at parcel centroid (radius 30mm)
- Parcel polygon overlays (stroke #CC0000)
- North arrow (top-left)
- Scale text (bottom-right)
"""

from __future__ import annotations

import base64
import math
from typing import Literal

from shapely.geometry import Polygon

from core.http_client import get_http_client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WMTS_URL = "https://data.geopf.fr/wmts"

LAYERS = {
    "scan25": "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR.CV",
    "planv2": "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2",
}

# A4 portrait usable area (mm)
_PAGE_W_MM = 200.0
_PAGE_H_MM = 230.0

# Default scale for PCMI1
_DEFAULT_SCALE = 25_000

# Degrees per page at 1/25000 for a ~200×230mm sheet
# 1 degree latitude ≈ 111_000 m, 1 degree longitude ≈ 73_000 m at 48.8°N
_DEG_PER_M_LAT = 1.0 / 111_000
_DEG_PER_M_LNG = 1.0 / 73_000

# delta: ~1.5km radius around parcel centroid
_DELTA_DEG = 0.015

# Standard WMTS tile size
_TILE_SIZE_PX = 256


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------


def _choose_wmts_layer(map_base: str) -> str:
    """Return WMTS layer name, falls back to scan25 for unknown values."""
    return LAYERS.get(map_base, LAYERS["scan25"])


# ---------------------------------------------------------------------------
# Bounds computation
# ---------------------------------------------------------------------------


def _compute_map_bounds(
    parcelles: list[Polygon],
    scale: int = _DEFAULT_SCALE,
) -> dict[str, float]:
    """Compute map bounds centered on parcels.

    Returns a dict with keys: min_lng, max_lng, min_lat, max_lat.
    Uses a fixed delta of 0.015° (~1.5 km) around the centroid, which is
    appropriate for 1/25 000 scale on an A4 page.
    """
    if not parcelles:
        raise ValueError("parcelles must not be empty")

    # Union centroid
    from shapely.ops import unary_union

    union = unary_union(parcelles)
    centroid = union.centroid

    lat = centroid.y
    lng = centroid.x

    delta = _DELTA_DEG

    return {
        "min_lng": lng - delta,
        "max_lng": lng + delta,
        "min_lat": lat - delta,
        "max_lat": lat + delta,
    }


# ---------------------------------------------------------------------------
# WMTS tile fetch
# ---------------------------------------------------------------------------


def _lng_lat_to_tile(lng: float, lat: float, zoom: int) -> tuple[int, int]:
    """Convert WGS84 longitude/latitude to WMTS/OSM tile x,y at given zoom."""
    lat_rad = math.radians(lat)
    n = 2**zoom
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


async def _fetch_wmts_tile(*, layer: str, z: int, x: int, y: int) -> bytes:
    """Fetch a single WMTS tile from IGN géoplateforme.

    Uses TileMatrixSet=PM (Google/OSM Web Mercator).
    """
    client = get_http_client()
    params = {
        "SERVICE": "WMTS",
        "REQUEST": "GetTile",
        "VERSION": "1.0.0",
        "LAYER": layer,
        "STYLE": "normal",
        "FORMAT": "image/png",
        "TILEMATRIXSET": "PM",
        "TILEMATRIX": str(z),
        "TILEROW": str(y),
        "TILECOL": str(x),
    }
    response = await client.get(WMTS_URL, params=params)
    response.raise_for_status()
    return response.content


# ---------------------------------------------------------------------------
# Coordinate projection helpers for SVG overlay
# ---------------------------------------------------------------------------


def _geo_to_svg(
    lng: float,
    lat: float,
    bounds: dict[str, float],
    svg_w: float,
    svg_h: float,
) -> tuple[float, float]:
    """Map geographic coordinates to SVG pixel coordinates."""
    x = (lng - bounds["min_lng"]) / (bounds["max_lng"] - bounds["min_lng"]) * svg_w
    # latitude increases upward, SVG y increases downward
    y = (1.0 - (lat - bounds["min_lat"]) / (bounds["max_lat"] - bounds["min_lat"])) * svg_h
    return x, y


# ---------------------------------------------------------------------------
# North arrow SVG snippet
# ---------------------------------------------------------------------------


def _north_arrow_svg(x: float, y: float) -> str:
    """Return SVG group for a simple north arrow at position (x, y)."""
    return (
        f'<g transform="translate({x},{y})">'
        f'<polygon points="0,-8 3,0 0,-2 -3,0" fill="#222222"/>'
        f'<polygon points="0,-2 3,0 0,8 -3,0" fill="#888888"/>'
        f'<text x="0" y="16" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="6" fill="#222222">N</text>'
        f"</g>"
    )


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------


async def generate_pcmi1(
    *,
    parcelles: list[Polygon],
    map_base: Literal["scan25", "planv2"] = "scan25",
) -> str:
    """Generate PCMI1 SVG with IGN base map + red circle + red polygon overlays.

    The SVG uses millimetres as the coordinate unit.
    Dimensions: 200mm wide × 230mm tall (A4 portrait usable area).

    Args:
        parcelles: list of Shapely Polygon objects in WGS84 (EPSG:4326).
        map_base:  WMTS layer key ("scan25" or "planv2").

    Returns:
        Full SVG document as a string.
    """
    if not parcelles:
        raise ValueError("parcelles must not be empty")

    layer = _choose_wmts_layer(map_base)
    bounds = _compute_map_bounds(parcelles)

    svg_w = _PAGE_W_MM
    svg_h = _PAGE_H_MM

    # Choose zoom level appropriate for 1/25000
    zoom = 14

    # Compute tile for map centre
    centre_lng = (bounds["min_lng"] + bounds["max_lng"]) / 2.0
    centre_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2.0
    tile_x, tile_y = _lng_lat_to_tile(centre_lng, centre_lat, zoom)

    # Attempt to fetch the tile; fall back to white background on error
    img_data_uri = ""
    try:
        tile_bytes = await _fetch_wmts_tile(layer=layer, z=zoom, x=tile_x, y=tile_y)
        b64 = base64.b64encode(tile_bytes).decode("ascii")
        img_data_uri = f"data:image/png;base64,{b64}"
    except Exception:
        # Graceful fallback — blank white area
        img_data_uri = ""

    # --- SVG elements ---------------------------------------------------------
    elements: list[str] = []

    # Base map image or white background
    if img_data_uri:
        elements.append(
            f'<image x="0" y="0" width="{svg_w}" height="{svg_h}" '
            f'href="{img_data_uri}" preserveAspectRatio="xMidYMid slice"/>'
        )
    else:
        elements.append(
            f'<rect x="0" y="0" width="{svg_w}" height="{svg_h}" fill="white"/>'
        )

    # --- Parcel polygon overlays ---------------------------------------------
    from shapely.ops import unary_union

    union_centroid = unary_union(parcelles).centroid

    for parcel in parcelles:
        coords = list(parcel.exterior.coords)
        pts = " ".join(
            f"{_geo_to_svg(lng, lat, bounds, svg_w, svg_h)[0]:.3f},"
            f"{_geo_to_svg(lng, lat, bounds, svg_w, svg_h)[1]:.3f}"
            for lng, lat in coords
        )
        elements.append(
            f'<polygon points="{pts}" '
            f'fill="none" stroke="#CC0000" stroke-width="0.5"/>'
        )

    # --- Red circle at centroid (radius 30mm) --------------------------------
    cx, cy = _geo_to_svg(union_centroid.x, union_centroid.y, bounds, svg_w, svg_h)
    elements.append(
        f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="30" '
        f'fill="none" stroke="#FF0000" stroke-width="1.5"/>'
    )

    # --- North arrow (top-left corner) ---------------------------------------
    elements.append(_north_arrow_svg(x=15.0, y=20.0))

    # --- Scale text (bottom-right) -------------------------------------------
    elements.append(
        f'<text x="{svg_w - 3}" y="{svg_h - 3}" '
        f'text-anchor="end" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="5" fill="#222222">'
        f"Échelle 1/25000 — IGN"
        f"</text>"
    )

    body = "\n  ".join(elements)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {svg_w} {svg_h}" '
        f'width="{svg_w}mm" height="{svg_h}mm">\n'
        f"  {body}\n"
        f"</svg>"
    )
