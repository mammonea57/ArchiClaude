"""Site parcel orientation analysis.

Computes the outward-facing azimuth (bearing from north) for each segment
of a parcel's exterior ring. Input polygon must be in a projected CRS
(Lambert-93 / EPSG:2154) so that distances are in metres.

Algorithm:
    For a CCW exterior ring, the outward normal of a segment (dx, dy) is
    obtained by rotating 90° clockwise: normal = (dy, -dx).
    Azimuth = atan2(normal_x, normal_y) in degrees, 0° = north, clockwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon

_MIN_SEGMENT_M = 0.01  # skip degenerate segments shorter than 1 cm

# Cardinal direction bins — 8 directions, 45° each, centred on multiples of 45°
_CARDINALS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


@dataclass(frozen=True)
class SegmentOrientation:
    """Orientation of one exterior ring segment."""

    azimut: float       # outward-facing azimuth in degrees (0=north, clockwise)
    longueur_m: float   # segment length in metres (projected CRS)
    qualification: str  # cardinal label: N, NE, E, SE, S, SO, O, NO
    start_x: float
    start_y: float
    end_x: float
    end_y: float


def _azimuth_degrees(dx: float, dy: float) -> float:
    """Return the azimuth in [0, 360) for a direction vector (dx, dy).

    Convention: 0° = north (+Y), 90° = east (+X), clockwise.
    atan2(dx, dy) gives the angle from north measured clockwise.
    """
    angle = math.degrees(math.atan2(dx, dy))
    return angle % 360.0


def _classify_azimuth(azimut: float) -> str:
    """Map *azimut* (degrees, clockwise from north) to 8 cardinal directions."""
    # Shift by 22.5° so that bins are centred on N, NE, E, …
    index = int((azimut + 22.5) % 360 / 45)
    return _CARDINALS[index]


def compute_orientations(polygon: Polygon) -> list[SegmentOrientation]:
    """Compute outward-facing orientations for each segment of *polygon*.

    Args:
        polygon: A :class:`shapely.geometry.Polygon` in a projected CRS
            where coordinates are in metres (e.g. Lambert-93 / EPSG:2154).
            The exterior ring is expected to be CCW (shapely default).

    Returns:
        List of :class:`SegmentOrientation`, one per non-degenerate segment
        of the exterior ring. Order follows the ring vertex order.
    """
    coords = list(polygon.exterior.coords)
    results: list[SegmentOrientation] = []

    for i in range(len(coords) - 1):
        x0, y0 = coords[i][0], coords[i][1]
        x1, y1 = coords[i + 1][0], coords[i + 1][1]

        dx = x1 - x0
        dy = y1 - y0
        length = math.hypot(dx, dy)

        if length < _MIN_SEGMENT_M:
            continue

        # Outward normal for CCW ring: rotate 90° clockwise → (dy, -dx)
        normal_x = dy
        normal_y = -dx

        azimut = _azimuth_degrees(normal_x, normal_y)
        qualification = _classify_azimuth(azimut)

        results.append(
            SegmentOrientation(
                azimut=azimut,
                longueur_m=length,
                qualification=qualification,
                start_x=x0,
                start_y=y0,
                end_x=x1,
                end_y=y1,
            )
        )

    return results
