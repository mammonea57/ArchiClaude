"""Unit tests for core.feasibility.engine — run_feasibility orchestrator."""

from __future__ import annotations

import pytest

from core.feasibility.engine import run_feasibility
from core.feasibility.schemas import Brief, FeasibilityResult
from core.plu.schemas import NumericRules


class TestRunFeasibility:
    def _make_rules(self, **kwargs) -> NumericRules:
        defaults = dict(
            hauteur_max_m=15,
            emprise_max_pct=60,
            pleine_terre_min_pct=30,
            recul_voirie_m=5,
            stationnement_par_logement=1.0,
            article_refs={},
            extraction_confidence=0.9,
            extraction_warnings=[],
        )
        defaults.update(kwargs)
        return NumericRules(**defaults)

    def _make_brief(self, **kwargs) -> Brief:
        defaults = dict(
            destination="logement_collectif",
            mix_typologique={"T2": 0.3, "T3": 0.4, "T4": 0.3},
        )
        defaults.update(kwargs)
        return Brief(**defaults)

    def test_basic_run(self):
        """Simple square parcel with basic rules should produce valid result."""
        terrain = {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.48, 48.83],
                    [2.485, 48.83],
                    [2.485, 48.835],
                    [2.48, 48.835],
                    [2.48, 48.83],
                ]
            ],
        }
        rules = self._make_rules()
        brief = self._make_brief()

        result = run_feasibility(terrain_geojson=terrain, numeric_rules=rules, brief=brief)

        assert isinstance(result, FeasibilityResult)
        assert result.surface_terrain_m2 > 0
        assert result.sdp_max_m2 > 0
        assert result.nb_niveaux > 0
        assert result.nb_logements_max > 0
        assert result.compliance is not None

    def test_footprint_geometry_returned(self):
        """Footprint GeoJSON should be non-empty for a valid parcel."""
        terrain = {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.35, 48.87],
                    [2.36, 48.87],
                    [2.36, 48.88],
                    [2.35, 48.88],
                    [2.35, 48.87],
                ]
            ],
        }
        rules = self._make_rules(recul_voirie_m=2.0)
        brief = self._make_brief()

        result = run_feasibility(terrain_geojson=terrain, numeric_rules=rules, brief=brief)

        assert isinstance(result.footprint_geojson, dict)
        assert result.footprint_geojson.get("type") in ("Polygon", "MultiPolygon")

    def test_compliance_populated(self):
        """ComplianceResult should be populated with incendie and RSDU fields."""
        terrain = {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.48, 48.83],
                    [2.485, 48.83],
                    [2.485, 48.835],
                    [2.48, 48.835],
                    [2.48, 48.83],
                ]
            ],
        }
        rules = self._make_rules()
        brief = self._make_brief()

        result = run_feasibility(terrain_geojson=terrain, numeric_rules=rules, brief=brief)

        assert result.compliance is not None
        assert result.compliance.incendie_classement in ("1ere", "2eme", "3A", "4eme", "IGH")
        assert len(result.compliance.rsdu_obligations) == 4
        assert result.compliance.re2020_seuil_applicable in ("2022", "2025", "2028")

    def test_no_servitudes_alerts_empty_input(self):
        """No monuments/risques/servitudes → no hard alerts."""
        terrain = {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.48, 48.83],
                    [2.485, 48.83],
                    [2.485, 48.835],
                    [2.48, 48.835],
                    [2.48, 48.83],
                ]
            ],
        }
        rules = self._make_rules()
        brief = self._make_brief()

        result = run_feasibility(
            terrain_geojson=terrain,
            numeric_rules=rules,
            brief=brief,
            monuments=[],
            risques=[],
            servitudes_gpu=[],
        )

        assert result.alertes_dures == []
        assert result.servitudes_actives == []

    def test_confidence_score_penalised_by_critical_alerts(self):
        """Critical servitude alert should reduce confidence score."""
        from core.sources.georisques import RisqueResult

        terrain = {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.48, 48.83],
                    [2.485, 48.83],
                    [2.485, 48.835],
                    [2.48, 48.835],
                    [2.48, 48.83],
                ]
            ],
        }
        rules = self._make_rules(extraction_confidence=0.9)
        brief = self._make_brief()
        # PPRI triggers a critical alert
        risques = [RisqueResult(type="ppri", code="94052", libelle="Zone inondable haute", niveau_alea=None)]

        result = run_feasibility(
            terrain_geojson=terrain,
            numeric_rules=rules,
            brief=brief,
            risques=risques,
        )

        assert result.confidence_score < 0.9
        assert any(a.level == "critical" for a in result.alertes_dures)

    def test_brief_targets_produce_ecart(self):
        """When brief sets nb_logements target, ecart_brief should include that entry."""
        terrain = {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.48, 48.83],
                    [2.485, 48.83],
                    [2.485, 48.835],
                    [2.48, 48.835],
                    [2.48, 48.83],
                ]
            ],
        }
        rules = self._make_rules()
        brief = self._make_brief(cible_nb_logements=5)

        result = run_feasibility(terrain_geojson=terrain, numeric_rules=rules, brief=brief)

        assert "nb_logements" in result.ecart_brief
        assert result.ecart_brief["nb_logements"].brief_value == 5.0

    def test_sru_rattrapage_commune(self):
        """Rattrapage commune should set LLS obligation on compliance."""
        terrain = {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.48, 48.83],
                    [2.485, 48.83],
                    [2.485, 48.835],
                    [2.48, 48.835],
                    [2.48, 48.83],
                ]
            ],
        }
        rules = self._make_rules()
        brief = self._make_brief()

        result = run_feasibility(
            terrain_geojson=terrain,
            numeric_rules=rules,
            brief=brief,
            commune_sru_statut="rattrapage",
        )

        assert result.compliance is not None
        assert result.compliance.lls_commune_statut == "rattrapage"
