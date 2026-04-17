"""Value cleaning utilities for PLU rule text fields.

Normalises raw strings extracted by the AI parser:
- Detect error/placeholder patterns and convert to None.
- Normalise "Non précisé" and "Non réglementé" strings by stripping trailing commentary.
- Strip whitespace and enforce a maximum length.
- Hoist numeric tokens to the front of a string for consistent display.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_LEN = 180

# Regex that matches a number token worth hoisting
_NUMBER_RE = re.compile(
    r"(\d+(?:[.,]\d+)?\s*(?:m[²2]?|%|places?|logements?)|R\+\d+)",
    re.IGNORECASE,
)

# Patterns that indicate the AI returned a placeholder / error value
_ERROR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*null\s*$", re.IGNORECASE),
    re.compile(r"^\s*none\s*$", re.IGNORECASE),
    re.compile(r"^\s*n/?a\s*$", re.IGNORECASE),
    re.compile(r"^\s*not\s+found\s*$", re.IGNORECASE),
    re.compile(r"^\s*non\s+trouv[ée]e?\s*$", re.IGNORECASE),
    re.compile(r"^\s*section\s+incompl[eè]te\s*$", re.IGNORECASE),
]

# Prefix patterns that should be normalised (suffix stripped)
_NON_PRECISE_RE = re.compile(
    r"^(Non\s+pr[eé]cis[eé]\s+dans\s+ce\s+r[eè]glement)\s*[—\-–].*$",
    re.IGNORECASE | re.DOTALL,
)
_NON_REGLEMENTE_RE = re.compile(
    r"^(Non\s+r[eé]glement[eé])\s*[—\-–].*$",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_error_pattern(value: str) -> bool:
    """Return True if *value* is a known error/placeholder string."""
    return any(p.match(value) for p in _ERROR_PATTERNS)


def clean_value(value: str | None) -> str | None:
    """Clean a raw PLU field value.

    - ``None`` → ``None``
    - Error patterns → ``None``
    - "Non précisé … — suffix" → "Non précisé dans ce règlement"
    - "Non réglementé — suffix" → "Non réglementé"
    - Strip leading/trailing whitespace
    - Truncate to 180 characters
    """
    if value is None:
        return None

    if is_error_pattern(value):
        return None

    # Normalise "Non précisé dans ce règlement — …"
    m = _NON_PRECISE_RE.match(value)
    if m:
        return m.group(1)

    # Normalise "Non réglementé — …"
    m = _NON_REGLEMENTE_RE.match(value)
    if m:
        return m.group(1)

    value = value.strip()
    return value[:_MAX_LEN]


def hoist_chiffre_front(value: str) -> str:
    """Move the first numeric token to the front of *value* for consistent display.

    If *value* already starts with a digit, ``R+``, or ``%``, it is returned
    unchanged.  If a matching number token is found elsewhere, it is moved to
    the front with the remainder appended (lowercased label trimmed).

    If no numeric token is found, *value* is returned unchanged.
    """
    stripped = value.strip()

    # Already starts with a number-like token — nothing to do
    if re.match(r"^\d|^R\+|^%", stripped):
        return stripped

    m = _NUMBER_RE.search(stripped)
    if not m:
        return stripped

    token = m.group(1)
    # Build the remainder: everything before the match + everything after,
    # with the colon-label stripped if there's a "Label : <token>" pattern.
    before = stripped[: m.start()].strip().rstrip(":").strip()
    after = stripped[m.end() :].strip()

    parts = [token]
    if before:
        parts.append(before.lower() if before.isupper() else before)
    if after:
        parts.append(after)

    return " ".join(p.strip() for p in parts if p.strip())
