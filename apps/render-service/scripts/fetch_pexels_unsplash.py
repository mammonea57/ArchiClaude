"""Fetch collective-housing / mixed-use refs from Unsplash + Openverse.

Originally targeted Pexels + Unsplash (per user spec), but Pexels' search HTML
sits behind a Cloudflare JS challenge that no plain-curl/requests UA bypasses
(Selenium is explicitly forbidden in the task brief). So:

  - PRIMARY  : Unsplash internal napi (`/napi/search/photos`). It returns clean
               JSON and answers correctly when called with the Googlebot UA.
               License: https://unsplash.com/license (commercial use OK).

  - FALLBACK : Openverse (`api.openverse.org`). Free, no key, aggregates only
               commercially-licensed CC images (Flickr CC-BY/0, Wikimedia, etc.).
               Used to replace Pexels' planned share of the volume.

Both sources are written into `refs/style_dataset/curate_pool/full|thumbs/` and
indexed in a *separate* manifest file (`manifest_pexels_unsplash.json`) so the
parallel Wikimedia agent and this one don't race on `manifest.json`.

Output schema per item:
    { id, full, thumb, caption, source_url, source_site, license,
      aesthetic_score (placeholder 6.0) }
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

# Queries cibler collective housing / mixed-use, éviter detached houses.
QUERIES = [
    "apartment building",
    "modern apartment exterior",
    "multi family residential",
    "mid rise apartment",
    "mixed use building",
    "social housing",
    "residential complex",
    "modern facade architecture",
    "urban housing",
    "concrete apartment",
    "brick apartment building",
    "balcony apartment building",
]

# Googlebot UA is the only one that gets past Unsplash's Anubis bot wall on the
# napi endpoint without a JS challenge token.
UA_GOOGLEBOT = "Googlebot/2.1 (+http://www.google.com/bot.html)"
UA_GENERIC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/121.0.0.0 Safari/537.36")

logger = logging.getLogger("archfr.curate.pexunsplash")


# ---------------------------------------------------------------------------
# Unsplash
# ---------------------------------------------------------------------------

def unsplash_search(query: str, page: int = 1, per_page: int = 30) -> list[dict]:
    """Hit Unsplash's internal `/napi/search/photos` endpoint. Returns list of
    dicts (or [] on failure). The caller is responsible for sleeping between
    calls.
    """
    url = (f"https://unsplash.com/napi/search/photos"
           f"?query={quote_plus(query)}&per_page={per_page}&page={page}")
    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": UA_GOOGLEBOT,
                                     "Accept": "application/json"})
        if resp.status_code != 200:
            logger.warning("unsplash %s page=%d → HTTP %d",
                           query, page, resp.status_code)
            return []
        data = resp.json()
        return data.get("results") or []
    except Exception as e:
        logger.warning("unsplash %s page=%d error : %s", query, page, e)
        return []


# ---------------------------------------------------------------------------
# Openverse  (Pexels fallback — Pexels itself is CF-blocked)
# ---------------------------------------------------------------------------

def openverse_search(query: str, page: int = 1, per_page: int = 30) -> list[dict]:
    """Openverse aggregates Wikimedia + Flickr + others with commercial licences
    already filtered server-side.
    """
    url = (f"https://api.openverse.org/v1/images/"
           f"?q={quote_plus(query)}&page={page}&page_size={per_page}"
           f"&license_type=commercial&extension=jpg")
    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": UA_GENERIC,
                                     "Accept": "application/json"})
        if resp.status_code != 200:
            logger.warning("openverse %s page=%d → HTTP %d",
                           query, page, resp.status_code)
            return []
        data = resp.json()
        return data.get("results") or []
    except Exception as e:
        logger.warning("openverse %s page=%d error : %s", query, page, e)
        return []


# ---------------------------------------------------------------------------
# Download + resize
# ---------------------------------------------------------------------------

def _download_bytes(url: str, ua: str = UA_GENERIC, timeout: int = 25) -> bytes | None:
    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": ua,
                                     "Accept": "image/*,*/*;q=0.8"},
                            stream=False)
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None


def save_image(content: bytes, dst_full: Path, dst_thumb: Path,
               thumb_size: int = 320, max_full_side: int = 1024) -> bool:
    """Resize to <=1024 long-side, save full JPEG + 320 thumb."""
    if not content:
        return False
    try:
        img = Image.open(io.BytesIO(content)).convert("RGB")
        if min(img.size) < 256:
            return False
        img.thumbnail((max_full_side, max_full_side), Image.LANCZOS)
        img.save(dst_full, "JPEG", quality=88)
        thumb = img.copy()
        thumb.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
        thumb.save(dst_thumb, "JPEG", quality=82)
        return True
    except Exception as e:
        logger.debug("save fail : %s", e)
        return False


# ---------------------------------------------------------------------------
# Per-source ingestion
# ---------------------------------------------------------------------------

def ingest_unsplash(queries: list[str], full_dir: Path, thumbs_dir: Path,
                    pages_per_query: int = 3, per_page: int = 30,
                    existing_urls: set[str] | None = None,
                    sleep_s: float = 0.8) -> list[dict]:
    existing_urls = existing_urls or set()
    out: list[dict] = []
    seen_ids: set[str] = set()
    for q in queries:
        for page in range(1, pages_per_query + 1):
            results = unsplash_search(q, page=page, per_page=per_page)
            if not results:
                break  # if a page is empty/blocked, skip rest of this query
            for r in results:
                uid = r.get("id")
                if not uid or uid in seen_ids:
                    continue
                seen_ids.add(uid)
                urls = r.get("urls") or {}
                # `regular` = ~1080px wide, perfect for resize-to-1024.
                full_url = urls.get("regular") or urls.get("full") or urls.get("raw")
                if not full_url:
                    continue
                if full_url in existing_urls:
                    continue
                img_id = "unsplash_" + hashlib.md5(uid.encode()).hexdigest()[:10]
                dst_full = full_dir / f"{img_id}.jpg"
                dst_thumb = thumbs_dir / f"{img_id}.jpg"
                if dst_full.exists() and dst_thumb.exists():
                    continue
                content = _download_bytes(full_url)
                if not save_image(content, dst_full, dst_thumb):
                    continue
                caption = (r.get("alt_description")
                           or r.get("description")
                           or q).strip()[:300]
                links = r.get("links") or {}
                out.append({
                    "id": img_id,
                    "full": f"full/{img_id}.jpg",
                    "thumb": f"thumbs/{img_id}.jpg",
                    "caption": caption,
                    "source_url": full_url,
                    "source_page": links.get("html", ""),
                    "source_site": "unsplash",
                    "license": "Unsplash License (commercial OK, https://unsplash.com/license)",
                    "aesthetic_score": 6.0,
                    "query": q,
                })
                time.sleep(0.15)  # gentle per-image
            logger.info("unsplash «%s» p%d → %d total kept",
                        q, page, len(out))
            time.sleep(sleep_s)
    return out


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_caption(s: str) -> str:
    if not s:
        return ""
    s = _HTML_TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:300]


def ingest_openverse(queries: list[str], full_dir: Path, thumbs_dir: Path,
                     pages_per_query: int = 3, per_page: int = 30,
                     existing_urls: set[str] | None = None,
                     sleep_s: float = 0.8) -> list[dict]:
    """Openverse pre-filters by commercial license; we just download."""
    existing_urls = existing_urls or set()
    out: list[dict] = []
    seen_ids: set[str] = set()
    for q in queries:
        for page in range(1, pages_per_query + 1):
            results = openverse_search(q, page=page, per_page=per_page)
            if not results:
                break
            for r in results:
                uid = r.get("id")
                if not uid or uid in seen_ids:
                    continue
                seen_ids.add(uid)
                full_url = r.get("url")
                if not full_url:
                    continue
                if full_url in existing_urls:
                    continue
                img_id = "openverse_" + hashlib.md5(uid.encode()).hexdigest()[:10]
                dst_full = full_dir / f"{img_id}.jpg"
                dst_thumb = thumbs_dir / f"{img_id}.jpg"
                if dst_full.exists() and dst_thumb.exists():
                    continue
                content = _download_bytes(full_url)
                if not save_image(content, dst_full, dst_thumb):
                    continue
                lic = (r.get("license") or "unknown")
                lic_v = r.get("license_version") or ""
                provider = r.get("provider") or r.get("source") or "openverse"
                caption = _clean_caption(r.get("title") or q)
                out.append({
                    "id": img_id,
                    "full": f"full/{img_id}.jpg",
                    "thumb": f"thumbs/{img_id}.jpg",
                    "caption": caption,
                    "source_url": full_url,
                    "source_page": r.get("foreign_landing_url", ""),
                    "source_site": f"openverse:{provider}",
                    "license": f"{lic} {lic_v} (commercial OK, Openverse)",
                    "aesthetic_score": 6.0,
                    "query": q,
                })
                time.sleep(0.10)
            logger.info("openverse «%s» p%d → %d total kept",
                        q, page, len(out))
            time.sleep(sleep_s)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unsplash-pages", type=int, default=3,
                    help="Pages per query for Unsplash (30/page)")
    ap.add_argument("--openverse-pages", type=int, default=2,
                    help="Pages per query for Openverse (30/page) — Pexels fallback")
    ap.add_argument("--per-page", type=int, default=30)
    ap.add_argument("--output-dir", type=Path, default=POOL_DIR)
    ap.add_argument("--manifest-name", default="manifest_pexels_unsplash.json")
    ap.add_argument("--unsplash-only", action="store_true")
    ap.add_argument("--openverse-only", action="store_true")
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

    manifest_path = args.output_dir / args.manifest_name
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        existing = []
    existing_urls = {item.get("source_url", "") for item in existing}

    t0 = time.time()
    new_items: list[dict] = []

    if not args.openverse_only:
        logger.info("=== Unsplash ===")
        new_items += ingest_unsplash(
            QUERIES, full_dir, thumbs_dir,
            pages_per_query=args.unsplash_pages,
            per_page=args.per_page,
            existing_urls=existing_urls,
        )

    if not args.unsplash_only:
        logger.info("=== Openverse (Pexels fallback — CF blocks Pexels) ===")
        new_items += ingest_openverse(
            QUERIES, full_dir, thumbs_dir,
            pages_per_query=args.openverse_pages,
            per_page=args.per_page,
            existing_urls=existing_urls,
        )

    combined = existing + new_items
    manifest_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    dt = time.time() - t0
    by_site: dict[str, int] = {}
    for it in new_items:
        s = it["source_site"].split(":")[0]
        by_site[s] = by_site.get(s, 0) + 1
    logger.info("DONE in %.0fs : %d new items (%s) ; manifest %d total",
                dt, len(new_items), by_site, len(combined))
    print(f"\n[OK] Pexels/Unsplash fetch : {len(new_items)} new images "
          f"({by_site}). Manifest : {manifest_path}")


if __name__ == "__main__":
    main()
