"""Filter the curate pool to keep only 3D renders / CGI archviz, drop real photos.

For LoRA training of an archviz style, we want CGI/rendered images
(MIR/Brick/Forbes Massie language), not photographs of existing
buildings. CLIP can distinguish photo vs render by texture, lighting,
and people rendering cues.

Strategy:
    pos_render = max similarity to CGI / rendered / archviz captions
    pos_photo  = max similarity to documentary / photo captions
    score = pos_render - pos_photo
    threshold > 0 → keep (= more "render-like")

Runs on the existing manifest.json — items below threshold are moved
to `_filtered_photos/` for audit.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"

# Captions that describe CGI / rendered images (POS)
RENDER_PROMPTS = (
    "a 3D architectural rendering of a future apartment building",
    "a CGI render of a residential building exterior",
    "an architectural visualization with computer-generated people and trees",
    "a photorealistic 3D render for a real estate marketing brochure",
    "a permit application render of a collective housing project",
    "an archviz exterior render showing a modern apartment block",
    "a 3D rendering with computed shadows and ambient occlusion",
    "a digital archviz of an unbuilt residential development",
    "a Lumion or V-Ray render of an apartment building",
    "a render of a not-yet-built mixed-use building with showroom-like people",
)

# Captions describing real-world photographs (NEG)
PHOTO_PROMPTS = (
    "a documentary photograph of an existing apartment building",
    "a real photograph of a city street with real people walking",
    "a heritage photograph of a Haussmann building in Paris",
    "an architectural photograph by a professional photographer",
    "a real estate listing photo of an apartment for sale",
    "a Google street view of a real built building",
    "a tourist snapshot of a historic district",
    "a black and white historical photograph of a building",
    "a smartphone photo of an apartment block",
    "a real photograph with motion blur and natural lighting",
)

logger = logging.getLogger("archfr.render_filter")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-dir", type=Path, default=DEFAULT_POOL_DIR)
    ap.add_argument("--threshold", type=float, default=0.005,
                    help="(render_score - photo_score) min. >0 = more render-like")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--regenerate-ui", action="store_true", default=True)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    manifest_path = args.pool_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d items from manifest", len(manifest))

    import torch
    import open_clip
    from PIL import Image

    device = "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k", device=device,
    )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval()

    prompts = list(RENDER_PROMPTS) + list(PHOTO_PROMPTS)
    n_render = len(RENDER_PROMPTS)
    with torch.no_grad():
        tok = tokenizer(prompts)
        text_feats = model.encode_text(tok)
        text_feats = text_feats / text_feats.norm(dim=-1, keepdim=True)

    photos_dir = args.pool_dir / "_filtered_photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    kept = []
    dropped_photos = []
    for i, item in enumerate(manifest):
        full_path = args.pool_dir / item["full"]
        if not full_path.exists():
            continue
        try:
            img = preprocess(Image.open(full_path).convert("RGB")).unsqueeze(0).to(device)
        except Exception:
            continue
        with torch.no_grad():
            img_feat = model.encode_image(img)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            sims = (img_feat @ text_feats.T).squeeze(0)
        render_max = sims[:n_render].max().item()
        photo_max = sims[n_render:].max().item()
        score = render_max - photo_max
        item["render_score"] = round(render_max, 4)
        item["photo_score"] = round(photo_max, 4)
        item["render_vs_photo"] = round(score, 4)
        if score >= args.threshold:
            kept.append(item)
        else:
            dropped_photos.append(item)
            if not args.dry_run:
                for sub in ("full", "thumb"):
                    src = args.pool_dir / item[sub]
                    if src.exists():
                        dst = photos_dir / item[sub]
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.move(str(src), str(dst))
                        except Exception:
                            pass
        if (i + 1) % 50 == 0:
            logger.info("  %d/%d (kept_render=%d photo_dropped=%d)",
                        i + 1, len(manifest), len(kept), len(dropped_photos))

    if not args.dry_run:
        manifest_path.write_text(json.dumps(kept, indent=2), encoding="utf-8")
        logger.info("Manifest rewritten with %d render-only items", len(kept))

    dt = time.time() - t0
    logger.info("DONE in %.0fs : renders=%d photos=%d (threshold=%.3f)",
                dt, len(kept), len(dropped_photos), args.threshold)

    if args.regenerate_ui and not args.dry_run:
        import subprocess
        subprocess.run(
            [str(REPO_ROOT / "apps" / "render-service" / ".venv" / "bin" / "python"),
             str(REPO_ROOT / "apps" / "render-service" / "scripts" / "generate_curate_ui.py")],
            capture_output=True, text=True,
        )

    print(f"\n✅ Render-filter: kept {len(kept)} renders, moved {len(dropped_photos)} photos to _filtered_photos/")


if __name__ == "__main__":
    main()
