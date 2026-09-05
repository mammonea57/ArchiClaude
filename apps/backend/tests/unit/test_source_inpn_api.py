"""Unit tests for core.sources.inpn_api — INPN WFS client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.

The on-disk cache is redirected to a tmp_path per test to avoid clobbering
``refs/cache/inpn_api/``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from core.sources import inpn_api
from core.sources.inpn_api import InpnBundle, fetch_inpn_overlays
from core.urbanism_overlays.schemas import EBC, ZNIEFF, Natura2000

# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "inpn_api_responses.json"


def _load_fixture(key: str) -> dict[str, Any]:
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_WFS_URL_RE = re.compile(r"https://data\.geopf\.fr/wfs/ows.*")

# Nogent-sur-Marne — 80 rue des Héros (approx, IDF, 94)
_LAT = 48.83558
_LNG = 2.4810


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the on-disk cache to a per-test temp directory + zero retry backoff."""
    monkeypatch.setattr(inpn_api, "_CACHE_DIR", tmp_path / "inpn_api")
    # Neutralise the exponential backoff inside tests so the 5xx retry loop
    # in test_degraded_mode_one_layer_fails runs in milliseconds.
    inpn_api._wfs_get.retry.wait = lambda *a, **kw: 0  # type: ignore[attr-defined]


def _add_layer_response(httpx_mock: HTTPXMock, typename: str, fixture_key: str) -> None:
    """Register a mock response keyed by the TYPENAMES query param.

    httpx URL-encodes ``:`` to ``%3A`` in query strings, so we match the
    URL-encoded form in our regex.
    """
    encoded = typename.replace(":", "%3A")
    pattern = re.compile(
        r"https://data\.geopf\.fr/wfs/ows.*TYPENAMES=" + re.escape(encoded)
    )
    httpx_mock.add_response(url=pattern, json=_load_fixture(fixture_key))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_fetch_all_layers_aggregates_features(httpx_mock: HTTPXMock) -> None:
    """Each WFS layer returns features — bundle aggregates them with applies=True."""
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.SIC:sic", "zsc_nogent")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZPS:zps", "zps_empty")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZNIEFF1:znieff1", "znieff1_nogent")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZNIEFF2:znieff2", "znieff2_empty")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.FORESTS:forets_publiques", "ebc_present")

    bundle: InpnBundle = await fetch_inpn_overlays(lat=_LAT, lng=_LNG, radius_m=500)

    # Feature aggregation
    assert bundle.feature_count == 3  # 1 ZSC + 1 ZNIEFF1 + 1 EBC
    layers = {f.layer for f in bundle.features}
    assert layers == {"ZSC", "ZNIEFF1", "EBC"}

    # ZSC feature parsed correctly
    zsc = next(f for f in bundle.features if f.layer == "ZSC")
    assert zsc.sitecode == "FR1100795"
    assert "Vincennes" in zsc.name

    # Natura 2000 overlay
    assert isinstance(bundle.natura2000, Natura2000)
    assert bundle.natura2000.applies is True
    assert bundle.natura2000.type_zone == "ZSC"
    assert bundle.natura2000.geometry_geojson is not None

    # ZNIEFF overlay — type 1 preferred when both present
    assert isinstance(bundle.znieff, ZNIEFF)
    assert bundle.znieff.applies is True
    assert bundle.znieff.type_znieff == "1"

    # EBC overlay
    assert isinstance(bundle.ebc, EBC)
    assert bundle.ebc.applies is True
    assert any("EBC" in n for n in bundle.ebc.notes)


async def test_empty_area_returns_non_applicable_overlays(httpx_mock: HTTPXMock) -> None:
    """All layers empty — bundle is empty and all overlays have applies=False."""
    for tn in [
        "PROTECTEDAREAS.SIC:sic",
        "PROTECTEDAREAS.ZPS:zps",
        "PROTECTEDAREAS.ZNIEFF1:znieff1",
        "PROTECTEDAREAS.ZNIEFF2:znieff2",
        "PROTECTEDAREAS.FORESTS:forets_publiques",
    ]:
        _add_layer_response(httpx_mock, tn, "all_empty")

    bundle = await fetch_inpn_overlays(lat=_LAT, lng=_LNG)

    assert bundle.feature_count == 0
    assert bundle.natura2000 is not None
    assert bundle.natura2000.applies is False
    assert bundle.znieff is not None
    assert bundle.znieff.applies is False
    assert bundle.ebc is not None
    assert bundle.ebc.applies is False


async def test_degraded_mode_one_layer_fails(httpx_mock: HTTPXMock) -> None:
    """A 5xx on one layer does not prevent the other layers from returning."""
    # ZSC fails — tenacity retries 4 times before giving up.
    zsc_pattern = re.compile(
        r"https://data\.geopf\.fr/wfs/ows.*TYPENAMES="
        + re.escape("PROTECTEDAREAS.SIC%3Asic")
    )
    for _ in range(4):
        httpx_mock.add_response(url=zsc_pattern, status_code=503)

    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZPS:zps", "zps_empty")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZNIEFF1:znieff1", "znieff1_nogent")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZNIEFF2:znieff2", "znieff2_empty")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.FORESTS:forets_publiques", "ebc_empty")

    bundle = await fetch_inpn_overlays(lat=_LAT, lng=_LNG)

    # ZSC dropped, ZNIEFF1 still present
    assert bundle.feature_count == 1
    assert bundle.features[0].layer == "ZNIEFF1"
    assert bundle.natura2000 is not None and bundle.natura2000.applies is False
    assert bundle.znieff is not None and bundle.znieff.applies is True


async def test_cache_hit_skips_network(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
) -> None:
    """Second call with same BBOX hits the cache — no second HTTP request issued."""
    # First call — register one response per layer.
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.SIC:sic", "zsc_nogent")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZPS:zps", "zps_empty")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZNIEFF1:znieff1", "znieff1_nogent")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.ZNIEFF2:znieff2", "znieff2_empty")
    _add_layer_response(httpx_mock, "PROTECTEDAREAS.FORESTS:forets_publiques", "ebc_empty")

    bundle1 = await fetch_inpn_overlays(lat=_LAT, lng=_LNG, radius_m=500)
    first_count = len(httpx_mock.get_requests())
    assert first_count == 5

    # Second call — no new mock responses added; pytest-httpx would raise if
    # any unhandled request were issued, so a clean run proves cache hit.
    bundle2 = await fetch_inpn_overlays(lat=_LAT, lng=_LNG, radius_m=500)
    assert len(httpx_mock.get_requests()) == first_count  # no new HTTP calls
    assert bundle2.feature_count == bundle1.feature_count


async def test_bbox_takes_precedence_over_latlng(httpx_mock: HTTPXMock) -> None:
    """Explicit BBOX is used verbatim and overrides lat/lng."""
    for tn in [
        "PROTECTEDAREAS.SIC:sic",
        "PROTECTEDAREAS.ZPS:zps",
        "PROTECTEDAREAS.ZNIEFF1:znieff1",
        "PROTECTEDAREAS.ZNIEFF2:znieff2",
        "PROTECTEDAREAS.FORESTS:forets_publiques",
    ]:
        _add_layer_response(httpx_mock, tn, "all_empty")

    explicit_bbox = (2.4700, 48.8300, 2.4900, 48.8400)
    await fetch_inpn_overlays(
        lat=_LAT, lng=_LNG, bbox=explicit_bbox,
    )

    # Verify the WFS BBOX query param matches the supplied tuple, not the
    # default radius derived from lat/lng.
    req = httpx_mock.get_requests()[0]
    bbox_param = req.url.params["BBOX"]
    parts = [float(p) for p in bbox_param.split(",")]
    assert parts == pytest.approx(list(explicit_bbox), rel=1e-5)


async def test_missing_inputs_raises() -> None:
    """Neither bbox nor (lat,lng) supplied -> ValueError (caller bug)."""
    with pytest.raises(ValueError, match="bbox or"):
        await fetch_inpn_overlays()
