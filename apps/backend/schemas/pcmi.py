"""Pydantic schemas for the PCMI dossier API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class StatusResponse(BaseModel):
    status: str
    indice_revision: str | None = None
    pieces_status: dict | None = None
    pdf_url: str | None = None
    zip_url: str | None = None
    error_msg: str | None = None


class SettingsUpdate(BaseModel):
    map_base: Literal["scan25", "planv2"] | None = None


class SettingsOut(BaseModel):
    map_base: str
