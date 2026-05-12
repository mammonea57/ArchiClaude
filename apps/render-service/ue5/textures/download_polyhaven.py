"""Download Polyhaven texture maps for every material in MATERIAL_LIBRARY.

Run from the render-service venv (no UE5 needed) :

    python -m apps.render-service.ue5.textures.download_polyhaven \\
        --cache apps/render-service/ue5/textures/textures_cache \\
        --resolution 4k

The script :
  - skips materials with no `polyhaven_slug` (e.g. zinc, fer_forge)
  - downloads Diffuse, nor_dx, arm (AO+Rough+Metallic packed), Displacement
  - keeps files under `<cache>/<material_name>/<map>.jpg`
  - is idempotent (skips if file already present and same md5)
  - logs progress and a summary
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Force UTF-8 on stdout so non-ASCII logs don't blow up the default
# Windows cp1252 console encoding.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# Allow running both as module and as standalone script
try:
    from .library import MATERIAL_LIBRARY, MaterialDef
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from library import MATERIAL_LIBRARY, MaterialDef  # type: ignore


POLYHAVEN_API = "https://api.polyhaven.com"
MAPS_TO_DOWNLOAD = ("Diffuse", "nor_dx", "arm", "Displacement")
DEFAULT_FORMAT = "jpg"  # smallest, good enough for archi-viz first pass
DEFAULT_RESOLUTION = "4k"
DEFAULT_USER_AGENT = "ArchiClaude/0.1 (render station)"


def log(msg: str) -> None:
    print(f"[poly-dl] {msg}", flush=True)


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def md5_of_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, expected_md5: Optional[str] = None) -> bool:
    """Download with retries. Returns True if file present and matches md5
    (or md5 not checkable)."""
    if expected_md5 and md5_of_file(dest) == expected_md5:
        log(f"  ✓ cached  {dest.name}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"  ↓ fetch   {dest.name}")
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as out:
            chunk_size = 1024 * 64
            while True:
                chunk = r.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
    except urllib.error.HTTPError as e:
        log(f"  !! HTTP {e.code} on {url}")
        return False
    if expected_md5:
        actual = md5_of_file(dest)
        if actual != expected_md5:
            log(f"  !! md5 mismatch ({actual} != {expected_md5})")
            return False
    return True


def pick_file_entry(files: dict, map_name: str, resolution: str, fmt: str) -> Optional[dict]:
    """Drill down into the /files response, return the {url,md5,size} entry
    for the requested map+res+format. None if any layer is missing."""
    by_res = files.get(map_name)
    if not by_res:
        return None
    by_fmt = by_res.get(resolution)
    if not by_fmt:
        return None
    entry = by_fmt.get(fmt)
    return entry


def download_material(
    mat: MaterialDef,
    cache_root: Path,
    resolution: str,
    fmt: str,
) -> dict:
    """Download all maps for one material. Returns a summary dict."""
    summary = {
        "name": mat.name,
        "slug": mat.polyhaven_slug,
        "downloaded": [],
        "missing": [],
        "skipped": False,
    }
    if not mat.polyhaven_slug:
        log(f"— {mat.name}: no polyhaven_slug, skipping (fallback color only)")
        summary["skipped"] = True
        return summary

    log(f"=== {mat.name} ← {mat.polyhaven_slug} ===")
    try:
        files = http_json(f"{POLYHAVEN_API}/files/{mat.polyhaven_slug}")
    except Exception as e:
        log(f"  !! failed to fetch file list : {e}")
        summary["missing"] = list(MAPS_TO_DOWNLOAD)
        return summary

    mat_dir = cache_root / mat.name

    for map_name in MAPS_TO_DOWNLOAD:
        entry = pick_file_entry(files, map_name, resolution, fmt)
        if entry is None:
            # Try fallback resolution 2k if 4k missing, or fallback format png
            for res_fb in (resolution, "2k", "1k"):
                for fmt_fb in (fmt, "png", "jpg"):
                    entry = pick_file_entry(files, map_name, res_fb, fmt_fb)
                    if entry:
                        if res_fb != resolution or fmt_fb != fmt:
                            log(f"  ~ {map_name}: using {res_fb}/{fmt_fb} (asked {resolution}/{fmt})")
                        break
                if entry:
                    break
        if entry is None:
            log(f"  !! {map_name}: not available for this asset")
            summary["missing"].append(map_name)
            continue
        ext = fmt if entry is files.get(map_name, {}).get(resolution, {}).get(fmt) else "png"
        url = entry["url"]
        ext = url.rsplit(".", 1)[-1].lower()  # actual extension from URL
        dest = mat_dir / f"{map_name}.{ext}"
        ok = download_file(url, dest, expected_md5=entry.get("md5"))
        if ok:
            summary["downloaded"].append(f"{map_name}.{ext}")
        else:
            summary["missing"].append(map_name)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(__file__).resolve().parent / "textures_cache",
        help="Local cache directory.",
    )
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION,
                        help="Texture resolution (1k/2k/4k/8k). Default: 4k.")
    parser.add_argument("--format", default=DEFAULT_FORMAT,
                        help="Image format (jpg/png/exr). Default: jpg.")
    parser.add_argument("--only", nargs="*", default=None,
                        help="If given, only download these material names.")
    args = parser.parse_args()

    cache_root = args.cache.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    log(f"Cache root : {cache_root}")
    log(f"Resolution : {args.resolution}   Format : {args.format}")

    selected = MATERIAL_LIBRARY
    if args.only:
        selected = {k: v for k, v in MATERIAL_LIBRARY.items() if k in args.only}
        if not selected:
            log(f"!! No materials match --only filter: {args.only}")
            return 2

    summaries = []
    for mat in selected.values():
        s = download_material(mat, cache_root, args.resolution, args.format)
        summaries.append(s)

    # Write index.json for the UE5 importer
    index = {"resolution": args.resolution, "format": args.format, "materials": summaries}
    index_path = cache_root / "index.json"
    index_path.write_text(json.dumps(index, indent=2))
    log(f"Wrote index : {index_path}")

    # Summary
    log("")
    log("=" * 60)
    n_done = sum(1 for s in summaries if s["downloaded"] and not s["missing"])
    n_partial = sum(1 for s in summaries if s["downloaded"] and s["missing"])
    n_skip = sum(1 for s in summaries if s["skipped"])
    n_fail = sum(1 for s in summaries if not s["skipped"] and not s["downloaded"])
    log(f"complete : {n_done}    partial : {n_partial}    skipped : {n_skip}    failed : {n_fail}")
    for s in summaries:
        if s["missing"] and not s["skipped"]:
            log(f"  ! {s['name']:20s} missing : {s['missing']}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
