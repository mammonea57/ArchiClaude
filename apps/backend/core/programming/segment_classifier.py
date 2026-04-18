"""Three-tier boundary segment classifier for parcelle geometry.

Classifies each linear segment of a parcelle boundary as one of:
- "voirie"     — fronts a public road (alignment)
- "separative" — lateral or shared boundary with neighbouring plot
- "fond"       — rear boundary

Classification tiers (in priority order):
  1. GPU prescriptions (typepsc=15) — most authoritative
  2. BDTopo road proximity — distance-based
  3. Heuristic fallback — length/position-based, with a warning

All geometries must be in Lambert-93 (EPSG:2154, metric CRS).
"""

from __future__ import annotations

import logging
import math
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from core.programming.schemas import ClassifiedSegment

_log = logging.getLogger(__name__)

# Distance threshold: a segment midpoint closer than this to a road is voirie
_ROAD_VOIRIE_THRESHOLD_M = 15.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _segment_length(start: tuple[float, float], end: tuple[float, float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    return math.hypot(dx, dy)


def _segment_midpoint(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
    return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)


def _extract_segments(parcelle: Polygon) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return consecutive vertex pairs from the exterior ring of the parcelle."""
    coords = list(parcelle.exterior.coords)
    segments = []
    for i in range(len(coords) - 1):
        segments.append((tuple(coords[i]), tuple(coords[i + 1])))  # type: ignore[arg-type]
    return segments  # type: ignore[return-value]


def _midpoint_distance_to_geom(
    mid: tuple[float, float],
    geom: BaseGeometry,
) -> float:
    """Return the distance from a midpoint to a Shapely geometry."""
    from shapely.geometry import Point

    return geom.distance(Point(mid))


# ---------------------------------------------------------------------------
# Tier 1 — GPU prescriptions
# ---------------------------------------------------------------------------


def _classify_by_gpu_prescriptions(
    parcelle: Polygon,
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    prescriptions_gpu: list[dict[str, Any]],
    recul_voirie: float,
    recul_sep: float,
    recul_fond: float,
) -> dict[int, str]:
    """Return a mapping {segment_index: type} for segments matched by GPU."""
    result: dict[int, str] = {}

    for idx, (start, end) in enumerate(segments):
        seg_line = LineString([start, end])
        for presc in prescriptions_gpu:
            geom = presc.get("geometry")
            if geom is None:
                continue
            typepsc = presc.get("typepsc", "")
            sous_type = presc.get("sous_type", "")
            if typepsc != "15":
                continue
            # Check if the prescription geometry intersects or is very close to this segment
            if geom.distance(seg_line) < 2.0:  # within 2 m tolerance
                if sous_type == "01":
                    result[idx] = "voirie"
                elif sous_type == "00":
                    result[idx] = "separative"
                # Other sub_types: no override
    return result


# ---------------------------------------------------------------------------
# Tier 2 — BDTopo roads
# ---------------------------------------------------------------------------


def _classify_by_roads(
    parcelle: Polygon,
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    roads: BaseGeometry,
    recul_voirie: float,
    recul_sep: float,
    recul_fond: float,
) -> dict[int, str]:
    """Classify segments using distance to road geometries.

    Strategy:
    - midpoint distance < threshold → voirie
    - largest midpoint distance to any road → fond
    - everything else → separative
    """
    distances: list[float] = []
    for start, end in segments:
        mid = _segment_midpoint(start, end)
        d = _midpoint_distance_to_geom(mid, roads)
        distances.append(d)

    result: dict[int, str] = {}
    max_dist = max(distances) if distances else 0.0
    fond_idx = distances.index(max_dist)

    for idx, d in enumerate(distances):
        if d < _ROAD_VOIRIE_THRESHOLD_M:
            result[idx] = "voirie"
        elif idx == fond_idx:
            result[idx] = "fond"
        else:
            result[idx] = "separative"

    # If no voirie was found from distances, mark the segment closest to road
    if not any(v == "voirie" for v in result.values()):
        min_dist_idx = distances.index(min(distances))
        result[min_dist_idx] = "voirie"

    return result


# ---------------------------------------------------------------------------
# Tier 3 — Heuristic fallback
# ---------------------------------------------------------------------------


def _classify_heuristic(
    parcelle: Polygon,
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    recul_voirie: float,
    recul_sep: float,
    recul_fond: float,
) -> dict[int, str]:
    """Heuristic classification based on segment length.

    Presumption:
    - Longest segment → voirie (street-facing)
    - Segment most geometrically opposite to voirie → fond
    - Others → séparative

    Issues a warning because this is approximate.
    """
    _log.warning(
        "Segment classification: using heuristic fallback (no roads or GPU prescriptions). "
        "Classification approximative — verify against PLU."
    )

    lengths = [_segment_length(s, e) for s, e in segments]
    max_len = max(lengths)
    voirie_idx = lengths.index(max_len)

    # Compute voirie midpoint
    voirie_mid = _segment_midpoint(segments[voirie_idx][0], segments[voirie_idx][1])

    # Find the segment whose midpoint is farthest from the voirie midpoint → fond
    other_dists = []
    for idx, (start, end) in enumerate(segments):
        if idx == voirie_idx:
            other_dists.append(-1.0)
            continue
        mid = _segment_midpoint(start, end)
        d = math.hypot(mid[0] - voirie_mid[0], mid[1] - voirie_mid[1])
        other_dists.append(d)

    fond_idx = other_dists.index(max(other_dists))

    result: dict[int, str] = {}
    for idx in range(len(segments)):
        if idx == voirie_idx:
            result[idx] = "voirie"
        elif idx == fond_idx:
            result[idx] = "fond"
        else:
            result[idx] = "separative"

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_segments(
    parcelle: Polygon,
    *,
    prescriptions_gpu: list[dict[str, Any]] | None = None,
    roads: BaseGeometry | None = None,
    recul_voirie: float = 5.0,
    recul_sep: float = 3.0,
    recul_fond: float = 3.0,
    recul_formula: str | None = None,
) -> list[ClassifiedSegment]:
    """Classify each boundary segment of the parcelle using a 3-tier strategy.

    Tiers (applied in order, higher tiers override lower for matched segments):
      1. GPU prescriptions (typepsc=15): most authoritative
      2. BDTopo roads: distance-based (< 15 m → voirie)
      3. Heuristic: length-based fallback with warning

    Args:
        parcelle: The parcel polygon in Lambert-93 (EPSG:2154).
        prescriptions_gpu: List of GPU prescription dicts with keys
            ``typepsc``, ``sous_type``, ``geometry`` (Shapely object).
        roads: Shapely geometry representing nearby road network (LineString,
            Polygon, MultiPolygon, etc.).  Distance is computed to this object.
        recul_voirie: Required setback from road alignment, metres.
        recul_sep: Required setback from separative boundary, metres.
        recul_fond: Required setback from rear boundary, metres.
        recul_formula: Optional parametric formula string applied to voirie
            segments (e.g. "H/2 min 3").  Stored on the returned
            ClassifiedSegment for later evaluation.

    Returns:
        List of ClassifiedSegment, one per exterior ring segment.
    """
    raw_segments = _extract_segments(parcelle)

    # --- Tier 3 (base layer) ---
    classification = _classify_heuristic(
        parcelle, raw_segments, recul_voirie, recul_sep, recul_fond
    )

    # --- Tier 2 — override with roads if provided ---
    if roads is not None:
        road_cls = _classify_by_roads(
            parcelle, raw_segments, roads, recul_voirie, recul_sep, recul_fond
        )
        classification.update(road_cls)

    # --- Tier 1 — override with GPU prescriptions if provided ---
    if prescriptions_gpu:
        gpu_cls = _classify_by_gpu_prescriptions(
            parcelle, raw_segments, prescriptions_gpu, recul_voirie, recul_sep, recul_fond
        )
        classification.update(gpu_cls)

    # --- Build ClassifiedSegment objects ---
    _recul_map = {
        "voirie": recul_voirie,
        "separative": recul_sep,
        "fond": recul_fond,
    }

    result: list[ClassifiedSegment] = []
    for idx, (start, end) in enumerate(raw_segments):
        seg_type = classification.get(idx, "separative")
        recul = _recul_map[seg_type]
        formula = recul_formula if seg_type == "voirie" else None
        length = _segment_length(start, end)
        result.append(
            ClassifiedSegment(
                start=start,
                end=end,
                segment_type=seg_type,  # type: ignore[arg-type]
                recul_m=recul,
                recul_formula=formula,
                longueur_m=length,
            )
        )

    return result
