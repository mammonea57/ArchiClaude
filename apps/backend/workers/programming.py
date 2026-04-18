"""ARQ worker for the architectural programming pipeline.

Full pipeline (classify → setback → envelope → solve → distribute → plans)
is stubbed for v1. DB integration and actual pipeline execution are wired
in subsequent phases when project state management is in place.
"""

from __future__ import annotations


async def run_programming_job(
    ctx: dict,
    *,
    project_id: str,
    parcelle_geojson: dict,
    segments_data: list[dict],
    hauteur_max_m: float,
    mix_brief: dict,
    risk_score: int,
    **kwargs: object,
) -> dict:
    """Full programming pipeline: classify → setback → envelope → solve → distribute → plans.

    v1: stubbed — actual DB integration and pipeline execution deferred to
    subsequent phases.
    """
    # TODO(phase 2): load project from DB, run full pipeline, persist results
    return {"status": "done", "project_id": project_id}
