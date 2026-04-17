"""Integration tests for /api/v1/parcels/* endpoints.

Source clients (ban, cadastre) are mocked so no real network calls are made.
The conftest `client` fixture provides an AsyncClient with ASGI transport.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from core.sources.ban import GeocodingResult
from core.sources.cadastre import ParcelleResult


class TestParcelSearch:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, client: AsyncClient) -> None:
        with patch("api.routes.parcels.ban.geocode", new_callable=AsyncMock) as mock:
            mock.return_value = [
                GeocodingResult(
                    label="12 Rue de la Paix 75002 Paris",
                    score=0.95,
                    lat=48.869,
                    lng=2.331,
                    citycode="75102",
                    city="Paris",
                )
            ]
            resp = await client.get(
                "/api/v1/parcels/search",
                params={"q": "12 rue de la Paix Paris"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["citycode"] == "75102"
        assert data[0]["label"] == "12 Rue de la Paix 75002 Paris"
        assert data[0]["score"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_search_respects_limit_param(self, client: AsyncClient) -> None:
        with patch("api.routes.parcels.ban.geocode", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = await client.get(
                "/api/v1/parcels/search",
                params={"q": "Paris", "limit": "10"},
            )
        assert resp.status_code == 200
        mock.assert_called_once_with("Paris", limit=10)

    @pytest.mark.asyncio
    async def test_search_short_query_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/parcels/search",
            params={"q": "ab"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_missing_query_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/parcels/search")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_returns_empty_list(self, client: AsyncClient) -> None:
        with patch("api.routes.parcels.ban.geocode", new_callable=AsyncMock, return_value=[]):
            resp = await client.get(
                "/api/v1/parcels/search",
                params={"q": "nowhere 99999"},
            )
        assert resp.status_code == 200
        assert resp.json() == []


class TestParcelAtPoint:
    @pytest.mark.asyncio
    async def test_returns_parcel(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.parcels.cadastre.fetch_parcelle_at_point",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ParcelleResult(
                code_insee="75102",
                section="AH",
                numero="0015",
                contenance_m2=890,
                commune="Paris",
                geometry={"type": "MultiPolygon", "coordinates": []},
            )
            resp = await client.get(
                "/api/v1/parcels/at-point",
                params={"lat": "48.869", "lng": "2.310"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["section"] == "AH"
        assert data["numero"] == "0015"
        assert data["code_insee"] == "75102"
        assert data["contenance_m2"] == 890
        assert data["commune"] == "Paris"

    @pytest.mark.asyncio
    async def test_not_found_404(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.parcels.cadastre.fetch_parcelle_at_point",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                "/api/v1/parcels/at-point",
                params={"lat": "48.0", "lng": "2.0"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_lat_out_of_range_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/parcels/at-point",
            params={"lat": "91.0", "lng": "2.0"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/parcels/at-point", params={"lat": "48.0"})
        assert resp.status_code == 422


class TestParcelByRef:
    @pytest.mark.asyncio
    async def test_returns_parcel(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.parcels.cadastre.fetch_parcelle_by_ref",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ParcelleResult(
                code_insee="94052",
                section="AB",
                numero="0042",
                contenance_m2=1250,
                commune="Nogent-sur-Marne",
                geometry={"type": "MultiPolygon", "coordinates": []},
            )
            resp = await client.get(
                "/api/v1/parcels/by-ref",
                params={"insee": "94052", "section": "AB", "numero": "00042"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["contenance_m2"] == 1250
        assert data["section"] == "AB"
        assert data["code_insee"] == "94052"
        assert data["commune"] == "Nogent-sur-Marne"

    @pytest.mark.asyncio
    async def test_not_found_404(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.parcels.cadastre.fetch_parcelle_by_ref",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                "/api/v1/parcels/by-ref",
                params={"insee": "75056", "section": "ZZ", "numero": "9999"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_insee_pattern_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/parcels/by-ref",
            params={"insee": "750", "section": "AB", "numero": "0042"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_section_pattern_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/parcels/by-ref",
            params={"insee": "75056", "section": "ABCD", "numero": "0042"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_calls_with_correct_args(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.parcels.cadastre.fetch_parcelle_by_ref",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ParcelleResult(
                code_insee="94052",
                section="AB",
                numero="0042",
                contenance_m2=None,
                commune="Nogent-sur-Marne",
                geometry={"type": "MultiPolygon", "coordinates": []},
            )
            await client.get(
                "/api/v1/parcels/by-ref",
                params={"insee": "94052", "section": "AB", "numero": "0042"},
            )
        mock.assert_called_once_with(code_insee="94052", section="AB", numero="0042")
