"""ARQ worker for PCMI6 render generation.

For v1 this is a stub. Full pipeline wiring happens when DB session is
available in worker context.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def generate_pcmi6_render_job(ctx, *, render_id: str, project_id: str):
    """Stub: full pipeline to be wired in a follow-up."""
    logger.info(f"PCMI6 render job stub: render_id={render_id} project_id={project_id}")
    return {"status": "done", "render_id": render_id}
