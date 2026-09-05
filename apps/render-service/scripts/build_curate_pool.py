"""Build a curation pool — standalone fetcher for LoRA style dataset.

Streams LAION-Aesthetics with PERMISSIVE filters so the user can manually
pick keepers via the browser UI. We skip CLIP filtering entirely (the
user is the filter), keep only a broad caption keyword + aesthetic score
threshold.

Output:
    refs/style_dataset/curate_pool/
        full/<id>.jpg          # 1024-max-side images for inspection
        thumbs/<id>.jpg        # 320×320 thumbnails for the UI grid
        manifest.json          # list of {id, caption, source_url, ...}

Usage:
    ~/Desktop/ArchiClaude/apps/render-service/.venv/bin/python \
        apps/render-service/scripts/build_curate_pool.py --n=1000
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]

LAION_REPO = "dclure/laion-aesthetics-12m-umap"
LAION_LICENSE = "CC-BY-4.0 (metadata) ; image rights remain with source URL hosts"

# Caption filter — biased toward COLLECTIVE residential / mixed-use,
# the actual target market for ArchiClaude (promoteurs immobiliers IDF).
PERMISSIVE_KEYWORDS = (
    # collective housing — high priority
    "apartment building", "apartment block", "block of flats", "block of apartments",
    "multi-family", "multifamily", "multi family", "collective housing",
    "social housing", "council housing", "affordable housing", "subsidized housing",
    "mixed-use building", "mixed use development",
    "mid-rise", "mid rise", "midrise", "low-rise", "high-rise", "highrise", "high rise",
    "condominium", "condo building", "tenement",
    "residential complex", "residential development", "residential building",
    "residential block", "residential tower", "apartment tower",
    "housing project", "housing development", "housing block",
    # archviz / promoteur deliverables
    "render", "rendering", "archviz", "architectural visualization",
    "building permit", "marketing render", "promoter render",
    "real estate render", "property development",
    # generic architectural
    "build", "facad", "exter", "archi",
    "tower", "skyline", "residential", "apartment", "loft", "estate",
    "office building", "skyscraper",
    "structure", "urban", "downtown", "neighborhood", "courtyard",
    "modernist", "contemporary architecture", "minimal architecture",
    "modern building", "modern apartment", "modern facade",
    "brick", "concrete", "glass facade", "metal cladding", "wood cladding",
    "rooftop", "balcon", "terrace", "loggia",
    "house", "home", "villa", "mansion",  # kept but lower priority via NEG
)

# Hard blacklist (interiors / non-buildings / known noise sources)
HARD_REJECT_CAPTION_TERMS = (
    "interior", "kitchen", "bedroom", "living room", "bathroom",
    "yacht", "boat", "vessel", "ship",
    "portrait", "person face",
    "fantasy", "dragon", "wizard",
    "anime", "manga",
    "abstract painting",
)

BLACKLIST_HOSTS = (
    "shutterstock.com", "istockphoto.com", "gettyimages.com",
    "alamy.com", "dreamstime.com", "123rf.com", "depositphotos.com",
    "adobestock.com", "stock.adobe.com",
)

logger = logging.getLogger("archfr.curate.pool")


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _is_blacklisted(url: str) -> bool:
    h = _host(url).lower()
    return any(b in h for b in BLACKLIST_HOSTS)


def _caption_passes(caption: str) -> bool:
    c = caption.lower()
    if any(t in c for t in HARD_REJECT_CAPTION_TERMS):
        return False
    return any(k in c for k in PERMISSIVE_KEYWORDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--min-score", type=float, default=5.8,
                    help="Aesthetic score threshold (lower=more permissive)")
    ap.add_argument("--max-scan", type=int, default=80_000,
                    help="Max LAION rows to scan looking for matches")
    ap.add_argument("--thumb-size", type=int, default=320)
    ap.add_argument("--max-full-side", type=int, default=1024)
    ap.add_argument("--output-dir", type=Path,
                    default=REPO_ROOT / "refs" / "style_dataset" / "curate_pool")
    ap.add_argument("--skip-rows", type=int, default=0)
    ap.add_argument("--append", action="store_true",
                    help="Append to existing manifest instead of overwriting")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    output_dir = args.output_dir
    full_dir = output_dir / "full"
    thumbs_dir = output_dir / "thumbs"
    full_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset
    except ImportError:
        logger.error("`datasets` library not installed — pip install datasets")
        sys.exit(1)

    try:
        import requests
        from PIL import Image
    except ImportError:
        logger.error("requests / PIL not installed")
        sys.exit(1)

    t0 = time.time()
    logger.info("Loading LAION dataset stream : %s", LAION_REPO)
    ds = load_dataset(LAION_REPO, split="train", streaming=True)
    if args.skip_rows:
        ds = ds.skip(args.skip_rows)
        logger.info("Skipped %d rows", args.skip_rows)

    manifest = []
    scanned = 0
    n_skipped_score = 0
    n_skipped_caption = 0
    n_skipped_blacklist = 0
    n_dl_fail = 0

    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    }

    for row in ds:
        scanned += 1
        if scanned > args.max_scan:
            logger.warning("Reached max-scan %d", args.max_scan)
            break
        if len(manifest) >= args.n:
            break
        if scanned % 5000 == 0:
            logger.info("  scanned=%d kept=%d (score-skip=%d cap-skip=%d bl-skip=%d dl-fail=%d)",
                        scanned, len(manifest), n_skipped_score,
                        n_skipped_caption, n_skipped_blacklist, n_dl_fail)

        score = float(row.get("AESTHETIC_SCORE") or row.get("aesthetic_score") or 0.0)
        if score < args.min_score:
            n_skipped_score += 1
            continue
        caption = (row.get("TEXT") or row.get("text") or "").strip()
        if not _caption_passes(caption):
            n_skipped_caption += 1
            continue
        url = (row.get("URL") or row.get("url") or "").strip()
        if not url or _is_blacklisted(url):
            n_skipped_blacklist += 1
            continue

        img_id = "curate_" + hashlib.md5(url.encode()).hexdigest()[:10]
        dst_full = full_dir / f"{img_id}.jpg"
        dst_thumb = thumbs_dir / f"{img_id}.jpg"
        if dst_full.exists() and dst_thumb.exists():
            continue  # already fetched in a previous run

        try:
            resp = requests.get(url, headers=headers, timeout=12, allow_redirects=True)
            if resp.status_code != 200 or not resp.content:
                n_dl_fail += 1
                continue
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            if min(img.size) < 256:
                n_dl_fail += 1
                continue
            img.thumbnail((args.max_full_side, args.max_full_side), Image.LANCZOS)
            img.save(dst_full, "JPEG", quality=88)
            thumb = img.copy()
            thumb.thumbnail((args.thumb_size, args.thumb_size), Image.LANCZOS)
            thumb.save(dst_thumb, "JPEG", quality=82)
        except Exception as exc:
            n_dl_fail += 1
            continue

        manifest.append({
            "id": img_id,
            "full": f"full/{img_id}.jpg",
            "thumb": f"thumbs/{img_id}.jpg",
            "caption": caption[:300],
            "source_url": url,
            "license": LAION_LICENSE,
            "aesthetic_score": score,
        })

    manifest_path = output_dir / "manifest.json"
    if args.append and manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing_ids = {item["id"] for item in existing}
            new_items = [m for m in manifest if m["id"] not in existing_ids]
            combined = existing + new_items
            logger.info("APPEND : existing=%d + new=%d → total=%d",
                        len(existing), len(new_items), len(combined))
            manifest = combined
        except Exception as e:
            logger.warning("Could not append (%s) — overwriting", e)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    dt = time.time() - t0
    logger.info(
        "POOL DONE : kept=%d / scanned=%d in %.0fs (score-skip=%d cap-skip=%d bl-skip=%d dl-fail=%d)",
        len(manifest), scanned, dt, n_skipped_score,
        n_skipped_caption, n_skipped_blacklist, n_dl_fail,
    )
    print(f"\n✅ Pool ready: {len(manifest)} images in {output_dir}")
    print(f"   Manifest: {manifest_path}")
    print(f"   Next: python apps/render-service/scripts/generate_curate_ui.py")


if __name__ == "__main__":
    main()
