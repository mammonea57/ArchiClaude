"""Tests for the multi-constraint MAX envelope solver (Phase 4).

Reference scenario : Nogent-sur-Marne, 80 rue des Héros (UA1).

PLU UA1 base : 80% emprise, 18 m hauteur, R+5, retrait 3 m latéral,
6m fond. Overlays applied :

  - ABF 500m (Église Saint-Saturnin, MH classé 1862, ~390 m)
  - Linéaire commercial L.151-16 côté Mairie
  - PPRI bleue : PHEC 33.50 NGF, terrain 33.20 NGF
  - Voisins BD TOPO : Mairie (n°88) + voisin briques (n°78)
  - Bonus UA1 toiture : +2 m
"""

from __future__ import annotations

from shapely.geometry import Polygon, mapping

from core.feasibility.multi_constraint_solver import (
    AbfPerimetre,
    LineaireCommercialLayer,
    MultiConstraintEnvelope,
    NeighborBuilding,
    NogentLayers,
    PpriCote,
    solve_max_envelope_multi_constraint,
)
from core.plu.schemas import NumericRules


def _nogent_80_heros_parcelle() -> dict:
    """≈ 500 m² rectangle aligned along Rue des Héros.

    25 m frontage × 20 m depth, metric CRS (Lambert-93-shaped).
    """
    return dict(mapping(Polygon([(0, 0), (25, 0), (25, 20), (0, 20)])))


def _plu_ua1_base() -> NumericRules:
    return NumericRules(
        hauteur_max_m=18.0,
        hauteur_max_niveaux=5,
        emprise_max_pct=80.0,
        recul_voirie_m=0.0,    # alignement forcé
        recul_limite_lat_m=3.0,
        recul_fond_m=6.0,
    )


def test_nogent_80_heros_full_chain() -> None:
    """All 13 steps run, binding constraints surfaced, envelope coherent."""
    parcelle = _nogent_80_heros_parcelle()
    layers = NogentLayers(
        abf=AbfPerimetre(
            monument_nom="Église Saint-Saturnin",
            monument_ref="PA00079894",
            distance_m=390.0,
            avis_conforme=True,
        ),
        lineaire_commercial=[
            LineaireCommercialLayer(
                geometry_geojson=dict(
                    mapping(Polygon([(0, -1), (25, -1), (25, 0), (0, 0)]))
                ),
                hauteur_rdc_commerce_min_m=3.0,
                interdit_logement_rdc=True,
            )
        ],
        ppri=PpriCote(
            cote_phec_ngf=33.50,
            cote_terrain_ngf=33.20,
            marge_securite_m=0.20,
            zone="bleue",
        ),
        neighbors=[
            # Mairie de Nogent (n°88) — adjacent east
            NeighborBuilding(
                geometry_geojson=dict(
                    mapping(Polygon([(25.5, 0), (40, 0), (40, 20), (25.5, 20)]))
                ),
                hauteur_m=15.0,
                is_principal=True,
            ),
            # Voisin briques R+4 (n°78) — adjacent west
            NeighborBuilding(
                geometry_geojson=dict(
                    mapping(Polygon([(-15, 0), (-0.5, 0), (-0.5, 20), (-15, 20)]))
                ),
                hauteur_m=12.0,
                is_principal=True,
            ),
        ],
        ua1_bonus_toiture_eligible=True,
        ua1_bonus_pignon_eligible=False,
    )

    result = solve_max_envelope_multi_constraint(
        _plu_ua1_base(), parcelle, layers, zone_plu="UA1"
    )

    assert isinstance(result, MultiConstraintEnvelope)
    # All 13 steps recorded.
    assert len(result.trace) == 13
    assert [t.step for t in result.trace] == list(range(1, 14))

    # ABF 500m fired (Saint-Saturnin to 390 m).
    abf_step = next(t for t in result.trace if t.step == 4)
    assert abf_step.applied is True
    assert "Saint-Saturnin" in abf_step.rationale

    # Linéaire commercial fired.
    lin_step = next(t for t in result.trace if t.step == 5)
    assert lin_step.applied is True
    assert lin_step.binding is True

    # PPRI fired (terrain 33.20 < PHEC+0.20 = 33.70).
    ppri_step = next(t for t in result.trace if t.step == 8)
    assert ppri_step.applied is True
    assert ppri_step.binding is True

    # PLU UA1 bonus toiture applied.
    plu_step = next(t for t in result.trace if t.step == 9)
    assert plu_step.applied is True
    assert "toiture" in plu_step.rationale

    # R.111-18 fired with 2 neighbours.
    r111_step = next(t for t in result.trace if t.step == 11)
    assert r111_step.applied is True
    assert r111_step.binding is True

    # Envelope coherent.
    env = result.envelope
    assert env.emprise_max_pct == 80.0
    # Height : 18 + 2 toiture - 0.50 PPRI = ~19.5 m
    assert 19.0 <= env.hauteur_max_plu_m <= 20.5
    # Niveaux : floor(19.5 / 3) = 6 niveaux total
    assert env.niveaux_max_plu in (6, 7)
    # SDP > 0 et footprint non vide.
    assert env.sdp_max_plu_m2 > 0
    assert env.footprint_max_plu_geojson != {}

    # Constraints applied populated.
    assert "ABF 500m" in result.constraints_applied
    assert any("Linéaire commercial" in c for c in result.constraints_applied)
    assert "PPRI" in result.constraints_applied
    assert "R.111-18" in result.constraints_applied
    assert any("PLU UA1" in c for c in result.constraints_applied)


def test_minimal_no_layers_still_works() -> None:
    """No nogentLayers → 13 trace rows, only PLU UA1 + retrait fire."""
    result = solve_max_envelope_multi_constraint(
        _plu_ua1_base(), _nogent_80_heros_parcelle(), None, zone_plu="UA1"
    )
    assert len(result.trace) == 13
    plu_step = next(t for t in result.trace if t.step == 9)
    assert plu_step.binding is True
    abf_step = next(t for t in result.trace if t.step == 4)
    assert abf_step.applied is False


def test_height_floor_with_pignon_bonus() -> None:
    """UA1 pignon bonus adds 1 niveau on top of toiture bonus."""
    layers = NogentLayers(
        ua1_bonus_toiture_eligible=True,
        ua1_bonus_pignon_eligible=True,
    )
    result = solve_max_envelope_multi_constraint(
        _plu_ua1_base(), _nogent_80_heros_parcelle(), layers, zone_plu="UA1"
    )
    # 18 + 2 toiture = 20m → 6 niveaux, +1 pignon = 7 niveaux
    assert result.envelope.niveaux_max_plu >= 6
