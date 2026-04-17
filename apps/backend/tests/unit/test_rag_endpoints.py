"""Unit tests for /api/v1/rag/* endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from core.analysis.rag.jurisprudences import JurisprudenceMatch
from core.analysis.rag.recours import RecoursMatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jur_match(**kwargs) -> JurisprudenceMatch:
    defaults = dict(
        id=str(uuid.uuid4()),
        reference="TA Paris 2023-001",
        source="Légifrance",
        motif_principal="Dépassement COS",
        resume="Le tribunal annule le permis pour dépassement du COS.",
        decision="Annulation",
        commune_insee="75056",
        similarity=0.87,
    )
    defaults.update(kwargs)
    return JurisprudenceMatch(**defaults)


def _make_rec_match(**kwargs) -> RecoursMatch:
    defaults = dict(
        id=str(uuid.uuid4()),
        commune_insee="75056",
        association="SOS Paris Vert",
        projet_conteste="Tour de logements R+12",
        motifs=["hauteur excessive", "non-conformité PLU"],
        resultat="rejeté",
        resume="Recours rejeté pour défaut d'intérêt à agir.",
        similarity=0.78,
    )
    defaults.update(kwargs)
    return RecoursMatch(**defaults)


# ---------------------------------------------------------------------------
# Jurisprudences search
# ---------------------------------------------------------------------------


async def test_jurisprudences_search(client: AsyncClient) -> None:
    """GET /rag/jurisprudences/search returns items list with correct fields."""
    match = _make_jur_match()

    with patch(
        "api.routes.rag.search_jurisprudences",
        new=AsyncMock(return_value=[match]),
    ):
        resp = await client.get(
            "/api/v1/rag/jurisprudences/search",
            params={"q": "dépassement COS zone UB", "commune_insee": "75056"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["reference"] == "TA Paris 2023-001"
    assert item["source"] == "Légifrance"
    assert item["decision"] == "Annulation"
    assert item["similarity"] == pytest.approx(0.87)


async def test_jurisprudences_search_without_commune(client: AsyncClient) -> None:
    """GET /rag/jurisprudences/search works without commune_insee parameter."""
    with patch(
        "api.routes.rag.search_jurisprudences",
        new=AsyncMock(return_value=[]),
    ):
        resp = await client.get(
            "/api/v1/rag/jurisprudences/search",
            params={"q": "hauteur maximale toiture"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"items": []}


async def test_short_query_422(client: AsyncClient) -> None:
    """GET /rag/jurisprudences/search returns 422 when q has fewer than 3 chars."""
    resp = await client.get(
        "/api/v1/rag/jurisprudences/search",
        params={"q": "ab"},
    )
    assert resp.status_code == 422


async def test_missing_q_422(client: AsyncClient) -> None:
    """GET /rag/jurisprudences/search returns 422 when q is missing."""
    resp = await client.get("/api/v1/rag/jurisprudences/search")
    assert resp.status_code == 422


async def test_jurisprudences_limit_param(client: AsyncClient) -> None:
    """GET /rag/jurisprudences/search passes limit to search function."""
    captured: dict = {}

    async def _mock_search(*, query, commune_insee=None, limit=5):
        captured["limit"] = limit
        return []

    with patch("api.routes.rag.search_jurisprudences", side_effect=_mock_search):
        resp = await client.get(
            "/api/v1/rag/jurisprudences/search",
            params={"q": "recul voirie", "limit": "3"},
        )

    assert resp.status_code == 200
    assert captured.get("limit") == 3


# ---------------------------------------------------------------------------
# Recours search
# ---------------------------------------------------------------------------


async def test_recours_search(client: AsyncClient) -> None:
    """GET /rag/recours/search returns items list with correct fields."""
    match = _make_rec_match()

    with patch(
        "api.routes.rag.search_recours",
        new=AsyncMock(return_value=[match]),
    ):
        resp = await client.get(
            "/api/v1/rag/recours/search",
            params={"commune_insee": "75056"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["commune_insee"] == "75056"
    assert item["association"] == "SOS Paris Vert"
    assert item["resultat"] == "rejeté"
    assert item["motifs"] == ["hauteur excessive", "non-conformité PLU"]
    assert item["similarity"] == pytest.approx(0.78)


async def test_missing_commune_422(client: AsyncClient) -> None:
    """GET /rag/recours/search returns 422 when commune_insee is missing."""
    resp = await client.get("/api/v1/rag/recours/search")
    assert resp.status_code == 422


async def test_invalid_commune_format_422(client: AsyncClient) -> None:
    """GET /rag/recours/search returns 422 for commune_insee not matching \\d{5}."""
    resp = await client.get(
        "/api/v1/rag/recours/search",
        params={"commune_insee": "7505A"},
    )
    assert resp.status_code == 422


async def test_recours_limit_param(client: AsyncClient) -> None:
    """GET /rag/recours/search passes limit to search function."""
    captured: dict = {}

    async def _mock_search(*, commune_insee, limit=3):
        captured["limit"] = limit
        return []

    with patch("api.routes.rag.search_recours", side_effect=_mock_search):
        resp = await client.get(
            "/api/v1/rag/recours/search",
            params={"commune_insee": "92012", "limit": "2"},
        )

    assert resp.status_code == 200
    assert captured.get("limit") == 2


async def test_recours_empty_results(client: AsyncClient) -> None:
    """GET /rag/recours/search returns empty items list when no results."""
    with patch(
        "api.routes.rag.search_recours",
        new=AsyncMock(return_value=[]),
    ):
        resp = await client.get(
            "/api/v1/rag/recours/search",
            params={"commune_insee": "93001"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"items": []}
