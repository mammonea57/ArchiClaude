"""Unit tests for workers.rag_ingest — JSON ingestion worker functions."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jurisprudences_json(tmp_path: Path) -> Path:
    """Write a minimal jurisprudences JSON file and return its path."""
    data = [
        {
            "id": str(uuid.uuid4()),
            "reference": "TA Paris 2023-001",
            "source": "Légifrance",
            "motif_principal": "Dépassement COS",
            "resume": "Le tribunal annule le permis en raison du dépassement du COS.",
            "decision": "Annulation",
            "commune_insee": "75056",
        },
        {
            "id": str(uuid.uuid4()),
            "reference": "CAA Versailles 2022-042",
            "source": "Légifrance",
            "motif_principal": "Prospect insuffisant",
            "resume": "La cour confirme l'annulation pour non-respect du prospect.",
            "decision": "Confirmation",
            "commune_insee": "92012",
        },
    ]
    file_path = tmp_path / "jurisprudences.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return file_path


def _write_recours_json(tmp_path: Path) -> Path:
    """Write a minimal recours JSON file and return its path."""
    data = [
        {
            "id": str(uuid.uuid4()),
            "commune_insee": "75056",
            "association": "SOS Paris Vert",
            "projet_conteste": "Tour R+12",
            "motifs": ["hauteur excessive"],
            "resultat": "rejeté",
            "resume": "Recours rejeté pour défaut d'intérêt à agir.",
        }
    ]
    file_path = tmp_path / "recours.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# ingest_jurisprudences_from_json
# ---------------------------------------------------------------------------


async def test_ingest_jurisprudences_returns_status_and_count(tmp_path: Path) -> None:
    """ingest_jurisprudences_from_json returns {status, count} for a valid JSON file."""
    from workers.rag_ingest import ingest_jurisprudences_from_json

    file_path = _write_jurisprudences_json(tmp_path)
    ctx: dict = {}

    result = await ingest_jurisprudences_from_json(ctx, file_path=str(file_path))

    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert result["count"] == 2


async def test_ingest_jurisprudences_missing_file(tmp_path: Path) -> None:
    """ingest_jurisprudences_from_json returns error status for a missing file."""
    from workers.rag_ingest import ingest_jurisprudences_from_json

    ctx: dict = {}
    result = await ingest_jurisprudences_from_json(
        ctx, file_path=str(tmp_path / "nonexistent.json")
    )

    assert result["status"] == "error"
    assert "error" in result


async def test_ingest_jurisprudences_invalid_json(tmp_path: Path) -> None:
    """ingest_jurisprudences_from_json returns error status for malformed JSON."""
    from workers.rag_ingest import ingest_jurisprudences_from_json

    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json {{{", encoding="utf-8")
    ctx: dict = {}

    result = await ingest_jurisprudences_from_json(ctx, file_path=str(bad_file))

    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# ingest_recours_from_json
# ---------------------------------------------------------------------------


async def test_ingest_recours_returns_status_and_count(tmp_path: Path) -> None:
    """ingest_recours_from_json returns {status, count} for a valid JSON file."""
    from workers.rag_ingest import ingest_recours_from_json

    file_path = _write_recours_json(tmp_path)
    ctx: dict = {}

    result = await ingest_recours_from_json(ctx, file_path=str(file_path))

    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert result["count"] == 1


async def test_ingest_recours_missing_file(tmp_path: Path) -> None:
    """ingest_recours_from_json returns error status for a missing file."""
    from workers.rag_ingest import ingest_recours_from_json

    ctx: dict = {}
    result = await ingest_recours_from_json(
        ctx, file_path=str(tmp_path / "nonexistent.json")
    )

    assert result["status"] == "error"
    assert "error" in result


async def test_ingest_recours_empty_list(tmp_path: Path) -> None:
    """ingest_recours_from_json handles an empty JSON array gracefully."""
    from workers.rag_ingest import ingest_recours_from_json

    empty_file = tmp_path / "empty.json"
    empty_file.write_text("[]", encoding="utf-8")
    ctx: dict = {}

    result = await ingest_recours_from_json(ctx, file_path=str(empty_file))

    assert result["status"] == "ok"
    assert result["count"] == 0


# ---------------------------------------------------------------------------
# Worker registration
# ---------------------------------------------------------------------------


def test_worker_has_ingest_functions() -> None:
    """Workers.main.Worker.functions includes both ingest worker functions."""
    from workers.main import Worker

    function_names = {f.__name__ for f in Worker.functions}
    assert "ingest_jurisprudences_from_json" in function_names
    assert "ingest_recours_from_json" in function_names
