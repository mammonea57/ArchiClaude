"""Sync any image files on disk that aren't yet in manifest.json.

Useful after a fetch script crashes before finishing its final manifest write.
Scans curate_pool/full/ for *.jpg files, cross-references with manifest, and
adds any missing entries with sensible defaults so they show up in the UI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_orphans")


def main():
    manifest_path = POOL_DIR / "manifest.json"
    full_dir = POOL_DIR / "full"
    thumbs_dir = POOL_DIR / "thumbs"

    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    known_ids = {it["id"] for it in manifest}
    logger.info("Manifest has %d items currently", len(manifest))

    on_disk = sorted(full_dir.glob("*.jpg"))
    logger.info("Found %d images on disk in full/", len(on_disk))

    added = 0
    for full_path in on_disk:
        img_id = full_path.stem  # e.g. "render_laion_a1b2c3"
        if img_id in known_ids:
            continue
        thumb_path = thumbs_dir / f"{img_id}.jpg"
        if not thumb_path.exists():
            continue  # no thumb → skip

        # Infer source from prefix
        if img_id.startswith("render_laion_"):
            source_site = "laion-aesthetics:render-filtered"
            license_ = "LAION-Aesthetics (CC-BY-4.0 metadata, image rights at source)"
        elif img_id.startswith("render_wm_"):
            source_site = "wikimedia:renderings"
            license_ = "Wikimedia Commons (CC-BY-SA / CC0 / PD)"
        elif img_id.startswith("ytp_"):
            source_site = "youtube:promoteur"
            license_ = "YouTube fair use commentary/research (R&D individual)"
        elif img_id.startswith("openverse_"):
            source_site = "openverse:flickr"
            license_ = "CC-BY / CC-BY-SA / CC0 (Openverse aggregator)"
        elif img_id.startswith("wikimedia_"):
            source_site = "wikimedia:archviz"
            license_ = "Wikimedia Commons"
        elif img_id.startswith("curate_"):
            source_site = "laion-aesthetics"
            license_ = "LAION-Aesthetics (CC-BY-4.0 metadata, image rights at source)"
        else:
            source_site = "unknown"
            license_ = "unknown"

        manifest.append({
            "id": img_id,
            "full": f"full/{img_id}.jpg",
            "thumb": f"thumbs/{img_id}.jpg",
            "caption": f"(orphan synced) {img_id}",
            "source_url": "",
            "license": license_,
            "aesthetic_score": 6.0,
            "source_site": source_site,
        })
        added += 1

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Added %d orphans, manifest now has %d items", added, len(manifest))


if __name__ == "__main__":
    main()
