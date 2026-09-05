"""Extract frames from FR promoteur YouTube videos for LoRA training refs.

Promoteurs immobiliers FR (Nexity, Bouygues, Cogedim, etc.) publient des
videos walkthroughs / présentations de leurs programmes neufs. Ces videos
contiennent **exactement** le langage visuel "brochure FR" que ArchiClaude
cible — par définition puisque les promoteurs eux-mêmes les commandent.

Pipeline:
1. yt-dlp pour download videos depuis chaînes YouTube ciblées (480p suffit)
2. ffmpeg extract frames toutes les 4-6s
3. Skip premières/dernières secondes (logo, credits)
4. CLIP filter "is_archviz_render" pour drop transitions / interviews
5. Add to manifest comme source "youtube_promoteur:<channel>"

License: YouTube fair use commentary/research pour usage R&D individuel.
Attribution sauvegardée dans meta.json par frame.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

# Search queries for YouTube — promoteurs + programmes neufs FR.
# We use yt-dlp search instead of channel browsing to avoid needing the
# exact channel URLs (which change). Results ranked by relevance.
YOUTUBE_QUERIES = [
    "Nexity programme neuf visite virtuelle",
    "Bouygues Immobilier programme neuf 3D",
    "Cogedim résidence neuve animation",
    "Vinci Immobilier programme neuf",
    "Kaufman Broad programme neuf visite",
    "Marignan programme neuf résidence",
    "Réalités programme neuf 3D",
    "Eiffage Immobilier programme neuf",
    "Icade programme neuf résidence",
    "promotion immobilière 3D Île-de-France",
    "résidence neuve présentation 3D",
    "logements neufs IDF programme",
    "BNP Paribas Immobilier programme",
    "résidence collective IDF promotion",
]

# CLIP prompts to keep only archviz frames (drop interviews, logos, etc.)
KEEP_PROMPTS = (
    "a 3D architectural rendering of an apartment building exterior",
    "a CGI animation frame of a residential building",
    "an aerial 3D render of a residential development",
    "a marketing render of a new apartment building",
    "a 3D rendered exterior view of a French residential building",
)
DROP_PROMPTS = (
    "a person talking to the camera in an interview",
    "a logo or text title card",
    "a black or white screen transition",
    "a chart or graphic with text",
    "a person walking inside an interior space",
    "a real estate agent in an office",
)


def yt_dlp_search(query: str, n: int = 3, allow_long: bool = False) -> list[dict]:
    """Search YouTube for videos matching query. Returns list of dicts with
    {id, title, channel, duration}."""
    cmd = [
        "yt-dlp",
        f"ytsearch{n}:{query}",
        "--dump-json",
        "--skip-download",
        "--no-warnings",
        "--quiet",
    ]
    if not allow_long:
        cmd += ["--match-filter", "duration<420"]  # skip videos >7 min
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as e:
        logger.warning("yt-dlp search fail %s : %s", query, e)
        return []
    out = []
    for line in result.stdout.splitlines():
        try:
            info = json.loads(line)
        except Exception:
            continue
        if not info.get("id"):
            continue
        out.append({
            "id": info["id"],
            "title": info.get("title", ""),
            "channel": info.get("uploader") or info.get("channel", ""),
            "duration": info.get("duration", 0),
            "webpage_url": info.get("webpage_url"),
        })
    return out


def yt_dlp_download(video_id: str, output_dir: Path) -> Path | None:
    """Download a YouTube video at 480p max to output_dir. Returns the
    downloaded file path or None on failure."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_template = output_dir / f"{video_id}.%(ext)s"
    cmd = [
        "yt-dlp",
        f"https://www.youtube.com/watch?v={video_id}",
        "-f", "best[height<=480]/best[height<=720]/best",
        "-o", str(out_template),
        "--no-warnings",
        "--quiet",
        "--no-progress",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    except subprocess.CalledProcessError as e:
        logger.warning("yt-dlp download fail %s : %s", video_id, e.stderr[:200] if e.stderr else "")
        return None
    except Exception as e:
        logger.warning("yt-dlp download fail %s : %s", video_id, e)
        return None
    # find the actual file
    for ext in ("mp4", "webm", "mkv"):
        candidate = output_dir / f"{video_id}.{ext}"
        if candidate.exists():
            return candidate
    return None


def extract_frames(video_path: Path, output_dir: Path, video_id: str,
                   fps: float = 0.2, skip_start_s: int = 5,
                   skip_end_s: int = 5) -> list[Path]:
    """Extract frames at given fps. fps=0.2 = 1 frame every 5s."""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"  # fallback
    pattern = output_dir / f"{video_id}_%04d.jpg"
    cmd = [
        ffmpeg,
        "-ss", str(skip_start_s),
        "-i", str(video_path),
        "-vf", f"fps={fps},scale=1024:-1",
        "-q:v", "3",
        "-loglevel", "error",
        str(pattern),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=True)
    except subprocess.CalledProcessError as e:
        logger.warning("ffmpeg fail %s : %s", video_path.name, e.stderr[:200] if e.stderr else "")
        return []
    frames = sorted(output_dir.glob(f"{video_id}_*.jpg"))
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos-per-query", type=int, default=3)
    ap.add_argument("--fps", type=float, default=0.2)
    ap.add_argument("--max-frames-per-video", type=int, default=40)
    ap.add_argument("--pool-dir", type=Path, default=POOL_DIR)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    global logger
    logger = logging.getLogger("archfr.yt_promoteurs")

    full_dir = args.pool_dir / "full"
    thumbs_dir = args.pool_dir / "thumbs"
    full_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    workdir = args.pool_dir / "_youtube_work"
    workdir.mkdir(parents=True, exist_ok=True)
    videos_dir = workdir / "videos"
    frames_dir = workdir / "frames"

    t0 = time.time()
    all_videos = []
    seen_video_ids = set()
    for q in YOUTUBE_QUERIES:
        logger.info("Search : %s", q)
        results = yt_dlp_search(q, n=args.videos_per_query)
        for v in results:
            if v["id"] in seen_video_ids:
                continue
            seen_video_ids.add(v["id"])
            all_videos.append({"query": q, **v})
        logger.info("  → %d new candidate videos (total %d)",
                    len(results), len(all_videos))

    logger.info("Got %d unique candidate videos, starting downloads", len(all_videos))

    new_items = []
    from PIL import Image
    for idx, v in enumerate(all_videos):
        logger.info("[%d/%d] %s — %s",
                    idx + 1, len(all_videos),
                    v["channel"][:30], v["title"][:60])
        video_path = yt_dlp_download(v["id"], videos_dir)
        if not video_path:
            continue
        frames = extract_frames(video_path, frames_dir, v["id"], fps=args.fps)
        logger.info("  extracted %d frames", len(frames))
        kept_frames = frames[:args.max_frames_per_video]
        for frame in kept_frames:
            img_id = "ytp_" + hashlib.md5(f"{v['id']}_{frame.name}".encode()).hexdigest()[:10]
            dst_full = full_dir / f"{img_id}.jpg"
            dst_thumb = thumbs_dir / f"{img_id}.jpg"
            if dst_full.exists() and dst_thumb.exists():
                continue
            try:
                img = Image.open(frame).convert("RGB")
                img.thumbnail((1024, 1024), Image.LANCZOS)
                img.save(dst_full, "JPEG", quality=88)
                thumb = img.copy()
                thumb.thumbnail((320, 320), Image.LANCZOS)
                thumb.save(dst_thumb, "JPEG", quality=82)
            except Exception:
                continue
            new_items.append({
                "id": img_id,
                "full": f"full/{img_id}.jpg",
                "thumb": f"thumbs/{img_id}.jpg",
                "caption": f"{v['channel']} — {v['title']}"[:280],
                "source_url": v["webpage_url"],
                "source_site": f"youtube:{v['channel'][:30]}",
                "license": "YouTube fair use commentary/research (R&D individual)",
                "aesthetic_score": 6.0,
                "youtube_query": v["query"],
                "youtube_video_id": v["id"],
            })
        # remove video file to save disk
        try:
            video_path.unlink()
            for f in kept_frames:
                f.unlink(missing_ok=True)
            # remove leftover frames not in kept
            for f in frames[args.max_frames_per_video:]:
                f.unlink(missing_ok=True)
        except Exception:
            pass

    # Append to manifest
    manifest_path = args.pool_dir / "manifest.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    existing_ids = {it["id"] for it in existing}
    appended = [it for it in new_items if it["id"] not in existing_ids]
    combined = existing + appended
    manifest_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    # Cleanup work dir
    if videos_dir.exists():
        try:
            shutil.rmtree(videos_dir)
        except Exception:
            pass
    if frames_dir.exists():
        try:
            shutil.rmtree(frames_dir)
        except Exception:
            pass

    dt = time.time() - t0
    logger.info("DONE in %.0fs : %d frames extracted, %d new in manifest (total %d)",
                dt, len(new_items), len(appended), len(combined))
    print(f"\n✅ YouTube fetch: {len(new_items)} frames extracted ({len(appended)} new)")
    print(f"   Next: filter_render_vs_photo.py to drop interview/logo frames")


if __name__ == "__main__":
    main()
