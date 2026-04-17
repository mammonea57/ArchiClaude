"""ARQ worker for async PLU rule extraction."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


async def run_extraction(
    ctx: dict,
    *,
    pdf_url: str,
    zone_code: str,
    zone_description: str,
    commune_name: str | None = None,
    commune_insee: str | None = None,
    plu_zone_id: str | None = None,
) -> dict:
    """Extract PLU rules from a PDF and numericize them.

    Args:
        ctx: ARQ worker context.
        pdf_url: Direct URL to the PLU/PLUi PDF.
        zone_code: Zone identifier, e.g. "UB" or "UA1".
        zone_description: Human-readable description for the prompt.
        commune_name: Target commune (required for PLUi commune filtering).
        commune_insee: INSEE code used for Paris Bioclimatique detection.
        plu_zone_id: UUID of the plu_zones row (for DB persistence, future use).

    Returns:
        dict with ``status``, ``parsed_rules``, and ``numeric_rules`` on success,
        or ``status="failed"`` on error.
    """
    from core.plu.extractor import extract_rules
    from core.plu.numericizer import numericize_rules

    parsed = await extract_rules(
        pdf_url=pdf_url,
        zone_code=zone_code,
        zone_description=zone_description,
        commune_name=commune_name,
        commune_insee=commune_insee,
    )
    if parsed is None:
        log.error(
            "run_extraction: extraction failed for zone %s (url=%s)", zone_code, pdf_url
        )
        return {"status": "failed", "error": "extraction_failed"}

    numeric = await numericize_rules(parsed)
    return {
        "status": "done",
        "parsed_rules": parsed.model_dump(),
        "numeric_rules": numeric.model_dump(),
    }
