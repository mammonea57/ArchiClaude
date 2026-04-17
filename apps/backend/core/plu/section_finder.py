"""Zone section finder for PLU/PLUi documents.

Ported from the TS bot's ``extractZoneSection()`` + ``extractFullZoneSection()``.
Two-stage extraction:
  1. Canonical header search (``Dispositions applicables à la zone ...``)
  2. Multi-pass regex scoring with regulatory-word density analysis
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REGULATORY_WORDS = re.compile(
    r"\b("
    r"interdit|autoris[ée]|hauteur|emprise|implantation|retrait|"
    r"destination|coefficient|CES|gabarit|façade|"
    r"limite\s+s[eé]parative|alignement|rez-de-chauss[ée]e|"
    r"étage|niveau|mètre|plafond|plancher|surface"
    r")\b",
    re.IGNORECASE,
)

_STRONG_HEADER_RE = re.compile(
    r"^[\s\n]*(?:ZONE\s+)?[A-Z0-9]+[\s\n]*$",
    re.IGNORECASE | re.MULTILINE,
)

_DISPOSITIONS_RE = re.compile(
    r"dispositions?\s+(?:applicables?|communes?|g[eé]n[eé]rales?|sp[eé]cifiques?)",
    re.IGNORECASE,
)

_REGLES_APPLICABLES_RE = re.compile(
    r"R[eè]gles?\s+applicables?",
    re.IGNORECASE,
)

_ELLIPSIS_RE = re.compile(r"\.{3,}")
_PAGE_NUMBER_RE = re.compile(r"\s\d{1,3}\s*\n")

# Common French words that should NOT be treated as zone codes
_COMMON_WORDS = frozenset(
    "de du des la le les et ou en un une au aux ce ces il on ne se sa si ni or car".split()
)

# Preposition variants for canonical headers
_PREPO = r"(?:à\s+la\s+|aux\s+|en\s+|dans\s+la\s+|pour\s+la\s+|propres?\s+à\s+la\s+)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc_re(s: str) -> str:
    """Escape a string for use in a regex pattern."""
    return re.escape(s)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_zone_variants(zone_code: str) -> list[str]:
    """Generate notation variants: UA1 -> [UA1, UA-1, UA.1, UA 1].

    If *zone_code* contains a letter followed by a digit, generate hyphen /
    dot / space variants.  Otherwise return ``[zone_code]``.
    """
    z = zone_code.upper()
    if not re.search(r"[A-Z]\d", z):
        return [z]

    variants: list[str] = [z]
    hyphen = re.sub(r"([A-Z]+)(\d)", r"\1-\2", z)
    dot = re.sub(r"([A-Z]+)(\d.*)", r"\1.\2", z)
    space = re.sub(r"([A-Z]+)(\d)", r"\1 \2", z)

    for v in (hyphen, dot, space):
        if v not in variants:
            variants.append(v)

    return variants


def score_candidate(context_text: str) -> int:
    """Score a candidate section by regulatory word density and markers.

    *context_text* is typically the first 4000 chars after a candidate match
    position.
    """
    score = 0

    # Strong header bonus: first 50 chars look like a standalone zone header
    if _STRONG_HEADER_RE.search(context_text[:50]):
        score += 150

    # Regulatory word density
    matches = _REGULATORY_WORDS.findall(context_text)
    score += len(matches) * 3

    # "Dispositions applicables|communes|générales|spécifiques" in first 500
    if _DISPOSITIONS_RE.search(context_text[:500]):
        score += 80

    # "Règles applicables" in first 300
    if _REGLES_APPLICABLES_RE.search(context_text[:300]):
        score += 60

    # Penalty: TOC-like content (many ellipses)
    if len(_ELLIPSIS_RE.findall(context_text[:1000])) > 5:
        score -= 100

    # Penalty: many page numbers (TOC)
    if len(_PAGE_NUMBER_RE.findall(context_text[:1000])) > 8:
        score -= 80

    return score


def find_zone_section(
    full_text: str,
    zone_code: str,
    *,
    commune_name: str | None = None,
    window_chars: int = 500_000,
) -> str | None:
    """Find the zone-specific section in a PLU document.

    Two-stage approach:
      1. Canonical header search (``Dispositions applicables ...``)
      2. Multi-pass regex scoring fallback

    Returns ``None`` if the zone is not found in the document.
    """
    z = zone_code.upper()

    # Stage 1 — canonical header
    result = _find_canonical_header(full_text, z)
    if result is not None and len(result) >= 5000:
        return result

    # Stage 2 — multi-pass regex scoring
    return _find_by_regex_scoring(full_text, z, window_chars=window_chars)


# ---------------------------------------------------------------------------
# Stage 1 — Canonical header search
# ---------------------------------------------------------------------------


def _find_canonical_header(full_text: str, zone_code: str) -> str | None:
    """Search for ``Dispositions applicables à la zone {variants}``."""
    # Try the label itself, then parent labels (UB2a -> UB2 -> UB)
    candidates = _label_candidates(zone_code)

    for label in candidates:
        section = _try_canonical_label(full_text, label)
        if section is not None:
            return section
    return None


def _label_candidates(zone_code: str) -> list[str]:
    """Generate label candidates: full code, then progressively shorter parents."""
    z = zone_code.upper()
    seen: list[str] = [z]

    # Strip lowercase suffix: UB2a -> UB2
    no_suffix = re.sub(r"[a-z]+$", "", zone_code).upper()
    if no_suffix and no_suffix != z and no_suffix not in seen:
        seen.append(no_suffix)

    # Strip digits: UB2 -> UB
    parent = re.sub(r"[0-9].*$", "", zone_code)
    parent = re.sub(r"[a-z]+$", "", parent).upper()
    if parent and len(parent) >= 1 and parent not in seen:
        seen.append(parent)

    return seen


def _try_canonical_label(full_text: str, label: str) -> str | None:
    """Try to find a canonical section for a single label variant."""
    esc = _esc_re(label)

    header_patterns = [
        # "Dispositions applicables à la/en/aux zone UB"
        re.compile(
            rf"Dispositions?\s+(?:applicables?|propres?)\s+{_PREPO}zones?\s+{esc}\b",
            re.IGNORECASE,
        ),
        # "Règlement/Règles applicables en zone UB"
        re.compile(
            rf"R[èe]gl(?:e|ement)s?\s+(?:applicables?\s+)?{_PREPO}zones?\s+{esc}\b",
            re.IGNORECASE,
        ),
        # "CHAPITRE VI — Dispositions applicables en zone UG"
        re.compile(
            rf"(?:CHAPITRE|TITRE|SECTION|PARTIE)\s+[IVX0-9]+\s*[-–—:.]?\s*"
            rf"(?:Dispositions?\s+(?:applicables?|propres?)\s+{_PREPO})?"
            rf"zones?\s+{esc}\b",
            re.IGNORECASE,
        ),
        # "ZONE UB" on its own line
        re.compile(
            rf"(?:^|\n)\s*ZONE\s+{esc}\s*(?:[-–—:\d]|\n|\s{{2,}})",
            re.IGNORECASE | re.MULTILINE,
        ),
        # "UB — Zone..." inverted form
        re.compile(
            rf"(?:^|\n)\s*{esc}\s*[-–—:]\s*Zone\s+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ]

    for pattern in header_patterns:
        positions: list[int] = []
        for m in pattern.finditer(full_text):
            positions.append(m.start())

        if not positions:
            continue

        # Take the last occurrence (avoids TOC / table of contents)
        start = positions[-1]

        # Find section end: next zone header with a DIFFERENT label
        end = _find_section_end(full_text, start + 100, label)

        if end - start >= 5000:
            return full_text[start:end]

    return None


def _find_section_end(full_text: str, search_from: int, current_label: str) -> int:
    """Find where the next DIFFERENT zone section begins."""
    end_pattern = re.compile(
        rf"(?:Dispositions?\s+(?:applicables?|propres?)\s+{_PREPO}zones?\s+"
        rf"|R[èe]gl(?:e|ement)s?\s+(?:applicables?\s+)?{_PREPO}zones?\s+"
        rf"|(?:^|\n)\s*ZONE\s+)"
        rf"([A-Z][A-Za-z0-9]*)\b",
        re.IGNORECASE | re.MULTILINE,
    )

    current_upper = current_label.upper()

    for m in end_pattern.finditer(full_text, pos=search_from):
        next_label = m.group(1)
        next_upper = next_label.upper()

        # Skip common French words
        if next_label.lower() in _COMMON_WORDS:
            continue
        # Skip same label
        if next_upper == current_upper:
            continue
        # Skip subsectors (UB -> UBa, UBb)
        if next_upper.startswith(current_upper):
            continue
        # Must contain at least one uppercase letter
        if not any(c.isupper() for c in next_label):
            continue

        return m.start()

    # No next zone found — take up to 800K chars
    return min(len(full_text), search_from + 800_000)


# ---------------------------------------------------------------------------
# Stage 2 — Multi-pass regex scoring
# ---------------------------------------------------------------------------


def _find_by_regex_scoring(
    full_text: str, zone_code: str, *, window_chars: int = 500_000
) -> str | None:
    """Multi-pass regex scoring: collect candidates, score each, take best."""
    variants = generate_zone_variants(zone_code)

    # Collect all candidate positions
    candidate_set: set[int] = set()

    for variant in variants:
        esc = _esc_re(variant)
        patterns = [
            # Tier 1: Strong header
            re.compile(
                rf"(?:^|\n)\s*(?:ZONE|CHAPITRE|TITRE|SECTION|PARTIE)\s+{esc}(?:\s|$|\n|\r)",
                re.IGNORECASE | re.MULTILINE,
            ),
            # Tier 2: Article marker
            re.compile(
                rf"\bARTICLE\s+{esc}[\s.\-]",
                re.IGNORECASE,
            ),
            # Tier 3: EOL isolation
            re.compile(
                rf"(?:^|\n)\s*{esc}\s*(?:\n|\r|$)",
                re.MULTILINE,
            ),
            # Tier 4: Bare word
            re.compile(
                rf"\b{esc}\b",
            ),
        ]

        for pattern in patterns:
            for m in pattern.finditer(full_text):
                candidate_set.add(m.start())

    if not candidate_set:
        return None

    candidates = sorted(candidate_set)

    # Score each candidate
    best_index = candidates[0]
    best_score = -1

    for idx in candidates:
        context = full_text[idx : idx + 4000]
        s = score_candidate(context)
        if s > best_score:
            best_score = s
            best_index = idx

    # Extract window around best candidate
    start = max(0, best_index - 3000)
    end = min(len(full_text), best_index + window_chars)
    return full_text[start:end]
