"""Pydantic schemas for agency settings endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class AgencySettingsUpdate(BaseModel):
    agency_name: str | None = None
    address: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    archi_ordre_number: str | None = None
    brand_primary_color: str | None = None


class AgencySettingsOut(BaseModel):
    agency_name: str | None
    logo_url: str | None = None
    contact_email: str | None = None
    brand_primary_color: str | None = None
