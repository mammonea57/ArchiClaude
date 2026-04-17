"""Unit tests for core.site.voisinage — neighbourhood building enrichment."""

from __future__ import annotations

from core.site.voisinage import VoisinEnrichi, enrich_voisinage
from core.sources.dpe import DpeResult
from core.sources.ign_bdtopo import BatimentResult


def _batiment(
    hauteur: float | None = 12.0,
    nb_etages: int | None = 3,
    usage: str | None = "Résidentiel",
    geometry: dict | None = None,
) -> BatimentResult:
    return BatimentResult(
        hauteur=hauteur,
        nb_etages=nb_etages,
        usage=usage,
        altitude_sol=None,
        altitude_toit=None,
        geometry=geometry or {"type": "Polygon", "coordinates": []},
    )


def _dpe(
    nb_niveaux: int | None = 3,
    classe_energie: str | None = "C",
) -> DpeResult:
    return DpeResult(
        nb_niveaux=nb_niveaux,
        hauteur_sous_plafond=2.5,
        classe_energie=classe_energie,
        type_batiment="immeuble",
        adresse="10 rue Test 75001 Paris",
    )


async def test_basic_enrichment() -> None:
    """Two buildings + 1 DPE → 2 VoisinEnrichi, one with DPE class."""
    batiments = [_batiment(nb_etages=3), _batiment(nb_etages=5)]
    dpe_nearby = [_dpe(nb_niveaux=3, classe_energie="C")]

    results = await enrich_voisinage(batiments=batiments, dpe_nearby=dpe_nearby)

    assert len(results) == 2
    for r in results:
        assert isinstance(r, VoisinEnrichi)

    # First building matches DPE (nb_etages=3 == nb_niveaux=3)
    assert results[0].dpe_classe == "C"
    # Second building (5 floors) has no DPE match
    assert results[1].dpe_classe is None


async def test_empty_batiments() -> None:
    """Empty buildings list → empty result."""
    results = await enrich_voisinage(batiments=[], dpe_nearby=[_dpe()])

    assert results == []


async def test_dpe_enrichment_matching_nb_niveaux() -> None:
    """Matching nb_niveaux → dpe_classe is populated."""
    bat = _batiment(nb_etages=4, usage="Commercial")
    dpe = _dpe(nb_niveaux=4, classe_energie="D")

    results = await enrich_voisinage(batiments=[bat], dpe_nearby=[dpe])

    assert len(results) == 1
    r = results[0]
    assert r.nb_etages == 4
    assert r.usage == "Commercial"
    assert r.dpe_classe == "D"


async def test_no_dpe_match() -> None:
    """No matching DPE → dpe_classe is None."""
    bat = _batiment(nb_etages=8)
    dpe = _dpe(nb_niveaux=3, classe_energie="B")

    results = await enrich_voisinage(batiments=[bat], dpe_nearby=[dpe])

    assert len(results) == 1
    assert results[0].dpe_classe is None


async def test_ouvertures_always_none() -> None:
    """Opening detection is deferred (Phase 6) → ouvertures_visibles is None."""
    results = await enrich_voisinage(
        batiments=[_batiment()],
        dpe_nearby=[],
    )

    assert len(results) == 1
    assert results[0].ouvertures_visibles is None


async def test_geometry_preserved() -> None:
    """Building geometry is preserved in the enriched result."""
    geom = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    bat = _batiment(geometry=geom)

    results = await enrich_voisinage(batiments=[bat], dpe_nearby=[])

    assert len(results) == 1
    assert results[0].geometry == geom


async def test_batiment_no_etages_no_dpe_match() -> None:
    """Building with nb_etages=None → no DPE match even if DPE records exist."""
    bat = _batiment(nb_etages=None)
    dpe = _dpe(nb_niveaux=3, classe_energie="A")

    results = await enrich_voisinage(batiments=[bat], dpe_nearby=[dpe])

    assert len(results) == 1
    assert results[0].dpe_classe is None


async def test_multiple_dpe_first_match_used() -> None:
    """When multiple DPE records match, the first one is used."""
    bat = _batiment(nb_etages=3)
    dpe_records = [
        _dpe(nb_niveaux=3, classe_energie="A"),
        _dpe(nb_niveaux=3, classe_energie="E"),
    ]

    results = await enrich_voisinage(batiments=[bat], dpe_nearby=dpe_records)

    assert len(results) == 1
    assert results[0].dpe_classe == "A"
