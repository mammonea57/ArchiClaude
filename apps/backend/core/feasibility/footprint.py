"""Footprint calculation — maximum constructible ground-floor area.

All geometries must be in Lambert-93 (EPSG:2154, metric CRS).

Algorithm (v2, 2026-04):
    1. Compute the parcel's minimum-rotated bounding box (OBB). The OBB's
       long axis defines the BUILDING ORIENTATION (architects always align
       the mass with the parcel's main dimension).
    2. Identify the voirie edge = the OBB edge closest to the geocoded
       street point (when provided) or, by default, the shorter edge
       facing the lowest Y in parcel frame ("sud" convention).
    3. Apply per-side setbacks (different for voirie, lateral, rear) in
       the PARCEL-ALIGNED frame, not an isotropic buffer.
    4. Trim the result from the REAR side (not from the centre) when
       capping to emprise_max_pct — this preserves voirie alignment
       which is what a PLU-respecting promoteur always does.
    5. Keep the building as a clean AXIS-ALIGNED rectangle in the
       parcel's rotated frame, then rotate it back to world frame.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.affinity import rotate as shp_rotate
from shapely.affinity import translate as shp_translate
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class FootprintResult:
    """Result of footprint computation."""

    footprint_geom: BaseGeometry
    surface_emprise_m2: float
    surface_pleine_terre_m2: float
    surface_terrain_m2: float


def _oriented_bounding_box(geom: Polygon | MultiPolygon) -> tuple[Polygon, float]:
    """Return the minimum-rotated rectangle of *geom* and its rotation in
    degrees (positive CCW). The rotation is how much the OBB's long edge
    deviates from the world X-axis.
    """
    obb = geom.minimum_rotated_rectangle
    # Compute the angle of the OBB's longer edge with the X-axis.
    coords = list(obb.exterior.coords)[:-1]
    # Pairs of consecutive edges
    edges = [(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    # The "long" edge is the longer of the first two (OBB has 2 lengths).
    e0_len = ((edges[0][1][0] - edges[0][0][0]) ** 2 + (edges[0][1][1] - edges[0][0][1]) ** 2) ** 0.5
    e1_len = ((edges[1][1][0] - edges[1][0][0]) ** 2 + (edges[1][1][1] - edges[1][0][1]) ** 2) ** 0.5
    long_edge = edges[0] if e0_len >= e1_len else edges[1]
    import math
    dx = long_edge[1][0] - long_edge[0][0]
    dy = long_edge[1][1] - long_edge[0][1]
    angle_deg = math.degrees(math.atan2(dy, dx))
    return obb, angle_deg


def _to_aligned_frame(
    geom: BaseGeometry, angle_deg: float, origin: tuple[float, float],
) -> BaseGeometry:
    """Rotate *geom* by -angle_deg around *origin* → axis-aligned frame."""
    return shp_rotate(geom, -angle_deg, origin=origin, use_radians=False)


def _from_aligned_frame(
    geom: BaseGeometry, angle_deg: float, origin: tuple[float, float],
) -> BaseGeometry:
    """Rotate back from aligned frame to world frame."""
    return shp_rotate(geom, angle_deg, origin=origin, use_radians=False)


def _pick_voirie_edge_in_aligned_frame(
    aligned_terrain: Polygon, voirie_point_aligned: Point | None,
) -> str:
    """Return which side of the aligned terrain's bbox faces the voirie:
    "sud" / "nord" / "ouest" / "est" in PARCEL-ALIGNED coordinates.
    """
    minx, miny, maxx, maxy = aligned_terrain.bounds
    if voirie_point_aligned is None:
        # Default: voirie to the south (min-y) — common in French sites.
        return "sud"
    px, py = voirie_point_aligned.x, voirie_point_aligned.y
    # Pick the side whose midline is closest to the voirie point.
    sides = {
        "sud": ((minx + maxx) / 2, miny),
        "nord": ((minx + maxx) / 2, maxy),
        "ouest": (minx, (miny + maxy) / 2),
        "est": (maxx, (miny + maxy) / 2),
    }
    return min(sides.keys(), key=lambda s: (sides[s][0] - px) ** 2 + (sides[s][1] - py) ** 2)


def compute_footprint(
    *,
    terrain: Polygon | MultiPolygon,
    recul_voirie_m: float = 0.0,
    recul_lat_m: float = 0.0,
    recul_fond_m: float = 0.0,
    emprise_max_pct: float = 100.0,
    ebc_geom: BaseGeometry | None = None,
    voirie_point: Point | None = None,
) -> FootprintResult:
    """Compute the maximum constructible footprint given terrain and PLU constraints.

    All input geometries must be in Lambert-93 (EPSG:2154, metres).

    The v2 algorithm aligns the building with the parcel's main axis and
    applies differential setbacks so the resulting footprint sits
    correctly against the voirie and respects lateral/rear margins —
    unlike the previous isotropic buffer which produced a centred,
    miniaturised rectangle disconnected from the street.

    Args:
        terrain: Parcel polygon(s) in Lambert-93.
        recul_voirie_m: Setback from voirie (street-facing edge).
        recul_lat_m: Setback from lateral property boundaries.
        recul_fond_m: Setback from rear boundary.
        emprise_max_pct: Maximum emprise au sol as % of terrain (0–100).
        ebc_geom: Espace Boisé Classé or other no-build zone.
        voirie_point: Optional street-side point in Lambert-93 used to
            identify which edge is the voirie; defaults to the parcel's
            OBB south side when omitted.

    Returns:
        FootprintResult with a clean axis-aligned (to parcel OBB)
        rectangle respecting setbacks and emprise cap.
    """
    terrain_area = terrain.area

    # 1. Oriented bounding box + rotation into aligned frame
    obb, angle = _oriented_bounding_box(terrain)
    origin = terrain.centroid.coords[0]
    aligned_terrain = _to_aligned_frame(terrain, angle, origin)
    aligned_pt = (
        _to_aligned_frame(voirie_point, angle, origin)
        if voirie_point is not None else None
    )

    minx, miny, maxx, maxy = aligned_terrain.bounds

    # 2. Identify voirie side in aligned frame
    voirie_side = _pick_voirie_edge_in_aligned_frame(aligned_terrain, aligned_pt)

    # 3. Apply per-side setbacks (differential). Each side gets its own
    # margin based on whether it's voirie / lateral / rear. Opposite of
    # voirie is "fond" (rear); the two perpendiculars are "laterales".
    OPPOSITE = {"sud": "nord", "nord": "sud", "ouest": "est", "est": "ouest"}
    fond_side = OPPOSITE[voirie_side]
    lateral_sides = {"sud", "nord", "ouest", "est"} - {voirie_side, fond_side}
    side_setback = {voirie_side: recul_voirie_m, fond_side: recul_fond_m}
    for s in lateral_sides:
        side_setback[s] = recul_lat_m

    # Carve the aligned terrain bbox with per-side setbacks
    rect_minx = minx + side_setback.get("ouest", 0.0)
    rect_maxx = maxx - side_setback.get("est", 0.0)
    rect_miny = miny + side_setback.get("sud", 0.0)
    rect_maxy = maxy - side_setback.get("nord", 0.0)

    if rect_maxx - rect_minx <= 0.5 or rect_maxy - rect_miny <= 0.5:
        # Parcel too narrow after setbacks
        return FootprintResult(
            footprint_geom=Polygon(),
            surface_emprise_m2=0.0,
            surface_pleine_terre_m2=terrain_area,
            surface_terrain_m2=terrain_area,
        )

    # 4. Clip to actual aligned terrain (handles non-rectangular parcels)
    rect_aligned = Polygon([
        (rect_minx, rect_miny), (rect_maxx, rect_miny),
        (rect_maxx, rect_maxy), (rect_minx, rect_maxy),
    ])
    footprint_aligned = rect_aligned.intersection(aligned_terrain)
    if footprint_aligned.is_empty:
        return FootprintResult(
            footprint_geom=Polygon(),
            surface_emprise_m2=0.0,
            surface_pleine_terre_m2=terrain_area,
            surface_terrain_m2=terrain_area,
        )

    # 5. EBC subtraction (aligned)
    if ebc_geom is not None and not ebc_geom.is_empty:
        ebc_aligned = _to_aligned_frame(ebc_geom, angle, origin)
        footprint_aligned = footprint_aligned.difference(ebc_aligned)
        if footprint_aligned.is_empty:
            return FootprintResult(
                footprint_geom=Polygon(),
                surface_emprise_m2=0.0,
                surface_pleine_terre_m2=terrain_area,
                surface_terrain_m2=terrain_area,
            )

    # 6. Emprise cap — trim from the REAR (fond) side, not from centroid,
    # so the building stays aligned with the voirie.
    emprise_max_m2 = terrain_area * emprise_max_pct / 100.0
    if footprint_aligned.area > emprise_max_m2:
        fxmin, fymin, fxmax, fymax = footprint_aligned.bounds
        if voirie_side == "sud":
            # Fond is nord (maxy) — shrink max_y downward
            new_maxy = fymin + emprise_max_m2 / (fxmax - fxmin)
            clip = Polygon([
                (fxmin, fymin), (fxmax, fymin),
                (fxmax, new_maxy), (fxmin, new_maxy),
            ])
        elif voirie_side == "nord":
            new_miny = fymax - emprise_max_m2 / (fxmax - fxmin)
            clip = Polygon([
                (fxmin, new_miny), (fxmax, new_miny),
                (fxmax, fymax), (fxmin, fymax),
            ])
        elif voirie_side == "ouest":
            new_maxx = fxmin + emprise_max_m2 / (fymax - fymin)
            clip = Polygon([
                (fxmin, fymin), (new_maxx, fymin),
                (new_maxx, fymax), (fxmin, fymax),
            ])
        else:  # est
            new_minx = fxmax - emprise_max_m2 / (fymax - fymin)
            clip = Polygon([
                (new_minx, fymin), (fxmax, fymin),
                (fxmax, fymax), (new_minx, fymax),
            ])
        footprint_aligned = footprint_aligned.intersection(clip)

    # 7. Rotate the footprint back to world coordinates.
    footprint = _from_aligned_frame(footprint_aligned, angle, origin)
    surface_emprise = footprint.area
    surface_pleine_terre = max(0.0, terrain_area - surface_emprise)

    return FootprintResult(
        footprint_geom=footprint,
        surface_emprise_m2=surface_emprise,
        surface_pleine_terre_m2=surface_pleine_terre,
        surface_terrain_m2=terrain_area,
    )
