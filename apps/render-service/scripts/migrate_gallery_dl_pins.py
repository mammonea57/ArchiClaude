"""Migrate gallery-dl downloaded Pinterest pins into manual_refs/.

gallery-dl downloads to its own naming scheme ; we standardise to
`pin_<pin_id>.jpg` and write a .meta.json sidecar.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MANUAL_REFS_DIR = REPO_ROOT / "refs" / "style_dataset" / "manual_refs"

from PIL import Image
import io
import re

GALLERY_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/pinterest_archi")

MANUAL_REFS_DIR.mkdir(parents=True, exist_ok=True)

n_copied = 0
n_skipped = 0
n_fail = 0
files = list(GALLERY_DIR.rglob("*"))
images = [f for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]

for src in images:
    name = src.stem
    m = re.search(r"pinterest_(\d+)", name)
    pin_id = m.group(1) if m else name
    dst = MANUAL_REFS_DIR / f"pin_{pin_id}.jpg"
    if dst.exists():
        n_skipped += 1
        continue
    try:
        img = Image.open(src).convert("RGB")
        if min(img.size) < 256:
            n_fail += 1
            continue
        img.thumbnail((1280, 1280), Image.LANCZOS)
        img.save(dst, "JPEG", quality=90)
        meta = {
            "id": f"pin_{pin_id}",
            "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
            "source_site": "pinterest:user_curated",
            "license": "User-curated Pinterest ref (R&D individual fair use)",
            "migrated_from": str(src),
        }
        (MANUAL_REFS_DIR / f"pin_{pin_id}.meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
        n_copied += 1
    except Exception as e:
        print(f"  fail {src.name}: {e}")
        n_fail += 1

print(f"✅ Migrated {n_copied} pins (skipped existing: {n_skipped}, failed: {n_fail})")
print(f"   Manual refs total: {len(list(MANUAL_REFS_DIR.glob('pin_*.jpg')))} pins + others")
