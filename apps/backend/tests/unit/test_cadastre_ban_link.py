"""Unit tests for the BAN-PLUS:lien_adresse_parcelle integration.

Validates the authoritative address→parcelle resolver
(:func:`core.sources.cadastre.resolve_parcelle_via_ban_link`) and the
PIP-fallback orchestrator (:func:`resolve_parcelle_for_geocode`).

HTTP calls are intercepted at transport level by pytest-httpx so the
module-level singleton in ``core.http_client`` is transparently mocked.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from core.sources.cadastre import (
    ParcelleResult,
    _ban_link_cache_path,
    _parse_idu,
    resolve_parcelle_for_geocode,
    resolve_parcelle_via_ban_link,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic FeatureCollection responses
# ---------------------------------------------------------------------------


def _ban_link_response(*, id_adr: str, idu: str) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "lien_adresse_parcelle.1",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[2.489, 48.839], [2.4892, 48.839]],
                },
                "geometry_name": "geom",
                "properties": {
                    "id_adr": id_adr,
                    "idu": idu,
                    "type_lien": "GEO",
                    "nb_adr": 1,
                    "nb_parc": 1,
                },
            }
        ],
        "totalFeatures": 1,
        "numberMatched": 1,
        "numberReturned": 1,
    }


def _parcelle_g0124_response() -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [2.489230, 48.838990],
                                [2.489440, 48.838990],
                                [2.489440, 48.839200],
                                [2.489230, 48.839200],
                                [2.489230, 48.838990],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "numero": "0124",
                    "section": "0G",
                    "code_dep": "94",
                    "code_com": "052",
                    "nom_com": "Nogent-sur-Marne",
                },
            }
        ],
    }


def _parcelle_g0123_response() -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [2.488800, 48.838900],
                                [2.489200, 48.838900],
                                [2.489200, 48.839200],
                                [2.488800, 48.839200],
                                [2.488800, 48.838900],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "numero": "0123",
                    "section": "0G",
                    "code_dep": "94",
                    "code_com": "052",
                    "nom_com": "Nogent-sur-Marne",
                },
            }
        ],
    }


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the BAN-PLUS local cache to a per-test tmp dir."""
    import core.sources.cadastre as cad

    monkeypatch.setattr(cad, "_BAN_LINK_CACHE_DIR", tmp_path / "ban_plus")
    return tmp_path


# ---------------------------------------------------------------------------
# IDU parser
# ---------------------------------------------------------------------------


def test_parse_idu_nogent_g0124() -> None:
    assert _parse_idu("940520000G0124") == ("94052", "0G", "0124")


def test_parse_idu_invalid_length_returns_none() -> None:
    assert _parse_idu("") is None
    assert _parse_idu("1234") is None
    assert _parse_idu("toolongtoolong123") is None


# ---------------------------------------------------------------------------
# resolve_parcelle_via_ban_link
# ---------------------------------------------------------------------------


_WFS_URL_RE = re.compile(r"https://data\.geopf\.fr/wfs/ows.*")


async def test_resolve_via_ban_link_returns_correct_idu(httpx_mock: HTTPXMock) -> None:
    """80 rue des Héros → BAN id 94052_4430_00080 → IDU 940520000G0124 → section 0G."""
    # First call: BAN-PLUS link → IDU
    httpx_mock.add_response(
        url=_WFS_URL_RE,
        match_content=None,
        json=_ban_link_response(
            id_adr="94052_4430_00080", idu="940520000G0124",
        ),
    )
    # Second call: BDPARCELLAIRE parcelle fetch
    httpx_mock.add_response(url=_WFS_URL_RE, json=_parcelle_g0124_response())

    result = await resolve_parcelle_via_ban_link("94052_4430_00080")

    assert result is not None
    assert isinstance(result, ParcelleResult)
    assert result.code_insee == "94052"
    assert result.section == "0G"
    assert result.numero == "0124"
    assert result.commune == "Nogent-sur-Marne"

    # First request must hit lien_adresse_parcelle with the right CQL filter
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    first_qs = requests[0].url.params
    assert first_qs["typeNames"] == "BAN-PLUS:lien_adresse_parcelle"
    assert first_qs["CQL_FILTER"] == "id_adr='94052_4430_00080'"


async def test_resolve_via_ban_link_missing_returns_none(httpx_mock: HTTPXMock) -> None:
    """Unknown BAN id → empty FeatureCollection → ``None``."""
    httpx_mock.add_response(
        url=_WFS_URL_RE,
        json={"type": "FeatureCollection", "features": []},
    )

    result = await resolve_parcelle_via_ban_link("inexistant")

    assert result is None
    # Only the BAN-PLUS WFS hit; no parcelle fetch since there was no IDU.
    assert len(httpx_mock.get_requests()) == 1


async def test_resolve_via_ban_link_empty_string_returns_none(
    httpx_mock: HTTPXMock,
) -> None:
    """An empty BAN id must short-circuit without any HTTP call."""
    result = await resolve_parcelle_via_ban_link("")
    assert result is None
    assert httpx_mock.get_requests() == []


async def test_resolve_via_ban_link_malformed_idu_returns_none(
    httpx_mock: HTTPXMock,
) -> None:
    """The BAN-PLUS layer returns a 7-char IDU — pipeline must reject it."""
    httpx_mock.add_response(
        url=_WFS_URL_RE,
        json=_ban_link_response(id_adr="bad", idu="123"),
    )
    result = await resolve_parcelle_via_ban_link("bad")
    assert result is None


# ---------------------------------------------------------------------------
# resolve_parcelle_for_geocode — orchestrator
# ---------------------------------------------------------------------------


async def test_orchestrator_prefers_ban_link(httpx_mock: HTTPXMock) -> None:
    """When ban_id is supplied AND resolvable, we never call PIP fallback."""
    httpx_mock.add_response(
        url=_WFS_URL_RE,
        json=_ban_link_response(id_adr="94052_4430_00078", idu="940520000G0123"),
    )
    httpx_mock.add_response(url=_WFS_URL_RE, json=_parcelle_g0123_response())

    result = await resolve_parcelle_for_geocode(
        ban_id="94052_4430_00078", lat=48.839001, lng=2.488971,
    )

    assert result is not None
    assert result.section == "0G"
    assert result.numero == "0123"
    # Two requests : BAN link + parcelle. No PIP bbox request.
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    for req in requests:
        assert "BBOX" not in req.url.params, "PIP bbox path must not be used"


async def test_orchestrator_falls_back_to_pip_when_ban_id_missing(
    httpx_mock: HTTPXMock,
) -> None:
    """No ban_id ⇒ skip the BAN-PLUS lookup and run fetch_parcelle_at_point."""
    # PIP bbox query returns one feature whose polygon contains the test point.
    httpx_mock.add_response(url=_WFS_URL_RE, json=_parcelle_g0124_response())

    result = await resolve_parcelle_for_geocode(
        ban_id=None, lat=48.839095, lng=2.489335,
    )

    assert result is not None
    assert result.section == "0G"
    assert result.numero == "0124"
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    # Must be a BBOX-driven PIP request, not a BAN-PLUS link query.
    qs = requests[0].url.params
    assert qs["typeName"] == "BDPARCELLAIRE-VECTEUR_WLD_BDD_WGS84G:parcelle"
    assert "BBOX" in qs


async def test_orchestrator_falls_back_to_pip_when_ban_link_empty(
    httpx_mock: HTTPXMock,
) -> None:
    """ban_id provided but BAN-PLUS has no row ⇒ orchestrator falls back to PIP."""
    # 1) BAN-PLUS link returns empty → resolver returns None
    httpx_mock.add_response(
        url=_WFS_URL_RE, json={"type": "FeatureCollection", "features": []},
    )
    # 2) PIP bbox returns the correct parcelle polygon
    httpx_mock.add_response(url=_WFS_URL_RE, json=_parcelle_g0124_response())

    result = await resolve_parcelle_for_geocode(
        ban_id="unknown_id", lat=48.839095, lng=2.489335,
    )

    assert result is not None
    assert result.section == "0G"
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    # First call = BAN-PLUS lookup; second = PIP bbox.
    assert requests[0].url.params["typeNames"] == "BAN-PLUS:lien_adresse_parcelle"
    assert "BBOX" in requests[1].url.params


# ---------------------------------------------------------------------------
# Local cache (30-day TTL)
# ---------------------------------------------------------------------------


async def test_ban_link_cache_hit_skips_http(
    httpx_mock: HTTPXMock, _isolate_cache: Path,
) -> None:
    """A second call with the same ban_id must serve from disk, no HTTP."""
    # Prime the cache
    httpx_mock.add_response(
        url=_WFS_URL_RE,
        json=_ban_link_response(id_adr="94052_4430_00080", idu="940520000G0124"),
    )
    httpx_mock.add_response(url=_WFS_URL_RE, json=_parcelle_g0124_response())
    first = await resolve_parcelle_via_ban_link("94052_4430_00080")
    assert first is not None
    first_n = len(httpx_mock.get_requests())

    # Cache file should exist now
    assert _ban_link_cache_path("94052_4430_00080").is_file()

    # Second call: only the BDPARCELLAIRE parcelle fetch should hit the wire,
    # the BAN-PLUS link lookup is served from cache.
    httpx_mock.add_response(url=_WFS_URL_RE, json=_parcelle_g0124_response())
    second = await resolve_parcelle_via_ban_link("94052_4430_00080")
    assert second is not None
    assert second.section == "0G"
    assert second.numero == "0124"

    delta = len(httpx_mock.get_requests()) - first_n
    assert delta == 1, "Cache hit must skip the lien_adresse_parcelle WFS call"
