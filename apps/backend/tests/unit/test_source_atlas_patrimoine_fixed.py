"""Regression tests for the 2026-06 schema migration of Atlas Patrimoine.

These tests verify the bug-fix that switched the ODSQL ``where`` clause
from the obsolete ``in_distance(geo_point_2d, ...)`` to the working
``within_distance(coordonnees_au_format_wgs84, ...)``. HTTP calls are
intercepted by pytest-httpx so no network is required.

See the legacy ``test_source_atlas_patrimoine.py`` for happy-path
coverage; this file only adds the regression checks for:

  * the new ODSQL query string used for the ``where`` parameter,
  * parsing the new schema fields
    (``titre_editorial_de_la_notice``, ``typologie_de_la_protection``,
    ``commune_forme_editoriale``, ``reference``,
    ``coordonnees_au_format_wgs84``),
  * graceful fallback to the legacy schema fields, and
  * the ``in_bbox`` clause now referencing ``coordonnees_au_format_wgs84``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from core.sources import atlas_patrimoine as ap

_RECORDS_URL_RE = re.compile(
    r"https://data\.culture\.gouv\.fr/api/explore/v2\.1/catalog/datasets/"
    r"liste-des-immeubles-proteges-au-titre-des-monuments-historiques/records.*"
)

# 80 rue des Héros, Nogent-sur-Marne (approx).
_LAT = 48.83558
_LNG = 2.4810


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _new_schema_record(
    *,
    designation: str,
    reference: str,
    protection: str,
    commune: str,
    lat: float,
    lng: float,
    code_insee: str = "94052",
) -> dict[str, Any]:
    """Build a record matching the **current** (2026) OpenDataSoft schema."""
    return {
        "reference": reference,
        "titre_editorial_de_la_notice": designation,
        "typologie_de_la_protection": protection,
        "commune_forme_editoriale": commune,
        "cog_insee_lors_de_la_protection": [code_insee],
        "departement_en_lettres": ["Val-de-Marne"],
        "adresse_forme_editoriale": "rue des Héros",
        "date_de_la_derniere_mise_a_jour": "2023-07-19",
        "coordonnees_au_format_wgs84": {"lon": lng, "lat": lat},
    }


def _payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_count": len(records), "results": records}


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache_dir = tmp_path / "atlas_patrimoine"
    monkeypatch.setattr(ap, "_CACHE_DIR", cache_dir)
    return cache_dir


# ---------------------------------------------------------------------------
# Regression — ODSQL clause uses ``within_distance`` + new field name
# ---------------------------------------------------------------------------


async def test_query_uses_within_distance_on_new_geo_field(
    httpx_mock: HTTPXMock,
) -> None:
    """The radius search must use ``within_distance(coordonnees_au_format_wgs84, ...)``.

    Regression : the previous query used ``in_distance(geo_point_2d, ...)``
    which the live API now rejects with ODSQLSyntaxError.
    """
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload([]))

    await ap.fetch_mh_around_point(
        lat=_LAT, lng=_LNG, radius_m=500, use_cache=False,
    )

    requests = httpx_mock.get_requests()
    assert requests, "no HTTP request was made"
    qs = str(requests[0].url)
    assert "within_distance" in qs, qs
    assert "coordonnees_au_format_wgs84" in qs, qs
    # The legacy clause must NOT appear anywhere.
    assert "in_distance(geo_point_2d" not in qs, qs
    assert "geo_point_2d" not in qs, qs


async def test_query_bbox_uses_new_geo_field(httpx_mock: HTTPXMock) -> None:
    """``in_bbox`` must reference the new ``coordonnees_au_format_wgs84`` field."""
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload([]))

    await ap.fetch_mh_in_bbox(
        bbox=(2.475, 48.830, 2.490, 48.842), use_cache=False,
    )

    requests = httpx_mock.get_requests()
    assert requests
    qs = str(requests[0].url)
    assert "in_bbox" in qs, qs
    assert "coordonnees_au_format_wgs84" in qs, qs
    assert "geo_point_2d" not in qs, qs


# ---------------------------------------------------------------------------
# Regression — parsing the current (2026) record schema
# ---------------------------------------------------------------------------


async def test_parses_new_schema_record(httpx_mock: HTTPXMock) -> None:
    """Records returned in the 2026 schema are mapped into AtlasPatrimoineFeature."""
    records = [
        _new_schema_record(
            designation="Église Saint-Saturnin",
            reference="PA00079894",
            protection="classé MH",
            commune="Nogent-sur-Marne",
            lat=48.8371655119725,
            lng=2.48751125133793,
        ),
        _new_schema_record(
            designation="Pavillon Baltard",
            reference="PA00079895",
            protection="classé MH",
            commune="Nogent-sur-Marne",
            lat=48.8329059312374,
            lng=2.47523753598777,
        ),
    ]
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload(records))

    features = await ap.fetch_mh_around_point(
        lat=_LAT, lng=_LNG, radius_m=2_000, use_cache=False,
    )

    assert len(features) == 2

    designations = {f.designation for f in features}
    assert "Église Saint-Saturnin" in designations
    assert "Pavillon Baltard" in designations

    by_ref = {f.reference_merimee: f for f in features}
    saturnin = by_ref["PA00079894"]
    assert saturnin.commune == "Nogent-sur-Marne"
    assert saturnin.code_insee == "94052"
    assert saturnin.protection == "classé MH"
    assert saturnin.lat == pytest.approx(48.8371655, abs=1e-5)
    assert saturnin.lng == pytest.approx(2.4875112, abs=1e-5)
    assert saturnin.distance_m is not None and saturnin.distance_m > 0


async def test_legacy_schema_record_still_parses(httpx_mock: HTTPXMock) -> None:
    """Records published in the older schema (``denomination``,
    ``statut_juridique``, ``geo_point_2d``, ...) must still parse so we
    don't break ingestion if the upstream rolls schemas back.
    """
    legacy = {
        "denomination": "Hôtel Coignard",
        "statut_juridique": "inscrit",
        "commune": "Nogent-sur-Marne",
        "code_insee": "94052",
        "departement_en_lettres": "Val-de-Marne",
        "adresse": "rue du Coignard",
        "reference_de_la_notice_merimee": "PA00079925",
        "geo_point_2d": {"lat": 48.8377835874714, "lon": 2.48876852049768},
    }
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload([legacy]))

    features = await ap.fetch_mh_around_point(
        lat=_LAT, lng=_LNG, radius_m=2_000, use_cache=False,
    )

    assert len(features) == 1
    f = features[0]
    assert f.designation == "Hôtel Coignard"
    assert f.protection == "inscrit"
    assert f.reference_merimee == "PA00079925"
    assert f.lat == pytest.approx(48.8377836, abs=1e-5)
