"""Unit tests for core.sources.dvf — DVF property transactions client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.dvf import DvfTransaction, fetch_dvf_parcelle

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "dvf_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_DVF_URL_RE = re.compile(r"https://api\.cquest\.org/dvf.*")

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_transactions_found(httpx_mock: HTTPXMock) -> None:
    """DVF response with 2 transactions is parsed into correct DvfTransaction objects."""
    httpx_mock.add_response(url=_DVF_URL_RE, json=_load_fixture("dvf_nogent_ab_42"))

    results = await fetch_dvf_parcelle(code_insee="94052", section="AB", numero="0042")

    assert len(results) == 2

    t0: DvfTransaction = results[0]
    assert t0.date_mutation == "2022-03-15"
    assert t0.nature_mutation == "Vente"
    assert t0.valeur_fonciere == pytest.approx(450_000.0)
    assert t0.type_local == "Appartement"
    assert t0.surface_m2 == pytest.approx(68.5)
    assert t0.nb_pieces == 3
    assert t0.code_commune == "94052"
    assert t0.adresse is not None
    assert "NOGENT" in t0.adresse.upper()

    t1: DvfTransaction = results[1]
    assert t1.valeur_fonciere == pytest.approx(520_000.0)
    assert t1.nb_pieces == 4
    # Second row has null address parts, falls back to adresse_norm
    assert t1.adresse is not None

    # Verify query params
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    params = requests[0].url.params
    assert params["code_commune"] == "94052"
    assert params["section"] == "AB"
    assert params["numero"] == "0042"


async def test_no_transactions(httpx_mock: HTTPXMock) -> None:
    """DVF response with empty resultats returns an empty list."""
    httpx_mock.add_response(url=_DVF_URL_RE, json=_load_fixture("dvf_empty"))

    results = await fetch_dvf_parcelle(code_insee="99999", section="ZZ", numero="0001")

    assert results == []
