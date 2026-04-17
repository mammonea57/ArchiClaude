"""Unit tests for core.sources.gpu — Géoportail de l'Urbanisme client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.gpu import (
    GpuDocument,
    GpuPrescription,
    GpuServitude,
    GpuZone,
    fetch_document,
    fetch_prescriptions_at_point,
    fetch_servitudes_at_point,
    fetch_zones_at_point,
)

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "gpu_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


# Coordinates for Nogent-sur-Marne test parcel (used for all tests)
_LAT = 48.8375
_LNG = 2.4833

_GPU_BASE = "https://apicarto.ign.fr/api/gpu"

# Regex patterns for each GPU endpoint (matches regardless of query params)
_ZONE_URBA_RE = re.compile(rf"{re.escape(_GPU_BASE)}/zone-urba.*")
_DOCUMENT_RE = re.compile(rf"{re.escape(_GPU_BASE)}/document.*")
_SUP_S_RE = re.compile(rf"{re.escape(_GPU_BASE)}/assiette-sup-s.*")
_SUP_L_RE = re.compile(rf"{re.escape(_GPU_BASE)}/assiette-sup-l.*")
_SUP_P_RE = re.compile(rf"{re.escape(_GPU_BASE)}/assiette-sup-p.*")
_PSC_SURF_RE = re.compile(rf"{re.escape(_GPU_BASE)}/prescription-surf.*")
_PSC_LIN_RE = re.compile(rf"{re.escape(_GPU_BASE)}/prescription-lin.*")
_PSC_PCT_RE = re.compile(rf"{re.escape(_GPU_BASE)}/prescription-pct.*")

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_zones_nogent(httpx_mock: HTTPXMock) -> None:
    """Zone-urba endpoint returns a GpuZone with libelle='UB' and typezone='U'."""
    httpx_mock.add_response(url=_ZONE_URBA_RE, json=_load_fixture("zone_urba_nogent"))

    zones = await fetch_zones_at_point(lat=_LAT, lng=_LNG)

    assert len(zones) == 1
    z: GpuZone = zones[0]
    assert z.libelle == "UB"
    assert z.typezone == "U"
    assert z.idurba == "94052_PLUi_20210610"
    assert z.partition == "94052"
    assert z.nomfic == "PLUi_Nogent_reglement_UB.pdf"
    assert z.geometry is not None
    assert z.geometry["type"] == "MultiPolygon"

    # Verify geom param was a GeoJSON Point
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    sent_geom = json.loads(requests[0].url.params["geom"])
    assert sent_geom["type"] == "Point"
    assert sent_geom["coordinates"] == pytest.approx([_LNG, _LAT])


async def test_document_nogent(httpx_mock: HTTPXMock) -> None:
    """Document endpoint returns a GpuDocument with typedoc='PLUi'."""
    httpx_mock.add_response(url=_DOCUMENT_RE, json=_load_fixture("document_nogent"))

    docs = await fetch_document(lat=_LAT, lng=_LNG)

    assert len(docs) == 1
    d: GpuDocument = docs[0]
    assert d.typedoc == "PLUi"
    assert d.idurba == "94052_PLUi_20210610"
    assert d.datappro == "2021-06-10"
    assert d.nom == "PLUi Val de Marne Est"


async def test_servitudes_found(httpx_mock: HTTPXMock) -> None:
    """Servitude surface endpoint returns a GpuServitude with categorie='AC1'.
    Linear and point endpoints return empty results.
    """
    httpx_mock.add_response(url=_SUP_S_RE, json=_load_fixture("servitudes_surf_nogent"))
    httpx_mock.add_response(url=_SUP_L_RE, json=_load_fixture("servitudes_lin_nogent"))
    httpx_mock.add_response(url=_SUP_P_RE, json=_load_fixture("servitudes_pct_nogent"))

    servitudes = await fetch_servitudes_at_point(lat=_LAT, lng=_LNG)

    assert len(servitudes) == 1
    s: GpuServitude = servitudes[0]
    assert s.categorie == "AC1"
    assert "monuments historiques" in s.libelle.lower()
    assert s.txt is not None
    assert s.geometry is not None
    assert s.geometry["type"] == "MultiPolygon"


async def test_servitudes_degraded_mode(httpx_mock: HTTPXMock) -> None:
    """When one servitude sub-endpoint fails, the others still succeed (mode dégradé)."""

    httpx_mock.add_response(url=_SUP_S_RE, json=_load_fixture("servitudes_surf_nogent"))
    httpx_mock.add_response(url=_SUP_L_RE, status_code=503)
    httpx_mock.add_response(url=_SUP_P_RE, json=_load_fixture("servitudes_pct_nogent"))

    # Should not raise — returns whatever succeeded
    servitudes = await fetch_servitudes_at_point(lat=_LAT, lng=_LNG)

    # Only surface endpoint had results
    assert len(servitudes) == 1
    assert servitudes[0].categorie == "AC1"


async def test_prescriptions_found(httpx_mock: HTTPXMock) -> None:
    """Prescription surface endpoint returns a GpuPrescription. Others are empty."""
    httpx_mock.add_response(url=_PSC_SURF_RE, json=_load_fixture("prescriptions_surf_nogent"))
    httpx_mock.add_response(url=_PSC_LIN_RE, json=_load_fixture("prescriptions_lin_nogent"))
    httpx_mock.add_response(url=_PSC_PCT_RE, json=_load_fixture("prescriptions_pct_nogent"))

    prescriptions = await fetch_prescriptions_at_point(lat=_LAT, lng=_LNG)

    assert len(prescriptions) == 1
    p: GpuPrescription = prescriptions[0]
    assert "boisé" in p.libelle.lower()
    assert p.typepsc == "15"
    assert p.txt is not None
    assert p.geometry is not None
    assert p.geometry["type"] == "MultiPolygon"


async def test_prescriptions_degraded_mode(httpx_mock: HTTPXMock) -> None:
    """When one prescription sub-endpoint fails, the others still succeed."""
    httpx_mock.add_response(url=_PSC_SURF_RE, status_code=500)
    httpx_mock.add_response(url=_PSC_LIN_RE, json=_load_fixture("prescriptions_lin_nogent"))
    httpx_mock.add_response(url=_PSC_PCT_RE, json=_load_fixture("prescriptions_pct_nogent"))

    # Should not raise — returns empty list (lin and pct have no features)
    prescriptions = await fetch_prescriptions_at_point(lat=_LAT, lng=_LNG)
    assert prescriptions == []
