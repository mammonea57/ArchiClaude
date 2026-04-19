"""PCMI6 render endpoints — create, list, update, delete, regenerate."""
import uuid

from fastapi import APIRouter, HTTPException

from schemas.pcmi6 import RenderCreate, RenderListResponse, RenderOut, RenderUpdate  # noqa: F401

router = APIRouter(prefix="/projects/{project_id}/pcmi6", tags=["pcmi6"])


@router.post("/renders", status_code=202)
async def create_render(project_id: str, body: RenderCreate):
    """Create a PCMI6 render job.

    For v1 returns a placeholder render_id. Multipart upload of layers
    (mask, normal, depth) will be wired when DB session is available.
    """
    render_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    return {"render_id": render_id, "job_id": job_id, "status": "queued"}


@router.get("/renders", response_model=RenderListResponse)
async def list_renders(project_id: str):
    """List all renders for a project."""
    return RenderListResponse(items=[], total=0)


@router.get("/renders/{render_id}", response_model=RenderOut)
async def get_render(project_id: str, render_id: str):
    """Get a specific render."""
    raise HTTPException(status_code=404, detail="Render not found")


@router.patch("/renders/{render_id}")
async def update_render(project_id: str, render_id: str, update: RenderUpdate):
    """Update render metadata (label, selected_for_pc)."""
    return {"status": "updated"}


@router.delete("/renders/{render_id}", status_code=204)
async def delete_render(project_id: str, render_id: str):
    """Delete a render."""
    return


@router.post("/renders/{render_id}/regenerate_variants", status_code=202)
async def regenerate_variants(project_id: str, render_id: str):
    """Regenerate 3 variants with different seeds."""
    return {"status": "queued", "variant_jobs": [str(uuid.uuid4()) for _ in range(3)]}
