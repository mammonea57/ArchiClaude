"""PLUi commune filter — strip paragraphs specific to other communes.

Ported from the TS bot's ``stripOtherCommunesFromSection()``.
Intercommunal PLU documents (PLUi) often contain commune-specific paragraphs
like ``Pour la commune de X``.  This module keeps only the target commune's
paragraphs plus neutral (general) paragraphs.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Split pattern — lookahead to preserve delimiters
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(
    r"(?=\n\s*(?:"
    r"Article|Paragraphe|"
    r"Pour la commune|Dans la commune|Sur la commune|"
    r"Commune de |"
    r"Dispositions? (?:sp[ée]cifiques?|particuli[èe]res?) (?:à|pour) |"
    r"R[èe]gles? propres? à |"
    r"R[èe]glement de |"
    r"En secteur |Pour le secteur |Dans le secteur "
    r")\s*)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Commune header detection patterns
# ---------------------------------------------------------------------------

# Commune name capture group: letters, accented chars, hyphens, spaces.
# Uses a greedy match followed by a terminator that does NOT include bare
# hyphens (to avoid splitting compound names like "Saint-Mandé" at the hyphen).
# Terminators: colon, period, comma, em/en-dash (with optional space), newline.
_COMMUNE_NAME_RE = r"([A-ZÉÈÊÀÂÎÔÏÛÇ][A-Za-zéèêàâîôïûç-]+(?:[\s-][A-Za-zéèêàâîôïûç-]+)*)"
_COMMUNE_TERM_RE = r"(?:\s*[–—:.]|\s*\n|,)"

_COMMUNE_HEADER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"^\s*(?:Pour|Dans|Sur)\s+la\s+commune\s+de\s+"
        + _COMMUNE_NAME_RE + _COMMUNE_TERM_RE,
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Commune\s+de\s+"
        + _COMMUNE_NAME_RE + _COMMUNE_TERM_RE,
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Dispositions?\s+(?:sp[ée]cifiques?|particuli[èe]res?)\s+(?:à|pour)\s+"
        r"(?:la\s+commune\s+de\s+)?"
        + _COMMUNE_NAME_RE + _COMMUNE_TERM_RE,
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*R[èe]glement\s+de\s+"
        + _COMMUNE_NAME_RE + _COMMUNE_TERM_RE,
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*R[èe]gles?\s+propres?\s+à\s+"
        + _COMMUNE_NAME_RE + _COMMUNE_TERM_RE,
        re.IGNORECASE,
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_commune_name(name: str) -> str:
    """Normalize: strip diacritics, lowercase, trim.

    Uses NFD decomposition to strip combining marks (e.g. ``e`` + accent ->
    ``e``).
    """
    nfkd = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return stripped.lower().strip()


def strip_other_communes(text: str, target_commune: str) -> str:
    """Filter PLUi text to keep only target commune paragraphs + neutral paragraphs.

    Paragraphs that mention a commune different from *target_commune* are
    dropped.  Paragraphs that either mention *target_commune* or don't mention
    any commune are kept.
    """
    if not target_commune:
        return text

    target_norm = normalize_commune_name(target_commune)

    # Split on commune-specific paragraph markers
    paragraphs = _SPLIT_RE.split(text)

    kept: list[str] = []
    for para in paragraphs:
        mentioned = _detect_commune(para)

        if mentioned is not None:
            mentioned_norm = normalize_commune_name(mentioned)
            if not _commune_matches(mentioned_norm, target_norm):
                # Paragraph is specific to a different commune — drop it
                continue

        kept.append(para)

    return "".join(kept)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_commune(paragraph: str) -> str | None:
    """Detect if a paragraph mentions a specific commune via header patterns.

    Returns the commune name if found, ``None`` otherwise.
    """
    for pattern in _COMMUNE_HEADER_PATTERNS:
        m = pattern.search(paragraph)
        if m:
            return m.group(1).strip()
    return None


def _commune_matches(mentioned_norm: str, target_norm: str) -> bool:
    """Flexible match: exact, prefix of the other, or first-4-chars prefix match.

    The 4-char prefix match is disabled when both names are compound (contain
    a hyphen/space) to avoid false positives like Saint-Mandé vs Saint-Maur.
    """
    if mentioned_norm == target_norm:
        return True
    if target_norm.startswith(mentioned_norm):
        return True
    if mentioned_norm.startswith(target_norm):
        return True
    # 4-char prefix match — only when names are NOT compound (no separator)
    # This avoids matching "Saint-Mandé" with "Saint-Maur" (both share "sain")
    has_sep_mentioned = "-" in mentioned_norm or " " in mentioned_norm
    has_sep_target = "-" in target_norm or " " in target_norm
    if has_sep_mentioned and has_sep_target:
        return False
    return (
        len(mentioned_norm) >= 4
        and len(target_norm) >= 4
        and mentioned_norm[:4] == target_norm[:4]
    )
