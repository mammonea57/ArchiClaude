"""ARQ worker task for PCMI dossier generation (v1 stub)."""

from __future__ import annotations


async def generate_pcmi_dossier(
    ctx: dict,
    *,
    project_id: str,
    map_base: str = "scan25",
) -> dict:
    """Generate the full PCMI dossier for *project_id*.

    This is a stub for v1 — the full implementation (calling the renderer,
    assembler, and R2 upload) will be wired in a subsequent sprint.
    """
    return {"status": "done", "project_id": project_id}
