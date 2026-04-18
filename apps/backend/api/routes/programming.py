"""Architectural programming API routes.

Endpoints for launching the programming pipeline, checking status,
retrieving the 3 scenarios, and serving SVG/DXF plans.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import Response

from schemas.programming import ProgramJobResponse, ProgramStatusResponse, ScenariosResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["programming"])


@router.post("/program", status_code=202, response_model=ProgramJobResponse)
async def start_programming(project_id: str) -> ProgramJobResponse:
    """Launch architectural programming pipeline. Returns job_id."""
    return ProgramJobResponse(job_id=str(uuid.uuid4()), status="queued")


@router.get("/program/status", response_model=ProgramStatusResponse)
async def programming_status(project_id: str) -> ProgramStatusResponse:
    """Get the programming job status for a project. v1: always pending."""
    return ProgramStatusResponse(status="pending")


@router.get("/scenarios", response_model=ScenariosResponse)
async def list_scenarios(project_id: str) -> ScenariosResponse:
    """List the 3 generated scenarios. v1: returns placeholder empty list."""
    return ScenariosResponse(
        scenarios=[],
        scenario_recommande="",
        raison="",
    )


@router.get("/scenarios/{scenario_nom}")
async def get_scenario(project_id: str, scenario_nom: str) -> dict:
    """Get a specific scenario by name. v1: placeholder data."""
    return {"nom": scenario_nom, "sdp_m2": 0, "nb_logements": 0}


@router.get("/plans/{plan_type}")
async def get_plan_svg(project_id: str, plan_type: str) -> Response:
    """Return an SVG plan.

    plan_type: masse, niveau_0, niveau_1, coupe, facade_rue, facade_arriere
    v1: generates a sample plan with placeholder geometry.
    """
    from shapely.geometry import Polygon

    from core.programming.plans.plan_masse import generate_plan_masse

    parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
    footprint = Polygon([(5, 5), (95, 5), (95, 75), (5, 75)])
    svg = generate_plan_masse(
        parcelle=parcelle,
        footprint=footprint,
        voirie_name="Rue placeholder",
    )
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/plans/{plan_type}/dxf")
async def get_plan_dxf(project_id: str, plan_type: str) -> Response:
    """Return a DXF plan as a downloadable file.

    v1: returns a minimal placeholder DXF with a label.
    """
    from core.programming.plans.renderer_dxf import DxfCanvas

    canvas = DxfCanvas()
    canvas.draw_text(0, 0, f"Plan {plan_type} - placeholder")
    return Response(
        content=canvas.to_bytes(),
        media_type="application/dxf",
        headers={"Content-Disposition": f"attachment; filename={plan_type}.dxf"},
    )
