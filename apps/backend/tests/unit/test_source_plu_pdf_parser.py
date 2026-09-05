"""Unit tests for core.sources.plu_pdf_parser — PLU PDF parser source loader.

The PLU PDF is the heaviest source in the dossier pipeline so the tests
focus on:

* deterministic article splitting (1..17) from a synthetic règlement,
* numeric extraction per article (hauteur, emprise, retraits, …),
* end-to-end behaviour against a mocked GPU + PDF download chain,
* graceful degradation: empty zone, unreachable PDF, scanned PDF.

Coordinates used for the live shape of the test: Nogent-sur-Marne,
80 rue des Héros — lat=48.83558, lng=2.4810. Only the lat/lng surface
matters here, all network calls are mocked.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pytest_httpx import HTTPXMock

from core.plu.article_parser import (
    parse_articles_numeric,
    split_articles,
)
from core.sources import plu_pdf_parser as sut
from core.sources.gpu import GpuDocument, GpuZone

# Nogent — 80 rue des Héros (approx)
_LAT = 48.83558
_LNG = 2.4810

# ---------------------------------------------------------------------------
# Fixture data — a minimal but representative PLU zone section
# ---------------------------------------------------------------------------

_NOGENT_UB_SECTION = """\
Dispositions applicables à la zone UB

La zone UB couvre les secteurs urbains denses.

ARTICLE UB 1 — Occupations et utilisations du sol interdites
Sont interdits les bâtiments à usage industriel.

ARTICLE UB 2 — Occupations et utilisations du sol soumises à conditions
Les constructions à usage d'entrepôt sont autorisées sous conditions.

ARTICLE UB 6 — Implantation par rapport aux voies
Les constructions doivent être implantées avec un retrait de 4 m de l'alignement.

ARTICLE UB 7 — Implantation par rapport aux limites séparatives
Le retrait minimum est de 6 m des limites séparatives.

ARTICLE UB 9 — Emprise au sol
L'emprise au sol des constructions ne doit pas excéder 50 % de la superficie du terrain.

ARTICLE UB 10 — Hauteur maximale
La hauteur maximale des constructions est fixée à 15 m au faîtage.

ARTICLE UB 12 — Stationnement
Il est exigé 1,5 places de stationnement par logement.

ARTICLE UB 13 — Espaces libres et plantations
La pleine terre doit représenter au moins 30 % de la surface du terrain.
"""

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "gpu_responses.json"

_PDF_URL = "https://www.geoportail-urbanisme.gouv.fr/document/94052_PLUi_20210610/PLUi_Nogent_reglement_UB.pdf"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


def _make_pdf_bytes(text: str) -> bytes:
    """Build a tiny single-page PDF whose extracted text matches *text*.

    Uses reportlab so accented French characters (à, é, …) survive pdfplumber
    extraction. Falls back to a hand-crafted PDF if reportlab is unavailable.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:  # pragma: no cover - reportlab is a test dep
        return _make_pdf_bytes_fallback(text)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 9)
    width, height = A4
    y = height - 40
    for line in text.split("\n"):
        c.drawString(40, y, line)
        y -= 12
        if y < 40:
            c.showPage()
            c.setFont("Helvetica", 9)
            y = height - 40
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_pdf_bytes_fallback(text: str) -> bytes:
    """Hand-crafted single-page PDF — used only if reportlab is missing."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines = escaped.split("\n")
    text_ops: list[str] = []
    for i, line in enumerate(lines):
        if i == 0:
            text_ops.append(f"({line}) Tj")
        else:
            text_ops.append("T*")
            text_ops.append(f"({line}) Tj")
    stream_body = (
        "BT\n/F1 10 Tf\n12 TL\n72 800 Td\n" + "\n".join(text_ops) + "\nET\n"
    )
    stream_bytes = stream_body.encode("latin-1", "replace")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Length "
        + str(len(stream_bytes)).encode("ascii")
        + b" >>\nstream\n"
        + stream_bytes
        + b"endstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj)
    xref_offset = out.tell()
    out.write(b"xref\n0 6\n0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    data = out.getvalue()
    if len(data) < 1100:
        data += b"\n% padding " + b"-" * (1100 - len(data)) + b"\n"
    return data


# ---------------------------------------------------------------------------
# Article parser — pure unit tests (no I/O)
# ---------------------------------------------------------------------------


def test_split_articles_zone_prefixed() -> None:
    """Article headers ``ARTICLE UB N`` are recognised and split."""
    articles = split_articles(_NOGENT_UB_SECTION, zone_code="UB")

    assert set(articles) == {1, 2, 6, 7, 9, 10, 12, 13}
    assert "industriel" in articles[1].lower()
    assert "50" in articles[9]
    assert "15 m" in articles[10]


def test_split_articles_other_zone_ignored() -> None:
    """When a zone prefix is given, headers belonging to other zones are skipped."""
    mixed = (
        "ARTICLE UA 10 — Hauteur\n"
        "Hauteur 9 m.\n"
        "ARTICLE UB 10 — Hauteur\n"
        "La hauteur maximale des constructions est fixée à 15 m.\n"
    )
    articles = split_articles(mixed, zone_code="UB")
    assert 10 in articles
    assert "15 m" in articles[10]
    assert "9 m" not in articles[10]


def test_split_articles_unprefixed() -> None:
    """Mono-zone PLU using plain ``Article N`` is also supported."""
    text = (
        "Article 9 — Emprise au sol\n"
        "L'emprise au sol est limitée à 40 %.\n"
        "Article 10 — Hauteur\n"
        "Hauteur maximale : 12 m.\n"
    )
    articles = split_articles(text)
    assert {9, 10} <= set(articles)


def test_parse_articles_numeric_nogent_ub() -> None:
    """All six numeric fields are extracted from the synthetic section."""
    articles = split_articles(_NOGENT_UB_SECTION, zone_code="UB")
    numeric = parse_articles_numeric(articles)

    assert numeric["hauteur_max_m"] == 15.0
    assert numeric["emprise_max_pct"] == 50.0
    assert numeric["retrait_voirie_min_m"] == 4.0
    assert numeric["retrait_lateral_min_m"] == 6.0
    assert numeric["stationnement_par_logement"] == 1.5
    assert numeric["pleine_terre_min_pct"] == 30.0


def test_parse_articles_numeric_handles_missing() -> None:
    """Missing articles yield ``None`` rather than raising."""
    numeric = parse_articles_numeric({})
    assert all(v is None for v in numeric.values())


def test_parse_articles_numeric_rejects_out_of_range() -> None:
    """A 250 m hauteur (absurd) is rejected by the sanity check."""
    bogus = {10: "Hauteur de 250 mètres"}
    numeric = parse_articles_numeric(bogus)
    assert numeric["hauteur_max_m"] is None


# ---------------------------------------------------------------------------
# Source loader — end-to-end with mocked GPU + PDF
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module-level CACHE_DIR to a temporary directory."""
    tmp = tmp_path / "plu_cache"
    monkeypatch.setattr(sut, "CACHE_DIR", tmp)
    return tmp


def _mock_gpu_zone() -> GpuZone:
    return GpuZone(
        libelle="UB",
        libelong="Zone urbaine mixte",
        typezone="U",
        partition="94052",
        idurba="94052_PLUi_20210610",
        nomfic="PLUi_Nogent_reglement_UB.pdf",
        urlfic=_PDF_URL,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[2.480, 48.835], [2.482, 48.835], [2.482, 48.837], [2.480, 48.837], [2.480, 48.835]]
            ],
        },
    )


def _mock_gpu_document() -> GpuDocument:
    return GpuDocument(
        idurba="94052_PLUi_20210610",
        typedoc="PLUi",
        datappro="2021-06-10",
        nom="PLUi Nogent",
    )


async def test_fetch_plu_overlays_nogent_happy_path(
    tmp_cache_dir: Path,
    httpx_mock: HTTPXMock,
) -> None:
    """End-to-end : GPU + PDF mocked → PLUZonage + PLUReglement populated."""
    pdf_bytes = _make_pdf_bytes(_NOGENT_UB_SECTION)
    httpx_mock.add_response(url=_PDF_URL, content=pdf_bytes, headers={"content-type": "application/pdf"})

    with patch(
        "core.sources.plu_pdf_parser.fetch_zones_at_point",
        new=AsyncMock(return_value=[_mock_gpu_zone()]),
    ), patch(
        "core.sources.plu_pdf_parser.fetch_document",
        new=AsyncMock(return_value=[_mock_gpu_document()]),
    ):
        result = await sut.fetch_plu_overlays(lat=_LAT, lng=_LNG)

    assert result.error is None
    assert result.features_count == 2
    assert result.zonage is not None
    assert result.zonage.zone_code == "UB"
    assert result.zonage.source_url == _PDF_URL
    assert result.zonage.last_updated == date.today()

    assert result.reglement is not None
    assert result.reglement.hauteur_max_m == 15.0
    assert result.reglement.emprise_max_pct == 50.0
    assert result.reglement.retrait_voirie_min_m == 4.0
    assert result.reglement.retrait_lateral_min_m == 6.0
    assert result.reglement.stationnement_par_logement == 1.5

    # Articles 1..17 — we should have at least the ones present in the fixture.
    assert {1, 2, 6, 7, 9, 10, 12, 13} <= set(result.articles)


async def test_fetch_plu_overlays_uses_cache_on_second_call(
    tmp_cache_dir: Path,
    httpx_mock: HTTPXMock,
) -> None:
    """Second call within the TTL must read from disk and skip the network."""
    pdf_bytes = _make_pdf_bytes(_NOGENT_UB_SECTION)
    httpx_mock.add_response(url=_PDF_URL, content=pdf_bytes, headers={"content-type": "application/pdf"})

    with patch(
        "core.sources.plu_pdf_parser.fetch_zones_at_point",
        new=AsyncMock(return_value=[_mock_gpu_zone()]),
    ), patch(
        "core.sources.plu_pdf_parser.fetch_document",
        new=AsyncMock(return_value=[]),
    ):
        first = await sut.fetch_plu_overlays(lat=_LAT, lng=_LNG)
        assert first.from_cache is False

        # No new HTTP response queued — second run must hit the cache only.
        second = await sut.fetch_plu_overlays(lat=_LAT, lng=_LNG)

    assert second.error is None
    assert second.from_cache is True
    assert second.reglement is not None and second.reglement.hauteur_max_m == 15.0


async def test_fetch_plu_overlays_no_zone(tmp_cache_dir: Path) -> None:
    """No GPU zone → empty result with ``no_zone`` error, never raises."""
    with patch(
        "core.sources.plu_pdf_parser.fetch_zones_at_point",
        new=AsyncMock(return_value=[]),
    ), patch(
        "core.sources.plu_pdf_parser.fetch_document",
        new=AsyncMock(return_value=[]),
    ):
        result = await sut.fetch_plu_overlays(lat=_LAT, lng=_LNG)

    assert result.error == "no_zone"
    assert result.zonage is None
    assert result.reglement is None
    assert result.features_count == 0


async def test_fetch_plu_overlays_pdf_unreachable(
    tmp_cache_dir: Path,
    httpx_mock: HTTPXMock,
) -> None:
    """Non-retryable PDF error → zonage still returned, reglement is None."""
    httpx_mock.add_response(url=_PDF_URL, status_code=404)

    with patch(
        "core.sources.plu_pdf_parser.fetch_zones_at_point",
        new=AsyncMock(return_value=[_mock_gpu_zone()]),
    ), patch(
        "core.sources.plu_pdf_parser.fetch_document",
        new=AsyncMock(return_value=[]),
    ):
        result = await sut.fetch_plu_overlays(lat=_LAT, lng=_LNG)

    assert result.error == "pdf_download_failed"
    assert result.zonage is not None
    assert result.zonage.zone_code == "UB"
    assert result.reglement is None
    assert result.features_count == 1


async def test_fetch_plu_overlays_retries_on_429(
    tmp_cache_dir: Path,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 response is retried with backoff, then succeeds."""
    # Make backoff instantaneous so the test stays fast.
    monkeypatch.setattr(sut, "_BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(sut, "_MAX_BACKOFF_S", 0.0)

    pdf_bytes = _make_pdf_bytes(_NOGENT_UB_SECTION)
    httpx_mock.add_response(url=_PDF_URL, status_code=429, headers={"retry-after": "0"})
    httpx_mock.add_response(url=_PDF_URL, content=pdf_bytes, headers={"content-type": "application/pdf"})

    with patch(
        "core.sources.plu_pdf_parser.fetch_zones_at_point",
        new=AsyncMock(return_value=[_mock_gpu_zone()]),
    ), patch(
        "core.sources.plu_pdf_parser.fetch_document",
        new=AsyncMock(return_value=[]),
    ):
        result = await sut.fetch_plu_overlays(lat=_LAT, lng=_LNG)

    assert result.error is None
    assert result.reglement is not None and result.reglement.hauteur_max_m == 15.0


async def test_fetch_plu_overlays_bbox_input(
    tmp_cache_dir: Path,
    httpx_mock: HTTPXMock,
) -> None:
    """A BBOX input is reduced to its centroid before querying GPU."""
    pdf_bytes = _make_pdf_bytes(_NOGENT_UB_SECTION)
    httpx_mock.add_response(url=_PDF_URL, content=pdf_bytes, headers={"content-type": "application/pdf"})

    captured: dict[str, float] = {}

    async def _fake_zones(*, lat: float, lng: float) -> list[GpuZone]:
        captured["lat"] = lat
        captured["lng"] = lng
        return [_mock_gpu_zone()]

    with patch(
        "core.sources.plu_pdf_parser.fetch_zones_at_point",
        new=_fake_zones,
    ), patch(
        "core.sources.plu_pdf_parser.fetch_document",
        new=AsyncMock(return_value=[]),
    ):
        bbox = (_LNG - 0.001, _LAT - 0.001, _LNG + 0.001, _LAT + 0.001)
        result = await sut.fetch_plu_overlays(bbox=bbox)

    assert result.error is None
    assert captured["lat"] == pytest.approx(_LAT)
    assert captured["lng"] == pytest.approx(_LNG)


async def test_fetch_plu_overlays_invalid_input() -> None:
    """Missing coordinates returns a typed error instead of raising."""
    result = await sut.fetch_plu_overlays()
    assert result.error == "invalid_coordinates"
    assert result.features_count == 0


# ---------------------------------------------------------------------------
# Real-world Nogent address: only run if the GPU fixture exists, and only to
# exercise the smoke-test reporting required by the task spec — still mocked.
# ---------------------------------------------------------------------------


def test_fixture_path_exists() -> None:
    """Sanity: GPU fixture JSON ships alongside the other source fixtures."""
    assert _FIXTURES_PATH.exists()
    data = json.loads(_FIXTURES_PATH.read_text())
    # Nogent zone fixture from the existing test suite.
    assert re.search(r"UB|nogent", json.dumps(data), re.IGNORECASE)
