"""Unit tests for core.sources.dpe — DPE ADEME energy diagnostics client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.dpe import DpeResult, fetch_dpe_around

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "dpe_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_DPE_URL_RE = re.compile(
    r"https://data\.ademe\.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe/lines.*"
)

_LAT = 48.8375
_LNG = 2.4833

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_dpe_found(httpx_mock: HTTPXMock) -> None:
    """DPE response with 2 results is parsed correctly, immeuble sorted first."""
    httpx_mock.add_response(url=_DPE_URL_RE, json=_load_fixture("dpe_nogent"))

    results = await fetch_dpe_around(lat=_LAT, lng=_LNG, radius_m=30)

    assert len(results) == 2

    # First result must be "immeuble" (sorted before "maison")
    first: DpeResult = results[0]
    assert first.type_batiment == "immeuble"
    assert first.nb_niveaux == 4
    assert first.hauteur_sous_plafond == pytest.approx(2.7)
    assert first.classe_energie == "C"
    assert first.adresse is not None
    assert "Nogent" in first.adresse

    second: DpeResult = results[1]
    assert second.type_batiment == "maison"
    assert second.nb_niveaux is None
    assert second.classe_energie == "D"

    # Verify query params
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    params = requests[0].url.params
    assert "geo_distance" in params
    assert str(radius := 30) and f"{radius}m" in params["geo_distance"]
    assert params["size"] == "20"
    assert "nombre_niveau_immeuble" in params["select"]
    assert "hauteur_sous_plafond" in params["select"]
    assert "classe_consommation_energie" in params["select"]


async def test_no_dpe(httpx_mock: HTTPXMock) -> None:
    """DPE response with empty results returns an empty list."""
    httpx_mock.add_response(url=_DPE_URL_RE, json=_load_fixture("dpe_empty"))

    results = await fetch_dpe_around(lat=_LAT, lng=_LNG)

    assert results == []
