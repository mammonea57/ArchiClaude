"""Unit tests for core.site.transports — public transport accessibility."""

from __future__ import annotations

from core.site.transports import DesserteResult, qualify_desserte
from core.sources.ign_transports import ArretTC


def _arret(nom: str, mode: str, distance_m: float, ligne: str | None = None) -> ArretTC:
    return ArretTC(
        nom=nom,
        mode=mode,
        ligne=ligne,
        exploitant=None,
        lat=48.85,
        lng=2.35,
        distance_m=distance_m,
    )


def test_metro_within_400m() -> None:
    """Metro stop ≤ 400m → bien_desservie and exoneration."""
    arrets = [_arret("Bastille", "metro", 350.0)]

    result = qualify_desserte(arrets)

    assert isinstance(result, DesserteResult)
    assert result.bien_desservie is True
    assert result.stationnement_exoneration_possible is True
    assert result.motif is not None
    assert "Bastille" in result.motif


def test_metro_beyond_400m_not_qualifying() -> None:
    """Metro stop > 400m does NOT qualify."""
    arrets = [_arret("Bastille", "metro", 500.0)]

    result = qualify_desserte(arrets)

    assert result.bien_desservie is False
    assert result.stationnement_exoneration_possible is False


def test_rer_within_400m() -> None:
    """RER stop ≤ 400m → bien_desservie."""
    arrets = [_arret("Nation RER", "RER", 380.0)]

    result = qualify_desserte(arrets)

    assert result.bien_desservie is True
    assert result.stationnement_exoneration_possible is True


def test_tram_within_300m() -> None:
    """Tram stop ≤ 300m → bien_desservie."""
    arrets = [_arret("Bobigny T1", "tram", 250.0)]

    result = qualify_desserte(arrets)

    assert result.bien_desservie is True
    assert result.stationnement_exoneration_possible is True


def test_tram_beyond_300m_not_qualifying() -> None:
    """Tram stop > 300m does NOT qualify."""
    arrets = [_arret("T3a", "tram", 350.0)]

    result = qualify_desserte(arrets)

    assert result.bien_desservie is False


def test_two_frequent_buses() -> None:
    """Two frequent bus lines within 300m → bien_desservie."""
    arrets = [
        _arret("Arrêt A", "bus", 200.0, ligne="183"),
        _arret("Arrêt B", "bus", 280.0, ligne="186"),
        _arret("Arrêt C", "bus", 310.0, ligne="62"),  # > 300m, excluded
    ]
    freq_lines = {"183", "186", "62"}

    result = qualify_desserte(arrets, frequent_bus_lines=freq_lines)

    assert result.bien_desservie is True
    assert result.stationnement_exoneration_possible is True
    assert "183" in (result.motif or "") or "186" in (result.motif or "")


def test_only_one_frequent_bus_not_qualifying() -> None:
    """Only one frequent bus line ≤300m → NOT bien_desservie."""
    arrets = [_arret("Bus A", "bus", 200.0, ligne="183")]
    freq_lines = {"183"}

    result = qualify_desserte(arrets, frequent_bus_lines=freq_lines)

    assert result.bien_desservie is False


def test_only_distant_bus() -> None:
    """Only bus stops, all > 300m → not bien_desservie."""
    arrets = [
        _arret("Bus far", "bus", 400.0, ligne="183"),
        _arret("Bus far2", "bus", 450.0, ligne="186"),
    ]

    result = qualify_desserte(arrets, frequent_bus_lines={"183", "186"})

    assert result.bien_desservie is False
    assert result.stationnement_exoneration_possible is False
    assert result.motif is None


def test_empty_returns_false() -> None:
    """Empty arrets list → not bien_desservie."""
    result = qualify_desserte([])

    assert result.bien_desservie is False
    assert result.stationnement_exoneration_possible is False
    assert result.motif is None


def test_no_frequent_lines_set_bus_not_qualifying() -> None:
    """Bus stops present but no frequent_bus_lines set → not bien_desservie."""
    arrets = [
        _arret("Bus 1", "bus", 100.0, ligne="183"),
        _arret("Bus 2", "bus", 150.0, ligne="186"),
    ]

    result = qualify_desserte(arrets)

    assert result.bien_desservie is False
