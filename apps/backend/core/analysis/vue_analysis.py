"""Vue droite/oblique analysis — conflict detection for neighbouring openings.

Implements the French Code Civil distance rules:
- Vue droite (perpendicular): minimum 1.90m from wall face (here simplified
  to 19m haversine distance from project centroid as per spec).
- Vue oblique (angled): minimum 0.60m (here simplified to 6m).
"""

from __future__ import annotations

import math
from typing import Literal

from core.feasibility.schemas import Ouverture, VueAnalysisResult, VueConflict

_DISTANCE_MIN_DROITE_M = 19.0
_DISTANCE_MIN_OBLIQUE_M = 6.0
_EARTH_RADIUS_M = 6_371_000.0


# ── Haversine helper ──────────────────────────────────────────────────────────

def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in metres between two WGS84 points."""
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ── Vue type classifier ───────────────────────────────────────────────────────

def classify_vue_type(angle_deg: float) -> Literal["droite", "oblique"]:
    """Classify a view angle as droite (< 45°) or oblique (>= 45°).

    Args:
        angle_deg: Angle between the window normal and the sight line, in degrees.

    Returns:
        "droite" for angles < 45°, "oblique" for angles >= 45°.
    """
    return "droite" if angle_deg < 45.0 else "oblique"


# ── Conflict detector ─────────────────────────────────────────────────────────

def detect_vue_conflicts(
    *,
    ouvertures: list[dict],
    footprint_centroid: tuple[float, float],
    projet_hauteur_m: float,
) -> VueAnalysisResult:
    """Detect vue droite/oblique conflicts between neighbouring openings and project.

    In v1, all openings are classified as vue droite (perpendicular) because
    computing the angle requires facade orientation data not yet available.

    Args:
        ouvertures: List of dicts with keys: batiment_id, etage, type, lat, lng.
        footprint_centroid: (lat, lng) of the project footprint centroid.
        projet_hauteur_m: Project height in metres (reserved for future use).

    Returns:
        VueAnalysisResult with all detected conflicts and risk level.
    """
    centroid_lat, centroid_lng = footprint_centroid

    parsed_ouvertures: list[Ouverture] = []
    conflits: list[VueConflict] = []

    for raw in ouvertures:
        ouv = Ouverture(
            batiment_id=raw["batiment_id"],
            etage=int(raw["etage"]),
            type=raw["type"],
            lat=float(raw["lat"]),
            lng=float(raw["lng"]),
        )
        parsed_ouvertures.append(ouv)

        distance = _haversine(centroid_lat, centroid_lng, ouv.lat, ouv.lng)

        # v1: all openings treated as vue droite
        vue_type: Literal["droite", "oblique"] = "droite"
        dist_min = _DISTANCE_MIN_DROITE_M

        if distance < dist_min:
            deficit = dist_min - distance
            conflits.append(
                VueConflict(
                    ouverture=ouv,
                    distance_m=distance,
                    type_vue=vue_type,
                    distance_min_requise_m=dist_min,
                    deficit_m=deficit,
                )
            )

    nb_droite = sum(1 for c in conflits if c.type_vue == "droite")
    nb_oblique = sum(1 for c in conflits if c.type_vue == "oblique")

    if nb_droite > 0:
        risque: Literal["aucun", "mineur", "majeur"] = "majeur"
    elif nb_oblique > 0:
        risque = "mineur"
    else:
        risque = "aucun"

    return VueAnalysisResult(
        ouvertures_detectees=parsed_ouvertures,
        conflits=conflits,
        nb_conflits_droite=nb_droite,
        nb_conflits_oblique=nb_oblique,
        risque_vue=risque,
    )
