"""Integration tests for /api/v1/plu/at-point endpoint.

All 6 source clients (gpu, georisques, pop) are mocked so no real network
calls are made. The conftest `client` fixture provides an AsyncClient with
ASGI transport.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from core.sources.georisques import RisqueResult
from core.sources.gpu import GpuDocument, GpuPrescription, GpuServitude, GpuZone
from core.sources.pop import MonumentResult


class TestPluAtPoint:
    @pytest.mark.asyncio
    async def test_returns_full_response(self, client: AsyncClient) -> None:
        with (
            patch(
                "api.routes.plu.gpu.fetch_zones_at_point",
                new_callable=AsyncMock,
                return_value=[
                    GpuZone(
                        libelle="UB",
                        libelong="Zone urbaine mixte",
                        typezone="U",
                        partition=None,
                        idurba="94052",
                        nomfic="reglement_UB.pdf",
                        urlfic="https://gpu.example/UB.pdf",
                        geometry={"type": "Polygon", "coordinates": []},
                    )
                ],
            ),
            patch(
                "api.routes.plu.gpu.fetch_document",
                new_callable=AsyncMock,
                return_value=[
                    GpuDocument(
                        idurba="94052",
                        typedoc="PLUi",
                        datappro="2022-03-15",
                        nom="PLUi Nogent-sur-Marne",
                    )
                ],
            ),
            patch(
                "api.routes.plu.gpu.fetch_servitudes_at_point",
                new_callable=AsyncMock,
                return_value=[
                    GpuServitude(
                        libelle="AC1 — Monuments historiques",
                        categorie="AC1",
                        txt="Périmètre de protection 500m",
                        geometry={"type": "Polygon", "coordinates": []},
                    )
                ],
            ),
            patch(
                "api.routes.plu.gpu.fetch_prescriptions_at_point",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.plu.georisques.fetch_risques",
                new_callable=AsyncMock,
                return_value=[
                    RisqueResult(
                        type="ppri",
                        code="PPRI_94",
                        libelle="Plan de prévention des risques inondation",
                        niveau_alea="moyen",
                    )
                ],
            ),
            patch(
                "api.routes.plu.pop.fetch_monuments_around",
                new_callable=AsyncMock,
                return_value=[
                    MonumentResult(
                        reference="PA94000001",
                        nom="Château de Nogent",
                        date_protection="1990-04-12",
                        commune="Nogent-sur-Marne",
                        departement="94",
                        lat=48.8375,
                        lng=2.4833,
                    )
                ],
            ),
        ):
            resp = await client.get(
                "/api/v1/plu/at-point",
                params={"lat": "48.8375", "lng": "2.4833"},
            )

        assert resp.status_code == 200
        data = resp.json()

        assert len(data["zones"]) == 1
        assert data["zones"][0]["libelle"] == "UB"
        assert data["zones"][0]["typezone"] == "U"

        assert data["document"] is not None
        assert data["document"]["typedoc"] == "PLUi"
        assert data["document"]["idurba"] == "94052"
        assert data["document"]["datappro"] == "2022-03-15"

        assert len(data["servitudes"]) == 1
        assert data["servitudes"][0]["categorie"] == "AC1"

        assert data["prescriptions"] == []

        assert len(data["risques"]) == 1
        assert data["risques"][0]["type"] == "ppri"
        assert data["risques"][0]["niveau_alea"] == "moyen"

        assert len(data["monuments"]) == 1
        assert data["monuments"][0]["reference"] == "PA94000001"
        assert data["monuments"][0]["nom"] == "Château de Nogent"

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plu/at-point")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_lng_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plu/at-point", params={"lat": "48.8375"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_lat_out_of_range_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/plu/at-point",
            params={"lat": "95.0", "lng": "2.4833"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_no_document_returns_null(self, client: AsyncClient) -> None:
        with (
            patch(
                "api.routes.plu.gpu.fetch_zones_at_point",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.plu.gpu.fetch_document",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.plu.gpu.fetch_servitudes_at_point",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.plu.gpu.fetch_prescriptions_at_point",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.plu.georisques.fetch_risques",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.plu.pop.fetch_monuments_around",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = await client.get(
                "/api/v1/plu/at-point",
                params={"lat": "48.0", "lng": "2.0"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["document"] is None
        assert data["zones"] == []
        assert data["servitudes"] == []
        assert data["prescriptions"] == []
        assert data["risques"] == []
        assert data["monuments"] == []

    @pytest.mark.asyncio
    async def test_all_sources_called_with_correct_coords(self, client: AsyncClient) -> None:
        with (
            patch(
                "api.routes.plu.gpu.fetch_zones_at_point",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_zones,
            patch(
                "api.routes.plu.gpu.fetch_document",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_doc,
            patch(
                "api.routes.plu.gpu.fetch_servitudes_at_point",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_serv,
            patch(
                "api.routes.plu.gpu.fetch_prescriptions_at_point",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_presc,
            patch(
                "api.routes.plu.georisques.fetch_risques",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_risques,
            patch(
                "api.routes.plu.pop.fetch_monuments_around",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_monuments,
        ):
            await client.get(
                "/api/v1/plu/at-point",
                params={"lat": "48.8375", "lng": "2.4833"},
            )

        mock_zones.assert_called_once_with(lat=48.8375, lng=2.4833)
        mock_doc.assert_called_once_with(lat=48.8375, lng=2.4833)
        mock_serv.assert_called_once_with(lat=48.8375, lng=2.4833)
        mock_presc.assert_called_once_with(lat=48.8375, lng=2.4833)
        mock_risques.assert_called_once_with(lat=48.8375, lng=2.4833)
        mock_monuments.assert_called_once_with(lat=48.8375, lng=2.4833, radius_m=500)
