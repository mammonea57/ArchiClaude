"""INSEE SRU (Solidarité et Renouvellement Urbain) commune status client.

Data source: ``data.gouv.fr`` dataset *"Communes et inventaire SRU"*
(``6564969d3579e21795ebd378``). Published yearly by the Direction
de l'Habitat, de l'Urbanisme et des Paysages (DHUP) — see
https://www.data.gouv.fr/datasets/communes-et-inventaire-sru/.

No API key required.

The SRU law (loi SRU, art. L.302-5 CCH) requires communes above a
population/EPCI threshold to maintain 20% or 25% social housing
(logements locatifs sociaux — LLS). Non-compliant communes face
financial penalties (``carence``, ``rattrapage``).

Implementation notes
--------------------
The historic dataset URL ``5e6e951806e3e779d36e40b8`` returns HTTP 404
since the 2025 bilan reorganisation. We now consume the canonical
yearly CSV located at
``static.data.gouv.fr/resources/communes-et-inventaire-sru/...``.
The latest resource URL is discovered dynamically from the dataset
metadata; an explicit override is available via the ``dataset_id``
argument so the loader can be pinned in tests / CI.

The CSV is served as Windows-1252 (CRLF, ``;`` separator). Both the
header set and the column wording change every year, so the loader
matches columns by tolerant substring patterns.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from core.http_client import fetch_json, get_http_client

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical "Communes et inventaire SRU" dataset on data.gouv.fr
# (Direction de l'Habitat, de l'Urbanisme et des Paysages — DHUP, MTECT).
_DATASET_ID = "6564969d3579e21795ebd378"
_DATASET_URL = f"https://www.data.gouv.fr/api/1/datasets/{_DATASET_ID}/"

# Cache lives alongside other source caches.
_DEFAULT_CACHE_DIR = (
    Path(__file__).resolve().parents[4] / "refs" / "cache" / "insee_sru"
)
_DEFAULT_CACHE_TTL_S = 30 * 24 * 3600  # 30 days


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommuneSRU:
    """SRU obligation status for a French commune.

    Fields mirror the canonical *"Communes et inventaire SRU"* schema and
    are stable across yearly bilans (taxonomy frozen by DHUP).
    """

    code_insee: str
    nom_commune: str | None = None
    population: int | None = None
    # SRU obligation
    commune_sru: bool = False            # subject to SRU article L.302-5
    commune_carencee: bool = False       # carencée (deficit + penalty + arrêté)
    commune_deficitaire: bool = False    # below quota but not yet carencée
    commune_exemptee: bool = False       # exemption decree
    taux_lls: float | None = None        # current social housing rate (% main residences)
    taux_cible: float | None = None      # 20.0 or 25.0
    penalite_eur: float | None = None    # annual penalty in EUR
    statut: str = "non_soumise"          # derived: carencee / deficitaire / conforme / non_soumise / exemptee
    bilan_annee: int | None = None
    last_update: str | None = None       # ISO-8601 from data.gouv.fr meta


# ---------------------------------------------------------------------------
# Local disk cache
# ---------------------------------------------------------------------------


def _cache_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _read_cached_csv(cache_dir: Path, url: str, ttl_seconds: int) -> bytes | None:
    path = cache_dir / f"{_cache_key(url)}.csv"
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > ttl_seconds:
            return None
        return path.read_bytes()
    except OSError:  # pragma: no cover — defensive
        return None


def _write_cached_csv(cache_dir: Path, url: str, payload: bytes) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{_cache_key(url)}.csv"
        tmp = path.with_suffix(".csv.tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)
    except OSError as exc:  # pragma: no cover
        _logger.warning("SRU: CSV cache write failed (%s) — continuing", exc)


# ---------------------------------------------------------------------------
# Resource discovery
# ---------------------------------------------------------------------------


_CSV_YEAR_RE = re.compile(r"(20\d{2})")


def _pick_latest_csv_resource(dataset_meta: dict[str, Any]) -> tuple[str, int] | None:
    """Pick the most recent ``donnees-sru-*.csv`` resource URL + year.

    Falls back to the first CSV resource if none of the titles match the
    ``donnees-sru-...-YYYY`` pattern (CI safety).
    """
    candidates: list[tuple[int, str]] = []
    fallback: str | None = None

    for resource in dataset_meta.get("resources", []):
        fmt = (resource.get("format") or "").lower()
        title = (resource.get("title") or "").lower()
        url = resource.get("url")
        if not url or fmt != "csv":
            continue
        if fallback is None:
            fallback = url
        if "donnees-sru" not in title and "communes-sru" not in title:
            continue
        match = _CSV_YEAR_RE.search(title)
        if match:
            candidates.append((int(match.group(1)), url))

    if candidates:
        candidates.sort(reverse=True)
        year, url = candidates[0]
        return url, year
    if fallback:
        return fallback, 0
    return None


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def _decode_csv(payload: bytes) -> str:
    """Decode the DHUP CSV (CP1252 → fallback UTF-8 → latin-1)."""
    for enc in ("cp1252", "utf-8", "latin-1"):
        try:
            return payload.decode(enc)
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="replace")  # pragma: no cover


def _norm(s: str) -> str:
    """Lowercase + ASCII-fold + strip non-alnum (header matching)."""
    s = s.lower()
    # poor-man's accent fold without external deps. Source = 31 chars,
    # destination = 31 chars (one replacement per source character).
    table = str.maketrans(
        "àáâãäåçèéêëìíîïñòóôõöùúûüýÿœæ’'",
        "aaaaaaceeeeiiiinooooouuuuyyoe  ",
    )
    s = s.translate(table)
    return re.sub(r"[^a-z0-9]+", "", s)


def _find_col(headers: list[str], *needles: str) -> str | None:
    """Return the original header whose normalised form contains every needle."""
    normed = {h: _norm(h) for h in headers}
    target = [_norm(n) for n in needles]
    for h, n in normed.items():
        if all(t in n for t in target):
            return h
    return None


def _parse_percent(raw: str | None) -> float | None:
    if raw is None or raw == "":
        return None
    s = str(raw).strip().replace("%", "").replace(",", ".").replace(" ", "")
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_eur(raw: str | None) -> float | None:
    if raw is None or raw == "":
        return None
    s = str(raw)
    # strip currency, NBSP, thin space, and FR thousands sep
    s = s.replace("€", "").replace(" ", "").replace(" ", "")
    s = s.replace(" ", "").replace(",", ".")
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    s = str(raw).strip().lower()
    return s in {"1", "true", "vrai", "oui", "o", "yes", "y"}


def _parse_int(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).replace(" ", "").replace(" ", ""))
    except ValueError:
        return None


def _row_to_status(row: dict[str, str], headers: list[str]) -> dict[str, Any]:
    """Translate a CSV row to keyword args for :class:`CommuneSRU`."""
    col_insee = _find_col(headers, "code", "insee") or _find_col(headers, "codecommune")
    col_nom = _find_col(headers, "nom", "commune")
    col_pop = _find_col(headers, "population")
    col_sru = _find_col(headers, "commune", "sru") or _find_col(headers, "soumise", "sru")
    col_def = _find_col(headers, "deficitaire")
    col_car = _find_col(headers, "carencee") or _find_col(headers, "carence")
    col_exempt = _find_col(headers, "exempt")
    col_taux = _find_col(headers, "taux", "sru") or _find_col(headers, "taux", "lls")
    col_cible = _find_col(headers, "taux", "cible") or _find_col(headers, "objectif")
    col_pen = _find_col(headers, "prelevement") or _find_col(headers, "penalite")

    return {
        "code_insee": (row.get(col_insee, "") or "").strip().zfill(5) if col_insee else "",
        "nom_commune": (row.get(col_nom) or None) if col_nom else None,
        "population": _parse_int(row.get(col_pop)) if col_pop else None,
        "commune_sru": _truthy(row.get(col_sru)) if col_sru else False,
        "commune_deficitaire": _truthy(row.get(col_def)) if col_def else False,
        "commune_carencee": _truthy(row.get(col_car)) if col_car else False,
        "commune_exemptee": _truthy(row.get(col_exempt)) if col_exempt else False,
        "taux_lls": _parse_percent(row.get(col_taux)) if col_taux else None,
        "taux_cible": _parse_percent(row.get(col_cible)) if col_cible else None,
        "penalite_eur": _parse_eur(row.get(col_pen)) if col_pen else None,
    }


def _derive_statut(kwargs: dict[str, Any]) -> str:
    if kwargs.get("commune_exemptee"):
        return "exemptee"
    if kwargs.get("commune_carencee"):
        return "carencee"
    if kwargs.get("commune_deficitaire"):
        return "rattrapage"
    if kwargs.get("commune_sru"):
        return "conforme"
    return "non_soumise"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def _download_csv(url: str) -> bytes | None:
    """Download a CSV resource as bytes, returning ``None`` on failure."""
    client = get_http_client()
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        _logger.warning("SRU CSV fetch failed (%s) — returning None", exc)
        return None


async def fetch_sru_commune(
    *,
    code_insee: str,
    cache_dir: Path | None = None,
    ttl_seconds: int = _DEFAULT_CACHE_TTL_S,
    use_cache: bool = True,
    dataset_url: str | None = None,
) -> CommuneSRU | None:
    """Fetch SRU status for *code_insee*.

    Steps:
        1. Lookup dataset metadata on data.gouv.fr.
        2. Pick the most recent ``donnees-sru-...-YYYY.csv`` resource.
        3. Download (or cache hit) the CSV.
        4. Locate the row for *code_insee* and translate fields.

    Args:
        code_insee: 5-digit INSEE municipality code.
        cache_dir: Override the default ``refs/cache/insee_sru/`` directory.
        ttl_seconds: Cache TTL (default 30 days).
        use_cache: Disable to bypass disk cache (e.g. in tests).
        dataset_url: Override the dataset metadata URL (useful for unit tests).

    Returns:
        :class:`CommuneSRU` when the commune is found.
        ``None`` when:
          * the dataset metadata or resource cannot be fetched, or
          * the CSV is malformed, or
          * the commune is not present in the published inventory.
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    code_insee = code_insee.strip().zfill(5)

    # 1) Dataset metadata
    try:
        dataset_meta = await fetch_json(dataset_url or _DATASET_URL)
    except Exception:
        _logger.warning("SRU dataset metadata lookup failed — returning None", exc_info=True)
        return None

    picked = _pick_latest_csv_resource(dataset_meta)
    if picked is None:
        _logger.warning("No SRU CSV resource discovered — returning None")
        return None
    resource_url, year = picked
    last_update = dataset_meta.get("last_update")

    # 2) CSV bytes (cache → network)
    payload: bytes | None = None
    if use_cache:
        payload = _read_cached_csv(cache_dir, resource_url, ttl_seconds)
    if payload is None:
        payload = await _download_csv(resource_url)
        if payload is None:
            return None
        if use_cache:
            _write_cached_csv(cache_dir, resource_url, payload)

    text = _decode_csv(payload)

    # 3) Sniff delimiter (FR uses ';' but the file shape may evolve)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = list(reader.fieldnames or [])
    if not headers:
        _logger.warning("SRU CSV has no headers — returning None")
        return None

    col_insee = _find_col(headers, "code", "insee") or _find_col(headers, "codecommune")
    if not col_insee:
        _logger.warning("SRU CSV: no INSEE code column found in %s", headers)
        return None

    for row in reader:
        row_code = (row.get(col_insee) or "").strip().zfill(5)
        if row_code != code_insee:
            continue
        kwargs = _row_to_status(row, headers)
        kwargs["statut"] = _derive_statut(kwargs)
        kwargs["bilan_annee"] = year or None
        kwargs["last_update"] = last_update
        kwargs["code_insee"] = code_insee  # canonical zero-padded
        try:
            return CommuneSRU(**kwargs)
        except (TypeError, ValueError):
            _logger.warning("SRU row for %s could not be parsed", code_insee, exc_info=True)
            return None

    return None


__all__ = [
    "CommuneSRU",
    "fetch_sru_commune",
]
