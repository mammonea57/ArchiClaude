"""Unit tests for core.feasibility.servitudes — hard constraint detection."""

from __future__ import annotations

import pytest

from core.feasibility.servitudes import ServitudeAlert, detect_servitudes_alerts
from core.sources.georisques import RisqueResult
from core.sources.gpu import GpuServitude
from core.sources.pop import MonumentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _monument(nom: str = "Église Saint-Pierre") -> MonumentResult:
    return MonumentResult(
        reference="PA00086zzz",
        nom=nom,
        date_protection="1900-01-01",
        commune="Paris",
        departement="75",
        lat=48.85,
        lng=2.35,
    )


def _risque(type_: str, niveau_alea: str | None = None) -> RisqueResult:
    return RisqueResult(
        type=type_,
        code=None,
        libelle=f"Risque {type_}",
        niveau_alea=niveau_alea,
    )


def _servitude(libelle: str = "", categorie: str = "") -> GpuServitude:
    return GpuServitude(
        libelle=libelle,
        categorie=categorie,
        txt=None,
        geometry=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_alerts() -> None:
    """Empty inputs → no alerts."""
    alerts = detect_servitudes_alerts(monuments=[], risques=[], servitudes=[])
    assert alerts == []


def test_monument_historique() -> None:
    """Monuments present → ABF warning."""
    alerts = detect_servitudes_alerts(
        monuments=[_monument()],
        risques=[],
        servitudes=[],
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.level == "warning"
    assert alert.type == "abf"
    assert "ABF" in alert.message or "avis" in alert.message.lower()
    assert alert.source == "pop"


def test_ppri() -> None:
    """PPRI risk → critical alert."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[_risque("ppri")],
        servitudes=[],
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.level == "critical"
    assert alert.type == "ppri"
    assert alert.source == "georisques"


def test_argiles_fort() -> None:
    """Argile with niveau_alea 'fort' → warning."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[_risque("argiles", "fort")],
        servitudes=[],
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.level == "warning"
    assert alert.type == "argiles"
    assert alert.source == "georisques"


def test_argiles_moyen_no_alert() -> None:
    """Argile with niveau_alea 'moyen' → no alert (only 'fort' triggers)."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[_risque("argiles", "moyen")],
        servitudes=[],
    )
    assert all(a.type != "argiles" for a in alerts)


def test_sol_pollue_basias() -> None:
    """BASIAS risk → critical sol_pollue alert."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[_risque("basias")],
        servitudes=[],
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.level == "critical"
    assert alert.type == "sol_pollue"
    assert alert.source == "georisques"


def test_sol_pollue_basol() -> None:
    """BASOL risk → critical sol_pollue alert."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[_risque("basol")],
        servitudes=[],
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.level == "critical"
    assert alert.type == "sol_pollue"


def test_ebc_by_libelle() -> None:
    """Servitude with 'ebc' in libelle → EBC warning."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[],
        servitudes=[_servitude(libelle="Espace boisé classé EBC", categorie="EL7")],
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.level == "warning"
    assert alert.type == "ebc"
    assert alert.source == "gpu"


def test_ebc_by_libelle_boise() -> None:
    """Servitude with 'boisé' in libelle → EBC warning."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[],
        servitudes=[_servitude(libelle="Zone boisée protégée", categorie="")],
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.type == "ebc"


def test_ebc_by_categorie() -> None:
    """Servitude with 'ebc' in categorie → EBC warning."""
    alerts = detect_servitudes_alerts(
        monuments=[],
        risques=[],
        servitudes=[_servitude(libelle="Prescription végétale", categorie="EBC")],
    )
    assert len(alerts) == 1
    assert alerts[0].type == "ebc"


def test_multiple_alerts() -> None:
    """Multiple issues → one alert per category."""
    alerts = detect_servitudes_alerts(
        monuments=[_monument()],
        risques=[_risque("ppri"), _risque("basias")],
        servitudes=[_servitude(libelle="EBC zone", categorie="")],
    )
    types = {a.type for a in alerts}
    assert "abf" in types
    assert "ppri" in types
    assert "sol_pollue" in types
    assert "ebc" in types
