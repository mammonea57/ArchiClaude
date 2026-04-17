"""Agency settings API routes — branding and contact management."""

from __future__ import annotations

from fastapi import APIRouter

from schemas.agency import AgencySettingsOut, AgencySettingsUpdate

router = APIRouter(prefix="/agency", tags=["agency"])


@router.get("/settings", response_model=AgencySettingsOut)
async def get_settings() -> AgencySettingsOut:
    """Get agency settings for the current user.

    v1: Returns empty placeholder. Auth + DB lookup deferred.
    """
    return AgencySettingsOut(
        agency_name=None,
        logo_url=None,
        contact_email=None,
        brand_primary_color=None,
    )


@router.put("/settings", response_model=AgencySettingsOut)
async def update_settings(body: AgencySettingsUpdate) -> AgencySettingsOut:
    """Update agency settings for the current user.

    v1: Echoes back the provided values. Persistence deferred.
    """
    return AgencySettingsOut(
        agency_name=body.agency_name,
        logo_url=None,
        contact_email=body.contact_email,
        brand_primary_color=body.brand_primary_color,
    )


@router.post("/logo")
async def upload_logo() -> dict:
    """Upload agency logo. v1: placeholder returns stub URL."""
    return {"logo_url": "placeholder"}
