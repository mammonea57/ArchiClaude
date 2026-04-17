"""Unit tests for core.sources.cadastre — API Carto IGN cadastre client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.cadastre import ParcelleResult, fetch_parcelle_at_point, fetch_parcelle_by_ref

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "cadastre_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_CADASTRE_URL_RE = re.compile(r"https://apicarto\.ign\.fr/api/cadastre/parcelle.*")

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_nogent_ab_42(httpx_mock: HTTPXMock) -> None:
    """Parcel AB-0042 in Nogent-sur-Marne is correctly parsed into a ParcelleResult."""
    httpx_mock.add_response(
        url="https://apicarto.ign.fr/api/cadastre/parcelle?code_insee=94052&section=AB&numero=0042",
        json=_load_fixture("parcelle_by_ref_nogent_AB_42"),
    )

    result = await fetch_parcelle_by_ref(code_insee="94052", section="AB", numero="0042")

    assert result is not None
    assert isinstance(result, ParcelleResult)
    assert result.code_insee == "94052"
    assert result.section == "AB"
    assert result.numero == "0042"
    assert result.contenance_m2 == 412
    assert result.commune == "Nogent-sur-Marne"
    assert result.geometry["type"] == "MultiPolygon"


async def test_not_found(httpx_mock: HTTPXMock) -> None:
    """Empty features list in the API response returns None."""
    httpx_mock.add_response(
        url="https://apicarto.ign.fr/api/cadastre/parcelle?code_insee=99999&section=ZZ&numero=9999",
        json={"type": "FeatureCollection", "features": []},
    )

    result = await fetch_parcelle_by_ref(code_insee="99999", section="ZZ", numero="9999")

    assert result is None


async def test_paris_at_point(httpx_mock: HTTPXMock) -> None:
    """Point query returns a ParcelleResult for the enclosing parcel."""
    httpx_mock.add_response(
        url=_CADASTRE_URL_RE,
        json=_load_fixture("parcelle_at_point_paris"),
    )

    result = await fetch_parcelle_at_point(lat=48.869, lng=2.331)

    assert result is not None
    assert isinstance(result, ParcelleResult)
    assert result.section == "AV"
    assert result.numero == "0018"
    assert result.code_insee == "75056"
    assert result.contenance_m2 == 287
    assert result.commune == "Paris 2e Arrondissement"
    assert result.geometry["type"] == "MultiPolygon"

    # Verify the request sent a 'geom' param containing a GeoJSON Point
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    sent_geom = json.loads(requests[0].url.params["geom"])
    assert sent_geom["type"] == "Point"
    assert sent_geom["coordinates"] == pytest.approx([2.331, 48.869])
