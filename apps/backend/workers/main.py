from __future__ import annotations

from arq.connections import RedisSettings
from pydantic_settings import BaseSettings, SettingsConfigDict

from workers.extraction import run_extraction
from workers.feasibility import run_feasibility_job
from workers.pcmi import generate_pcmi_dossier
from workers.pcmi6 import generate_pcmi6_render_job
from workers.pcmi6_retention import purge_old_renders
from workers.pdf import generate_pdf_job
from workers.programming import run_programming_job
from workers.rag_ingest import ingest_jurisprudences_from_json, ingest_recours_from_json


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://localhost:6379/0"


_worker_settings = WorkerSettings()


async def noop_task(ctx: dict, message: str) -> str:
    """Tâche placeholder Phase 0. Remplacée par extraction/feasibility/pdf en phases suivantes."""
    return f"noop: {message}"


class Worker:
    """ARQ worker settings. Entry point: `arq workers.main.Worker`."""

    functions = [noop_task, run_extraction, run_feasibility_job, generate_pdf_job, generate_pcmi_dossier, run_programming_job, ingest_jurisprudences_from_json, ingest_recours_from_json, generate_pcmi6_render_job, purge_old_renders]
    redis_settings = RedisSettings.from_dsn(_worker_settings.redis_url)
    max_jobs = 10
    job_timeout = 600
    keep_result = 3600
