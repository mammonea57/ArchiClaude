"""Unit tests for core.sources.insee_sru — SRU commune status client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.insee_sru import CommuneSRU, fetch_sru_commune

_DATASET_URL_RE = re.compile(r"https://www\.data\.gouv\.fr/api/1/datasets/.*")
_RESOURCE_URL = "https://static.data.gouv.fr/resources/sru-bilan.json"
_RESOURCE_URL_RE = re.compile(r"https://static\.data\.gouv\.fr/.*")

_DATASET_META = {
    "resources": [
        {
            "url": _RESOURCE_URL,
            "format": "json",
            "mime": "application/json",
        }
    ]
}

_SRU_DATA = [
    {
        "code_insee": "92012",
        "taux_lls": 18.5,
        "taux_cible": 25.0,
        "statut": "rattrapage",
        "penalite": 125000.0,
    },
    {
        "code_insee": "75056",
        "taux_lls": 22.3,
        "taux_cible": 25.0,
        "statut": "conforme",
        "penalite": None,
    },
]


async def test_commune_found(httpx_mock: HTTPXMock) -> None:
    """Returns CommuneSRU when the commune is in the dataset."""
    httpx_mock.add_response(url=_DATASET_URL_RE, json=_DATASET_META)
    httpx_mock.add_response(url=_RESOURCE_URL_RE, json=_SRU_DATA)

    result = await fetch_sru_commune(code_insee="92012")

    assert result is not None
    assert isinstance(result, CommuneSRU)
    assert result.code_insee == "92012"
    assert result.taux_lls == pytest.approx(18.5)
    assert result.taux_cible == pytest.approx(25.0)
    assert result.statut == "rattrapage"
    assert result.penalite_eur == pytest.approx(125000.0)


async def test_commune_not_found(httpx_mock: HTTPXMock) -> None:
    """Returns None when the commune is not in the dataset."""
    httpx_mock.add_response(url=_DATASET_URL_RE, json=_DATASET_META)
    httpx_mock.add_response(url=_RESOURCE_URL_RE, json=_SRU_DATA)

    result = await fetch_sru_commune(code_insee="01001")

    assert result is None


async def test_api_error_returns_none(httpx_mock: HTTPXMock) -> None:
    """Graceful degradation: returns None when dataset metadata lookup fails."""
    httpx_mock.add_response(url=_DATASET_URL_RE, status_code=503)

    result = await fetch_sru_commune(code_insee="92012")

    assert result is None


async def test_conforme_commune(httpx_mock: HTTPXMock) -> None:
    """Returns correct statut for a compliant commune."""
    httpx_mock.add_response(url=_DATASET_URL_RE, json=_DATASET_META)
    httpx_mock.add_response(url=_RESOURCE_URL_RE, json=_SRU_DATA)

    result = await fetch_sru_commune(code_insee="75056")

    assert result is not None
    assert result.statut == "conforme"
    assert result.penalite_eur is None
