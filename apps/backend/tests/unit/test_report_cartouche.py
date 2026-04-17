"""Unit tests for core.reports.cartouche — cartouche builder."""

from __future__ import annotations

import pytest

from core.reports.cartouche import build_cartouche


def test_full_settings() -> None:
    result = build_cartouche(
        agency_name="Cabinet Moreau",
        brand_primary_color="#112233",
        logo_url="https://example.com/logo.svg",
        project_ref="PC-2026-001",
        drawn_by="A. Dupont",
        checked_by="B. Martin",
        scale="1:100",
        date="2026-04-17",
    )
    assert result["agency_name"] == "Cabinet Moreau"
    assert result["brand_primary_color"] == "#112233"
    assert result["logo_url"] == "https://example.com/logo.svg"
    assert result["project_ref"] == "PC-2026-001"
    assert result["drawn_by"] == "A. Dupont"
    assert result["checked_by"] == "B. Martin"
    assert result["scale"] == "1:100"
    assert result["date"] == "2026-04-17"


def test_minimal_settings() -> None:
    result = build_cartouche()
    assert result["agency_name"] == "ArchiClaude"
    assert result["brand_primary_color"] == "#0d9488"
    # optional fields default to None or empty
    assert "logo_url" in result
    assert "project_ref" in result


def test_with_logo_url() -> None:
    result = build_cartouche(logo_url="https://cdn.example.com/logo.png")
    assert result["logo_url"] == "https://cdn.example.com/logo.png"
    # defaults still apply
    assert result["agency_name"] == "ArchiClaude"
    assert result["brand_primary_color"] == "#0d9488"


def test_returns_dict() -> None:
    result = build_cartouche()
    assert isinstance(result, dict)


def test_override_agency_name() -> None:
    result = build_cartouche(agency_name="Studio Z")
    assert result["agency_name"] == "Studio Z"
    assert result["brand_primary_color"] == "#0d9488"  # default unchanged


def test_brand_color_default() -> None:
    result = build_cartouche()
    assert result["brand_primary_color"] == "#0d9488"
