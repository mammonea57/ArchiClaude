"""Unit tests for core.sources.gpu_wfs — GPU WFS loader.

Network calls are intercepted by pytest-httpx so the module-level
httpx client in core.http_client is transparently mocked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources import gpu_wfs as mod
from core.sources.gpu_wfs import (
    GpuWfsBundle,
    _bbox_from_point,
    _cache_key,
    _cache_path,
    load_gpu_overlays,
)

# ---------------------------------------------------------------------------
# Constants — Nogent 80 rue des Héros
# ---------------------------------------------------------------------------

_LAT = 48.83558
_LNG = 2.4810

# Match any data.geopf.fr WFS request regardless of query parameters
_WFS_RE = re.compile(r"https://data\.geopf\.fr/wfs/ows.*")


# ---------------------------------------------------------------------------
# Fixtures: redirect the disk cache to a tmp dir so tests don't pollute repo
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "gpu_wfs_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(mod, "_CACHE_DIR", cache_dir)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    # Speed retries to milliseconds in tests so the suite stays snappy.
    monkeypatch.setattr(mod, "_BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(mod, "_BACKOFF_MAX_S", 0.05)


# ---------------------------------------------------------------------------
# Sample WFS payloads (minimal but realistic GeoJSON)
# ---------------------------------------------------------------------------


def _zone_payload() -> dict:  # type: ignore[type-arg]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[
                        [2.4805, 48.8351],
                        [2.4815, 48.8351],
                        [2.4815, 48.8361],
                        [2.4805, 48.8361],
                        [2.4805, 48.8351],
                    ]]],
                },
                "properties": {
                    "libelle": "UA1",
                    "libelong": "Zone urbaine centrale dense",
                    "typezone": "U",
                    "partition": "94052",
                    "idurba": "94052_PLUi_20210610",
                    "nomfic": "PLUi_Nogent_UA1.pdf",
                    "urlfic": "https://www.geoportail-urbanisme.gouv.fr/document/UA1.pdf",
                },
            }
        ],
    }


def _prescription_payload() -> dict:  # type: ignore[type-arg]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [2.480, 48.835], [2.482, 48.835], [2.482, 48.836], [2.480, 48.836], [2.480, 48.835],
                ]]},
                "properties": {
                    "libelle": "EBC — Espace Boisé Classé",
                    "typepsc": "01",
                    "txt": "Préservation des boisements existants",
                },
            }
        ],
    }


def _sup_payload() -> dict:  # type: ignore[type-arg]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": [[[
                    [2.478, 48.834], [2.483, 48.834], [2.483, 48.837], [2.478, 48.837], [2.478, 48.834],
                ]]]},
                "properties": {
                    "libelle": "Périmètre de protection MH",
                    "categorie": "AC1",
                    "txt": "Monument historique — 500 m",
                },
            }
        ],
    }


def _oap_payload() -> dict:  # type: ignore[type-arg]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [2.480, 48.835], [2.482, 48.835], [2.482, 48.836], [2.480, 48.836], [2.480, 48.835],
                ]]},
                "properties": {
                    "nom_oap": "OAP Cœur de Ville",
                    "type_oap": "sectorielle",
                    "txt": "Densification + commerces en RDC",
                },
            }
        ],
    }


def _empty_fc() -> dict:  # type: ignore[type-arg]
    return {"type": "FeatureCollection", "features": []}


# ---------------------------------------------------------------------------
# Helpers used by tests
# ---------------------------------------------------------------------------


def _register_all_layers(
    httpx_mock: HTTPXMock,
    *,
    overrides: dict[str, dict] | None = None,  # type: ignore[type-arg]
    statuses: dict[str, int] | None = None,
) -> None:
    """Register one response per WFS layer, in the order they will be called.

    pytest-httpx matches responses FIFO for a given URL pattern, and the
    loader's asyncio.gather() launches all eight calls concurrently. Since
    we cannot reliably predict completion order, we rely on per-call
    matching via the TYPENAMES query parameter using callback responses.
    """
    overrides = overrides or {}
    statuses = statuses or {}

    # Snapshot the (name, typename) pairs from the module's mapping
    for name, typename in mod._TYPENAMES.items():
        status = statuses.get(name)
        payload = overrides.get(name)
        if status is not None and status >= 400:
            httpx_mock.add_response(
                url=re.compile(
                    rf"https://data\.geopf\.fr/wfs/ows.*TYPENAMES={re.escape(typename)}.*"
                ),
                status_code=status,
            )
        else:
            httpx_mock.add_response(
                url=re.compile(
                    rf"https://data\.geopf\.fr/wfs/ows.*TYPENAMES={re.escape(typename)}.*"
                ),
                json=payload if payload is not None else _empty_fc(),
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bbox_from_point_is_centered() -> None:
    bbox = _bbox_from_point(_LAT, _LNG, radius_m=50.0)
    min_lng, min_lat, max_lng, max_lat = bbox
    # Roughly symmetric around the point
    assert min_lng < _LNG < max_lng
    assert min_lat < _LAT < max_lat
    # 50 m radius at IDF latitudes ⇒ ~0.00045° lat, ~0.00068° lng
    assert (max_lat - min_lat) == pytest.approx(50 / 111_000 * 2, rel=1e-3)
    assert (max_lng - min_lng) == pytest.approx(50 / 73_000 * 2, rel=1e-3)


async def test_bbox_required_when_no_point() -> None:
    with pytest.raises(ValueError, match="bbox= or both lat= and lng="):
        await load_gpu_overlays()


def test_cache_key_is_deterministic() -> None:
    bbox = (2.480, 48.835, 2.482, 48.836)
    assert _cache_key("wfs_du:zone_urba", bbox) == _cache_key("wfs_du:zone_urba", bbox)
    assert _cache_key("wfs_du:zone_urba", bbox) != _cache_key("wfs_sup:assiette_sup_s", bbox)


async def test_load_gpu_overlays_nogent_returns_features(httpx_mock: HTTPXMock) -> None:
    _register_all_layers(
        httpx_mock,
        overrides={
            "zone_urba": _zone_payload(),
            "prescription_surf": _prescription_payload(),
            "assiette_sup_s": _sup_payload(),
            "secteur_oap": _oap_payload(),
        },
    )

    bundle = await load_gpu_overlays(lat=_LAT, lng=_LNG, use_cache=False)

    assert isinstance(bundle, GpuWfsBundle)
    assert bundle.feature_count() == 4
    assert len(bundle.zones) == 1
    assert bundle.zones[0].libelle == "UA1"
    assert bundle.zones[0].typezone == "U"
    assert bundle.zones[0].idurba == "94052_PLUi_20210610"
    assert len(bundle.prescriptions) == 1
    assert bundle.prescriptions[0].geom_kind == "surf"
    assert "boisé" in bundle.prescriptions[0].libelle.lower()
    assert len(bundle.sups) == 1
    assert bundle.sups[0].categorie == "AC1"
    assert bundle.sups[0].geom_kind == "s"
    assert len(bundle.oap_sectors) == 1
    assert bundle.oap_sectors[0].nom_oap == "OAP Cœur de Ville"


async def test_load_gpu_overlays_empty_when_no_data(httpx_mock: HTTPXMock) -> None:
    _register_all_layers(httpx_mock)

    bundle = await load_gpu_overlays(lat=_LAT, lng=_LNG, use_cache=False)

    assert bundle.feature_count() == 0
    assert bundle.zones == []
    assert bundle.prescriptions == []
    assert bundle.sups == []
    assert bundle.oap_sectors == []


async def test_load_gpu_overlays_skips_failing_layers(httpx_mock: HTTPXMock) -> None:
    """A definitive 404 on one layer must not abort the others."""
    _register_all_layers(
        httpx_mock,
        overrides={"zone_urba": _zone_payload(), "secteur_oap": _oap_payload()},
        statuses={"assiette_sup_s": 404, "prescription_surf": 404},
    )

    bundle = await load_gpu_overlays(lat=_LAT, lng=_LNG, use_cache=False)

    # The two successful layers still flowed through:
    assert len(bundle.zones) == 1
    assert len(bundle.oap_sectors) == 1
    # The failing layers returned no features (skipped, not crashed):
    assert bundle.sups == []
    assert bundle.prescriptions == []
    # And the errors are surfaced in layer_errors for the caller to act on
    assert "assiette_sup_s" in bundle.layer_errors
    assert "prescription_surf" in bundle.layer_errors
    assert "HTTP 404" in bundle.layer_errors["assiette_sup_s"]


async def test_load_gpu_overlays_uses_cache(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    """Second call with use_cache=True must not hit the network."""
    _register_all_layers(
        httpx_mock,
        overrides={"zone_urba": _zone_payload()},
    )

    bundle_1 = await load_gpu_overlays(lat=_LAT, lng=_LNG, use_cache=True)
    assert len(bundle_1.zones) == 1
    first_request_count = len(httpx_mock.get_requests())
    assert first_request_count == len(mod._TYPENAMES)

    # Cache files should now exist on disk
    cache_files = list(mod._CACHE_DIR.glob("*.json"))
    assert len(cache_files) == len(mod._TYPENAMES)

    # Reset mock — second call must serve everything from cache
    httpx_mock.reset()
    bundle_2 = await load_gpu_overlays(lat=_LAT, lng=_LNG, use_cache=True)
    assert len(bundle_2.zones) == 1
    assert httpx_mock.get_requests() == []


async def test_load_gpu_overlays_explicit_bbox(httpx_mock: HTTPXMock) -> None:
    _register_all_layers(httpx_mock, overrides={"zone_urba": _zone_payload()})
    bbox = (2.4805, 48.8351, 2.4815, 48.8361)

    bundle = await load_gpu_overlays(bbox=bbox, use_cache=False)

    assert bundle.bbox == bbox
    assert len(bundle.zones) == 1


async def test_load_gpu_overlays_retries_on_5xx(httpx_mock: HTTPXMock) -> None:
    """A transient 503 on zone_urba should be retried, not skipped."""
    # First call to zone_urba returns 503, then succeeds. All other layers
    # always return empty.
    zone_typename = mod._TYPENAMES["zone_urba"]

    # First-shot 503 for zone_urba
    httpx_mock.add_response(
        url=re.compile(rf"https://data\.geopf\.fr/wfs/ows.*TYPENAMES={re.escape(zone_typename)}.*"),
        status_code=503,
    )
    # Then a success
    httpx_mock.add_response(
        url=re.compile(rf"https://data\.geopf\.fr/wfs/ows.*TYPENAMES={re.escape(zone_typename)}.*"),
        json=_zone_payload(),
    )
    # Other layers: just empty FC (one response per layer, since the
    # loader calls each typename exactly once).
    for name, typename in mod._TYPENAMES.items():
        if name == "zone_urba":
            continue
        httpx_mock.add_response(
            url=re.compile(rf"https://data\.geopf\.fr/wfs/ows.*TYPENAMES={re.escape(typename)}.*"),
            json=_empty_fc(),
        )

    bundle = await load_gpu_overlays(lat=_LAT, lng=_LNG, use_cache=False)

    assert len(bundle.zones) == 1, "zone_urba should be present after one retry"


def test_to_jsonable_roundtrips() -> None:
    bbox = (2.4805, 48.8351, 2.4815, 48.8361)
    bundle = GpuWfsBundle(bbox=bbox)
    payload = bundle.to_jsonable()
    assert payload["bbox"] == list(bbox)
    assert payload["zones"] == []
    assert payload["layer_errors"] == {}
