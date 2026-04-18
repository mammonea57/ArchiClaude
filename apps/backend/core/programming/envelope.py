"""Envelope calculator — gabarit-enveloppe par tranches horizontales.

Computes the constructible footprint for each storey level, taking into
account parametric setback formulas that make the setback grow with height
(e.g. French PLU règles de prospect).

All geometries must be in Lambert-93 (EPSG:2154, metric CRS).

Formula mini-language
---------------------
Supported recul_formula strings (case-insensitive, spaces ignored):

  "H/2"         — setback = H / 2
  "H/3"         — setback = H / 3
  "H/2 min 3"   — setback = max(H/2, 3)   (minimum floor)
  "H/2 max 6"   — setback = min(H/2, 6)   (maximum ceiling)
  "H/3 min 4"   — setback = max(H/3, 4)
  numeric only  — constant override (e.g. "5")

The parser is regex-based and never uses eval().
"""

from __future__ import annotations

import math
import re

from shapely.geometry import Polygon

from core.programming.schemas import ClassifiedSegment, NiveauFootprint
from core.programming.setback_engine import compute_footprint_by_segments

# ---------------------------------------------------------------------------
# Formula parser
# ---------------------------------------------------------------------------

# Pattern: optional "H/N" part + optional " min X" or " max X" modifiers
_RE_FORMULA = re.compile(
    r"""
    ^
    \s*
    (?:
        H\s*/\s*(?P<divisor>\d+(?:\.\d+)?)  # H/N
        | (?P<const>\d+(?:\.\d+)?)            # plain constant
    )
    (?:
        \s+(?P<mod>min|max)\s+(?P<mod_val>\d+(?:\.\d+)?)
    )?
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _evaluate_formula(formula: str, h: float) -> float | None:
    """Evaluate a recul formula at height H=h.

    Args:
        formula: Formula string (e.g. "H/2 min 3").
        h: Height in metres at the current storey level.

    Returns:
        Computed setback in metres, or None if the formula cannot be parsed.
    """
    m = _RE_FORMULA.match(formula.strip())
    if m is None:
        return None

    if m.group("divisor") is not None:
        divisor = float(m.group("divisor"))
        if divisor == 0:
            return None
        value = h / divisor
    else:
        value = float(m.group("const"))

    if m.group("mod") is not None:
        mod_val = float(m.group("mod_val"))
        mod = m.group("mod").lower()
        if mod == "min":
            value = max(value, mod_val)
        elif mod == "max":
            value = min(value, mod_val)

    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_envelope(
    *,
    parcelle: Polygon,
    segments: list[ClassifiedSegment],
    hauteur_max_m: float,
    hauteur_par_niveau: float = 3.0,
) -> list[NiveauFootprint]:
    """Compute the constructible footprint for each storey level.

    For each level n (0-indexed):
      - floor height h = (n+1) × hauteur_par_niveau
      - For segments with recul_formula: evaluate the formula at h
      - For segments with fixed recul_m: keep as-is
      - Compute footprint via setback_engine.compute_footprint_by_segments

    Args:
        parcelle: The parcel polygon in Lambert-93 (EPSG:2154).
        segments: Classified segments with their setback distances and
            optional recul_formula strings.
        hauteur_max_m: Maximum building height in metres.  Determines the
            number of levels: ceil(hauteur_max_m / hauteur_par_niveau).
        hauteur_par_niveau: Floor-to-floor height in metres (default 3.0).

    Returns:
        List of NiveauFootprint, one per level, from ground floor (niveau=0)
        to top floor.
    """
    nb_niveaux = max(1, math.ceil(hauteur_max_m / hauteur_par_niveau))
    results: list[NiveauFootprint] = []

    for n in range(nb_niveaux):
        h = (n + 1) * hauteur_par_niveau

        # Build segments with setbacks evaluated at this height
        evaluated_segs: list[ClassifiedSegment] = []
        for seg in segments:
            if seg.recul_formula is not None:
                computed = _evaluate_formula(seg.recul_formula, h)
                if computed is not None:
                    # Replace recul_m with the formula-evaluated value
                    evaluated_segs.append(
                        ClassifiedSegment(
                            start=seg.start,
                            end=seg.end,
                            segment_type=seg.segment_type,
                            recul_m=computed,
                            recul_formula=seg.recul_formula,
                            longueur_m=seg.longueur_m,
                        )
                    )
                    continue
            evaluated_segs.append(seg)

        footprint = compute_footprint_by_segments(
            parcelle=parcelle,
            segments=evaluated_segs,
        )

        results.append(
            NiveauFootprint(
                niveau=n,
                hauteur_plancher_m=h,
                footprint=footprint,
                surface_m2=footprint.area,
            )
        )

    return results
