"""Merge curate_pool manifests + download missing images.

After the parallel agents (Wikimedia + Openverse) crashed mid-run,
this script:
1. Loads all 3 manifests (original, wikimedia, pexels_unsplash/openverse)
2. Downloads any missing images referenced in manifests
3. Writes a unified manifest.json (with pre-merge backup)
4. Reports final state

Pure-Python, no Modal, no API key required (Openverse + Wikimedia CC
images are direct HTTP downloads).
"""

from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path

import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("merge")


def download_image(url: str, dst_full: Path, dst_thumb: Path,
                   max_full_side: int = 1024, thumb_size: int = 320) -> bool:
    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": UA},
                            allow_redirects=True)
        if resp.status_code != 200 or not resp.content:
            return False
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        if min(img.size) < 256:
            return False
        img.thumbnail((max_full_side, max_full_side), Image.LANCZOS)
        img.save(dst_full, "JPEG", quality=88)
        thumb = img.copy()
        thumb.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
        thumb.save(thumb_path := dst_thumb, "JPEG", quality=82)
        return True
    except Exception as e:
        logger.debug("DL fail %s : %s", url, e)
        return False


def main():
    full_dir = POOL_DIR / "full"
    thumbs_dir = POOL_DIR / "thumbs"
    full_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    main_manifest = POOL_DIR / "manifest.json"
    wm_manifest = POOL_DIR / "manifest_wikimedia.json"
    pu_manifest = POOL_DIR / "manifest_pexels_unsplash.json"

    items_main = json.loads(main_manifest.read_text()) if main_manifest.exists() else []
    items_wm = json.loads(wm_manifest.read_text()) if wm_manifest.exists() else []
    items_pu = json.loads(pu_manifest.read_text()) if pu_manifest.exists() else []

    logger.info("Loaded manifests : main=%d wikimedia=%d pexels/openverse=%d",
                len(items_main), len(items_wm), len(items_pu))

    # Backup the existing manifest
    if main_manifest.exists():
        backup = POOL_DIR / "manifest_pre_merge.json"
        backup.write_text(main_manifest.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("Backed up main manifest → %s", backup.name)

    # Deduplicate by ID
    seen_ids = set()
    combined = []
    for item in items_main + items_wm + items_pu:
        iid = item.get("id")
        if not iid or iid in seen_ids:
            continue
        seen_ids.add(iid)
        combined.append(item)
    logger.info("Combined (dedup) : %d items", len(combined))

    # Download missing images
    n_downloaded = 0
    n_already = 0
    n_fail = 0
    n_no_url = 0
    for item in combined:
        iid = item["id"]
        dst_full = full_dir / f"{iid}.jpg"
        dst_thumb = thumbs_dir / f"{iid}.jpg"
        if dst_full.exists() and dst_thumb.exists():
            n_already += 1
            continue
        url = item.get("source_url") or item.get("thumb_url") or item.get("full_url")
        if not url:
            n_no_url += 1
            continue
        if download_image(url, dst_full, dst_thumb):
            n_downloaded += 1
            if n_downloaded % 10 == 0:
                logger.info("  downloaded %d so far", n_downloaded)
        else:
            n_fail += 1
        time.sleep(0.3)

    # Drop items whose image we couldn't acquire
    final = []
    for item in combined:
        iid = item["id"]
        if (full_dir / f"{iid}.jpg").exists() and (thumbs_dir / f"{iid}.jpg").exists():
            final.append(item)
    logger.info("Final manifest after image validation : %d items", len(final))

    main_manifest.write_text(json.dumps(final, indent=2), encoding="utf-8")
    logger.info("DONE : already=%d downloaded=%d fail=%d no_url=%d → kept=%d",
                n_already, n_downloaded, n_fail, n_no_url, len(final))


if __name__ == "__main__":
    main()
