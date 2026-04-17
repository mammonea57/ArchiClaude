"""Cartouche builder — builds a standardised cartouche dict with sensible defaults.

build_cartouche(**kwargs) -> dict
"""

from __future__ import annotations

from typing import Any


def build_cartouche(
    *,
    agency_name: str = "ArchiClaude",
    brand_primary_color: str = "#0d9488",
    logo_url: str | None = None,
    project_ref: str | None = None,
    drawn_by: str | None = None,
    checked_by: str | None = None,
    scale: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Build a cartouche dict with defaults.

    All fields are present in the returned dict; optional fields are None
    when not provided.

    Args:
        agency_name: Name of the architectural agency. Default: "ArchiClaude".
        brand_primary_color: Hex colour for brand accent. Default: "#0d9488" (teal-600).
        logo_url: URL or data-URI of agency logo image.
        project_ref: Internal project reference code.
        drawn_by: Name of drafter.
        checked_by: Name of checker / BET visa.
        scale: Drawing scale string, e.g. "1:100".
        date: Issue date string, e.g. "2026-04-17".

    Returns:
        dict with all cartouche fields.
    """
    return {
        "agency_name": agency_name,
        "brand_primary_color": brand_primary_color,
        "logo_url": logo_url,
        "project_ref": project_ref,
        "drawn_by": drawn_by,
        "checked_by": checked_by,
        "scale": scale,
        "date": date,
    }
