"""JSON repair utilities for PLU AI extraction outputs.

Port of the TypeScript extractAndParseJson() from the Urbanisme bot.
Handles truncated/malformed LLM responses gracefully.
"""

from __future__ import annotations

import json
import re


def _count_unescaped_quotes(s: str) -> int:
    """Count unescaped double-quote characters in *s*."""
    count = 0
    i = 0
    while i < len(s):
        if s[i] == "\\" :
            i += 2  # skip escaped char
            continue
        if s[i] == '"':
            count += 1
        i += 1
    return count


def _repair_truncated(raw: str) -> str | None:
    """Attempt to repair a truncated JSON string.

    Strategy (mirrors the TS implementation):
    1. Odd number of unescaped quotes → truncate to last clean boundary.
    2. Remove trailing comma before repair attempts.
    3. Count brace nesting and auto-close missing ``}``.
    4. Fix trailing comma before ``}``.
    """
    s = raw.strip()

    # --- Step 1: fix odd-quote truncation ---
    if _count_unescaped_quotes(s) % 2 != 0:
        # Find the last position where a complete string value ends:
        # a closing quote followed by optional whitespace then comma or }
        # This handles both '","' and '", "' (with spaces) patterns.
        last_brace = s.rfind("}")

        # Find the last complete "value" boundary (closing quote + comma/brace)
        matches = list(re.finditer(r'"[^"]*"\s*[,}]', s))
        if matches:
            last_match = matches[-1]
            # Truncate after the comma/brace that ends this last complete field
            end_pos = last_match.end()
            # If the boundary character was a comma, replace with }
            if s[end_pos - 1] == ",":
                s = s[: end_pos - 1] + "}"
            else:
                s = s[:end_pos]
        elif last_brace > 0:
            s = s[: last_brace + 1]
        else:
            # No clean boundary — give up on this path
            return None

    # --- Step 2: remove bare trailing comma (e.g. "value",} or "value", ) ---
    s = re.sub(r",\s*}", "}", s)

    # --- Step 3: auto-close missing braces ---
    depth = 0
    in_string = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and in_string:
            i += 2
            continue
        if c == '"':
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        i += 1

    if depth > 0:
        s += "}" * depth

    # --- Step 4: final cleanup of trailing commas before } ---
    s = re.sub(r",\s*}", "}", s)

    return s


def extract_and_parse_json(raw: str) -> dict | None:  # type: ignore[type-arg]
    """Extract and parse the first JSON object from *raw*.

    Tries in order:
    1. Markdown ```json ... ``` fence.
    2. Brace-delimited content (first ``{`` to last ``}``).
    3. Truncation repair heuristics.

    Returns ``None`` if no valid JSON object can be recovered.
    """
    if not raw or not raw.strip():
        return None

    # --- 1. Markdown fence ---
    md_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if md_match:
        candidate = md_match.group(1).strip()
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass  # fall through to repair

    # --- 2. Brace-delimited extraction ---
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")

    if first_brace != -1 and last_brace > first_brace:
        candidate = raw[first_brace : last_brace + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass  # fall through to repair

        # --- 3. Repair the brace-delimited fragment ---
        repaired = _repair_truncated(candidate)
        if repaired:
            try:
                result = json.loads(repaired)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    elif first_brace != -1:
        # Brace found but no closing brace — try repair on everything from first_brace
        candidate = raw[first_brace:]
        repaired = _repair_truncated(candidate)
        if repaired:
            try:
                result = json.loads(repaired)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    return None
