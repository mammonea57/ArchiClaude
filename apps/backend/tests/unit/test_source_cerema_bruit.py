"""Unit tests for core.sources.cerema_bruit — Cerema noise classification WFS client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.cerema_bruit import ClassementSonore, fetch_classement_sonore

_WFS_URL_RE = re.compile(r"https://data\.geopf\.fr/wfs/ows.*")

_LAT = 48.8375
_LNG = 2.4833

_VOIES_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "categorie": 2,
                "type_infra": "route",
                "nom_voie": "Avenue de la République",
                "lden": 68.5,
            },
            "geometry": {"type": "LineString", "coordinates": [[2.483, 48.837], [2.484, 48.838]]},
        }
    ],
}

_EMPTY_RESPONSE = {
    "type": "FeatureCollection",
    "features": [],
}


async def test_voies_found(httpx_mock: HTTPXMock) -> None:
    """Returns ClassementSonore list when WFS returns noise features."""
    httpx_mock.add_response(url=_WFS_URL_RE, json=_VOIES_RESPONSE)

    results = await fetch_classement_sonore(lat=_LAT, lng=_LNG, radius_m=200)

    assert len(results) == 1
    r: ClassementSonore = results[0]
    assert r.categorie == 2
    assert r.type_infra == "route"
    assert r.nom_voie == "Avenue de la République"
    assert r.lden == pytest.approx(68.5)


async def test_no_voies(httpx_mock: HTTPXMock) -> None:
    """Returns empty list when WFS returns no features."""
    httpx_mock.add_response(url=_WFS_URL_RE, json=_EMPTY_RESPONSE)

    results = await fetch_classement_sonore(lat=_LAT, lng=_LNG)

    assert results == []


async def test_error_returns_empty(httpx_mock: HTTPXMock) -> None:
    """Returns empty list (graceful degradation) when WFS returns an error."""
    httpx_mock.add_response(url=_WFS_URL_RE, status_code=503)

    results = await fetch_classement_sonore(lat=_LAT, lng=_LNG)

    assert results == []
