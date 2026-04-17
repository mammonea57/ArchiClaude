from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FIXTURES_PATH = Path(__file__).parent / "parcelles_reference.yaml"


@dataclass(frozen=True)
class ReferenceParcel:
    id: str
    address: str
    insee: str
    section: str
    numero: str
    zone_plu_code: str
    extra: dict[str, Any]


def load_reference_parcels(path: Path = DEFAULT_FIXTURES_PATH) -> list[ReferenceParcel]:
    if not path.exists():
        raise FileNotFoundError(f"Fixtures file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    parcels_raw = data.get("parcelles", [])
    parcels: list[ReferenceParcel] = []
    for raw in parcels_raw:
        known_keys = {"id", "address", "insee", "section", "numero", "zone_plu_code"}
        extra = {k: v for k, v in raw.items() if k not in known_keys}
        parcels.append(
            ReferenceParcel(
                id=raw["id"],
                address=raw["address"],
                insee=raw["insee"],
                section=raw["section"],
                numero=raw["numero"],
                zone_plu_code=raw["zone_plu_code"],
                extra=extra,
            )
        )
    return parcels
