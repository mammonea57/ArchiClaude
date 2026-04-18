"""Tests for core.analysis.pre_instruction — deterministic checklist generator."""

import pytest

from core.analysis.pre_instruction import generate_checklist
from core.feasibility.schemas import PreInstructionItem


def _item_names(items: list[PreInstructionItem]) -> list[str]:
    return [i.demarche for i in items]


def _find(items: list[PreInstructionItem], demarche: str) -> PreInstructionItem | None:
    for i in items:
        if demarche in i.demarche:
            return i
    return None


# ── always-present items ──────────────────────────────────────────────────────

def test_always_includes_geometre():
    items = generate_checklist(alerts=[], risk_score=10)
    assert any("géomètre" in i.demarche.lower() for i in items)


def test_geometre_timing_is_90():
    items = generate_checklist(alerts=[], risk_score=10)
    geometre = next(i for i in items if "géomètre" in i.demarche.lower())
    assert geometre.timing_jours == 90


def test_always_includes_servitudes():
    items = generate_checklist(alerts=[], risk_score=10)
    assert any("servitudes" in i.demarche.lower() for i in items)


def test_servitudes_timing_is_60():
    items = generate_checklist(alerts=[], risk_score=10)
    serv = next(i for i in items if "servitudes" in i.demarche.lower())
    assert serv.timing_jours == 60


# ── conditional: ABF ─────────────────────────────────────────────────────────

def test_abf_when_monument():
    alerts = [{"type": "abf", "message": "monument historique à 450m"}]
    items = generate_checklist(alerts=alerts, risk_score=20)
    abf = _find(items, "ABF")
    assert abf is not None
    assert abf.priorite == "obligatoire"
    assert abf.timing_jours == 45


def test_no_abf_without_monument():
    items = generate_checklist(alerts=[], risk_score=20)
    assert _find(items, "ABF") is None


# ── conditional: étude sol G2 ────────────────────────────────────────────────

def test_g2_when_argiles():
    alerts = [{"type": "argiles", "message": "retrait-gonflement argiles présent"}]
    items = generate_checklist(alerts=alerts, risk_score=20)
    g2 = _find(items, "G2")
    assert g2 is not None
    assert g2.priorite == "obligatoire"
    assert g2.timing_jours == 75


def test_g2_when_sol_pollue():
    alerts = [{"type": "sol_pollue", "message": "site BASIAS recensé"}]
    items = generate_checklist(alerts=alerts, risk_score=20)
    assert _find(items, "G2") is not None


def test_no_g2_without_sol_alert():
    items = generate_checklist(alerts=[], risk_score=20)
    assert _find(items, "G2") is None


# ── conditional: RDV pré-instruction ─────────────────────────────────────────

def test_pre_instruction_high_risk():
    items = generate_checklist(alerts=[], risk_score=50)
    rdv = _find(items, "pré-instruction")
    assert rdv is not None
    assert rdv.priorite == "fortement_recommande"
    assert rdv.timing_jours == 60


def test_pre_instruction_low_risk():
    items = generate_checklist(alerts=[], risk_score=30)
    rdv = _find(items, "pré-instruction")
    assert rdv is not None
    assert rdv.priorite == "recommande"


# ── conditional: acoustique ──────────────────────────────────────────────────

def test_acoustique_when_bruit():
    items = generate_checklist(alerts=[], risk_score=10, classement_sonore=2)
    acou = _find(items, "acoustique")
    assert acou is not None
    assert acou.timing_jours == 45


def test_no_acoustique_when_no_bruit():
    items = generate_checklist(alerts=[], risk_score=10, classement_sonore=None)
    assert _find(items, "acoustique") is None


def test_no_acoustique_when_classement_3():
    items = generate_checklist(alerts=[], risk_score=10, classement_sonore=3)
    assert _find(items, "acoustique") is None


# ── conditional: RE2020 thermique ────────────────────────────────────────────

def test_re2020_when_tall():
    items = generate_checklist(alerts=[], risk_score=10, nb_niveaux=5)
    re = _find(items, "RE2020")
    assert re is not None
    assert re.timing_jours == 30


def test_no_re2020_when_short():
    items = generate_checklist(alerts=[], risk_score=10, nb_niveaux=3)
    assert _find(items, "RE2020") is None


# ── conditional: notification voisins ────────────────────────────────────────

def test_voisins_when_high_risk():
    items = generate_checklist(alerts=[], risk_score=70)
    voisins = _find(items, "voisins")
    assert voisins is not None
    assert voisins.timing_jours == 15


def test_no_voisins_when_low_risk():
    items = generate_checklist(alerts=[], risk_score=50)
    assert _find(items, "voisins") is None


# ── ordering ─────────────────────────────────────────────────────────────────

def test_sorted_by_timing():
    """Items must be sorted descending by timing_jours (J-90 first)."""
    alerts = [{"type": "abf", "message": "x"}, {"type": "argiles", "message": "y"}]
    items = generate_checklist(alerts=alerts, risk_score=70, classement_sonore=1, nb_niveaux=5)
    timings = [i.timing_jours for i in items]
    assert timings == sorted(timings, reverse=True)


def test_all_items_are_pre_instruction_items():
    items = generate_checklist(alerts=[], risk_score=30)
    for item in items:
        assert isinstance(item, PreInstructionItem)
