"""Apply the user's curated selection from the browser UI.

Reads a `selection.json` file (downloaded from curate.html via the
"Export selection" button), looks up each picked id in the pool
manifest, and copies the corresponding full-resolution images into
`refs/style_dataset/manual_refs/` with caption sidecars.

Output structure:
    refs/style_dataset/manual_refs/
        <id>.jpg                  # full image
        <id>.txt                  # caption sidecar (LoRA training pickup)
        <id>.meta.json            # source URL + license attribution

Usage:
    .venv/bin/python apps/render-service/scripts/apply_curate_selection.py \
        ~/Downloads/selection.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"
DEFAULT_MANUAL_REFS_DIR = REPO_ROOT / "refs" / "style_dataset" / "manual_refs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("selection_json", type=Path,
                    help="selection.json downloaded from curate.html")
    ap.add_argument("--pool-dir", type=Path, default=DEFAULT_POOL_DIR)
    ap.add_argument("--manual-refs-dir", type=Path, default=DEFAULT_MANUAL_REFS_DIR)
    ap.add_argument("--overwrite", action="store_true",
                    help="Overwrite existing files in manual_refs/")
    args = ap.parse_args()

    if not args.selection_json.exists():
        print(f"Selection file not found : {args.selection_json}")
        sys.exit(1)

    manifest_path = args.pool_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Pool manifest not found : {manifest_path}")
        sys.exit(1)

    selection_data = json.loads(args.selection_json.read_text(encoding="utf-8"))
    selected_ids = set(selection_data.get("selection", []))
    print(f"Selection has {len(selected_ids)} ids (exported {selection_data.get('exported_at', 'unknown')})")

    manifest = {item["id"]: item for item in json.loads(manifest_path.read_text(encoding="utf-8"))}

    args.manual_refs_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped_missing = 0
    skipped_existing = 0
    for sid in selected_ids:
        item = manifest.get(sid)
        if not item:
            skipped_missing += 1
            print(f"  ⚠️  Manifest miss: {sid}")
            continue
        src_full = args.pool_dir / item["full"]
        if not src_full.exists():
            skipped_missing += 1
            print(f"  ⚠️  Source image missing: {src_full}")
            continue
        dst_img = args.manual_refs_dir / f"{sid}.jpg"
        dst_txt = args.manual_refs_dir / f"{sid}.txt"
        dst_meta = args.manual_refs_dir / f"{sid}.meta.json"
        if dst_img.exists() and not args.overwrite:
            skipped_existing += 1
            continue
        shutil.copy2(src_full, dst_img)
        dst_txt.write_text(item.get("caption", ""), encoding="utf-8")
        dst_meta.write_text(json.dumps({
            "id": sid,
            "source_url": item.get("source_url"),
            "license": item.get("license"),
            "aesthetic_score": item.get("aesthetic_score"),
            "added_from": "curate_pool",
            "selection_exported_at": selection_data.get("exported_at"),
        }, indent=2), encoding="utf-8")
        copied += 1

    print(f"\n✅ Applied: copied {copied} new images to {args.manual_refs_dir}")
    if skipped_existing:
        print(f"   ({skipped_existing} already existed — use --overwrite to replace)")
    if skipped_missing:
        print(f"   ⚠️  {skipped_missing} ids were missing from the pool")


if __name__ == "__main__":
    main()
