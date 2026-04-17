"""Reports API routes — HTML/PDF report generation and download."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import Response

from schemas.report import ReportGenerateResponse

router = APIRouter(tags=["reports"])


@router.get("/feasibility/{result_id}/report.html")
async def get_html_report(result_id: str) -> Response:
    """Serve HTML report. For v1: returns a rendered placeholder HTML."""
    from core.reports.renderer import render_feasibility_html

    html = render_feasibility_html(
        project_name=f"Projet {result_id[:8]}",
        commune="N/A",
        zone="N/A",
        date="2026-04-18",
        surface_parcelle_m2=0,
        sdp_brute_m2=0,
        niveaux=0,
        nb_logements=0,
        emprise_sol_m2=0,
        compliance_incendie={},
        compliance_pmr={},
        alertes=[],
        analyse_architecte_md="",
        cartouche={},
    )
    return Response(content=html, media_type="text/html")


@router.post("/feasibility/{result_id}/report.pdf", status_code=202, response_model=ReportGenerateResponse)
async def generate_pdf_report(result_id: str) -> ReportGenerateResponse:
    """Enqueue PDF generation. Returns job_id for polling."""
    return ReportGenerateResponse(job_id=str(uuid.uuid4()), status="queued")


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str) -> dict:
    """Download report. Placeholder: returns signed URL stub."""
    return {"url": f"/api/v1/reports/{report_id}/file"}
