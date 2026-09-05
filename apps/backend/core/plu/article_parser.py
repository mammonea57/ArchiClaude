"""Zone-by-zone PLU article parser (articles 1 to 17).

The historical PLU template (CU R.123-9, applicable to PLU pre-2015) groups
règles into 16 articles ; the post-2015 PLU template (CU R.151-9) keeps the
same numbering up to 17. This module extracts the per-article text *within a
single zone section* so each règle can be processed independently.

The parser is deterministic — no LLM call. It is used by
:mod:`core.sources.plu_pdf_parser` to feed
:class:`core.urbanism_overlays.schemas.PLUReglement` /
:class:`PLUZonage` instances with structured fields.

Supported numbering conventions
-------------------------------
* ``Article UB 1`` / ``Article UB1`` (zone-prefixed)
* ``Article 1`` (mono-zone PLU)
* ``ARTICLE 1.`` / ``Article 1 –`` / ``Article 1 :`` (delimiters)

The output is a dict ``{article_number: raw_text}`` keyed by integers 1..17,
plus best-effort numeric extraction for the four most common règles
(hauteur, emprise, retraits, stationnement).
"""

from __future__ import annotations

import logging
import re
from typing import Final

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Articles 1 to 17 — every legal article in either the pre-2015 or
#: post-2015 PLU template. Articles 16 and 17 only exist in some PLU.
ARTICLE_NUMBERS: Final[tuple[int, ...]] = tuple(range(1, 18))

#: Short FR label per article — purely informative.
ARTICLE_LABELS: Final[dict[int, str]] = {
    1: "Occupations et utilisations du sol interdites",
    2: "Occupations et utilisations du sol soumises à conditions",
    3: "Accès et voirie",
    4: "Desserte par les réseaux",
    5: "Caractéristiques des terrains",
    6: "Implantation par rapport aux voies",
    7: "Implantation par rapport aux limites séparatives",
    8: "Implantation des constructions les unes par rapport aux autres",
    9: "Emprise au sol",
    10: "Hauteur maximale",
    11: "Aspect extérieur",
    12: "Stationnement",
    13: "Espaces libres et plantations",
    14: "Coefficient d'occupation des sols (COS)",
    15: "Performances énergétiques et environnementales",
    16: "Infrastructures et réseaux de communications électroniques",
    17: "Dispositions particulières",
}


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

# Anchor for any "Article N" header — captures zone prefix optionally,
# the article number, and the rest of the line up to the next newline.
_ARTICLE_HEADER_RE = re.compile(
    r"""
    (?:^|\n)\s*                          # start of a line
    ARTICLE\s+                           # literal
    (?:(?P<zone>[A-Z]{1,3}[A-Z0-9]*)\s*)?# optional zone prefix (UB, UA1, …)
    (?P<num>1[0-7]|[1-9])                # article number 1..17
    (?![0-9])                            # not followed by another digit
    [\s.\-–—:]*                          # delimiter
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Heights — capture decimals with comma or dot
_HAUTEUR_RE = re.compile(
    r"hauteur(?:\s+\w+){0,6}?\s+(?:de|à|=|:|fix[ée]e?\s+(?:à|de)?)?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:m|mètres?)\b",
    re.IGNORECASE,
)

# Emprise au sol percentage
_EMPRISE_RE = re.compile(
    r"emprise(?:\s+au\s+sol)?(?:\s+\w+){0,8}?\s+"
    r"(?:de|à|=|:|inférieure?\s+à|maximale?\s+(?:de|à)?|exc[ée]der|d[ée]passer)?\s*"
    r"(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:%|p\.?\s*cent)",
    re.IGNORECASE,
)

# Recul / retrait minimum metres
_RETRAIT_RE = re.compile(
    r"(?:recul|retrait)(?:\s+\w+){0,5}?\s+"
    r"(?:de|à|=|:|au\s+moins|minimum\s+(?:de)?)?\s*"
    r"(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:m|mètres?)\b",
    re.IGNORECASE,
)

# Stationnement — places par logement
_STATIONNEMENT_RE = re.compile(
    r"(\d(?:[.,]\d{1,2})?)\s*place[s]?\s+"
    r"(?:de\s+stationnement\s+)?(?:par|/)\s*logement",
    re.IGNORECASE,
)

# Pleine terre percentage
_PLEINE_TERRE_RE = re.compile(
    r"pleine[- ]terre(?:\s+\w+){0,5}?\s+"
    r"(?:de|à|=|:|au\s+moins|minimum\s+(?:de)?)?\s*"
    r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Article splitting
# ---------------------------------------------------------------------------


def split_articles(zone_section_text: str, *, zone_code: str | None = None) -> dict[int, str]:
    """Split a zone-section text into ``{article_num: text}`` for articles 1..17.

    The function scans every ``Article N`` header inside the section and slices
    the text from one header to the next. If a zone prefix is present (e.g.
    ``Article UB 1``) and ``zone_code`` is provided, headers belonging to
    other zones are ignored — this protects against bleed-through when the
    section was poorly cut.

    Args:
        zone_section_text: Output of
            :func:`core.plu.section_finder.find_zone_section`.
        zone_code: Restrict to headers that match this zone prefix when set.

    Returns:
        Mapping article number → raw text. Empty dict when no article is
        recognised (e.g. the section is a scanned image or uses a fully
        custom numbering).
    """
    if not zone_section_text:
        return {}

    target_zone = zone_code.upper() if zone_code else None

    # Collect every (article_num, start_pos) pair, filtered by zone prefix.
    hits: list[tuple[int, int]] = []
    for m in _ARTICLE_HEADER_RE.finditer(zone_section_text):
        header_zone = (m.group("zone") or "").upper()
        if (
            target_zone is not None
            and header_zone
            and not _zone_matches(target_zone, header_zone)
        ):
            continue
        try:
            num = int(m.group("num"))
        except ValueError:
            continue
        if 1 <= num <= 17:
            hits.append((num, m.start()))

    if not hits:
        return {}

    # Slice from each header to the next; for the last header, take the rest
    # of the section.
    out: dict[int, str] = {}
    for i, (num, start) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(zone_section_text)
        text = zone_section_text[start:end].strip()
        # Keep the *first* occurrence per article number — subsequent hits
        # are usually cross-references in later articles.
        out.setdefault(num, text)

    return out


def _zone_matches(target: str, header_zone: str) -> bool:
    """Return True when ``header_zone`` belongs to ``target``.

    ``UB`` matches ``UB``, ``UB1``, ``UB2a`` ; ``UB1`` only matches ``UB1``,
    ``UB1a`` (not ``UB`` nor ``UB2``).
    """
    if header_zone == target:
        return True
    # Header more specific than target (UB → UB1, UB2a)
    if header_zone.startswith(target) and len(header_zone) > len(target):
        # The first extra character must be a digit or lowercase letter
        ch = header_zone[len(target)]
        return ch.isdigit() or ch.islower()
    return False


# ---------------------------------------------------------------------------
# Numeric extraction per article
# ---------------------------------------------------------------------------


def parse_articles_numeric(
    articles: dict[int, str],
) -> dict[str, float | None]:
    """Best-effort numeric extraction from a per-article text mapping.

    The extraction is intentionally conservative — when several values match
    inside an article, the *first* one is returned. The aim is to feed an
    initial :class:`PLUReglement` instance; downstream LLM extraction can
    refine values.

    Returns a dict with the following keys (each may be ``None``):

    * ``hauteur_max_m``  (article 10)
    * ``emprise_max_pct`` (article 9)
    * ``retrait_voirie_min_m`` (article 6)
    * ``retrait_lateral_min_m`` (article 7)
    * ``stationnement_par_logement`` (article 12)
    * ``pleine_terre_min_pct`` (article 13)
    """
    return {
        "hauteur_max_m": _first_float(_HAUTEUR_RE, articles.get(10, "")),
        "emprise_max_pct": _first_float(_EMPRISE_RE, articles.get(9, "")),
        "retrait_voirie_min_m": _first_float(_RETRAIT_RE, articles.get(6, "")),
        "retrait_lateral_min_m": _first_float(_RETRAIT_RE, articles.get(7, "")),
        "stationnement_par_logement": _first_float(
            _STATIONNEMENT_RE, articles.get(12, "")
        ),
        "pleine_terre_min_pct": _first_float(
            _PLEINE_TERRE_RE, articles.get(13, "")
        ),
    }


def _first_float(pattern: re.Pattern[str], text: str) -> float | None:
    if not text:
        return None
    m = pattern.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    try:
        v = float(raw)
    except ValueError:
        return None
    # Sanity checks: % must be ≤ 100, hauteur ≤ 200 m
    if pattern in (_EMPRISE_RE, _PLEINE_TERRE_RE) and not 0 <= v <= 100:
        return None
    if pattern in (_HAUTEUR_RE, _RETRAIT_RE) and not 0 <= v <= 200:
        return None
    return v
