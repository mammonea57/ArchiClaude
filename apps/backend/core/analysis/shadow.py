"""Shadow simulation — solar position + 2-mode shadow projection.

Mode A: critical winter shadows (Dec 21, 10h/12h/14h).
Mode B: contextual aggravation vs existing neighbour shadows.

Uses simplified astronomical formulas appropriate for metropolitan France
(lat ~43–51°N).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

# ── Dataclasses (NOT Pydantic — internal computation results) ─────────────────

@dataclass
class ShadowModeAResult:
    """Three critical Dec-21 shadows at 10h, 12h, 14h."""
    shadows: list[dict] = field(default_factory=list)  # [{"hour": int, "shadow": BaseGeometry}]
    max_shadow_length_m: float = 0.0


@dataclass
class ShadowModeBResult:
    """Contextual aggravation vs existing neighbour shadows."""
    ombre_existante_m2: float = 0.0
    ombre_future_m2: float = 0.0
    ombre_ajoutee_m2: float = 0.0
    pct_aggravation: float = 0.0
    project_shadow: BaseGeometry | None = None


# ── Solar position ────────────────────────────────────────────────────────────

def compute_sun_position(*, lat: float, lng: float, month: int, day: int, hour: float) -> tuple[float, float]:
    """Return (altitude_deg, azimuth_deg) for a given location and time.

    Uses simplified astronomical formulas (Spencer 1971 / standard textbook).
    Longitude is used to compute the approximate solar time offset vs UTC.
    Azimuth is measured clockwise from north (180° = south).

    Args:
        lat: Latitude in decimal degrees.
        lng: Longitude in decimal degrees.
        month: Month (1–12).
        day: Day of month.
        hour: Local solar hour (e.g. 12 = solar noon).

    Returns:
        (altitude_degrees, azimuth_degrees)
    """
    # Day of year
    doy = _day_of_year(month, day)

    # Solar declination (degrees)
    declination = 23.45 * math.sin(math.radians((360.0 / 365.0) * (doy - 80)))

    # Hour angle: 0 at solar noon, ±15°/hour
    hour_angle = 15.0 * (hour - 12.0)

    lat_r = math.radians(lat)
    dec_r = math.radians(declination)
    ha_r = math.radians(hour_angle)

    sin_alt = (
        math.sin(lat_r) * math.sin(dec_r)
        + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r)
    )
    # Clamp to [-1, 1] to guard against floating-point error
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude_rad = math.asin(sin_alt)
    altitude_deg = math.degrees(altitude_rad)

    # Azimuth (from north, clockwise)
    cos_alt = math.cos(altitude_rad)
    if cos_alt < 1e-10:
        # Sun is at zenith
        azimuth_deg = 180.0
    else:
        cos_az = (math.sin(dec_r) - math.sin(lat_r) * sin_alt) / (math.cos(lat_r) * cos_alt)
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth_deg = math.degrees(math.acos(cos_az))
        # In the afternoon (hour > 12) azimuth is > 180° (west side)
        if hour > 12.0:
            azimuth_deg = 360.0 - azimuth_deg

    return altitude_deg, azimuth_deg


def _day_of_year(month: int, day: int) -> int:
    """Approximate day of year (ignores leap years)."""
    days_in_months = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return sum(days_in_months[: month - 1]) + day


# ── Shadow projection ─────────────────────────────────────────────────────────

def compute_shadow_polygon(
    building: BaseGeometry,
    hauteur_m: float,
    sun_altitude: float,
    sun_azimuth: float,
) -> BaseGeometry:
    """Project a building's footprint shadow onto the ground plane.

    The shadow is cast in the direction opposite to the sun (azimuth + 180°).
    Shadow length = hauteur_m / tan(sun_altitude).

    Args:
        building: Shapely geometry of the building footprint (metres CRS).
        hauteur_m: Building height in metres.
        sun_altitude: Solar altitude angle in degrees (> 0 = above horizon).
        sun_azimuth: Solar azimuth in degrees clockwise from north.

    Returns:
        Convex hull of the union of the original footprint and its translated
        shadow polygon.
    """
    if sun_altitude <= 0:
        # Sun below horizon — return empty polygon (no shadow)
        return building.convex_hull

    alt_r = math.radians(sun_altitude)
    shadow_length = hauteur_m / math.tan(alt_r)

    # Shadow direction = azimuth + 180° (opposite to sun)
    shadow_dir_deg = (sun_azimuth + 180.0) % 360.0
    shadow_dir_r = math.radians(shadow_dir_deg)

    # Convert azimuth (clockwise from north) to standard math angle
    # North = +y, East = +x  →  dx = sin(azimuth), dy = cos(azimuth)
    dx = shadow_length * math.sin(shadow_dir_r)
    dy = shadow_length * math.cos(shadow_dir_r)

    from shapely.affinity import translate
    translated = translate(building, xoff=dx, yoff=dy)

    return unary_union([building, translated]).convex_hull


# ── Mode A ───────────────────────────────────────────────────────────────────

def compute_shadow_mode_a(
    building: BaseGeometry,
    hauteur_m: float,
    lat: float = 48.8566,
    lng: float = 2.3522,
) -> ShadowModeAResult:
    """Compute 3 critical winter shadows: Dec 21 at 10h, 12h, 14h.

    Args:
        building: Building footprint geometry (projected CRS, metres).
        hauteur_m: Building height in metres.
        lat: Latitude (default Paris).
        lng: Longitude (default Paris).

    Returns:
        ShadowModeAResult with a list of 3 shadow entries.
    """
    critical_hours = [10, 12, 14]
    shadows = []
    max_len = 0.0

    for h in critical_hours:
        alt, az = compute_sun_position(lat=lat, lng=lng, month=12, day=21, hour=h)
        shadow = compute_shadow_polygon(building, hauteur_m=hauteur_m, sun_altitude=alt, sun_azimuth=az)
        if alt > 0:
            shadow_length = hauteur_m / math.tan(math.radians(alt))
            max_len = max(max_len, shadow_length)
        shadows.append({"hour": h, "shadow": shadow, "sun_altitude": alt, "sun_azimuth": az})

    return ShadowModeAResult(shadows=shadows, max_shadow_length_m=max_len)


# ── Mode B ───────────────────────────────────────────────────────────────────

def compute_shadow_mode_b(
    projet: BaseGeometry,
    hauteur_m: float,
    voisins: list[dict],
    lat: float = 48.8566,
    lng: float = 2.3522,
) -> ShadowModeBResult:
    """Compute shadow aggravation vs existing neighbours — Dec 21 at 12h.

    Args:
        projet: Project building footprint geometry (projected CRS, metres).
        hauteur_m: Project building height in metres.
        voisins: List of neighbour dicts with keys:
            ``geometry`` (GeoJSON-like __geo_interface__ dict) and
            ``hauteur_m`` (float).
        lat: Latitude (default Paris).
        lng: Longitude (default Paris).

    Returns:
        ShadowModeBResult with aggravation metrics.
    """
    alt, az = compute_sun_position(lat=lat, lng=lng, month=12, day=21, hour=12)

    # Existing neighbour shadows
    neighbour_shadows = []
    for v in voisins:
        geom = shape(v["geometry"])
        h = float(v.get("hauteur_m", 10.0))
        s = compute_shadow_polygon(geom, hauteur_m=h, sun_altitude=alt, sun_azimuth=az)
        neighbour_shadows.append(s)

    ombre_existante = unary_union(neighbour_shadows) if neighbour_shadows else projet.__class__()
    ombre_existante_m2 = ombre_existante.area if not ombre_existante.is_empty else 0.0

    # Project shadow
    project_shadow = compute_shadow_polygon(projet, hauteur_m=hauteur_m, sun_altitude=alt, sun_azimuth=az)

    # Future = union of existing + project
    if ombre_existante.is_empty:
        ombre_future = project_shadow
    else:
        ombre_future = unary_union([ombre_existante, project_shadow])

    ombre_future_m2 = ombre_future.area

    # Added shadow = future minus existing
    ombre_ajoutee = ombre_future.difference(ombre_existante)
    ombre_ajoutee_m2 = ombre_ajoutee.area

    # Aggravation percentage
    pct_aggravation = ombre_ajoutee_m2 / ombre_future_m2 * 100.0 if ombre_future_m2 > 0 else 0.0

    return ShadowModeBResult(
        ombre_existante_m2=ombre_existante_m2,
        ombre_future_m2=ombre_future_m2,
        ombre_ajoutee_m2=ombre_ajoutee_m2,
        pct_aggravation=pct_aggravation,
        project_shadow=project_shadow,
    )
