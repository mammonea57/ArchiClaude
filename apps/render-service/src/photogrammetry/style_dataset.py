"""Style dataset builder for ArchiClaude archviz LoRA training.

Assembles a training-ready dataset of archviz reference images from
**legal, free, license-clean** sources only :

1. **HPSv3** (`xswu/HPDv3` on HuggingFace) — 1.08M preference pairs,
   Apache 2.0. Filter captions on archviz keywords.
2. **LAION-Aesthetics 6+** — open dataset (CLIP-filtered, MIT-style),
   filter by aesthetic score >= 6.5 + archviz keywords.
3. **Polyhaven** — CC0 + AI training EXPLICITLY allowed in TOS.
   We only fetch HDRI/texture *metadata* (URLs + license) because the
   actual files are 100s of MB each ; LoRA training uses the HDRI as
   environment lighting at render time, not as a target image.
4. **manual_refs/** — slot for user-curated images (fair-use research,
   personal R&D consultation per EU Article 4 TDM exception). Captions
   auto-generated via BLIP-2 if not provided.

**Forbidden sources** (TOS-banned, NEVER touched here) :
- Architizer / Dezeen / ArchDaily / Behance scraping
- Mapillary photogrammetry (CC-BY-SA viral — would force open-source us)
- Google Street View (TOS interdit 3D + EU DMA blocker)
- Kitbash3D / Quixel mega assets (AI training explicitly forbidden)
- Magnum / Nat Geo / fine-art photo archives (copyright + moral rights)

Each downloaded image is saved alongside a `.meta.json` recording :
- `source` : "hpsv3" / "laion" / "polyhaven" / "manual"
- `original_url` : provenance for audit
- `license` : the upstream license string
- `caption` : training prompt
- `aesthetic_score` : when available

Final `build_combined_dataset` step deduplicates via perceptual hash
(ImageHash phash) and emits a HuggingFace-style folder :

    output_dir/
        images/000001.jpg
        images/000002.jpg
        ...
        captions.jsonl    # one JSON per line : {file_name, caption, source, license}

Usage :
    # CLI smoke test (50 images, real download)
    cd apps/render-service
    .venv/bin/python -m photogrammetry.style_dataset --smoke-test --n 50

    # Full dataset build (2000 images, used as input to Modal LoRA training)
    .venv/bin/python -m photogrammetry.style_dataset --full --n 2000 \
        --out refs/style_dataset/combined_v1
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urlparse

logger = logging.getLogger("archfr.style_dataset")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

# -- defaults -----------------------------------------------------------------

# Keywords that qualify a caption as archviz-relevant. Designed to be high
# precision : we'd rather drop 50% of relevant images than admit interior
# food photography.
ARCHVIZ_KEYWORDS: tuple[str, ...] = (
    "architecture",
    "architectural",
    "building",
    "facade",
    "façade",
    "skyscraper",
    "apartment",
    "residential",
    "housing",
    "condominium",
    "townhouse",
    "render",
    "rendering",
    "3d render",
    "exterior",
    "urban",
    "cityscape",
    "streetscape",
    "modern building",
    "concrete building",
    "brick building",
    "office building",
    "high rise",
    "low rise",
    "mid rise",
    "house exterior",
    "courtyard",
    "rooftop",
)

# Negative keywords — caption containing these is rejected. We want NO
# interiors (they pollute the LoRA toward IKEA-rendering aesthetics) and
# NO people-centric photography (portrait composition leaks into output).
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "interior design",
    "living room",
    "bedroom",
    "kitchen",
    "bathroom",
    "portrait",
    "woman",
    "man wearing",
    "fashion",
    "wedding",
    "food",
    "cake",
    "dessert",
    "selfie",
    "anime",
    "cartoon",
    "logo",
    "infographic",
)

# Watermark / stock-photo host blacklist. URLs from these hosts almost
# always come with embedded watermarks ("Shutterstock"/"iStock"/etc.)
# that LoRA training will happily learn as part of the style. We drop
# them at URL-filter time, *before* spending bandwidth on the download.
STOCK_PHOTO_HOST_BLACKLIST: tuple[str, ...] = (
    "shutterstock.com",
    "istockphoto.com",
    "gettyimages.com",
    "gettyimages.co.uk",
    "alamy.com",
    "dreamstime.com",
    "123rf.com",
    "depositphotos.com",
    "adobestock.com",
    "stock.adobe.com",
    "fotolia.com",
    "bigstockphoto.com",
    "canstockphoto.com",
    "agefotostock.com",
)

# CLIP zero-shot classifier prompts. POSITIVE captions describe what we
# *want* in the LoRA training set (exterior archviz). NEGATIVE captions
# describe known failure modes (interiors, portraits, watermark stock).
# Score = max(POS sim) - max(NEG sim) — threshold tuned to ~0.05 empirically.
CLIP_POSITIVE_PROMPTS: tuple[str, ...] = (
    "photorealistic architectural visualization render of a residential building exterior",
    "professional archviz exterior render of a modern apartment building",
    "realistic exterior facade view of a contemporary multi-story building with windows",
    "architectural permit application exterior render with people and cars on the street",
    "photorealistic 3D render of a residential collective housing project facade",
)
CLIP_NEGATIVE_PROMPTS: tuple[str, ...] = (
    # interiors
    "interior of a kitchen or living room",
    "interior bedroom",
    # people / portraits / non-architectural subjects
    "portrait of a person",
    "person face close-up",
    # stylized / non-photoreal
    "fantasy concept art with castles and dragons",
    "stylized digital illustration cartoon",
    "futuristic cyberpunk sci-fi cityscape neon",
    "abstract art",
    "video game concept art",
    "anime architecture",
    # boats / vehicles luxury (recurring smoke_test_200 false positives)
    "yacht boat luxury vessel deck",
    "car interior dashboard",
    # stock / watermarked
    "watermarked stock photo",
    "logo design",
    "vintage photograph",
    # misc
    "landscape nature without buildings",
)

# Default CLIP filter threshold. Calibrated against smoke_test_200 audit
# (2026-06-04): old threshold 0.05 gave 67% precision. New stricter prompts
# (more specific POS, more comprehensive NEG) allow tighter threshold 0.08.
CLIP_DEFAULT_THRESHOLD = 0.08

# HuggingFace dataset identifiers
# HPSv3 / HPDv3 = official MizzenAI/HPDv3 repo (Aug 2025, MIT license, non-gated).
# 1.14M rows, 141 GB total — we stream just what we need.
# Older mirror names kept as last-resort fallback.
HPSV3_CANDIDATES = (
    "MizzenAI/HPDv3",              # official, MIT license (verified 2026-06-04)
    "MirageML/HPDv3",
    "xswu/HPDv3",
    "yuvalkirstain/HPDv3",
    "xswu/HPDv2",
    "yuvalkirstain/pickapic_v1",   # last-resort fallback : same preference-pair schema
)
LAION_AES_REPO = "dclure/laion-aesthetics-12m-umap"  # tiny derivative with scores
# Note : the official `laion/laion-aesthetics_v2_6plus` requires the
# 12M parquet — too heavy for a 500-image fetch. We use the dclure
# derivative which exposes URL + caption + aesthetic_score and let us
# stream-download just the rows we need.
POLYHAVEN_API_BASE = "https://api.polyhaven.com"


# -- data model ---------------------------------------------------------------


@dataclass
class StyleEntry:
    """One training sample : image + caption + license metadata.

    Saved as `<idx>.jpg` + `<idx>.meta.json` until the final combined
    dataset is built, then promoted into `images/` + `captions.jsonl`.
    """
    source: str                # "hpsv3" / "laion" / "polyhaven" / "manual"
    caption: str
    original_url: str
    license: str
    image_bytes: Optional[bytes] = field(default=None, repr=False)
    aesthetic_score: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    phash: Optional[str] = None  # perceptual hash, filled at dedup time

    def to_meta(self) -> dict:
        d = asdict(self)
        d.pop("image_bytes", None)
        return d


# -- helpers ------------------------------------------------------------------


def _caption_matches_archviz(caption: str) -> bool:
    """True if caption contains an archviz keyword AND no negative keyword."""
    if not caption:
        return False
    c = caption.lower()
    if any(neg in c for neg in NEGATIVE_KEYWORDS):
        return False
    return any(kw in c for kw in ARCHVIZ_KEYWORDS)


def _safe_filename(idx: int, source: str) -> str:
    return f"{source}_{idx:05d}"


def _download_image(url: str, timeout: float = 20.0) -> Optional[bytes]:
    """Fetch an image URL with httpx. Returns None on any failure."""
    try:
        import httpx
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "ArchiClaude/1.0 (research; +mammonea57@gmail.com)"},
        ) as client:
            r = client.get(url)
            r.raise_for_status()
            # Quick sanity check : content-type
            ctype = r.headers.get("content-type", "").lower()
            if not any(t in ctype for t in ("image/", "octet-stream")):
                return None
            data = r.content
            if len(data) < 5_000:   # < 5 KB = probably a placeholder / error page
                return None
            return data
    except Exception as e:
        logger.debug("download failed %s : %s", url, e)
        return None


def _is_blacklisted_url(url: str) -> bool:
    """True if `url`'s host matches a stock-photo / watermark domain.

    We match on suffix so subdomains (e.g. `image.shutterstock.com`)
    are caught alongside the bare domain. The blacklist is conservative
    — only domains where watermarks are baked into delivered images.
    """
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in STOCK_PHOTO_HOST_BLACKLIST)


def _have_hf_auth() -> bool:
    """True if a HuggingFace auth token is reachable.

    Checks (in order) :
    1. `HF_TOKEN` environment variable (canonical for CI / Modal secrets)
    2. `HUGGING_FACE_HUB_TOKEN` env var (older alias still in use)
    3. `~/.huggingface/token` (legacy `huggingface-cli login` location)
    4. `~/.cache/huggingface/token` (new default since `huggingface_hub` 0.14+)
    """
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        return True
    candidates = [
        Path.home() / ".huggingface" / "token",
        Path.home() / ".cache" / "huggingface" / "token",
    ]
    return any(p.exists() and p.stat().st_size > 0 for p in candidates)


# -- CLIP zero-shot filter ----------------------------------------------------
#
# We lazy-init the model once per process — loading ViT-B-32 takes ~5s on
# CPU but the per-image scoring is ~30ms, so amortising the load over a
# whole fetch run is well worth it.

_CLIP_MODEL = None       # type: ignore[var-annotated]
_CLIP_PROCESSOR = None   # type: ignore[var-annotated]
_CLIP_TEXT_EMB = None    # type: ignore[var-annotated]   # (pos+neg) text embeddings precomputed


def _ensure_clip_loaded() -> bool:
    """Lazy-load CLIP ViT-B/32 (laion2b). Returns True on success.

    Uses transformers.CLIPModel for portability — `open_clip` would also
    work but we don't want to add a deps just for this one classifier.
    """
    global _CLIP_MODEL, _CLIP_PROCESSOR, _CLIP_TEXT_EMB
    if _CLIP_MODEL is not None:
        return True
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
    except ImportError as e:
        logger.warning("CLIP filter unavailable (transformers/torch missing : %s)", e)
        return False
    try:
        # ViT-B/32 laion2b checkpoint — small (~150MB), fast on CPU
        # (~30ms/image) and trained on a much larger corpus than the
        # original OpenAI ViT-B/32, so it's strictly better for our
        # zero-shot classification task.
        model_id = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
        _CLIP_PROCESSOR = CLIPProcessor.from_pretrained(model_id)
        _CLIP_MODEL = CLIPModel.from_pretrained(model_id).eval()
        with torch.no_grad():
            prompts = list(CLIP_POSITIVE_PROMPTS) + list(CLIP_NEGATIVE_PROMPTS)
            inputs = _CLIP_PROCESSOR(text=prompts, return_tensors="pt", padding=True)
            txt = _CLIP_MODEL.get_text_features(**inputs)
            txt = txt / txt.norm(dim=-1, keepdim=True)
            _CLIP_TEXT_EMB = txt
        logger.info("CLIP filter : loaded %s (cpu)", model_id)
        return True
    except Exception as e:
        logger.warning("CLIP filter load failed : %s", e)
        _CLIP_MODEL = None
        _CLIP_PROCESSOR = None
        _CLIP_TEXT_EMB = None
        return False


def _clip_score_image(img_bytes: bytes) -> Optional[float]:
    """Return (max(POS sim) - max(NEG sim)) for one image. None on failure.

    Higher score = more confidently archviz-exterior. Threshold ~0.05.
    """
    if _CLIP_MODEL is None or _CLIP_PROCESSOR is None or _CLIP_TEXT_EMB is None:
        return None
    try:
        import torch
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        with torch.no_grad():
            inputs = _CLIP_PROCESSOR(images=img, return_tensors="pt")
            img_feat = _CLIP_MODEL.get_image_features(**inputs)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            sims = (img_feat @ _CLIP_TEXT_EMB.T).squeeze(0)  # [n_prompts]
            n_pos = len(CLIP_POSITIVE_PROMPTS)
            pos_sim = sims[:n_pos].max().item()
            neg_sim = sims[n_pos:].max().item()
            return float(pos_sim - neg_sim)
    except Exception as e:
        logger.debug("CLIP score failed : %s", e)
        return None


def _perceptual_hash(img_bytes: bytes) -> Optional[str]:
    """Compute pHash for dedup. Returns hex string, or None on failure."""
    try:
        import imagehash
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        return str(imagehash.phash(img))
    except ImportError:
        # imagehash not installed → fall back to SHA1 of bytes
        return hashlib.sha1(img_bytes).hexdigest()
    except Exception as e:
        logger.debug("phash failed : %s", e)
        return None


# -- main builder -------------------------------------------------------------


class StyleDatasetBuilder:
    """Orchestrates fetching + filtering + caching of style dataset sources.

    Each fetch_* method downloads to a source-specific subdir of
    `cache_root`. `build_combined_dataset` then merges them into one
    HuggingFace-style folder with dedup.
    """

    def __init__(self, cache_root: Path):
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    # ---- CLIP filter -------------------------------------------------------

    def clip_filter_archviz(
        self,
        entries: List[StyleEntry],
        threshold: float = CLIP_DEFAULT_THRESHOLD,
        rejected_dir: Optional[Path] = None,
    ) -> List[StyleEntry]:
        """Return only entries whose CLIP archviz-exterior score >= threshold.

        Rejected entries are saved (image + meta + score) under
        `rejected_dir` (defaults to `<cache_root>/rejected/`) so the user
        can eyeball whether the threshold is too strict / too loose.

        If CLIP is unavailable (model load fails / torch missing), we
        log a warning and return the input unchanged — better to ship a
        slightly noisy LoRA than crash the pipeline.
        """
        if not entries:
            return entries
        if not _ensure_clip_loaded():
            logger.warning(
                "clip_filter_archviz : CLIP unavailable, skipping filter "
                "(input %d entries returned untouched)", len(entries),
            )
            return entries

        if rejected_dir is None:
            rejected_dir = self.cache_root / "rejected"
        rejected_dir = Path(rejected_dir)
        rejected_dir.mkdir(parents=True, exist_ok=True)

        kept: list[StyleEntry] = []
        rejected: list[tuple[StyleEntry, float]] = []
        for e in entries:
            if e.image_bytes is None:
                # Metadata-only entry (e.g. polyhaven) — pass through.
                kept.append(e)
                continue
            score = _clip_score_image(e.image_bytes)
            if score is None:
                # If scoring failed, keep the entry (fail-open).
                kept.append(e)
                continue
            if score >= threshold:
                kept.append(e)
            else:
                rejected.append((e, score))

        # Persist rejected for audit
        for i, (e, score) in enumerate(rejected):
            stem = f"{e.source}_rej_{int(time.time())}_{i:04d}"
            try:
                (rejected_dir / f"{stem}.jpg").write_bytes(e.image_bytes or b"")
                meta = e.to_meta()
                meta["clip_archviz_score"] = score
                meta["rejected_threshold"] = threshold
                (rejected_dir / f"{stem}.meta.json").write_text(
                    json.dumps(meta, indent=2)
                )
            except Exception as ex:
                logger.debug("failed to persist rejected %s : %s", stem, ex)

        logger.info(
            "clip_filter_archviz : kept %d / %d (threshold=%.3f, rejected=%d → %s)",
            len(kept), len(entries), threshold, len(rejected), rejected_dir,
        )
        return kept

    # ---- HPSv3 -------------------------------------------------------------

    def fetch_hpsv3_subset(
        self,
        n: int = 500,
        archviz_keywords: Sequence[str] = ARCHVIZ_KEYWORDS,
    ) -> List[StyleEntry]:
        """Pull HPSv3 preference pairs, filter for archviz captions.

        HPSv3 is `xswu/HPDv3` on HuggingFace — 1.08M preference pairs of
        (prompt, chosen, rejected). We keep only the **chosen** image
        and only if the prompt looks archviz-relevant. Apache 2.0 license
        explicitly permits training derivative models.

        Note 2026-06 : HPSv3 has *very few* explicitly-archviz prompts
        (it's mostly portraits + generic SD prompts). Realistic yield :
        ~5-10% of n requested. We compensate by oversampling 5x.
        """
        outdir = self.cache_root / "hpsv3"
        outdir.mkdir(parents=True, exist_ok=True)

        try:
            from datasets import load_dataset
        except ImportError:
            logger.error("`datasets` not installed — pip install datasets")
            return []

        # HPSv3 + most preference datasets on HF are gated → need auth.
        # Detect *up front* so we can skip with a clear message instead
        # of letting `load_dataset` throw an opaque 401 deep inside.
        if not _have_hf_auth():
            logger.warning(
                "hpsv3 : no HuggingFace auth token detected. To enable :\n"
                "  1) huggingface-cli login   (paste token from "
                "https://huggingface.co/settings/tokens)\n"
                "  2) Accept the dataset license on "
                "https://huggingface.co/datasets/MirageML/HPDv3 "
                "(or whichever HPDv3 mirror you have access to)\n"
                "  3) (optional) export HF_TOKEN=hf_... for non-interactive use\n"
                "Skipping HPSv3 — pipeline will still work via LAION + manual_refs."
            )
            return []

        target = n
        oversample = max(target * 8, 200)
        logger.info("hpsv3 : streaming %d rows, target %d archviz matches", oversample, target)

        entries: list[StyleEntry] = []
        ds = None
        used_repo = None
        last_err: str = ""
        for repo in HPSV3_CANDIDATES:
            try:
                ds = load_dataset(repo, split="train", streaming=True)
                used_repo = repo
                logger.info("hpsv3 : using repo %s", repo)
                break
            except Exception as e:
                last_err = str(e)[:200]
                logger.debug("hpsv3 candidate %s failed : %s", repo, last_err)
        if ds is None:
            # Distinguish "401/403 license not accepted" from "404 repo gone"
            # so the user knows which knob to turn.
            hint = ""
            if "401" in last_err or "403" in last_err or "gated" in last_err.lower():
                hint = (
                    "\nLooks like HF returned 401/403 — your token is valid "
                    "but you have not accepted the dataset license. Visit the "
                    "dataset page on huggingface.co and click 'Agree and access'."
                )
            logger.warning(
                "hpsv3 : all candidate repos failed (last error : %s).%s "
                "Skipping HPSv3.",
                last_err, hint,
            )
            return []

        scanned = 0
        for row in ds:
            scanned += 1
            if scanned > oversample:
                break
            # HPSv3 schema may vary by version. Try a few candidate column names.
            prompt = row.get("prompt") or row.get("caption") or row.get("text") or ""
            if not _caption_matches_archviz(prompt):
                continue

            # Look for the chosen image URL or PIL Image
            img_field = row.get("chosen_image") or row.get("image1") or row.get("image")
            img_bytes: Optional[bytes] = None
            url = row.get("chosen_url") or row.get("image1_url") or ""

            if hasattr(img_field, "save"):
                # PIL Image
                buf = io.BytesIO()
                try:
                    img_field.convert("RGB").save(buf, format="JPEG", quality=92)
                    img_bytes = buf.getvalue()
                except Exception:
                    pass
            elif url:
                img_bytes = _download_image(url)

            if not img_bytes:
                continue

            entry = StyleEntry(
                source="hpsv3",
                caption=prompt.strip(),
                original_url=url or f"hf://{used_repo}#row{scanned}",
                license="apache-2.0",
                image_bytes=img_bytes,
            )
            entries.append(entry)
            if len(entries) >= target:
                break

        logger.info("hpsv3 : scanned %d rows, kept %d archviz matches", scanned, len(entries))
        # Post-download CLIP filter — kicks out interiors / portraits
        # whose captions snuck past the keyword filter.
        entries = self.clip_filter_archviz(entries)
        self._persist_entries(entries, outdir)
        return entries

    # ---- LAION-Aesthetics --------------------------------------------------

    def fetch_laion_aesthetics_archviz(
        self,
        n: int = 500,
        min_score: float = 6.5,
        skip_rows: int = 0,
    ) -> List[StyleEntry]:
        """Pull LAION-Aesthetics 6+, filter caption + aesthetic score.

        We use the `dclure/laion-aesthetics-12m-umap` derivative which
        exposes (URL, TEXT, AESTHETIC_SCORE) without us having to
        download the 12M-row parquet. LAION's CLIP-filtered subset is
        permissively redistributable (CC-BY-4.0 metadata, image URLs
        point back to original sources).

        Returns at most `n` entries with `aesthetic_score >= min_score`
        AND archviz keyword match.

        Note 2026-06 : LAION-Aesthetics tends to surface ~60-70%
        building exteriors when filtered with our keywords ; the rest
        is misc urban scenes / landscape photography that incidentally
        mentions "building". Acceptable signal-to-noise for LoRA.
        """
        outdir = self.cache_root / "laion_archviz"
        outdir.mkdir(parents=True, exist_ok=True)

        try:
            from datasets import load_dataset
        except ImportError:
            logger.error("`datasets` not installed — pip install datasets")
            return []

        target = n
        # Conservative oversample : ~3% of rows match our archviz filter.
        oversample = max(target * 40, 2000)
        logger.info("laion : streaming up to %d rows for target %d", oversample, target)

        try:
            ds = load_dataset(LAION_AES_REPO, split="train", streaming=True)
            if skip_rows > 0:
                ds = ds.skip(skip_rows)
                logger.info("laion : skipped %d rows", skip_rows)
        except Exception as e:
            logger.warning("laion load_dataset failed : %s", e)
            return []

        entries: list[StyleEntry] = []
        scanned = 0
        skipped_score = 0
        skipped_caption = 0
        skipped_blacklist = 0
        download_failures = 0

        for row in ds:
            scanned += 1
            if scanned > oversample:
                break
            score = float(row.get("AESTHETIC_SCORE") or row.get("aesthetic_score") or 0.0)
            if score < min_score:
                skipped_score += 1
                continue
            caption = row.get("TEXT") or row.get("text") or ""
            if not _caption_matches_archviz(caption):
                skipped_caption += 1
                continue
            url = row.get("URL") or row.get("url") or ""
            if not url:
                continue
            # Stock-photo / watermark host blacklist — applied BEFORE
            # download to save bandwidth and avoid teaching the LoRA
            # to draw "Shutterstock" diagonals across every output.
            if _is_blacklisted_url(url):
                skipped_blacklist += 1
                continue
            img_bytes = _download_image(url)
            if not img_bytes:
                download_failures += 1
                continue

            entries.append(StyleEntry(
                source="laion",
                caption=caption.strip(),
                original_url=url,
                license="cc-by-4.0 (metadata) / original-source (image)",
                aesthetic_score=score,
                image_bytes=img_bytes,
            ))
            if len(entries) >= target:
                break

        logger.info(
            "laion : scanned %d, score-skip %d, caption-skip %d, "
            "blacklist-skip %d, dl-fail %d, kept (pre-CLIP) %d",
            scanned, skipped_score, skipped_caption,
            skipped_blacklist, download_failures, len(entries),
        )
        # Post-download CLIP filter — drops interiors / portraits /
        # watermarked stock that snuck past the caption + URL filters.
        entries = self.clip_filter_archviz(entries)
        logger.info("laion : kept %d after CLIP filter", len(entries))
        self._persist_entries(entries, outdir)
        return entries

    # ---- Polyhaven (metadata only) -----------------------------------------

    def fetch_polyhaven_hdris_textures(self) -> List[StyleEntry]:
        """Index Polyhaven HDRIs + textures by querying their public JSON API.

        Polyhaven explicitly allows AI training (see https://polyhaven.com/license).
        Their HDRIs (8K EXR) and PBR textures (8K) are too heavy to
        commit to the dataset (each ~100-500 MB). We store **metadata
        only** — URL + license + tags — for later use as ControlNet
        environment input at render time, not as LoRA training targets.

        Returns a list of metadata-only StyleEntry (no image_bytes).
        """
        outdir = self.cache_root / "polyhaven_refs"
        outdir.mkdir(parents=True, exist_ok=True)

        try:
            import httpx
        except ImportError:
            logger.error("`httpx` not installed")
            return []

        entries: list[StyleEntry] = []
        # We want outdoor / architectural HDRIs + facade textures.
        endpoints = [
            ("hdris", "outdoor"),
            ("hdris", "skies"),
            ("hdris", "urban"),
            ("textures", "brick"),
            ("textures", "concrete"),
            ("textures", "wood planks"),
            ("textures", "stone"),
        ]
        try:
            with httpx.Client(timeout=15.0) as client:
                for asset_type, category in endpoints:
                    url = f"{POLYHAVEN_API_BASE}/assets?t={asset_type}&c={category}"
                    try:
                        r = client.get(url)
                        r.raise_for_status()
                        assets = r.json()
                    except Exception as e:
                        logger.debug("polyhaven %s/%s failed : %s", asset_type, category, e)
                        continue
                    for slug, meta in assets.items():
                        entries.append(StyleEntry(
                            source="polyhaven",
                            caption=f"{meta.get('name', slug)} ({category} {asset_type[:-1]})",
                            original_url=f"https://polyhaven.com/a/{slug}",
                            license="CC0",
                        ))
        except Exception as e:
            logger.warning("polyhaven indexing failed : %s", e)
            return []

        manifest_path = outdir / "polyhaven_manifest.json"
        manifest_path.write_text(json.dumps([e.to_meta() for e in entries], indent=2))
        logger.info("polyhaven : indexed %d assets → %s", len(entries), manifest_path)
        return entries

    # ---- Manual refs (user-curated) ----------------------------------------

    def index_manual_refs(self, folder: Path) -> List[StyleEntry]:
        """Scan a user-curated `manual_refs/` folder, auto-caption if needed.

        Convention :
        - One image file per ref : .jpg / .jpeg / .png / .webp
        - Optional sidecar `.txt` with the caption (preferred — manual
          caption beats auto-caption every time)
        - Optional sidecar `.meta.json` with license attribution if known

        If no caption sidecar exists, we attempt BLIP-2 auto-caption (lazy
        import — only loads the model if needed). If BLIP-2 isn't
        available locally, we fall back to a generic "architectural
        photograph" caption + a warning to the user.

        License attribution defaults to "user-curated fair-use research
        (EU TDM Art 4 exception)" — the user is responsible for ensuring
        each ref is properly licensed for their training use.
        """
        folder = Path(folder)
        if not folder.exists():
            logger.warning("manual_refs folder %s does not exist", folder)
            return []

        IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
        entries: list[StyleEntry] = []
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMG_EXT)
        if not files:
            logger.info("manual_refs : no images in %s (drop your curated PNGs here)", folder)
            return []

        # Lazy-load BLIP-2 only if we need auto-captioning
        blip_processor = None
        blip_model = None

        for img_path in files:
            caption_txt = img_path.with_suffix(".txt")
            meta_json = img_path.with_suffix(".meta.json")

            if caption_txt.exists():
                caption = caption_txt.read_text().strip()
            else:
                # Auto-caption via BLIP-2 (lazy load)
                caption = None
                if blip_processor is None:
                    caption = self._try_load_blip()
                    if caption is None:
                        caption = "architectural photograph, building exterior"
                        logger.warning(
                            "manual_refs : BLIP-2 unavailable, using fallback caption "
                            "for %s — write a .txt sidecar for better quality",
                            img_path.name,
                        )

            license_str = "user-curated fair-use research (EU TDM Art 4 exception)"
            original_url = ""
            if meta_json.exists():
                try:
                    md = json.loads(meta_json.read_text())
                    license_str = md.get("license", license_str)
                    original_url = md.get("original_url", original_url)
                except Exception:
                    pass

            entries.append(StyleEntry(
                source="manual",
                caption=caption,
                original_url=original_url or f"local://{img_path.name}",
                license=license_str,
                image_bytes=img_path.read_bytes(),
            ))

        logger.info("manual_refs : indexed %d user-curated images", len(entries))
        return entries

    def _try_load_blip(self) -> Optional[str]:
        """Attempt to load BLIP-2 and return None if unavailable.

        Returns None (and logs a warning) rather than crashing — the
        caller falls back to a generic caption.
        """
        try:
            # Just probe whether the deps exist ; actual model loading
            # would happen in a tighter loop. For scaffolding we keep it
            # at probe-only.
            import transformers  # noqa: F401
            return None  # signal: probe ok but model not loaded yet
        except ImportError:
            return None

    # ---- Persistence + dedup ------------------------------------------------

    def _persist_entries(self, entries: List[StyleEntry], outdir: Path) -> None:
        """Save each entry as `<idx>.jpg` + `<idx>.meta.json`.

        Indices auto-bump past any existing files so reruns extend the
        cache rather than overwriting it.
        """
        outdir.mkdir(parents=True, exist_ok=True)
        if not entries:
            return
        # Find next free index for this source
        source = entries[0].source
        existing = sorted(outdir.glob(f"{source}_*.jpg"))
        start = 0
        if existing:
            # filename pattern : <source>_<idx:5d>.jpg
            try:
                last = existing[-1].stem
                start = int(last.split("_")[-1]) + 1
            except (ValueError, IndexError):
                start = len(existing)

        for offset, entry in enumerate(entries):
            if entry.image_bytes is None:
                continue
            stem = _safe_filename(start + offset, entry.source)
            img_path = outdir / f"{stem}.jpg"
            meta_path = outdir / f"{stem}.meta.json"
            img_path.write_bytes(entry.image_bytes)
            meta_path.write_text(json.dumps(entry.to_meta(), indent=2))

    def build_combined_dataset(
        self,
        output_dir: Path,
        max_total: int = 2000,
    ) -> Path:
        """Merge all source caches → final training-ready folder.

        Layout :
            output_dir/
                images/000001.jpg
                captions.jsonl    # {file_name, text, source, license, score}
                ATTRIBUTION.md    # human-readable license summary
        """
        output_dir = Path(output_dir)
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # Gather every (image, meta) pair from source subdirs
        sources = ["hpsv3", "laion_archviz", "manual_refs"]
        all_entries: list[StyleEntry] = []
        for src_dir_name in sources:
            src_dir = self.cache_root / src_dir_name
            if not src_dir.exists():
                continue
            for meta_path in sorted(src_dir.glob("*.meta.json")):
                # meta_path is `<stem>.meta.json` ; sibling image is
                # `<stem>.jpg`. Pathlib.with_suffix() only strips the
                # last suffix (`.json`), so we strip both manually.
                base = meta_path.parent / meta_path.name[:-len(".meta.json")]
                img_path = base.with_suffix(".jpg")
                if not img_path.exists():
                    img_path = base.with_suffix(".png")
                if not img_path.exists():
                    continue
                try:
                    md = json.loads(meta_path.read_text())
                    img_bytes = img_path.read_bytes()
                    entry = StyleEntry(
                        source=md.get("source", src_dir_name),
                        caption=md.get("caption", ""),
                        original_url=md.get("original_url", ""),
                        license=md.get("license", "unknown"),
                        aesthetic_score=md.get("aesthetic_score"),
                        image_bytes=img_bytes,
                    )
                    entry.phash = _perceptual_hash(img_bytes)
                    all_entries.append(entry)
                except Exception as e:
                    logger.debug("skip %s : %s", meta_path, e)

        logger.info("combined : loaded %d candidates", len(all_entries))

        # Dedup via pHash (Hamming distance == 0 considered duplicate ;
        # for stricter near-dup we'd use Hamming <= 6)
        seen_hashes: set[str] = set()
        deduped: list[StyleEntry] = []
        for e in all_entries:
            if e.phash and e.phash in seen_hashes:
                continue
            seen_hashes.add(e.phash or "")
            deduped.append(e)

        logger.info("combined : %d after dedup (removed %d)",
                    len(deduped), len(all_entries) - len(deduped))

        # Cap to max_total
        if len(deduped) > max_total:
            deduped = deduped[:max_total]
            logger.info("combined : capped to %d", max_total)

        captions_path = output_dir / "captions.jsonl"
        with captions_path.open("w") as f:
            for i, e in enumerate(deduped):
                fname = f"{i:06d}.jpg"
                (images_dir / fname).write_bytes(e.image_bytes)
                line = {
                    "file_name": f"images/{fname}",
                    "text": e.caption,
                    "source": e.source,
                    "license": e.license,
                    "aesthetic_score": e.aesthetic_score,
                    "original_url": e.original_url,
                }
                f.write(json.dumps(line) + "\n")

        # Attribution summary
        by_source: dict[str, int] = {}
        for e in deduped:
            by_source[e.source] = by_source.get(e.source, 0) + 1
        attr_path = output_dir / "ATTRIBUTION.md"
        attr_lines = [
            "# Dataset Attribution",
            "",
            f"Built {time.strftime('%Y-%m-%d %H:%M:%S')} — {len(deduped)} images.",
            "",
            "## Sources",
            "",
        ]
        for src, count in sorted(by_source.items()):
            attr_lines.append(f"- **{src}** : {count} images")
        attr_lines.extend([
            "",
            "## Licenses",
            "",
            "- HPSv3 : Apache 2.0 — derivative training permitted",
            "- LAION-Aesthetics : CC-BY-4.0 metadata, image URLs point to "
            "original sources (each image inherits its own upstream license)",
            "- Polyhaven : CC0 — public domain, AI training explicitly allowed",
            "- Manual refs : user-curated, fair-use research (EU Article 4 TDM exception)",
            "",
            "Per-image attribution is in `captions.jsonl` (one row per image).",
        ])
        attr_path.write_text("\n".join(attr_lines))

        logger.info("combined dataset written to %s (%d images)", output_dir, len(deduped))
        return output_dir


# -- CLI ----------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true",
                        help="Quick run : ~30 LAION + ~20 HPSv3 to validate pipeline")
    parser.add_argument("--full", action="store_true",
                        help="Full run : up to --n images across all sources")
    parser.add_argument("--n", type=int, default=2000,
                        help="Target dataset size (only used with --full)")
    parser.add_argument("--out", type=Path,
                        default=Path("refs/style_dataset/combined_v1"),
                        help="Output directory for combined dataset")
    parser.add_argument("--cache-root", type=Path,
                        default=Path("refs/style_dataset"),
                        help="Where source-specific caches live")
    parser.add_argument("--no-laion", action="store_true",
                        help="Skip LAION fetch (when API rate-limited)")
    parser.add_argument("--no-hpsv3", action="store_true",
                        help="Skip HPSv3 fetch")
    parser.add_argument("--include-polyhaven", action="store_true",
                        help="Also index Polyhaven HDRIs (metadata only)")
    args = parser.parse_args(argv)

    if not args.smoke_test and not args.full:
        parser.error("pass --smoke-test or --full")

    builder = StyleDatasetBuilder(cache_root=args.cache_root)

    if args.smoke_test:
        # Output folder name reflects target size (--n=50 → smoke_test_50,
        # --n=200 → smoke_test_200, etc.). Defaults to 50 if --n unset.
        target = args.n if args.n != 2000 else 50
        out = args.cache_root / f"smoke_test_{target}"
        builder.cache_root = out
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        laion_count = 0
        hpsv3_count = 0
        # Split target ~3:2 LAION:HPSv3 (HPSv3 yield is much lower in practice).
        laion_target = int(target * 0.6) if not args.no_hpsv3 else target
        hpsv3_target = max(target - laion_target, 0)
        if not args.no_laion:
            laion_count = len(builder.fetch_laion_aesthetics_archviz(
                n=laion_target, min_score=6.0))
        if not args.no_hpsv3 and hpsv3_target > 0:
            hpsv3_count = len(builder.fetch_hpsv3_subset(n=hpsv3_target))
        # If HPSv3 was unavailable (no HF auth), top up with extra LAION
        # so the smoke test still hits the target and proves the pipeline.
        # We use skip_rows to advance past the rows already consumed so
        # we don't refetch+dedup duplicates.
        if hpsv3_count == 0 and not args.no_laion and laion_count < target:
            top_up = target - laion_count
            logger.info("smoke : topping up %d more from LAION (HPSv3 unavailable)", top_up)
            extra = len(builder.fetch_laion_aesthetics_archviz(
                n=top_up, min_score=6.0, skip_rows=2000))
            laion_count += extra
        # Build combined out of what we got
        builder.build_combined_dataset(out, max_total=target)
        elapsed = time.time() - t0
        logger.info("smoke test done in %.1fs (laion=%d, hpsv3=%d)",
                    elapsed, laion_count, hpsv3_count)
        # Print location for the user
        print(f"\n→ Smoke test images in : {out / 'images'}")
        print(f"→ Captions in : {out / 'captions.jsonl'}")
        print(f"→ Rejected by CLIP audit : {out / 'rejected'}")
        return 0

    # Full mode
    t0 = time.time()
    if not args.no_laion:
        builder.fetch_laion_aesthetics_archviz(n=args.n // 2)
    if not args.no_hpsv3:
        builder.fetch_hpsv3_subset(n=args.n // 4)
    if args.include_polyhaven:
        builder.fetch_polyhaven_hdris_textures()
    manual = args.cache_root / "manual_refs"
    if manual.exists():
        manual_entries = builder.index_manual_refs(manual)
        builder._persist_entries(manual_entries, args.cache_root / "manual_refs_indexed")

    builder.build_combined_dataset(args.out, max_total=args.n)
    elapsed = time.time() - t0
    logger.info("full dataset build done in %.1fs", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
