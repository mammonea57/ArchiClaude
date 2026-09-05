"""Recover user-selected images that were moved by filter passes.

The user's curate.html ❤️ selections take precedence over the auto
CLIP filters. If a selected ID isn't in the live pool, search the
_filtered_photos/ and _filtered_out/ folders for it and restore.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"
MANUAL_REFS_DIR = REPO_ROOT / "refs" / "style_dataset" / "manual_refs"

FILTERED_SUBDIRS = ("_filtered_out", "_filtered_photos")


def find_image(img_id: str) -> Path | None:
    """Search pool/full and all _filtered_* subdirs for <img_id>.jpg."""
    p = POOL_DIR / "full" / f"{img_id}.jpg"
    if p.exists():
        return p
    for sub in FILTERED_SUBDIRS:
        p = POOL_DIR / sub / "full" / f"{img_id}.jpg"
        if p.exists():
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("selection_json", type=Path)
    args = ap.parse_args()

    sel = json.loads(args.selection_json.read_text(encoding="utf-8"))
    ids = sel.get("selection", [])
    print(f"Recovering {len(ids)} user-selected ids...")
    MANUAL_REFS_DIR.mkdir(parents=True, exist_ok=True)

    n_copied = 0
    n_missing = 0
    for img_id in ids:
        src = find_image(img_id)
        if not src:
            print(f"  ❌ NOT FOUND : {img_id}")
            n_missing += 1
            continue
        dst = MANUAL_REFS_DIR / f"{img_id}.jpg"
        if dst.exists():
            continue
        shutil.copy2(src, dst)
        # Write minimal meta
        meta = {"id": img_id, "source_path": str(src),
                "user_selected": True, "recovered_at": sel.get("exported_at")}
        (MANUAL_REFS_DIR / f"{img_id}.meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
        n_copied += 1
    print(f"✅ Recovered {n_copied} user picks. Missing: {n_missing}")


if __name__ == "__main__":
    main()
