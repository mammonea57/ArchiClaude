"""Merge curate_pool sub-manifests into a single manifest.json.

Reads any of:
  - manifest.json (existing — typically the LAION/original pool)
  - manifest_wikimedia.json
  - manifest_pexels_unsplash.json
  - manifest_pexels.json
  - manifest_unsplash.json

Backs the existing manifest.json up to manifest_pre_merge.json, then writes
the deduplicated union (by id) to manifest.json.
"""

from __future__ import annotations
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

SUB_MANIFESTS = [
    "manifest_wikimedia.json",
    "manifest_pexels_unsplash.json",
    "manifest_pexels.json",
    "manifest_unsplash.json",
]


def main() -> None:
    main_path = POOL_DIR / "manifest.json"
    seen_ids: set[str] = set()
    combined: list[dict] = []
    source_counts: dict[str, int] = {}

    if main_path.exists():
        for item in json.loads(main_path.read_text(encoding="utf-8")):
            iid = item.get("id")
            if iid and iid not in seen_ids:
                seen_ids.add(iid)
                combined.append(item)
        source_counts["manifest.json (original)"] = len(combined)
        # Backup
        backup = POOL_DIR / "manifest_pre_merge.json"
        shutil.copy2(main_path, backup)
        print(f"backed up manifest.json -> {backup.name}")

    for name in SUB_MANIFESTS:
        p = POOL_DIR / name
        if not p.exists():
            print(f"skip: {name} (not found)")
            continue
        items = json.loads(p.read_text(encoding="utf-8"))
        added = 0
        for it in items:
            iid = it.get("id")
            if iid and iid not in seen_ids:
                seen_ids.add(iid)
                combined.append(it)
                added += 1
        source_counts[name] = added
        print(f"merged: {name} -> +{added} new (file had {len(items)})")

    main_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"\nFinal manifest.json: {len(combined)} unique items")
    print("Breakdown:")
    for k, v in source_counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
