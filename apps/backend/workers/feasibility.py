"""ARQ worker task for running feasibility analysis in the background."""

from __future__ import annotations


async def run_feasibility_job(
    ctx: dict,
    *,
    project_id: str,
    terrain_geojson: dict,
    numeric_rules_dict: dict,
    brief_dict: dict,
    monuments: list | None = None,
    risques: list | None = None,
    servitudes_gpu: list | None = None,
    altitude_sol_m: float | None = None,
    commune_sru_statut: str = "non_soumise",
    annee_cible_pc: int = 2025,
    **kwargs,
) -> dict:
    """Run the feasibility engine for a project in an ARQ worker context.

    Args:
        ctx: ARQ job context (contains Redis connection, job_id, etc.).
        project_id: UUID of the project being analyzed.
        terrain_geojson: GeoJSON geometry (WGS84) of the terrain.
        numeric_rules_dict: Serialised NumericRules as a plain dict.
        brief_dict: Serialised Brief as a plain dict.
        monuments: Optional pre-fetched monument results.
        risques: Optional pre-fetched risk results.
        servitudes_gpu: Optional pre-fetched GPU servitudes.
        altitude_sol_m: Ground altitude in metres NGF.
        commune_sru_statut: SRU status of the commune.
        annee_cible_pc: Target year for building permit submission.
        **kwargs: Ignored extra keyword arguments for forward-compatibility.

    Returns:
        Dict with ``{"status": "done", "result": <FeasibilityResult.model_dump()>}``.
    """
    from core.feasibility.engine import run_feasibility
    from core.feasibility.schemas import Brief
    from core.plu.schemas import NumericRules

    rules = NumericRules(**numeric_rules_dict)
    brief = Brief(**brief_dict)

    result = run_feasibility(
        terrain_geojson=terrain_geojson,
        numeric_rules=rules,
        brief=brief,
        monuments=monuments,
        risques=risques,
        servitudes_gpu=servitudes_gpu,
        altitude_sol_m=altitude_sol_m,
        commune_sru_statut=commune_sru_statut,
        annee_cible_pc=annee_cible_pc,
    )

    return {"status": "done", "project_id": project_id, "result": result.model_dump()}
