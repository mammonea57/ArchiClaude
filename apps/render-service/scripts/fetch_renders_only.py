"""Fetch ONLY 3D archviz renders (no real photos) from LAION + Wikimedia.

Strategy:
1. LAION-Aesthetics streaming with HARD caption requirement : must contain
   one of (render, rendering, archviz, visualization, cgi, lumion, v-ray,
   twinmotion, unreal engine, unity, sketchup render, blender render,
   3ds max, photoreal cgi, illustration architectural)
2. Wikimedia Commons "Architectural renderings" + sibling categories.

Adds to existing manifest, with id prefixes `render_` for traceability.
After running, pair with filter_render_vs_photo.py to remove residual photos.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

LAION_REPO = "dclure/laion-aesthetics-12m-umap"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Caption MUST contain at least one of these tokens (LAION filter)
RENDER_KEYWORDS = (
    "render", "rendering", "archviz", "arch viz",
    "architectural visualization", "architectural illustration",
    "cgi", "computer graphics", "computer-generated",
    "lumion", "v-ray", "vray", "twinmotion", "unreal engine",
    "sketchup render", "blender render", "3ds max",
    "photoreal cgi", "artist impression", "artists impression",
    "competition proposal", "winning proposal",
    "unbuilt", "design proposal", "design competition",
    "showroom render", "marketing render", "future development",
)

# Wikimedia categories specifically for rendered/illustrated architecture
WIKIMEDIA_RENDER_CATEGORIES = [
    "Category:Architectural renderings",
    "Category:Architectural illustrations",
    "Category:Architectural drawings",
    "Category:Architectural visualization",
    "Category:Computer-generated architectural images",
    "Category:CAD drawings",
    "Category:3D models of buildings",
    "Category:Architectural projects",
    "Category:Unbuilt architectural projects",
    "Category:Architectural design",
]

logger = logging.getLogger("archfr.renders_only")


def fetch_laion_renders(n: int, min_score: float, max_scan: int,
                         skip_rows: int, full_dir: Path,
                         thumbs_dir: Path) -> list[dict]:
    from datasets import load_dataset
    ds = load_dataset(LAION_REPO, split="train", streaming=True)
    if skip_rows > 0:
        ds = ds.skip(skip_rows)

    items: list[dict] = []
    scanned = 0
    cap_skip = 0
    score_skip = 0
    dl_fail = 0

    for row in ds:
        scanned += 1
        if scanned > max_scan or len(items) >= n:
            break
        if scanned % 5000 == 0:
            logger.info("  LAION scanned=%d kept=%d (cap-skip=%d score-skip=%d dl-fail=%d)",
                        scanned, len(items), cap_skip, score_skip, dl_fail)

        score = float(row.get("AESTHETIC_SCORE") or row.get("aesthetic_score") or 0.0)
        if score < min_score:
            score_skip += 1
            continue
        caption = (row.get("TEXT") or row.get("text") or "").strip().lower()
        if not any(k in caption for k in RENDER_KEYWORDS):
            cap_skip += 1
            continue
        url = (row.get("URL") or row.get("url") or "").strip()
        if not url:
            continue

        img_id = "render_laion_" + hashlib.md5(url.encode()).hexdigest()[:8]
        dst_full = full_dir / f"{img_id}.jpg"
        dst_thumb = thumbs_dir / f"{img_id}.jpg"
        if dst_full.exists() and dst_thumb.exists():
            continue

        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=12, allow_redirects=True)
            if resp.status_code != 200 or not resp.content:
                dl_fail += 1
                continue
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            if min(img.size) < 256:
                dl_fail += 1
                continue
            img.thumbnail((1024, 1024), Image.LANCZOS)
            img.save(dst_full, "JPEG", quality=88)
            thumb = img.copy()
            thumb.thumbnail((320, 320), Image.LANCZOS)
            thumb.save(dst_thumb, "JPEG", quality=82)
        except Exception:
            dl_fail += 1
            continue

        items.append({
            "id": img_id,
            "full": f"full/{img_id}.jpg",
            "thumb": f"thumbs/{img_id}.jpg",
            "caption": caption[:280],
            "source_url": url,
            "license": "LAION-Aesthetics metadata (CC-BY-4.0) ; image rights at source URL",
            "aesthetic_score": score,
            "source_site": "laion-aesthetics:render-filtered",
        })

    logger.info("LAION final : kept=%d (cap-skip=%d score-skip=%d dl-fail=%d)",
                len(items), cap_skip, score_skip, dl_fail)
    return items


def fetch_wikimedia_render_categories(total_cap: int, per_category: int,
                                       full_dir: Path,
                                       thumbs_dir: Path) -> list[dict]:
    items: list[dict] = []
    for cat in WIKIMEDIA_RENDER_CATEGORIES:
        if len(items) >= total_cap:
            break
        logger.info("→ Wikimedia category : %s", cat)
        try:
            url = "https://commons.wikimedia.org/w/api.php?" + urlencode({
                "action": "query",
                "list": "categorymembers",
                "cmtitle": cat,
                "cmtype": "file",
                "cmlimit": per_category,
                "format": "json",
                "formatversion": "2",
            })
            r = requests.get(url, timeout=20,
                             headers={"User-Agent": "ArchiClaude-LoRA-renders/0.1"})
            r.raise_for_status()
            titles = [m["title"] for m in r.json().get("query", {}).get("categorymembers", [])
                      if m.get("title", "").startswith("File:")]
        except Exception as e:
            logger.warning("  cat fetch fail %s : %s", cat, e)
            continue
        logger.info("  found %d titles", len(titles))

        if not titles:
            continue
        for batch_start in range(0, len(titles), 25):
            batch = titles[batch_start:batch_start + 25]
            try:
                url = "https://commons.wikimedia.org/w/api.php?" + urlencode({
                    "action": "query",
                    "prop": "imageinfo",
                    "titles": "|".join(batch),
                    "iiprop": "url|size|extmetadata|mime",
                    "iiurlwidth": "1024",
                    "format": "json",
                    "formatversion": "2",
                })
                r = requests.get(url, timeout=30,
                                 headers={"User-Agent": "ArchiClaude-LoRA-renders/0.1"})
                r.raise_for_status()
            except Exception as e:
                logger.warning("  imageinfo fail : %s", e)
                continue
            for p in r.json().get("query", {}).get("pages", []):
                info = p.get("imageinfo")
                if not info:
                    continue
                ii = info[0]
                mime = ii.get("mime", "")
                if not mime.startswith(("image/jpeg", "image/png")):
                    continue
                if ii.get("width", 0) < 600:
                    continue
                src_url = ii.get("thumburl") or ii.get("url")
                if not src_url:
                    continue
                img_id = "render_wm_" + hashlib.md5(src_url.encode()).hexdigest()[:8]
                dst_full = full_dir / f"{img_id}.jpg"
                dst_thumb = thumbs_dir / f"{img_id}.jpg"
                if dst_full.exists() and dst_thumb.exists():
                    continue
                try:
                    resp = requests.get(src_url, timeout=20,
                                        headers={"User-Agent": "ArchiClaude-LoRA-renders/0.1"})
                    if resp.status_code != 200 or len(resp.content) < 1024:
                        continue
                    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                    if min(img.size) < 256:
                        continue
                    img.thumbnail((1024, 1024), Image.LANCZOS)
                    img.save(dst_full, "JPEG", quality=88)
                    thumb = img.copy()
                    thumb.thumbnail((320, 320), Image.LANCZOS)
                    thumb.save(dst_thumb, "JPEG", quality=82)
                except Exception:
                    continue

                ext = ii.get("extmetadata", {})
                items.append({
                    "id": img_id,
                    "full": f"full/{img_id}.jpg",
                    "thumb": f"thumbs/{img_id}.jpg",
                    "caption": (((ext.get("ImageDescription") or {}).get("value") or "") or p.get("title", ""))[:280],
                    "source_url": src_url,
                    "source_page": ii.get("descriptionurl", ""),
                    "license": (ext.get("LicenseShortName") or {}).get("value", "unknown"),
                    "aesthetic_score": 6.0,
                    "source_site": "wikimedia:renderings",
                    "wikimedia_category": cat,
                })
                if len(items) >= total_cap:
                    break
            if len(items) >= total_cap:
                break
            time.sleep(0.5)
        logger.info("  cat-cumulative : %d items", len(items))

    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-laion", type=int, default=600)
    ap.add_argument("--n-wikimedia", type=int, default=400)
    ap.add_argument("--laion-min-score", type=float, default=5.5)
    ap.add_argument("--laion-max-scan", type=int, default=300_000)
    ap.add_argument("--laion-skip-rows", type=int, default=0)
    ap.add_argument("--pool-dir", type=Path, default=POOL_DIR)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    full_dir = args.pool_dir / "full"
    thumbs_dir = args.pool_dir / "thumbs"
    full_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    logger.info("Phase 1/2 : LAION renders (target=%d, max-scan=%d, min-score=%.1f)",
                args.n_laion, args.laion_max_scan, args.laion_min_score)
    laion = fetch_laion_renders(
        n=args.n_laion, min_score=args.laion_min_score,
        max_scan=args.laion_max_scan, skip_rows=args.laion_skip_rows,
        full_dir=full_dir, thumbs_dir=thumbs_dir,
    )

    logger.info("Phase 2/2 : Wikimedia rendering categories (target=%d)", args.n_wikimedia)
    wm = fetch_wikimedia_render_categories(
        total_cap=args.n_wikimedia, per_category=80,
        full_dir=full_dir, thumbs_dir=thumbs_dir,
    )

    manifest_path = args.pool_dir / "manifest.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    existing_ids = {it["id"] for it in existing}
    new_items = [it for it in (laion + wm) if it["id"] not in existing_ids]
    combined = existing + new_items
    manifest_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    dt = time.time() - t0
    logger.info("DONE in %.0fs : LAION=%d Wikimedia=%d (new=%d) | manifest now %d items",
                dt, len(laion), len(wm), len(new_items), len(combined))
    print(f"\n✅ Renders fetch: LAION={len(laion)} WM={len(wm)} new={len(new_items)} total_manifest={len(combined)}")
    print(f"   Next: filter_render_vs_photo.py then refresh curate.html")


if __name__ == "__main__":
    main()
