"""API routes for PCMI dossier generation.

All routes are nested under /projects/{project_id}/pcmi.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from core.pcmi.schemas import PCMI_ORDER, PCMI_TITRES
from schemas.pcmi import GenerateResponse, SettingsOut, SettingsUpdate, StatusResponse

router = APIRouter(prefix="/projects/{project_id}/pcmi", tags=["pcmi"])


@router.post("/generate", status_code=202, response_model=GenerateResponse)
async def generate_pcmi(project_id: str) -> GenerateResponse:
    """Queue a PCMI dossier generation job for *project_id*."""
    return GenerateResponse(job_id=str(uuid.uuid4()), status="queued")


@router.get("/status", response_model=StatusResponse)
async def pcmi_status(project_id: str) -> StatusResponse:
    """Return the latest dossier generation status for *project_id*."""
    return StatusResponse(status="not_generated")


@router.get("/dossier.pdf", response_class=PlainTextResponse)
async def get_dossier_pdf(project_id: str) -> PlainTextResponse:
    """Placeholder — returns 200 with a stub message until R2 integration."""
    return PlainTextResponse(
        content=f"Dossier PDF not yet generated for project {project_id}",
        status_code=200,
    )


@router.get("/dossier.zip", response_class=PlainTextResponse)
async def get_dossier_zip(project_id: str) -> PlainTextResponse:
    """Placeholder — returns 200 with a stub message until R2 integration."""
    return PlainTextResponse(
        content=f"Dossier ZIP not yet generated for project {project_id}",
        status_code=200,
    )


@router.get("/{piece}/pdf", response_class=PlainTextResponse)
async def get_piece_pdf(project_id: str, piece: str) -> Response:
    """Placeholder — individual piece PDF (not yet generated)."""
    if piece not in PCMI_ORDER:
        return Response(
            status_code=404,
            content=f"Unknown piece: {piece}",
            media_type="text/plain",
        )
    return PlainTextResponse(
        content=f"PDF for {piece} not yet generated for project {project_id}",
        status_code=200,
    )


@router.get("/{piece}")
async def get_piece_svg(project_id: str, piece: str) -> Response:
    """Return a stub SVG for the requested PCMI piece."""
    if piece not in PCMI_ORDER:
        return Response(
            status_code=404,
            content=f"Unknown piece: {piece}",
            media_type="text/plain",
        )
    titre = PCMI_TITRES[piece]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm">'
        f'<text x="50" y="50">{piece} \u2014 {titre}</text>'
        f"</svg>"
    )
    return Response(content=svg, media_type="image/svg+xml")


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(project_id: str, settings: SettingsUpdate) -> SettingsOut:
    """Update PCMI generation settings for *project_id*."""
    return SettingsOut(map_base=settings.map_base or "scan25")
