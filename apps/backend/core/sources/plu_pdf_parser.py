"""PLU PDF parser — fetch + cache + structure into urbanism_overlays models.

This source loader chains:

1. **GPU** (``core.sources.gpu``) → resolve the PLU zone *and* PDF URL for
   a given WGS84 point (or BBOX).
2. **PDF download** (``httpx``) with disk cache (``refs/cache/plu_pdf_parser/``,
   30-day TTL) + exponential backoff on transient errors.
3. **Text extraction** via :mod:`core.plu.pdf_fetcher`.
4. **Zone section** via :func:`core.plu.section_finder.find_zone_section`.
5. **Article splitting (1..17)** via :mod:`core.plu.article_parser`.
6. **Pydantic output** — :class:`PLUZonage` + :class:`PLUReglement` instances
   from :mod:`core.urbanism_overlays.schemas`.

Public API
----------

``fetch_plu_overlays(*, lat, lng) -> PLUParseResult``

The function is safe to call on any FR coordinate: on failure it logs and
returns an empty :class:`PLUParseResult` rather than raising.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from core.plu.article_parser import (
    ARTICLE_LABELS,
    parse_articles_numeric,
    split_articles,
)
from core.plu.section_finder import find_zone_section
from core.sources.gpu import fetch_document, fetch_zones_at_point
from core.urbanism_overlays.schemas import PLUReglement, PLUZonage

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------

#: Repo root – three parents up from ``apps/backend/core/sources/``.
_REPO_ROOT = Path(__file__).resolve().parents[4]

#: Default cache directory: ``<repo>/refs/cache/plu_pdf_parser/``.
CACHE_DIR: Path = _REPO_ROOT / "refs" / "cache" / "plu_pdf_parser"

#: TTL = 30 days in seconds.
CACHE_TTL_SECONDS: float = 30 * 24 * 3600.0

_PDF_TIMEOUT = httpx.Timeout(connect=5.0, read=40.0, write=5.0, pool=5.0)

_PDF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ArchiClaude/1.0)",
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Referer": "https://www.geoportail-urbanisme.gouv.fr/",
}

# Exponential backoff parameters
_MAX_RETRIES = 4
_BASE_BACKOFF_S = 0.5
_MAX_BACKOFF_S = 30.0

# Status codes that justify a retry (transient).
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class PLUParseResult:
    """Aggregated outcome of one ``fetch_plu_overlays`` call.

    Both ``zonage`` and ``reglement`` are returned as
    :mod:`core.urbanism_overlays.schemas` instances so the dossier pipeline
    can drop them straight into an :class:`UrbanismOverlayBundle`.
    """

    zonage: PLUZonage | None = None
    reglement: PLUReglement | None = None
    articles: dict[int, str] = field(default_factory=dict)
    pdf_url: str | None = None
    idurba: str | None = None
    sha256: str | None = None
    from_cache: bool = False
    error: str | None = None

    @property
    def features_count(self) -> int:
        """Convenience metric: how many distinct overlays were produced."""
        return sum(1 for x in (self.zonage, self.reglement) if x is not None)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _ensure_cache_dir() -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - best effort
        log.warning("plu_pdf_parser: cannot create cache dir %s — %s", CACHE_DIR, exc)


def _cache_path_for(url: str) -> Path:
    """Return the cache file path for *url* — sha256-hashed to stay portable."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{digest}.pdf"


def _cache_fresh(path: Path) -> bool:
    """True when ``path`` exists and is younger than the TTL."""
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < CACHE_TTL_SECONDS


def _read_cache(path: Path) -> bytes | None:
    if not _cache_fresh(path):
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        log.warning("plu_pdf_parser: cache read failed %s — %s", path, exc)
        return None


def _write_cache(path: Path, data: bytes) -> None:
    _ensure_cache_dir()
    try:
        path.write_bytes(data)
    except OSError as exc:  # pragma: no cover - best effort
        log.warning("plu_pdf_parser: cache write failed %s — %s", path, exc)


# ---------------------------------------------------------------------------
# PDF download with exponential backoff + rate-limit handling
# ---------------------------------------------------------------------------


async def _download_pdf_with_backoff(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bytes | None:
    """Download a PDF with exponential backoff. Returns ``None`` on failure.

    * Retries on ConnectError / ReadTimeout / status codes in
      :data:`_RETRYABLE_STATUS`.
    * Honours ``Retry-After`` on 429/503 when present.
    * Exponential backoff with jitter capped at :data:`_MAX_BACKOFF_S`.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=_PDF_TIMEOUT, headers=_PDF_HEADERS)

    assert client is not None  # for type-checker
    try:
        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.get(url)
                status = response.status_code
                if 200 <= status < 300:
                    if "text/html" in response.headers.get("content-type", ""):
                        log.warning("plu_pdf_parser: HTML instead of PDF at %s", url)
                        return None
                    return response.content
                if status in _RETRYABLE_STATUS:
                    sleep_s = _retry_after_or_backoff(response, attempt)
                    log.info(
                        "plu_pdf_parser: HTTP %d on %s — retry in %.1fs (attempt %d/%d)",
                        status, url, sleep_s, attempt + 1, _MAX_RETRIES,
                    )
                    await asyncio.sleep(sleep_s)
                    continue
                log.warning("plu_pdf_parser: HTTP %d on %s — giving up", status, url)
                return None
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                sleep_s = _backoff_delay(attempt)
                log.info(
                    "plu_pdf_parser: transport error on %s (%s) — retry in %.1fs (attempt %d/%d)",
                    url, exc, sleep_s, attempt + 1, _MAX_RETRIES,
                )
                await asyncio.sleep(sleep_s)
            except httpx.HTTPError as exc:
                log.warning("plu_pdf_parser: HTTP error on %s — %s", url, exc)
                return None
        log.warning("plu_pdf_parser: max retries exhausted for %s", url)
        return None
    finally:
        if own_client:
            await client.aclose()


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter."""
    base = _BASE_BACKOFF_S * (2**attempt)
    capped = min(base, _MAX_BACKOFF_S)
    return capped * (0.5 + random.random())


def _retry_after_or_backoff(response: httpx.Response, attempt: int) -> float:
    raw = response.headers.get("retry-after")
    if raw:
        try:
            return min(float(raw), _MAX_BACKOFF_S)
        except ValueError:
            pass
    return _backoff_delay(attempt)


# ---------------------------------------------------------------------------
# PDF text extraction (kept local to avoid hard dep on pdfplumber import-time)
# ---------------------------------------------------------------------------


def _extract_text(pdf_bytes: bytes) -> str | None:
    try:
        import pdfplumber  # local import — heavy dependency
    except ImportError:  # pragma: no cover
        log.warning("plu_pdf_parser: pdfplumber not installed — cannot parse")
        return None

    try:
        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n\n".join(pages)
    except Exception as exc:
        log.warning("plu_pdf_parser: pdfplumber extraction failed — %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_plu_overlays(
    *,
    lat: float | None = None,
    lng: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    client: httpx.AsyncClient | None = None,
) -> PLUParseResult:
    """Fetch the PLU PDF for a point (or BBOX centroid) and structure it.

    Args:
        lat: WGS84 latitude — required when ``bbox`` is not given.
        lng: WGS84 longitude — required when ``bbox`` is not given.
        bbox: ``(west, south, east, north)`` in WGS84. The centroid is used
            to query GPU.
        client: Optional pre-configured httpx client (mainly for tests).

    Returns:
        :class:`PLUParseResult` — always returned; check ``error`` and
        ``features_count`` to know whether anything was parsed.
    """
    point = _coords(lat=lat, lng=lng, bbox=bbox)
    if point is None:
        return PLUParseResult(error="invalid_coordinates")
    plat, plng = point

    # 1. Resolve zone + planning document via GPU
    try:
        zones, documents = await asyncio.gather(
            fetch_zones_at_point(lat=plat, lng=plng),
            fetch_document(lat=plat, lng=plng),
            return_exceptions=False,
        )
    except Exception as exc:
        log.warning("plu_pdf_parser: GPU query failed for (%s,%s) — %s", plat, plng, exc)
        return PLUParseResult(error=f"gpu_unreachable: {exc!s}")

    if not zones:
        log.info("plu_pdf_parser: no PLU zone at (%s,%s)", plat, plng)
        return PLUParseResult(error="no_zone")

    zone = zones[0]
    pdf_url = zone.urlfic
    idurba = zone.idurba or (documents[0].idurba if documents else None)

    # Build a baseline PLUZonage immediately so the caller always gets some
    # structured information (even when the PDF is unreachable).
    zonage = PLUZonage(
        applies=True,
        zone_code=(zone.libelle or "").upper(),
        source_url=pdf_url,
        last_updated=date.today(),
        geometry_geojson=zone.geometry,
        notes=[zone.libelong] if zone.libelong else [],
    )

    if not pdf_url:
        log.info("plu_pdf_parser: zone %s has no PDF URL", zonage.zone_code)
        return PLUParseResult(
            zonage=zonage,
            idurba=idurba,
            error="no_pdf_url",
        )

    # 2. Download (cache → network)
    cache_path = _cache_path_for(pdf_url)
    pdf_bytes = _read_cache(cache_path)
    from_cache = pdf_bytes is not None

    if pdf_bytes is None:
        pdf_bytes = await _download_pdf_with_backoff(pdf_url, client=client)
        if pdf_bytes is None:
            return PLUParseResult(
                zonage=zonage, pdf_url=pdf_url, idurba=idurba, error="pdf_download_failed"
            )
        if len(pdf_bytes) >= 1000:
            _write_cache(cache_path, pdf_bytes)

    if len(pdf_bytes) < 1000:
        return PLUParseResult(
            zonage=zonage, pdf_url=pdf_url, idurba=idurba, error="pdf_too_small"
        )

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    # 3. Text extraction
    text = _extract_text(pdf_bytes)
    if not text or len(text.strip()) < 100:
        return PLUParseResult(
            zonage=zonage,
            pdf_url=pdf_url,
            idurba=idurba,
            sha256=sha256,
            from_cache=from_cache,
            error="pdf_text_too_short",
        )

    # 4. Zone section
    zone_section = find_zone_section(text, zonage.zone_code) or text

    # 5. Article split (1..17)
    articles = split_articles(zone_section, zone_code=zonage.zone_code)

    # 6. Numeric extraction → PLUReglement
    numeric = parse_articles_numeric(articles)
    reglement = PLUReglement(
        applies=True,
        source_url=pdf_url,
        last_updated=date.today(),
        hauteur_max_m=numeric["hauteur_max_m"],
        emprise_max_pct=numeric["emprise_max_pct"],
        retrait_voirie_min_m=numeric["retrait_voirie_min_m"],
        retrait_lateral_min_m=numeric["retrait_lateral_min_m"],
        pleine_terre_min_pct=numeric["pleine_terre_min_pct"],
        stationnement_par_logement=numeric["stationnement_par_logement"],
        notes=_article_notes(articles),
    )

    return PLUParseResult(
        zonage=zonage,
        reglement=reglement,
        articles=articles,
        pdf_url=pdf_url,
        idurba=idurba,
        sha256=sha256,
        from_cache=from_cache,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coords(
    *,
    lat: float | None,
    lng: float | None,
    bbox: tuple[float, float, float, float] | None,
) -> tuple[float, float] | None:
    if lat is not None and lng is not None:
        if not _valid_latlng(lat, lng):
            return None
        return (lat, lng)
    if bbox is not None and len(bbox) == 4:
        w, s, e, n = bbox
        clat = (s + n) / 2
        clng = (w + e) / 2
        if not _valid_latlng(clat, clng):
            return None
        return (clat, clng)
    return None


def _valid_latlng(lat: float, lng: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0


def _article_notes(articles: dict[int, str]) -> list[str]:
    """Build a compact FR list of articles found in the zone section."""
    notes: list[str] = []
    for num in sorted(articles):
        label = ARTICLE_LABELS.get(num, "")
        head = _first_meaningful_line(articles[num])
        if head:
            notes.append(f"Art. {num} — {label} : {head[:120]}")
        else:
            notes.append(f"Art. {num} — {label}")
    return notes


_HEADER_LINE_RE = re.compile(r"^\s*ARTICLE\s+", re.IGNORECASE)


def _first_meaningful_line(text: str) -> str:
    for raw_line in text.splitlines()[1:]:
        line = raw_line.strip()
        if not line or _HEADER_LINE_RE.match(line):
            continue
        return line
    return ""


__all__ = [
    "CACHE_DIR",
    "CACHE_TTL_SECONDS",
    "PLUParseResult",
    "fetch_plu_overlays",
]


# ---------------------------------------------------------------------------
# Module-level helper for ad-hoc usage from a script
# ---------------------------------------------------------------------------


def _summarise(result: PLUParseResult) -> dict[str, Any]:
    """Return a small dict useful for logging / CLI demo."""
    return {
        "features_count": result.features_count,
        "zone_code": result.zonage.zone_code if result.zonage else None,
        "pdf_url": result.pdf_url,
        "from_cache": result.from_cache,
        "articles_found": sorted(result.articles.keys()),
        "hauteur_max_m": result.reglement.hauteur_max_m if result.reglement else None,
        "emprise_max_pct": (
            result.reglement.emprise_max_pct if result.reglement else None
        ),
        "error": result.error,
    }
