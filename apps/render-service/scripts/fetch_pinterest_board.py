"""Fetch all pins from a user-curated Pinterest board.

User-curated boards represent the user's own taste, so images go DIRECTLY
into `refs/style_dataset/manual_refs/` (highest priority dataset tier),
NOT into the curate_pool.

Pipeline:
1. Hit the RSS feed at https://<host>/<user>/<board>.rss → list of pin URLs
2. For each pin URL, fetch the HTML page
3. Parse <meta property="og:image" content="..."> → high-res image URL
4. Download → manual_refs/pin_<hash>.jpg + .meta.json with pin URL + caption

Usage:
    python fetch_pinterest_board.py https://fr.pinterest.com/mammonea57/archiclaude
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
MANUAL_REFS_DIR = REPO_ROOT / "refs" / "style_dataset" / "manual_refs"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pinterest")


def parse_rss(rss_xml: str) -> list[dict]:
    """Extract (link, title, description) tuples from Pinterest RSS XML."""
    items = []
    for item_match in re.finditer(r"<item>(.+?)</item>", rss_xml, re.DOTALL):
        block = item_match.group(1)
        link_m = re.search(r"<link>([^<]+)</link>", block)
        title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.DOTALL)
        desc_m = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.DOTALL)
        if not link_m:
            continue
        items.append({
            "url": link_m.group(1).strip(),
            "title": (title_m.group(1) if title_m else "").strip()[:300],
            "description": (desc_m.group(1) if desc_m else "").strip()[:400],
        })
    return items


def extract_og_image(html: str) -> str | None:
    """Extract og:image URL from HTML. Pinterest writes <meta> tags with
    several attribute orderings, so try a few.
    """
    # Pinterest format : <meta content="URL" data-app="true" name="og:image" property="og:image"/>
    for pattern in (
        r'<meta\s+content=["\']([^"\']+)["\'][^>]*\bog:image\b',
        r'<meta\s+[^>]*\bog:image\b[^>]*content=["\']([^"\']+)["\']',
        r'<meta\s+(?:property|name)=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\']og:image["\']',
    ):
        # Be strict — must NOT match og:image:width / og:image:height tags
        for m in re.finditer(pattern, html, re.IGNORECASE):
            url = m.group(1)
            # Filter out non-image URLs (logos / dimensions)
            if url.startswith("http") and any(ext in url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
                return url
    return None


def download_pin_image(pin_url: str, session: requests.Session) -> tuple[str | None, str | None]:
    """Fetch a pin page, extract its og:image URL, return (image_url, page_html)."""
    try:
        resp = session.get(pin_url, headers={"User-Agent": UA}, timeout=15)
        if resp.status_code != 200:
            return None, None
        img_url = extract_og_image(resp.text)
        return img_url, resp.text
    except Exception as e:
        logger.debug("Pin fetch fail %s : %s", pin_url, e)
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board_url", help="Pinterest board URL")
    ap.add_argument("--max-pins", type=int, default=500)
    ap.add_argument("--output-dir", type=Path, default=MANUAL_REFS_DIR)
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Normalize URL: convert .com/.fr endings to .rss
    board_url = args.board_url.rstrip("/").split("?")[0]
    if board_url.endswith(".rss"):
        rss_url = board_url
    else:
        rss_url = board_url + ".rss"
    logger.info("Fetching RSS : %s", rss_url)

    session = requests.Session()
    resp = session.get(rss_url, headers={"User-Agent": UA}, timeout=20)
    if resp.status_code != 200:
        logger.error("RSS fetch returned %d", resp.status_code)
        sys.exit(1)
    items = parse_rss(resp.text)
    logger.info("Parsed %d items from RSS", len(items))
    if not items:
        logger.error("No items in RSS — board may be empty or URL wrong")
        sys.exit(1)

    items = items[:args.max_pins]
    t0 = time.time()
    n_downloaded = 0
    n_skipped = 0
    n_fail = 0

    for idx, item in enumerate(items):
        pin_url = item["url"]
        pin_id_match = re.search(r"/pin/(\d+)", pin_url)
        pin_id = pin_id_match.group(1) if pin_id_match else hashlib.md5(pin_url.encode()).hexdigest()[:12]
        img_id = f"pin_{pin_id}"
        dst = args.output_dir / f"{img_id}.jpg"
        if dst.exists():
            n_skipped += 1
            continue

        img_url, _ = download_pin_image(pin_url, session)
        if not img_url:
            n_fail += 1
            continue

        # Upgrade to higher-res variant if Pinterest serves a sized URL
        # (Pinterest URLs often have /236x/ or /474x/ → bump to /originals/)
        img_url_hd = re.sub(r"/\d+x/", "/originals/", img_url)
        img_url_hd = re.sub(r"/\d+x\d+/", "/originals/", img_url_hd)

        try:
            for try_url in (img_url_hd, img_url):
                r = session.get(try_url, headers={"User-Agent": UA},
                                timeout=20, allow_redirects=True)
                if r.status_code == 200 and r.content:
                    img = Image.open(io.BytesIO(r.content)).convert("RGB")
                    if min(img.size) < 320:
                        continue
                    img.thumbnail((1280, 1280), Image.LANCZOS)
                    img.save(dst, "JPEG", quality=90)
                    break
            else:
                n_fail += 1
                continue
        except Exception as e:
            logger.debug("Image fail %s : %s", img_url, e)
            n_fail += 1
            continue

        meta = {
            "id": img_id,
            "pin_url": pin_url,
            "image_url": img_url,
            "caption": item.get("title") or item.get("description", "")[:200],
            "source_site": "pinterest:user_curated",
            "license": "User-curated reference (Pinterest pin links to original source ; usage : R&D individual fair use)",
        }
        (args.output_dir / f"{img_id}.meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        # Caption sidecar for LoRA training pickup
        if item.get("description"):
            (args.output_dir / f"{img_id}.txt").write_text(
                item["description"], encoding="utf-8")

        n_downloaded += 1
        if n_downloaded % 10 == 0:
            logger.info("  downloaded %d / %d (skipped=%d fail=%d)",
                        n_downloaded, len(items), n_skipped, n_fail)
        time.sleep(0.4)  # be nice

    dt = time.time() - t0
    logger.info("DONE in %.0fs : downloaded=%d skipped=%d fail=%d → %s",
                dt, n_downloaded, n_skipped, n_fail, args.output_dir)
    print(f"\n✅ Pinterest board synced : {n_downloaded} new pins")
    print(f"   Skipped (already present) : {n_skipped}")
    print(f"   Failed : {n_fail}")
    print(f"   Manual refs total : {len(list(args.output_dir.glob('pin_*.jpg')))}")


if __name__ == "__main__":
    main()
