from __future__ import annotations

from arq.connections import RedisSettings
from pydantic_settings import BaseSettings, SettingsConfigDict

from workers.extraction import run_extraction


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://localhost:6379/0"


_worker_settings = WorkerSettings()


async def noop_task(ctx: dict, message: str) -> str:
    """Tâche placeholder Phase 0. Remplacée par extraction/feasibility/pdf en phases suivantes."""
    return f"noop: {message}"


class Worker:
    """ARQ worker settings. Entry point: `arq workers.main.Worker`."""

    functions = [noop_task, run_extraction]
    redis_settings = RedisSettings.from_dsn(_worker_settings.redis_url)
    max_jobs = 10
    job_timeout = 600
    keep_result = 3600
