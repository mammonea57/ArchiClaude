"""Pydantic schemas for architectural programming API."""

from __future__ import annotations

from pydantic import BaseModel


class ScenarioOut(BaseModel):
    """Single scenario output for the comparison view."""

    nom: str
    sdp_m2: float
    nb_logements: int
    nb_niveaux: int
    mix_utilise: dict[str, float]
    mix_ajustements: list[str]
    marge_pct: float
    variante_acces_separes: bool


class ScenariosResponse(BaseModel):
    """Full scenarios response with recommendation."""

    scenarios: list[ScenarioOut]
    scenario_recommande: str
    raison: str


class ProgramJobResponse(BaseModel):
    """Response for POST /projects/{id}/program — job has been queued."""

    job_id: str
    status: str


class ProgramStatusResponse(BaseModel):
    """Response for GET /projects/{id}/program/status."""

    status: str
