"""Regression tests for the 2026-06 fix of ``core.sources.ign_transports``.

The legacy implementation queried a single (wrong) BDTOPO_V3 layer that
never returned railway stations. The new implementation combines:

  * IGN POI Gares WFS layer
    ``UTILIYANDGOVERNMENTALSERVICES.IGN.POI.GARES:gares`` for SNCF /
    RER / Transilien stations.
  * OpenStreetMap Overpass for metro / RER / tram / bus.
  * The original BDTOPO layer (kept for backward compat with existing
    fixtures).

HTTP calls are intercepted by pytest-httpx so the suite never touches
the network. Each test redirects the local cache to ``tmp_path`` so the
developer's real cache is never altered.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from core.sources import ign_transports as it
from core.sources.ign_transports import fetch_arrets_around

_WFS_URL_RE = re.compile(r"https://data\.geopf\.fr/wfs/ows.*")
_WFS_LEGACY_URL_RE = re.compile(
    r"https://data\.geopf\.fr/wfs/ows.*zone_d_activites_ou_d_interet.*"
)
_WFS_GARES_URL_RE = re.compile(
    r"https://data\.geopf\.fr/wfs/ows.*POI\.GARES.*"
)
_OVERPASS_URL_RE = re.compile(r"https://(overpass\.kumi\.systems|.*overpass-api\.de)/api/interpreter.*")

# 80 rue des Héros, Nogent-sur-Marne.
_LAT = 48.83558
_LNG = 2.4810


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache_dir = tmp_path / "ign_transports"
    monkeypatch.setattr(it, "_CACHE_DIR", cache_dir)
    return cache_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ign_gares_response(stations: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a FeatureCollection matching the IGN POI Gares schema."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s["lng"], s["lat"]]},
                "properties": {
                    "toponyme": s["nom"],
                    "nature": s.get("nature", "Gare voyageurs uniquement"),
                    "designations": s.get("designations", ""),
                },
            }
            for s in stations
        ],
    }


def _overpass_response(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 0.6, "generator": "Overpass API", "elements": elements}


def _osm_node(
    *,
    lat: float,
    lng: float,
    name: str,
    railway: str | None = None,
    public_transport: str | None = None,
    highway: str | None = None,
    train: str | None = None,
    rer: str | None = None,
    subway: str | None = None,
    tram: str | None = None,
    operator: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    tags: dict[str, Any] = {"name": name}
    if railway: tags["railway"] = railway
    if public_transport: tags["public_transport"] = public_transport
    if highway: tags["highway"] = highway
    if train: tags["train"] = train
    if rer: tags["rer"] = rer
    if subway: tags["subway"] = subway
    if tram: tags["tram"] = tram
    if operator: tags["operator"] = operator
    if ref: tags["ref"] = ref
    return {"type": "node", "id": int(abs(lat * lng * 1000)), "lat": lat, "lon": lng, "tags": tags}


# ---------------------------------------------------------------------------
# Regression — Nogent finds the RER A gare
# ---------------------------------------------------------------------------


async def test_nogent_rer_a_station_is_found(httpx_mock: HTTPXMock) -> None:
    """The Nogent-le-Perreux station must be present in the result list.

    Regression : the previous loader returned 0 stops because it queried
    ``BDTOPO_V3:zone_d_activites_ou_d_interet`` which never contains
    railway stations.
    """
    # IGN WFS — legacy returns empty, gares returns the real Nogent stations.
    httpx_mock.add_response(
        url=_WFS_LEGACY_URL_RE,
        json={"type": "FeatureCollection", "features": []},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_WFS_GARES_URL_RE,
        json=_ign_gares_response([
            {
                "nom": "gare de nogent-le perreux",
                "lat": 48.83849512,
                "lng": 2.49406622,
                "designations": "gare voyageurs uniquement",
            },
            {
                "nom": "gare de nogent-sur-marne",
                "lat": 48.83451945,
                "lng": 2.47168754,
                "designations": "gare voyageurs uniquement",
            },
        ]),
        is_reusable=True,
    )
    # Overpass — return the RER A halt with train=yes.
    httpx_mock.add_response(
        url=_OVERPASS_URL_RE,
        json=_overpass_response([
            _osm_node(
                lat=48.8386135, lng=2.4942678,
                name="Nogent - Le Perreux", railway="station", train="yes",
                operator="RATP",
            ),
        ]),
        is_reusable=True,
    )

    arrets = await fetch_arrets_around(
        lat=_LAT, lng=_LNG, radius_m=800, use_cache=False,
    )

    names = [a.nom.lower() for a in arrets]
    # At least one Nogent / Le Perreux entry must be present.
    assert any("nogent" in n for n in names), f"no nogent station found: {names}"

    # The nearest railway station must be within 500m of the parcelle.
    rail = [a for a in arrets if a.mode in ("gare", "RER")]
    assert rail, f"no railway station in results: {arrets}"
    rail.sort(key=lambda a: a.distance_m or 9e9)
    nearest = rail[0]
    assert nearest.distance_m is not None
    assert nearest.distance_m < 500, (
        f"expected RER/gare within 500m of 80 rue des Héros, got {nearest}"
    )


# ---------------------------------------------------------------------------
# Regression — wired up to IGN gares typename
# ---------------------------------------------------------------------------


async def test_query_uses_ign_gares_typename(httpx_mock: HTTPXMock) -> None:
    """The loader must hit the IGN POI Gares WFS layer."""
    httpx_mock.add_response(
        url=_WFS_LEGACY_URL_RE,
        json={"type": "FeatureCollection", "features": []},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_WFS_GARES_URL_RE,
        json={"type": "FeatureCollection", "features": []},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_OVERPASS_URL_RE, json=_overpass_response([]),
        is_reusable=True,
    )

    await fetch_arrets_around(lat=_LAT, lng=_LNG, radius_m=500, use_cache=False)

    urls = [str(r.url) for r in httpx_mock.get_requests() if "geopf.fr" in str(r.url)]
    assert any("UTILIYANDGOVERNMENTALSERVICES.IGN.POI.GARES" in u for u in urls), urls


# ---------------------------------------------------------------------------
# Sort + mode classification
# ---------------------------------------------------------------------------


async def test_results_sorted_by_distance(httpx_mock: HTTPXMock) -> None:
    """ArretTC are returned by ascending distance."""
    httpx_mock.add_response(
        url=_WFS_LEGACY_URL_RE,
        json={"type": "FeatureCollection", "features": []},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_WFS_GARES_URL_RE,
        json=_ign_gares_response([
            {"nom": "Gare lointaine", "lat": 48.8400, "lng": 2.4860,
             "designations": "gare voyageurs uniquement"},
            {"nom": "Gare proche", "lat": 48.8360, "lng": 2.4815,
             "designations": "gare voyageurs uniquement"},
        ]),
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_OVERPASS_URL_RE, json=_overpass_response([]),
        is_reusable=True,
    )

    arrets = await fetch_arrets_around(
        lat=_LAT, lng=_LNG, radius_m=1_000, use_cache=False,
    )

    rail = [a for a in arrets if a.mode in ("gare", "RER")]
    assert len(rail) >= 2
    distances = [a.distance_m for a in rail if a.distance_m is not None]
    assert distances == sorted(distances)


async def test_overpass_metro_and_bus_are_classified(httpx_mock: HTTPXMock) -> None:
    """Overpass nodes are mapped onto the correct mode taxonomy."""
    httpx_mock.add_response(
        url=_WFS_LEGACY_URL_RE,
        json={"type": "FeatureCollection", "features": []},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_WFS_GARES_URL_RE,
        json={"type": "FeatureCollection", "features": []},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_OVERPASS_URL_RE,
        json=_overpass_response([
            _osm_node(
                lat=48.8358, lng=2.4812, name="Test métro",
                railway="station", subway="yes", operator="RATP", ref="9",
            ),
            _osm_node(
                lat=48.8360, lng=2.4811, name="Test bus",
                highway="bus_stop", operator="RATP", ref="113",
            ),
            _osm_node(
                lat=48.8362, lng=2.4813, name="Test tram",
                railway="tram_stop", operator="IDFM", ref="T1",
            ),
        ]),
        is_reusable=True,
    )

    arrets = await fetch_arrets_around(
        lat=_LAT, lng=_LNG, radius_m=300, use_cache=False,
    )

    modes = {a.mode: a for a in arrets}
    assert "metro" in modes, modes
    assert "bus" in modes, modes
    assert "tram" in modes, modes
    assert modes["bus"].ligne == "113"
    assert modes["tram"].ligne == "T1"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


async def test_all_sources_fail_returns_empty(httpx_mock: HTTPXMock) -> None:
    """All upstream errors must be swallowed (return []), never raise."""
    httpx_mock.add_response(url=_WFS_URL_RE, status_code=503, is_reusable=True)
    httpx_mock.add_response(url=_OVERPASS_URL_RE, status_code=503, is_reusable=True)

    arrets = await fetch_arrets_around(
        lat=_LAT, lng=_LNG, radius_m=500, use_cache=False,
    )
    assert arrets == []
