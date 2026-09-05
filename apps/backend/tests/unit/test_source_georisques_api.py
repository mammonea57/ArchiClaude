"""Unit tests for core.sources.georisques_api — full v1 multi-endpoint client.

Covers:
* Successful aggregation across the seven endpoints.
* Local on-disk cache (write + hit).
* Mode dégradé : one endpoint 5xx → others still returned.
* Exponential backoff: 503 then 200 → success on retry.
* Mapping to ``_RisqueBase`` subclasses (PPRI, RGA, BASIAS, BASOL, SIS,
  ICPE, Cavites).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from core.sources.georisques_api import (
    ENDPOINTS,
    GeorisquesQuery,
    fetch_all_features,
    fetch_georisques_overlays,
)
from core.urbanism_overlays.schemas import (
    BASIAS,
    BASOL,
    PPRI,
    RGA,
    SIS,
    Cavites,
    ICPE,
)

# Nogent — 80 rue des Héros (approx, in Val-de-Marne PPRi zone)
_LAT = 48.83558
_LNG = 2.4810


# ---------------------------------------------------------------------------
# Fixture payloads (minimal but schema-compatible)
# ---------------------------------------------------------------------------


def _ppri_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "type_risque": "inondation",
                "code_risque": "PPRi-Val-de-Marne",
                "libelle_risque": "Plan de prévention du risque inondation",
                "niveau_alea": "zone bleu",
            }
        ]
    }


def _rga_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "code_alea": "G2",
                "libelle_alea": "Retrait-gonflement des argiles",
                "niveau_alea": "moyen",
            }
        ]
    }


def _basias_payload() -> dict[str, Any]:
    return {
        "data": [
            {"nom_usuel": "Garage ancien rue des Héros", "raison_sociale": "SARL Y"},
            {"nom_usuel": "Ancienne pressing", "raison_sociale": "SAS X"},
        ]
    }


def _basol_payload() -> dict[str, Any]:
    return {"data": [{"nom_usuel": "Site BASOL Nogent", "nom": "ex-usine"}]}


def _sis_payload() -> dict[str, Any]:
    return {"data": [{"nom": "SIS Bord de Marne"}]}


def _icpe_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "nom_etablissement": "Dépôt logistique 94",
                "regime": "A",
                "rayon_effets": "300",
            }
        ]
    }


def _cavites_payload() -> dict[str, Any]:
    return {"data": [{"nature": "Carrière souterraine"}]}


def _empty_payload() -> dict[str, Any]:
    return {"data": []}


def _mock_all_endpoints_ok(httpx_mock: HTTPXMock) -> None:
    """Wire every GeoRisques endpoint to a successful payload."""
    payloads = {
        "ppri": _ppri_payload(),
        "rga": _rga_payload(),
        "basias": _basias_payload(),
        "basol": _basol_payload(),
        "sis": _sis_payload(),
        "icpe": _icpe_payload(),
        "cavites": _cavites_payload(),
    }
    for name, url in ENDPOINTS.items():
        # is_reusable so a same-URL retry from the cache miss flow does
        # not raise "no more responses".
        httpx_mock.add_response(
            url=re.compile(re.escape(url) + r".*"),
            json=payloads[name],
            is_reusable=True,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_fetch_overlays_aggregates_all_endpoints(
    httpx_mock: HTTPXMock, tmp_path: Path,
) -> None:
    """Happy path: every endpoint returns features → overlays for each type."""
    _mock_all_endpoints_ok(httpx_mock)

    result = await fetch_georisques_overlays(
        lat=_LAT, lng=_LNG, cache_dir=tmp_path / "cache", use_cache=False,
    )

    assert result.total_features == 1 + 1 + 2 + 1 + 1 + 1 + 1  # 8
    assert result.feature_counts == {
        "ppri": 1, "rga": 1, "basias": 2, "basol": 1,
        "sis": 1, "icpe": 1, "cavites": 1,
    }
    assert result.errors == {}

    by_type = {type(o).__name__: o for o in result.overlays}
    assert isinstance(by_type["PPRI"], PPRI)
    assert by_type["PPRI"].zone_alea == "bleu"
    assert isinstance(by_type["RGA"], RGA)
    assert by_type["RGA"].niveau == "moyen"
    assert isinstance(by_type["BASIAS"], BASIAS)
    assert isinstance(by_type["BASOL"], BASOL)
    assert isinstance(by_type["SIS"], SIS)
    icpe = by_type["ICPE"]
    assert isinstance(icpe, ICPE)
    assert icpe.rayon_effets_m == 300.0
    assert isinstance(by_type["Cavites"], Cavites)

    # Two BASIAS features → two overlays of the same type
    basias_overlays = [o for o in result.overlays if isinstance(o, BASIAS)]
    assert len(basias_overlays) == 2


async def test_local_cache_written_and_reused(
    httpx_mock: HTTPXMock, tmp_path: Path,
) -> None:
    """First call writes JSON to refs/cache; second call hits cache (no HTTP)."""
    cache_dir = tmp_path / "cache"
    _mock_all_endpoints_ok(httpx_mock)

    first = await fetch_georisques_overlays(
        lat=_LAT, lng=_LNG, cache_dir=cache_dir, use_cache=True,
    )
    assert first.total_features > 0
    cached_files = list(cache_dir.glob("*.json"))
    assert len(cached_files) == len(ENDPOINTS), \
        f"expected {len(ENDPOINTS)} cache files, got {len(cached_files)}"

    # Drop the registered HTTP mocks → if the cache is honoured we should
    # not need any network call.
    httpx_mock.reset()

    second = await fetch_georisques_overlays(
        lat=_LAT, lng=_LNG, cache_dir=cache_dir, use_cache=True,
    )
    assert second.feature_counts == first.feature_counts


async def test_mode_degrade_one_endpoint_fails(
    httpx_mock: HTTPXMock, tmp_path: Path,
) -> None:
    """A persistent 500 on one endpoint does not abort the bundle."""
    # ppri returns 500 for every attempt; the others succeed.
    httpx_mock.add_response(
        url=re.compile(re.escape(ENDPOINTS["ppri"]) + r".*"),
        status_code=500,
        is_reusable=True,
    )
    for name, url in ENDPOINTS.items():
        if name == "ppri":
            continue
        httpx_mock.add_response(
            url=re.compile(re.escape(url) + r".*"),
            json=_empty_payload() if name in {"basias", "icpe"} else _rga_payload(),
            is_reusable=True,
        )

    result = await fetch_georisques_overlays(
        lat=_LAT, lng=_LNG, cache_dir=tmp_path / "cache", use_cache=False,
    )
    assert "ppri" in result.errors
    assert result.feature_counts.get("ppri", 0) == 0
    # Other endpoints still returned data.
    assert sum(v for k, v in result.feature_counts.items() if k != "ppri") > 0


async def test_exponential_backoff_recovers_after_503(
    httpx_mock: HTTPXMock, tmp_path: Path,
) -> None:
    """One 503 followed by a 200 → endpoint succeeds on retry."""
    rga_url_re = re.compile(re.escape(ENDPOINTS["rga"]) + r".*")
    httpx_mock.add_response(url=rga_url_re, status_code=503)
    httpx_mock.add_response(url=rga_url_re, json=_rga_payload(), is_reusable=True)

    # The other endpoints just return empty so we can isolate RGA.
    for name, url in ENDPOINTS.items():
        if name == "rga":
            continue
        httpx_mock.add_response(
            url=re.compile(re.escape(url) + r".*"),
            json=_empty_payload(),
            is_reusable=True,
        )

    result = await fetch_georisques_overlays(
        lat=_LAT, lng=_LNG, cache_dir=tmp_path / "cache", use_cache=False,
    )
    assert result.feature_counts["rga"] == 1
    assert "rga" not in result.errors


async def test_bbox_query_mode(
    httpx_mock: HTTPXMock, tmp_path: Path,
) -> None:
    """BBOX accepted as alternative to lat/lng; param contains bbox=..."""
    _mock_all_endpoints_ok(httpx_mock)
    bbox = (2.480, 48.834, 2.482, 48.837)

    result = await fetch_georisques_overlays(
        bbox=bbox, cache_dir=tmp_path / "cache", use_cache=False,
    )
    assert result.total_features > 0

    seen_bbox_param = False
    for req in httpx_mock.get_requests():
        if req.url.params.get("bbox"):
            seen_bbox_param = True
            assert "2.48" in req.url.params["bbox"]
            break
    assert seen_bbox_param, "no request carried a bbox= parameter"


async def test_query_validates_input() -> None:
    """GeorisquesQuery rejects missing coordinates."""
    with pytest.raises(ValueError):
        GeorisquesQuery().base_params()


async def test_fetch_all_features_endpoint_subset(
    httpx_mock: HTTPXMock, tmp_path: Path,
) -> None:
    """When ``endpoints=[...]`` is set, only those endpoints are queried."""
    httpx_mock.add_response(
        url=re.compile(re.escape(ENDPOINTS["rga"]) + r".*"),
        json=_rga_payload(),
        is_reusable=True,
    )

    query = GeorisquesQuery(lat=_LAT, lng=_LNG)
    raw = await fetch_all_features(
        query,
        cache_dir=tmp_path / "cache",
        use_cache=False,
        endpoints=["rga"],
    )
    assert list(raw.keys()) == ["rga"]
