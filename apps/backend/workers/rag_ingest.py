"""ARQ worker tasks for RAG data ingestion from JSON files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def ingest_jurisprudences_from_json(ctx: dict, *, file_path: str) -> dict:
    """Load jurisprudences from a JSON file.

    Reads the JSON file at *file_path*, logs the record count, and returns a
    result dict. Actual embedding generation and DB insertion are deferred until
    a DB session is wired into the worker context.

    Args:
        ctx: ARQ job context.
        file_path: Absolute path to a JSON file containing a list of
            jurisprudence dicts.

    Returns:
        ``{"status": "ok", "count": <n>}`` on success, or
        ``{"status": "error", "error": <message>}`` on failure.
    """
    path = Path(file_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        msg = f"Fichier introuvable : {file_path}"
        logger.error(msg)
        return {"status": "error", "error": msg}
    except OSError as exc:
        msg = f"Erreur lecture fichier : {exc}"
        logger.error(msg)
        return {"status": "error", "error": msg}

    try:
        records: list = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"JSON invalide dans {file_path} : {exc}"
        logger.error(msg)
        return {"status": "error", "error": msg}

    count = len(records)
    logger.info(
        "ingest_jurisprudences_from_json: %d enregistrements chargés depuis %s",
        count,
        file_path,
    )
    # TODO (Phase 6 DB wiring): generate embeddings and upsert into pgvector table
    return {"status": "ok", "count": count}


async def ingest_recours_from_json(ctx: dict, *, file_path: str) -> dict:
    """Load recours cases from a JSON file.

    Reads the JSON file at *file_path*, logs the record count, and returns a
    result dict. Actual embedding generation and DB insertion are deferred until
    a DB session is wired into the worker context.

    Args:
        ctx: ARQ job context.
        file_path: Absolute path to a JSON file containing a list of
            recours case dicts.

    Returns:
        ``{"status": "ok", "count": <n>}`` on success, or
        ``{"status": "error", "error": <message>}`` on failure.
    """
    path = Path(file_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        msg = f"Fichier introuvable : {file_path}"
        logger.error(msg)
        return {"status": "error", "error": msg}
    except OSError as exc:
        msg = f"Erreur lecture fichier : {exc}"
        logger.error(msg)
        return {"status": "error", "error": msg}

    try:
        records: list = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"JSON invalide dans {file_path} : {exc}"
        logger.error(msg)
        return {"status": "error", "error": msg}

    count = len(records)
    logger.info(
        "ingest_recours_from_json: %d enregistrements chargés depuis %s",
        count,
        file_path,
    )
    # TODO (Phase 6 DB wiring): generate embeddings and upsert into pgvector table
    return {"status": "ok", "count": count}
