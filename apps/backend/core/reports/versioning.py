"""Report versioning — version number computation and diff generation.

compute_next_version(existing_versions: list[int]) -> int
build_version_diff(v_old: dict, v_new: dict) -> dict
"""

from __future__ import annotations

from typing import Any


def compute_next_version(existing_versions: list[int]) -> int:
    """Compute the next version number.

    Returns max(existing_versions) + 1, or 1 if the list is empty.

    Args:
        existing_versions: List of existing version integers (may be non-sequential).

    Returns:
        Next version integer >= 1.
    """
    if not existing_versions:
        return 1
    return max(existing_versions) + 1


def build_version_diff(v_old: dict[str, Any], v_new: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a diff dict containing only fields that changed between two versions.

    - Fields present in both with equal values are omitted.
    - Fields added in v_new appear with old=None, new=<value>.
    - Fields removed in v_new appear with old=<value>, new=None.
    - Fields changed appear with old=<old>, new=<new>.

    Args:
        v_old: Previous version data dict.
        v_new: New version data dict.

    Returns:
        Dict keyed by field name; each value is {"old": ..., "new": ...}.
        Empty dict means no changes.
    """
    all_keys = set(v_old.keys()) | set(v_new.keys())
    diff: dict[str, dict[str, Any]] = {}

    for key in all_keys:
        old_val = v_old.get(key)
        new_val = v_new.get(key)
        if old_val != new_val:
            diff[key] = {"old": old_val, "new": new_val}

    return diff
