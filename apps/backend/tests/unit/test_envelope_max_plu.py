"""Unit tests for compute_max_envelope — the MAX PLU envelope a
parcelle can legally sustain, independent of the designed project.
"""

from __future__ import annotations

from shapely.geometry import Polygon, mapping

from core.building_model.pipeline import compute_max_envelope
from core.building_model.schemas import EnvelopeMaxPLU
from core.plu.schemas import NumericRules


def _metric_rect_500m2_geojson() -> dict:
    """A 25 m × 20 m = 500 m² rectangle in a metric CRS.

    Bounds are kept > 1° so the heuristic in compute_max_envelope treats
    them as already-metric (no WGS84 reprojection).
    """
    return dict(mapping(Polygon([(0, 0), (25, 0), (25, 20), (0, 20)])))


def test_nogent_ua1_500m2_max_envelope() -> None:
    """Nogent UA1 reference case.

    Inputs:
      - 500 m² rectangular parcelle (25 m × 20 m)
      - emprise 80 %, hauteur 18 m, R+5, retrait isotrope 3 m

    Expected:
      - footprint after isotropic 3 m inward buffer = 19 m × 14 m = 266 m²
        (which is BELOW the 0.80 × 500 = 400 m² emprise cap → cap inactive)
      - hauteur_max_plu_m = min(18, 5*3 + 0.5) = 15.5
      - niveaux_max_plu = floor(15.5 / 3) = 5
      - sdp_max_plu_m2 ≈ 266 × 5 = 1330 m²
    """
    rules = NumericRules(
        hauteur_max_m=18.0,
        hauteur_max_niveaux=5,
        emprise_max_pct=80.0,
        recul_voirie_m=3.0,
        recul_limite_lat_m=3.0,
        recul_fond_m=3.0,
    )
    parcelle = _metric_rect_500m2_geojson()

    env = compute_max_envelope(rules, parcelle)

    assert isinstance(env, EnvelopeMaxPLU)

    # Footprint after 3 m retrait: 19 × 14 = 266 m²
    assert 260.0 <= env.emprise_max_m2 <= 270.0
    assert env.emprise_max_pct == 80.0

    # Height = min(18, 5*3 + 0.5) = 15.5
    assert env.hauteur_max_plu_m == 15.5
    assert env.niveaux_max_plu == 5

    # SDP = footprint × 5 niveaux
    expected_sdp = env.emprise_max_m2 * 5
    assert abs(env.sdp_max_plu_m2 - expected_sdp) < 0.1

    assert env.retrait_applique_m == 3.0
    assert env.footprint_max_plu_geojson  # non-empty


def test_emprise_cap_binding() -> None:
    """When emprise_max_pct caps the buffered footprint, the cap wins.

    1000 m² parcelle (50 × 20), retrait 1 m → buffered ≈ 48 × 18 = 864 m².
    With emprise 50 % → cap = 500 m². Cap is binding.
    """
    rules = NumericRules(
        hauteur_max_m=12.0,
        emprise_max_pct=50.0,
        recul_voirie_m=1.0,
        recul_limite_lat_m=1.0,
        recul_fond_m=1.0,
    )
    parcelle = dict(mapping(Polygon([(0, 0), (50, 0), (50, 20), (0, 20)])))

    env = compute_max_envelope(rules, parcelle)

    # Cap binding → emprise = 50% × 1000 = 500 m²
    assert abs(env.emprise_max_m2 - 500.0) < 1.0
    assert env.niveaux_max_plu == 4  # floor(12 / 3) = 4


def test_height_cap_min_of_hauteur_and_niveaux() -> None:
    """hauteur_max_m=9 binds over niveaux_max=5 (5×3+0.5=15.5)."""
    rules = NumericRules(
        hauteur_max_m=9.0,
        hauteur_max_niveaux=5,
        emprise_max_pct=100.0,
        recul_voirie_m=0.0,
        recul_limite_lat_m=0.0,
        recul_fond_m=0.0,
    )
    parcelle = dict(mapping(Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])))

    env = compute_max_envelope(rules, parcelle)

    assert env.hauteur_max_plu_m == 9.0
    assert env.niveaux_max_plu == 3  # floor(9 / 3) = 3


def test_sdp_capped_by_cos() -> None:
    """COS × terrain caps SDP below the geometric ceiling."""
    rules = NumericRules(
        hauteur_max_m=18.0,
        hauteur_max_niveaux=5,
        emprise_max_pct=80.0,
        recul_voirie_m=0.0,
        recul_limite_lat_m=0.0,
        recul_fond_m=0.0,
        cos=1.5,  # 500 × 1.5 = 750 m² hard SDP cap
    )
    parcelle = _metric_rect_500m2_geojson()

    env = compute_max_envelope(rules, parcelle)

    # Without COS: emprise (400) × 5 = 2000 m². With COS: cap 750.
    assert env.sdp_max_plu_m2 <= 750.0 + 0.5
    assert env.sdp_max_plu_m2 >= 749.0


def test_no_height_rule_falls_back_to_single_niveau() -> None:
    """Missing hauteur PLU → 1 niveau fallback + note."""
    rules = NumericRules(
        emprise_max_pct=100.0,
        recul_voirie_m=0.0,
        recul_limite_lat_m=0.0,
        recul_fond_m=0.0,
    )
    parcelle = _metric_rect_500m2_geojson()

    env = compute_max_envelope(rules, parcelle)

    assert env.niveaux_max_plu == 1
    assert env.hauteur_max_plu_m == 3.0
    assert any("hauteur" in n.lower() for n in env.notes)
