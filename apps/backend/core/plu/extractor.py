"""Main PLU extraction orchestrator.

Pipeline: PDF URL → text → zone section → commune filter → LLM → JSON → ParsedRules.
"""

from __future__ import annotations

import logging
import os
import re

import anthropic

from core.plu import pdf_fetcher
from core.plu.commune_filter import strip_other_communes
from core.plu.json_repair import extract_and_parse_json
from core.plu.prompt import build_extraction_prompt
from core.plu.schemas import ParsedRules
from core.plu.section_finder import find_zone_section
from core.plu.value_cleaner import clean_value

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PARSED_FIELDS: list[str] = [
    "hauteur",
    "emprise",
    "implantation_voie",
    "limites_separatives",
    "stationnement",
    "lls",
    "espaces_verts",
    "destinations",
]

# PLUi detection keywords
_PLUI_KEYWORDS = (
    r"PLUi|PLU intercommunal|communaut[eé]s?\s+concern[eé]es?|territoire intercommunal"
)

_PLUI_RE = re.compile(_PLUI_KEYWORDS, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_model(*, is_plui: bool, text_length: int) -> str:
    """Select the Claude model based on document complexity.

    PLUi documents or very long texts (> 120K chars) use Sonnet for better
    accuracy.  Simpler mono-commune PLU use the faster/cheaper Haiku.
    """
    if is_plui or text_length > 120_000:
        return "claude-sonnet-4-6-20250514"
    return "claude-haiku-4-5-20251001"


async def extract_rules(
    *,
    pdf_url: str,
    zone_code: str,
    zone_description: str,
    commune_name: str | None = None,
    commune_insee: str | None = None,
) -> ParsedRules | None:
    """Main extraction pipeline: PDF → ParsedRules.

    Args:
        pdf_url: Direct URL to the PLU/PLUi PDF.
        zone_code: Zone identifier, e.g. "UB" or "UA1".
        zone_description: Human-readable description for the prompt.
        commune_name: Target commune (required for PLUi commune filtering).
        commune_insee: INSEE code (reserved for future use).

    Returns:
        ``ParsedRules`` on success, ``None`` if the PDF is unavailable or the
        LLM response cannot be parsed.
    """
    # 1. Fetch PDF text
    fetch_result = await pdf_fetcher.fetch_pdf_text(pdf_url)
    if fetch_result is None:
        log.warning("extract_rules: PDF unavailable or unreadable: %s", pdf_url)
        return None

    full_text, _sha256 = fetch_result

    # 2. Detect PLUi
    is_plui = bool(_PLUI_RE.search(full_text[:5000]))

    # 3. Find zone section
    plu_text: str
    zone_section = find_zone_section(full_text, zone_code, commune_name=commune_name)
    if zone_section is not None:
        plu_text = zone_section
    else:
        log.info(
            "extract_rules: zone section not found for %s — using full text", zone_code
        )
        plu_text = full_text

    # 4. Filter PLUi communes
    if is_plui and commune_name:
        plu_text = strip_other_communes(plu_text, commune_name)

    # 5. Build prompt and select model
    question = build_extraction_prompt(
        zone_code=zone_code,
        zone_description=zone_description,
        commune_name=commune_name,
        is_plui=is_plui,
    )
    model = select_model(is_plui=is_plui, text_length=len(plu_text))

    # 6. Call LLM with prompt caching
    try:
        raw_response = await _call_llm(
            model=model,
            plu_text=plu_text,
            question=question,
        )
    except Exception as exc:
        log.error("extract_rules: LLM call failed — %s", exc)
        return None

    # 7. Parse JSON response
    parsed_dict = extract_and_parse_json(raw_response)
    if parsed_dict is None:
        log.warning(
            "extract_rules: LLM response not parseable for zone %s (url=%s)",
            zone_code,
            pdf_url,
        )
        return None

    # 8. Clean values
    cleaned: dict = {}
    for field in _PARSED_FIELDS:
        raw_value = parsed_dict.get(field)
        if isinstance(raw_value, str):
            cleaned[field] = clean_value(raw_value)
        else:
            cleaned[field] = None

    pages = parsed_dict.get("pages", {})
    if not isinstance(pages, dict):
        pages = {}

    return ParsedRules(**cleaned, pages=pages, source="ai_parsed")


# ---------------------------------------------------------------------------
# LLM call (separated for easy mocking in tests)
# ---------------------------------------------------------------------------


async def _call_llm(*, model: str, plu_text: str, question: str) -> str:
    """Call Anthropic API with prompt caching.

    The PLU text is sent as an ephemeral cached prefix so repeated calls on the
    same document benefit from Anthropic's prompt caching (5-minute TTL).
    """
    client = anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY", "")
    )
    response = await client.messages.create(
        model=model,
        max_tokens=3000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"TEXTE DU RÈGLEMENT :\n{plu_text}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": question,
                    },
                ],
            }
        ],
    )
    return response.content[0].text  # type: ignore[union-attr]
