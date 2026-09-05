"""Fetch collective-housing / mixed-use architecture refs from Wikimedia Commons.

Wikimedia Commons has a curated category tree of architecture photos under
permissive licenses (CC-BY-SA, CC0, public domain). Cleanest legal source for
ArchiClaude LoRA training — far better than scraping Architizer/Dezeen.

We target categories specifically tied to ArchiClaude's market:
- Apartment buildings (worldwide + France)
- Public/social housing
- Mixed-use developments
- Mid-rise / mid-density urban housing
- Modern architecture in France / Île-de-France

Output appends to the existing curate_pool/ manifest.
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
from urllib.parse import quote, urlencode

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

# Categories targeting promoteur immobilier / archi IDF context.
# Prioritise collective + French if possible.
WIKIMEDIA_CATEGORIES = [
    # France + IDF (highest priority — geographic match)
    "Category:Apartment buildings in Paris",
    "Category:Apartment buildings in France",
    "Category:Modern architecture in France",
    "Category:Buildings and structures in Île-de-France",
    "Category:HLM in France",
    "Category:Social housing in France",
    "Category:Cité radieuse",  # Le Corbusier collective housing iconic
    # Collective housing worldwide
    "Category:Apartment buildings",
    "Category:Social housing buildings",
    "Category:Public housing buildings",
    "Category:Council housing in the United Kingdom",
    "Category:Mid-rise apartment buildings",
    "Category:Mixed-use buildings",
    "Category:Residential buildings by country",
    # Modern reference
    "Category:Modern architecture in Europe",
    "Category:Apartment buildings completed in the 2020s",
    "Category:Apartment buildings completed in the 2010s",
]

LICENSE_NOTE = "Wikimedia Commons (CC-BY-SA, CC0, or public domain — see meta.json per file)"

logger = logging.getLogger("archfr.curate.wikimedia")


UA = "ArchiClaude-LoRA-curate/0.2 (https://github.com/mammonea57/archiclaude; mammonea57@gmail.com) requests/2"


def api_call(params: dict, timeout: int = 30, max_retries: int = 5) -> dict:
    import requests
    url = "https://commons.wikimedia.org/w/api.php?" + urlencode({
        **params, "format": "json", "formatversion": "2",
    })
    delay = 1.0
    for attempt in range(max_retries):
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            wait = float(ra) if ra and ra.isdigit() else delay
            logger.info("  429 from API, sleeping %.1fs (attempt %d)", wait, attempt + 1)
            time.sleep(wait)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def fetch_category_files(category: str, limit: int = 200) -> list[str]:
    """Return list of File: titles in the given category (non-recursive)."""
    cont = None
    titles: list[str] = []
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": "file",
            "cmlimit": min(500, limit - len(titles)),
        }
        if cont:
            params["cmcontinue"] = cont
        try:
            data = api_call(params)
        except Exception as e:
            logger.warning("API error %s : %s", category, e)
            break
        members = data.get("query", {}).get("categorymembers", [])
        for m in members:
            t = m.get("title", "")
            if t and t.startswith("File:"):
                titles.append(t)
        if len(titles) >= limit:
            break
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
    return titles[:limit]


def fetch_image_info(titles: list[str]) -> list[dict]:
    """Batch query imageinfo for a list of File: titles."""
    if not titles:
        return []
    out = []
    # Wikimedia API limits to 50 titles per query
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        params = {
            "action": "query",
            "prop": "imageinfo",
            "titles": "|".join(chunk),
            "iiprop": "url|size|extmetadata|mime",
            "iiurlwidth": "1024",
        }
        try:
            data = api_call(params)
        except Exception as e:
            logger.warning("imageinfo error : %s", e)
            continue
        pages = data.get("query", {}).get("pages", [])
        for p in pages:
            info = p.get("imageinfo")
            if not info:
                continue
            ii = info[0]
            mime = ii.get("mime", "")
            if not mime.startswith("image/jpeg") and not mime.startswith("image/png"):
                continue  # skip SVG, GIF, etc.
            if ii.get("width", 0) < 800 or ii.get("height", 0) < 600:
                continue  # too small
            ext = ii.get("extmetadata", {})
            out.append({
                "title": p.get("title"),
                "thumb_url": ii.get("thumburl") or ii.get("url"),
                "full_url": ii.get("url"),
                "width": ii.get("width"),
                "height": ii.get("height"),
                "license": (ext.get("LicenseShortName") or {}).get("value", "unknown"),
                "artist": (ext.get("Artist") or {}).get("value", ""),
                "description": (ext.get("ImageDescription") or {}).get("value", ""),
                "source_page": ii.get("descriptionurl"),
            })
    return out


def download_image(url: str, output_path: Path, thumb_path: Path,
                   thumb_size: int = 320, max_full_side: int = 1024,
                   max_retries: int = 4) -> bool:
    import requests
    from PIL import Image
    delay = 1.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url, timeout=25, stream=True,
                headers={"User-Agent": UA},
            )
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                wait = float(ra) if ra and ra.isdigit() else delay
                logger.info("  429 from upload, sleeping %.1fs", wait)
                time.sleep(wait)
                delay *= 2
                continue
            if resp.status_code != 200:
                logger.debug("Download %s returned %d", url, resp.status_code)
                return False
            content = resp.content
            if not content or len(content) < 1024:
                return False
            img = Image.open(io.BytesIO(content)).convert("RGB")
            if min(img.size) < 256:
                return False
            img.thumbnail((max_full_side, max_full_side), Image.LANCZOS)
            img.save(output_path, "JPEG", quality=88)
            thumb = img.copy()
            thumb.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
            thumb.save(thumb_path, "JPEG", quality=82)
            return True
        except Exception as e:
            logger.debug("Download fail %s : %s", url, e)
            time.sleep(delay)
            delay *= 2
    return False


def _clean_html(s: str) -> str:
    """Strip HTML tags from caption/description (Wikimedia returns rich HTML)."""
    import re
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=120,
                    help="Max files per category")
    ap.add_argument("--total-cap", type=int, default=2000,
                    help="Stop fetching once this many new images are added")
    ap.add_argument("--thumb-size", type=int, default=320)
    ap.add_argument("--output-dir", type=Path, default=POOL_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    full_dir = args.output_dir / "full"
    thumbs_dir = args.output_dir / "thumbs"
    full_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    # IMPORTANT: write to manifest_wikimedia.json so we don't race with the
    # Pexels/Unsplash agent or the main manifest.json. Merging is done later.
    manifest_path = args.output_dir / "manifest_wikimedia.json"
    main_manifest_path = args.output_dir / "manifest.json"
    existing = []
    existing_titles: set[str] = set()
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_titles = {item.get("source_url", "") for item in existing}
    # Also seed dedupe set from main manifest so we don't re-download images
    # already accepted in the main pool.
    if main_manifest_path.exists():
        try:
            main_items = json.loads(main_manifest_path.read_text(encoding="utf-8"))
            for it in main_items:
                if it.get("source_url"):
                    existing_titles.add(it["source_url"])
        except Exception:
            pass

    logger.info("Starting Wikimedia fetch — %d categories, target %d images",
                len(WIKIMEDIA_CATEGORIES), args.total_cap)

    t0 = time.time()
    new_items = []
    n_seen_titles = set()
    for cat in WIKIMEDIA_CATEGORIES:
        if len(new_items) >= args.total_cap:
            break
        logger.info("→ %s", cat)
        titles = fetch_category_files(cat, limit=args.per_category)
        logger.info("  found %d files", len(titles))
        # Dedupe across categories
        titles = [t for t in titles if t not in n_seen_titles]
        n_seen_titles.update(titles)
        infos = fetch_image_info(titles)
        logger.info("  → %d usable image infos", len(infos))

        n_added_cat = 0
        for info in infos:
            if len(new_items) >= args.total_cap:
                break
            url = info["thumb_url"]
            if url in existing_titles:
                continue
            img_id = "wikimedia_" + hashlib.md5(url.encode()).hexdigest()[:10]
            dst_full = full_dir / f"{img_id}.jpg"
            dst_thumb = thumbs_dir / f"{img_id}.jpg"
            if dst_full.exists() and dst_thumb.exists():
                continue
            if args.dry_run:
                n_added_cat += 1
                continue
            ok = download_image(url, dst_full, dst_thumb, args.thumb_size)
            time.sleep(0.25)  # polite delay to avoid Wikimedia 429
            if not ok:
                continue
            caption = _clean_html(info.get("description") or "") or info["title"]
            new_items.append({
                "id": img_id,
                "full": f"full/{img_id}.jpg",
                "thumb": f"thumbs/{img_id}.jpg",
                "caption": caption,
                "source_url": info["thumb_url"],
                "source_page": info.get("source_page", ""),
                "license": info.get("license", "unknown"),
                "artist": _clean_html(info.get("artist", "")),
                "aesthetic_score": 6.0,  # placeholder so UI filter works
                "wikimedia_category": cat,
            })
            n_added_cat += 1
            # Incremental manifest persist every 25 new items so we don't lose
            # progress on interrupt or 429 storms.
            if not args.dry_run and len(new_items) % 25 == 0:
                manifest_path.write_text(
                    json.dumps(existing + new_items, indent=2), encoding="utf-8")
        logger.info("  added %d new images from this category (total new: %d)",
                    n_added_cat, len(new_items))
        time.sleep(1.0)  # polite per-category breather

    if not args.dry_run:
        combined = existing + new_items
        manifest_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
        logger.info("Manifest written : %d existing + %d new = %d total",
                    len(existing), len(new_items), len(combined))

    dt = time.time() - t0
    logger.info("DONE in %.0fs", dt)
    print(f"\n✅ Wikimedia fetch : {len(new_items)} new images added")
    print(f"   Next: run filter_curate_pool.py then refresh curate.html")


if __name__ == "__main__":
    main()
