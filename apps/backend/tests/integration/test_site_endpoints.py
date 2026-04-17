"""Integration tests for /api/v1/site/* endpoints.

All external source functions are mocked at the route-module level so no real
network calls are made. The conftest ``client`` fixture provides an AsyncClient
with ASGI transport wired to the test database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from core.site.bruit import BruitSiteResult
from core.site.transports import DesserteResult
from core.site.voisinage import VoisinEnrichi
from core.sources.bruitparif import BruitparifResult
from core.sources.cerema_bruit import ClassementSonore
from core.sources.dpe import DpeResult
from core.sources.dvf import DvfTransaction
from core.sources.google_streetview import StreetViewImage
from core.sources.ign_bdtopo import BatimentResult
from core.sources.ign_transports import ArretTC
from core.sources.mapillary import MapillaryPhoto
from core.sources.sitadel import ComparablePC


class TestSitePhotos:
    @pytest.mark.asyncio
    async def test_mapillary_one_photo_streetview_none(self, client: AsyncClient) -> None:
        """Mapillary returns 1 photo; streetview returns None → streetview list is empty."""
        with (
            patch(
                "api.routes.site.mapillary.fetch_photos_around",
                new_callable=AsyncMock,
                return_value=[
                    MapillaryPhoto(
                        image_id="img123",
                        thumb_url="https://example.com/thumb.jpg",
                        captured_at=1_700_000_000_000,
                        compass_angle=90.0,
                        lat=48.84,
                        lng=2.35,
                    )
                ],
            ),
            patch(
                "api.routes.site.google_streetview.fetch_streetview_image",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.get(
                "/api/v1/site/photos",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["mapillary"]) == 1
        assert data["mapillary"][0]["image_id"] == "img123"
        assert data["mapillary"][0]["thumb_url"] == "https://example.com/thumb.jpg"
        assert data["mapillary"][0]["captured_at"] == 1_700_000_000_000
        assert data["mapillary"][0]["compass_angle"] == 90.0
        assert data["streetview"] == []

    @pytest.mark.asyncio
    async def test_streetview_present_in_list(self, client: AsyncClient) -> None:
        """When Street View returns an image it appears as a single-item list."""
        with (
            patch(
                "api.routes.site.mapillary.fetch_photos_around",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.site.google_streetview.fetch_streetview_image",
                new_callable=AsyncMock,
                return_value=StreetViewImage(
                    pano_id="pano_abc",
                    image_url="https://maps.googleapis.com/maps/api/streetview?pano=pano_abc",
                    lat=48.84,
                    lng=2.35,
                    date="2023-06",
                ),
            ),
        ):
            resp = await client.get(
                "/api/v1/site/photos",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["mapillary"] == []
        assert len(data["streetview"]) == 1
        assert data["streetview"][0]["pano_id"] == "pano_abc"
        assert data["streetview"][0]["date"] == "2023-06"

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/site/photos")
        assert resp.status_code == 422


class TestSiteBruit:
    @pytest.mark.asyncio
    async def test_cerema_cat3_bruitparif_none(self, client: AsyncClient) -> None:
        """Cerema returns 1 category-3 voie, Bruitparif returns None → classement=3, isolation=True."""
        with (
            patch(
                "api.routes.site.cerema_bruit.fetch_classement_sonore",
                new_callable=AsyncMock,
                return_value=[
                    ClassementSonore(
                        categorie=3,
                        type_infra="route",
                        nom_voie="Boulevard de la République",
                        lden=71.5,
                    )
                ],
            ),
            patch(
                "api.routes.site.bruitparif.fetch_bruit_idf",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.get(
                "/api/v1/site/bruit",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["classement_sonore"] == 3
        assert data["source"] == "cerema"
        assert data["lden_dominant"] == 71.5
        assert data["isolation_acoustique_obligatoire"] is True

    @pytest.mark.asyncio
    async def test_no_data_returns_none_fields(self, client: AsyncClient) -> None:
        """Both sources empty → classement_sonore=None, isolation=False."""
        with (
            patch(
                "api.routes.site.cerema_bruit.fetch_classement_sonore",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.site.bruitparif.fetch_bruit_idf",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.get(
                "/api/v1/site/bruit",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["classement_sonore"] is None
        assert data["source"] is None
        assert data["isolation_acoustique_obligatoire"] is False

    @pytest.mark.asyncio
    async def test_bruitparif_worse_than_cerema(self, client: AsyncClient) -> None:
        """Bruitparif cat 1 overrides Cerema cat 3."""
        with (
            patch(
                "api.routes.site.cerema_bruit.fetch_classement_sonore",
                new_callable=AsyncMock,
                return_value=[
                    ClassementSonore(categorie=3, type_infra="route", nom_voie="Rue test", lden=71.0)
                ],
            ),
            patch(
                "api.routes.site.bruitparif.fetch_bruit_idf",
                new_callable=AsyncMock,
                return_value=BruitparifResult(
                    lden=82.0,
                    lnight=75.0,
                    source_type="routier",
                    code_insee="75056",
                ),
            ),
        ):
            resp = await client.get(
                "/api/v1/site/bruit",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["classement_sonore"] == 1
        assert data["isolation_acoustique_obligatoire"] is True

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/site/bruit")
        assert resp.status_code == 422


class TestSiteTransports:
    @pytest.mark.asyncio
    async def test_rer_at_300m_is_bien_desservie(self, client: AsyncClient) -> None:
        """A RER stop at 300m → bien_desservie=True, stationnement_exoneration_possible=True."""
        with patch(
            "api.routes.site.ign_transports.fetch_arrets_around",
            new_callable=AsyncMock,
            return_value=[
                ArretTC(
                    nom="Vincennes RER A",
                    mode="RER",
                    ligne="A",
                    exploitant="RATP",
                    lat=48.845,
                    lng=2.439,
                    distance_m=300.0,
                )
            ],
        ):
            resp = await client.get(
                "/api/v1/site/transports",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["arrets"]) == 1
        assert data["arrets"][0]["nom"] == "Vincennes RER A"
        assert data["arrets"][0]["mode"] == "RER"
        assert data["arrets"][0]["distance_m"] == 300.0
        assert data["bien_desservie"] is True
        assert data["stationnement_exoneration_possible"] is True
        assert "RER" in data["motif"]

    @pytest.mark.asyncio
    async def test_no_stops_not_bien_desservie(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.site.ign_transports.fetch_arrets_around",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                "/api/v1/site/transports",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["arrets"] == []
        assert data["bien_desservie"] is False
        assert data["stationnement_exoneration_possible"] is False
        assert data["motif"] is None

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/site/transports")
        assert resp.status_code == 422


class TestSiteVoisinage:
    @pytest.mark.asyncio
    async def test_one_building_with_dpe_match(self, client: AsyncClient) -> None:
        """BDTopo returns 1 building (5 floors), DPE returns 1 matching record → dpe_classe set."""
        with (
            patch(
                "api.routes.site.ign_bdtopo.fetch_batiments_around",
                new_callable=AsyncMock,
                return_value=[
                    BatimentResult(
                        hauteur=18.0,
                        nb_etages=5,
                        usage="Résidentiel",
                        altitude_sol=35.0,
                        altitude_toit=53.0,
                        geometry={"type": "Polygon", "coordinates": []},
                    )
                ],
            ),
            patch(
                "api.routes.site.dpe.fetch_dpe_around",
                new_callable=AsyncMock,
                return_value=[
                    DpeResult(
                        nb_niveaux=5,
                        hauteur_sous_plafond=2.5,
                        classe_energie="C",
                        type_batiment="immeuble",
                        adresse="12 Rue de la Paix 75001 Paris",
                    )
                ],
            ),
        ):
            resp = await client.get(
                "/api/v1/site/voisinage",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["batiments"]) == 1
        bat = data["batiments"][0]
        assert bat["hauteur"] == 18.0
        assert bat["nb_etages"] == 5
        assert bat["usage"] == "Résidentiel"
        assert bat["dpe_classe"] == "C"
        assert bat["ouvertures_visibles"] is None

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, client: AsyncClient) -> None:
        with (
            patch(
                "api.routes.site.ign_bdtopo.fetch_batiments_around",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.routes.site.dpe.fetch_dpe_around",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = await client.get(
                "/api/v1/site/voisinage",
                params={"lat": "48.84", "lng": "2.35"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["batiments"] == []

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/site/voisinage")
        assert resp.status_code == 422


class TestSiteComparables:
    @pytest.mark.asyncio
    async def test_one_pc_returned(self, client: AsyncClient) -> None:
        """Sitadel returns 1 PC → projects list has 1 item with correct fields."""
        with patch(
            "api.routes.site.sitadel.fetch_pc_commune",
            new_callable=AsyncMock,
            return_value=[
                ComparablePC(
                    date_arrete="2023-09-12",
                    adresse="45 Rue de Rivoli 75001 Paris",
                    nb_logements=24,
                    sdp_m2=1850.0,
                    destination="Logement",
                    hauteur_niveaux=6,
                    lat=48.857,
                    lng=2.349,
                    source="opendata_paris",
                )
            ],
        ):
            resp = await client.get(
                "/api/v1/site/comparables",
                params={"code_insee": "75056"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["projects"]) == 1
        proj = data["projects"][0]
        assert proj["date_arrete"] == "2023-09-12"
        assert proj["adresse"] == "45 Rue de Rivoli 75001 Paris"
        assert proj["nb_logements"] == 24
        assert proj["sdp_m2"] == 1850.0
        assert proj["destination"] == "Logement"
        assert proj["hauteur_niveaux"] == 6
        assert proj["source"] == "opendata_paris"

    @pytest.mark.asyncio
    async def test_empty_list(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.site.sitadel.fetch_pc_commune",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                "/api/v1/site/comparables",
                params={"code_insee": "94052"},
            )

        assert resp.status_code == 200
        assert resp.json()["projects"] == []

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/site/comparables")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_code_insee_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/site/comparables",
            params={"code_insee": "ABCDE"},
        )
        assert resp.status_code == 422


class TestSiteDvf:
    @pytest.mark.asyncio
    async def test_one_appartement_transaction_aggregates(self, client: AsyncClient) -> None:
        """DVF returns 1 Appartement transaction 350000€ / 65m² → prix_moyen_m2_appartement correct."""
        with patch(
            "api.routes.site.dvf.fetch_dvf_parcelle",
            new_callable=AsyncMock,
            return_value=[
                DvfTransaction(
                    date_mutation="2023-04-15",
                    nature_mutation="Vente",
                    valeur_fonciere=350_000.0,
                    type_local="Appartement",
                    surface_m2=65.0,
                    nb_pieces=3,
                    code_commune="75056",
                    adresse="10 Rue de la Paix 75001 Paris",
                )
            ],
        ):
            resp = await client.get(
                "/api/v1/site/dvf",
                params={"code_insee": "75056", "section": "AB", "numero": "0042"},
            )

        assert resp.status_code == 200
        data = resp.json()

        assert len(data["transactions"]) == 1
        txn = data["transactions"][0]
        assert txn["date_mutation"] == "2023-04-15"
        assert txn["nature_mutation"] == "Vente"
        assert txn["valeur_fonciere"] == 350_000.0
        assert txn["type_local"] == "Appartement"
        assert txn["surface_m2"] == 65.0
        assert txn["nb_pieces"] == 3

        agg = data["aggregates"]
        assert agg["nb_transactions"] == 1
        expected_prix = round(350_000.0 / 65.0, 2)
        assert agg["prix_moyen_m2_appartement"] == expected_prix
        assert agg["prix_moyen_m2_maison"] is None

    @pytest.mark.asyncio
    async def test_maison_transaction_aggregates(self, client: AsyncClient) -> None:
        """DVF returns 1 Maison transaction → prix_moyen_m2_maison set, appartement None."""
        with patch(
            "api.routes.site.dvf.fetch_dvf_parcelle",
            new_callable=AsyncMock,
            return_value=[
                DvfTransaction(
                    date_mutation="2022-11-01",
                    nature_mutation="Vente",
                    valeur_fonciere=480_000.0,
                    type_local="Maison",
                    surface_m2=120.0,
                    nb_pieces=5,
                    code_commune="94052",
                    adresse=None,
                )
            ],
        ):
            resp = await client.get(
                "/api/v1/site/dvf",
                params={"code_insee": "94052", "section": "BC", "numero": "0100"},
            )

        assert resp.status_code == 200
        data = resp.json()
        agg = data["aggregates"]
        assert agg["nb_transactions"] == 1
        assert agg["prix_moyen_m2_maison"] == round(480_000.0 / 120.0, 2)
        assert agg["prix_moyen_m2_appartement"] is None

    @pytest.mark.asyncio
    async def test_empty_transactions(self, client: AsyncClient) -> None:
        with patch(
            "api.routes.site.dvf.fetch_dvf_parcelle",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                "/api/v1/site/dvf",
                params={"code_insee": "75056", "section": "AB", "numero": "0001"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["transactions"] == []
        assert data["aggregates"]["nb_transactions"] == 0
        assert data["aggregates"]["prix_moyen_m2_appartement"] is None
        assert data["aggregates"]["prix_moyen_m2_maison"] is None

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/site/dvf")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_code_insee_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/site/dvf",
            params={"code_insee": "ABCDE", "section": "AB", "numero": "0042"},
        )
        assert resp.status_code == 422
