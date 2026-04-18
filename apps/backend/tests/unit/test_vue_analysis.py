"""Tests for core.analysis.vue_analysis — vue droite/oblique detection."""


from core.analysis.vue_analysis import classify_vue_type, detect_vue_conflicts
from core.feasibility.schemas import VueAnalysisResult

# ── classify_vue_type ─────────────────────────────────────────────────────────

def test_classify_droite_10():
    assert classify_vue_type(10.0) == "droite"


def test_classify_droite_44():
    assert classify_vue_type(44.9) == "droite"


def test_classify_droite_0():
    assert classify_vue_type(0.0) == "droite"


def test_classify_oblique_46():
    assert classify_vue_type(46.0) == "oblique"


def test_classify_oblique_89():
    assert classify_vue_type(89.0) == "oblique"


def test_classify_oblique_45():
    assert classify_vue_type(45.0) == "oblique"


# ── detect_vue_conflicts ──────────────────────────────────────────────────────

# Paris centroid ≈ (48.8566, 2.3522)
_CENTROID = (48.8566, 2.3522)


def test_no_conflicts_far_away():
    """Ouverture 500m away → no conflict."""
    # ~0.005° ≈ 500m in lat
    ouvertures = [
        {"batiment_id": "A", "etage": 1, "type": "fenetre", "lat": 48.8616, "lng": 2.3522}
    ]
    result = detect_vue_conflicts(
        ouvertures=ouvertures,
        footprint_centroid=_CENTROID,
        projet_hauteur_m=10.0,
    )
    assert isinstance(result, VueAnalysisResult)
    assert result.risque_vue == "aucun"
    assert len(result.conflits) == 0


def test_vue_droite_conflict_very_close():
    """Ouverture ~5m away (same lat/lng essentially) → droite conflict → majeur."""
    # ~0.00005° ≈ 5m lat
    ouvertures = [
        {"batiment_id": "B", "etage": 0, "type": "fenetre", "lat": 48.85660, "lng": 2.35225}
    ]
    result = detect_vue_conflicts(
        ouvertures=ouvertures,
        footprint_centroid=_CENTROID,
        projet_hauteur_m=10.0,
    )
    assert result.risque_vue == "majeur"
    assert result.nb_conflits_droite >= 1


def test_empty_ouvertures():
    result = detect_vue_conflicts(
        ouvertures=[],
        footprint_centroid=_CENTROID,
        projet_hauteur_m=10.0,
    )
    assert result.risque_vue == "aucun"
    assert len(result.conflits) == 0
    assert result.nb_conflits_droite == 0
    assert result.nb_conflits_oblique == 0


def test_result_is_vue_analysis_result():
    result = detect_vue_conflicts(
        ouvertures=[],
        footprint_centroid=_CENTROID,
        projet_hauteur_m=8.0,
    )
    assert isinstance(result, VueAnalysisResult)


def test_ouvertures_are_recorded():
    """All passed ouvertures should appear in ouvertures_detectees."""
    ouvertures = [
        {"batiment_id": "X", "etage": 2, "type": "baie_vitree", "lat": 48.8616, "lng": 2.3522},
        {"batiment_id": "Y", "etage": 1, "type": "fenetre", "lat": 48.8516, "lng": 2.3522},
    ]
    result = detect_vue_conflicts(
        ouvertures=ouvertures,
        footprint_centroid=_CENTROID,
        projet_hauteur_m=10.0,
    )
    assert len(result.ouvertures_detectees) == 2


def test_conflict_fields():
    """Conflict item must have distance_m, type_vue, distance_min_requise_m, deficit_m."""
    ouvertures = [
        {"batiment_id": "Z", "etage": 0, "type": "fenetre", "lat": 48.85660, "lng": 2.35225}
    ]
    result = detect_vue_conflicts(
        ouvertures=ouvertures,
        footprint_centroid=_CENTROID,
        projet_hauteur_m=10.0,
    )
    if result.conflits:
        c = result.conflits[0]
        assert c.distance_m >= 0
        assert c.type_vue in ("droite", "oblique")
        assert c.distance_min_requise_m > 0
        assert c.deficit_m > 0
