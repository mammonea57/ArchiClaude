"""Pydantic schemas for report generation endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ReportGenerateResponse(BaseModel):
    job_id: str
    status: str
