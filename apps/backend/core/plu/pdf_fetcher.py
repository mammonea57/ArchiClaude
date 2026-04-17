"""Fetch PLU PDF and extract text via pdfplumber, compute sha256."""

from __future__ import annotations

import hashlib
import io
import logging

import httpx
import pdfplumber

from core.http_client import get_http_client

log = logging.getLogger(__name__)

PDF_TIMEOUT = httpx.Timeout(connect=5.0, read=40.0, write=5.0, pool=5.0)

_PDF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ArchiClaude/1.0)",
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Referer": "https://www.geoportail-urbanisme.gouv.fr/",
}

_MIN_TEXT_CHARS = 100


async def fetch_pdf_text(url: str) -> tuple[str, str] | None:
    """Download PDF, extract text, return (text, sha256) or None on failure.

    Returns:
        ``(text, sha256)`` tuple if successful and the PDF contains a text layer.
        ``None`` if the download fails, the PDF is too small, or the text layer
        is below *_MIN_TEXT_CHARS* (scanned / image-only PDF).
    """
    client = get_http_client()

    # 1. Download PDF bytes
    try:
        response = await client.get(url, headers=_PDF_HEADERS, timeout=PDF_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log.warning("pdf_fetcher: HTTP %s for %s", exc.response.status_code, url)
        return None
    except httpx.TransportError as exc:
        log.warning("pdf_fetcher: transport error for %s — %s", url, exc)
        return None

    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type:
        log.warning("pdf_fetcher: received HTML instead of PDF for %s", url)
        return None

    pdf_bytes = response.content
    if len(pdf_bytes) < 1000:
        log.warning("pdf_fetcher: PDF too small (%d bytes) for %s", len(pdf_bytes), url)
        return None

    # 2. Compute sha256
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    # 3. Extract text via pdfplumber (page by page, join with \n\n)
    try:
        pages_text: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                pages_text.append(page_text)
        text = "\n\n".join(pages_text)
    except Exception as exc:
        log.warning("pdf_fetcher: pdfplumber extraction failed for %s — %s", url, exc)
        return None

    # 4. Return None if text too short (possibly scanned)
    if len(text.strip()) < _MIN_TEXT_CHARS:
        log.warning(
            "pdf_fetcher: text too short (%d chars) — likely scanned PDF: %s",
            len(text.strip()),
            url,
        )
        return None

    return text, sha256
