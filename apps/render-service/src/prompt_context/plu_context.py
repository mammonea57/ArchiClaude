"""PLU rules → architectural constraints.

Strategy : the backend already exposes the PLU API + an extracted-rules table
(`plu_zone_rules_numeric`) — the right long-term move is to query that. For
the first pass we use a two-layer lookup, both indexed by (commune, sector) :

  1. ``_LOCAL_PLU_RULES`` — hard-coded defaults seeded from project memory
     (e.g. Nogent UA1 = 80% emprise, H 18m, R+5). Acts as a safety net.
  2. ``plu_rules_cache.json`` — auto-extracted rules written by
     ``apps/backend/scripts/pull_plu.py`` for any commune × zone in France.
     Loaded once at module import. **Cache wins on conflict.**

When the backend's ``/plu/zone/.../rules`` endpoint becomes structured enough,
swap ``_lookup_local`` with ``_lookup_api``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .reasoning import PluConstraints

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local PLU rule database — seeded from project memory + official PLU PDFs.
# Index by (commune_lower, sector_upper). Add entries as new communes onboard.
# ---------------------------------------------------------------------------

_LOCAL_PLU_RULES: dict[tuple[str, str], dict[str, Any]] = {
    # Nogent-sur-Marne UA1 — secteur dense centre-ville, mémoire projet.
    ("nogent-sur-marne", "UA1"): {
        "emprise_max_pct": 0.80,
        "hauteur_max_m": 18.0,
        "hauteur_max_storeys": 5,
        # Article UA1.11 prescrit façades en pierre meulière OU enduit ton clair,
        # toiture zinc à la française OU tuile plate, RDC pierre/brique commercial.
        "materials_prescribed": ["pierre_meuliere", "enduit_clair", "brique"],
        "toiture_prescribed": ["zinc", "tuile_plate"],
        "retrait_limites_m": 3.0,
        "pleine_terre_pct": 0.10,
        "article_refs": ["UA1.9", "UA1.10", "UA1.11"],
    },
    # Default / fallback for unknown UA sectors in IDF — conservative defaults.
    ("__default__", "UA"): {
        "emprise_max_pct": 0.60,
        "hauteur_max_m": 15.0,
        "hauteur_max_storeys": 4,
        "materials_prescribed": ["enduit_clair"],
        "toiture_prescribed": ["zinc", "tuile_plate", "terrasse"],
        "retrait_limites_m": 3.0,
        "pleine_terre_pct": 0.20,
        "article_refs": [],
    },
}


# ---------------------------------------------------------------------------
# JSON cache (auto-extracted by apps/backend/scripts/pull_plu.py).
# Loaded once at module import — restart the render-service to pick up changes.
# Cache wins on conflict with `_LOCAL_PLU_RULES`.
# ---------------------------------------------------------------------------

_CACHE_PATH = Path(__file__).with_name("plu_rules_cache.json")


def _load_cache() -> dict[tuple[str, str], dict[str, Any]]:
    """Read plu_rules_cache.json and return it indexed by (commune, sector)."""
    if not _CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("plu_rules_cache unreadable, ignoring: %s", exc)
        return {}

    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rules in entries.items():
        if not isinstance(rules, dict) or "|" not in key:
            continue
        commune, sector = key.split("|", 1)
        out[(commune.strip().lower(), sector.strip().upper())] = rules
    return out


_CACHE_PLU_RULES: dict[tuple[str, str], dict[str, Any]] = _load_cache()


def _merged_rules(commune: str, sector: str) -> dict[str, Any] | None:
    """Return cache ∪ local for (commune, sector), with cache winning."""
    key = (commune, sector)
    local = _LOCAL_PLU_RULES.get(key)
    cached = _CACHE_PLU_RULES.get(key)
    if local is None and cached is None:
        return None
    merged: dict[str, Any] = {}
    if local:
        merged.update(local)
    if cached:
        # Drop _meta from the merged constraint dict — caller doesn't need it
        merged.update({k: v for k, v in cached.items() if k != "_meta"})
    return merged


def _commune_from_bm(bm: dict[str, Any], project_id: str | None = None) -> str | None:
    """Extract commune name from BM address OR (fallback) the project name.

    The BM's metadata.address is often the validation label ("Projet zone UA1"),
    not the parcel address. So we try, in order :
      1. BM metadata.address
      2. Project endpoint name (e.g. "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne")
    """
    candidates: list[str] = []
    addr = (bm.get("model_json", bm).get("metadata") or {}).get("address", "") or ""
    candidates.append(addr.lower())
    if project_id:
        try:
            import httpx
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"http://localhost:8000/api/v1/projects/{project_id}")
                if r.status_code == 200:
                    candidates.append((r.json().get("name") or "").lower())
        except Exception:
            pass

    known = ["nogent-sur-marne", "vincennes", "saint-mandé", "saint-maurice",
             "paris", "la queue-en-brie"]
    for source in candidates:
        for c in known:
            if c in source:
                return c
    return None


def _sector_from_bm(bm: dict[str, Any]) -> str | None:
    """Extract PLU sector code from the BM metadata.address (e.g. 'UA1')."""
    addr = (bm.get("model_json", bm).get("metadata") or {}).get("address", "") or ""
    # Look for a token like UA1, UA, UB1, UC2, etc.
    import re
    m = re.search(r"\b(U[A-Z][0-9]?)\b", addr.upper())
    return m.group(1) if m else None


def fetch_plu_constraints(bm: dict[str, Any], project_id: str | None = None) -> PluConstraints:
    """Resolve the PLU constraints applicable to the project's parcel.

    Priority :
      1. Exact (commune, sector) match in `_LOCAL_PLU_RULES`.
      2. Fall back to (`__default__`, sector_letter_only) — e.g. UA1 → UA.
      3. Empty constraints (caller should check `.sector is None`).

    Future : when the backend `/plu/zone/{id}/rules` returns structured numeric
    rules, swap this function's body to query that endpoint via httpx.
    """
    commune = _commune_from_bm(bm, project_id=project_id)
    sector = _sector_from_bm(bm)

    rules: dict[str, Any] | None = None
    if commune and sector:
        rules = _merged_rules(commune, sector)
    if rules is None and sector:
        # Fall back on default for the sector family (UA, UB, UC...)
        sector_family = sector[:2]  # "UA1" → "UA"
        rules = _merged_rules("__default__", sector_family)

    if rules is None:
        return PluConstraints(sector=sector)

    return PluConstraints(
        sector=sector,
        emprise_max_pct=rules.get("emprise_max_pct"),
        hauteur_max_m=rules.get("hauteur_max_m"),
        hauteur_max_storeys=rules.get("hauteur_max_storeys"),
        materials_prescribed=list(rules.get("materials_prescribed", [])),
        toiture_prescribed=list(rules.get("toiture_prescribed", [])),
        retrait_limites_m=rules.get("retrait_limites_m"),
        pleine_terre_pct=rules.get("pleine_terre_pct"),
        article_refs=list(rules.get("article_refs", [])),
    )
