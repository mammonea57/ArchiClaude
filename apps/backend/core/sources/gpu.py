"""Géoportail de l'Urbanisme (GPU) client via API Carto IGN.

Fetches PLU zones, planning documents, servitudes, and prescriptions.
No API key required.

API documentation: https://apicarto.ign.fr/api/doc/gpu
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from core.http_client import fetch_json

_BASE_URL = "https://apicarto.ign.fr/api/gpu"

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GpuZone:
    """A PLU/PLUi urban planning zone."""

    libelle: str           # e.g. "UB"
    libelong: str | None
    typezone: str          # U, AU, A, N
    partition: str | None
    idurba: str | None
    nomfic: str | None
    urlfic: str | None
    geometry: dict[str, Any] | None


@dataclass(frozen=True)
class GpuDocument:
    """A GPU planning document (PLU, PLUi, POS, CC, RNU)."""

    idurba: str
    typedoc: str           # PLU, PLUi, POS, CC, RNU
    datappro: str | None
    nom: str | None


@dataclass(frozen=True)
class GpuServitude:
    """A planning servitude (SUP — Servitude d'Utilité Publique)."""

    libelle: str
    categorie: str         # AC1, PM1, etc.
    txt: str | None
    geometry: dict[str, Any] | None


@dataclass(frozen=True)
class GpuPrescription:
    """A PLU prescription (surface, linear or point)."""

    libelle: str
    txt: str | None
    typepsc: str | None
    geometry: dict[str, Any] | None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _point_geom(lat: float, lng: float) -> str:
    """Return a JSON-serialised GeoJSON Point for use as the ``geom`` parameter."""
    return json.dumps({"type": "Point", "coordinates": [lng, lat]})


def _geom_or_none(feature: dict[str, Any]) -> dict[str, Any] | None:
    geom = feature.get("geometry")
    return geom if geom else None


# ---------------------------------------------------------------------------
# Public async functions
# ---------------------------------------------------------------------------


async def fetch_zones_at_point(*, lat: float, lng: float) -> list[GpuZone]:
    """Return all PLU zones that contain the given WGS84 point.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        List of :class:`GpuZone`. Empty list when no zones are found.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    params: dict[str, str | int | float] = {"geom": _point_geom(lat, lng)}
    data = await fetch_json(f"{_BASE_URL}/zone-urba", params=params)
    results: list[GpuZone] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        results.append(
            GpuZone(
                libelle=props.get("libelle", ""),
                libelong=props.get("libelong"),
                typezone=props.get("typezone", ""),
                partition=props.get("partition"),
                idurba=props.get("idurba"),
                nomfic=props.get("nomfic"),
                urlfic=props.get("urlfic"),
                geometry=_geom_or_none(feature),
            )
        )
    return results


async def fetch_document(*, lat: float, lng: float) -> list[GpuDocument]:
    """Return the planning document(s) applicable at the given WGS84 point.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        List of :class:`GpuDocument`. Empty list when no document is found.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    params: dict[str, str | int | float] = {"geom": _point_geom(lat, lng)}
    data = await fetch_json(f"{_BASE_URL}/document", params=params)
    results: list[GpuDocument] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        results.append(
            GpuDocument(
                idurba=props.get("idurba", ""),
                typedoc=props.get("typedoc", ""),
                datappro=props.get("datappro"),
                nom=props.get("nom"),
            )
        )
    return results


async def fetch_servitudes_at_point(*, lat: float, lng: float) -> list[GpuServitude]:
    """Return all SUP servitudes at the given WGS84 point.

    Queries the three geometry-type endpoints (surface, linear, point) and
    aggregates results. Each endpoint is wrapped in a try/except to enable
    graceful degradation if one fails.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        Aggregated list of :class:`GpuServitude` from all three endpoints.
    """
    endpoints = ["assiette-sup-s", "assiette-sup-l", "assiette-sup-p"]
    params: dict[str, str | int | float] = {"geom": _point_geom(lat, lng)}
    results: list[GpuServitude] = []

    for endpoint in endpoints:
        try:
            data = await fetch_json(f"{_BASE_URL}/{endpoint}", params=params)
            for feature in data.get("features", []):
                props = feature.get("properties", {})
                results.append(
                    GpuServitude(
                        libelle=props.get("libelle", ""),
                        categorie=props.get("categorie", ""),
                        txt=props.get("txt"),
                        geometry=_geom_or_none(feature),
                    )
                )
        except Exception:
            _logger.warning("GPU servitude endpoint %s unavailable — skipping", endpoint, exc_info=True)

    return results


async def fetch_prescriptions_at_point(*, lat: float, lng: float) -> list[GpuPrescription]:
    """Return all PLU prescriptions at the given WGS84 point.

    Queries the three geometry-type endpoints (surface, linear, point) and
    aggregates results. Each endpoint is wrapped in a try/except to enable
    graceful degradation if one fails.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        Aggregated list of :class:`GpuPrescription` from all three endpoints.
    """
    endpoints = ["prescription-surf", "prescription-lin", "prescription-pct"]
    params: dict[str, str | int | float] = {"geom": _point_geom(lat, lng)}
    results: list[GpuPrescription] = []

    for endpoint in endpoints:
        try:
            data = await fetch_json(f"{_BASE_URL}/{endpoint}", params=params)
            for feature in data.get("features", []):
                props = feature.get("properties", {})
                results.append(
                    GpuPrescription(
                        libelle=props.get("libelle", ""),
                        txt=props.get("txt"),
                        typepsc=props.get("typepsc"),
                        geometry=_geom_or_none(feature),
                    )
                )
        except Exception:
            _logger.warning(
                "GPU prescription endpoint %s unavailable — skipping", endpoint, exc_info=True
            )

    return results
