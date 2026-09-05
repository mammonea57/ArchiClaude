"""Filter the existing curate pool using CLIP image-side classification.

Reads `refs/style_dataset/curate_pool/manifest.json`, classifies each
image with CLIP zero-shot ("building/archviz" vs "person/animal/anime/etc"),
and moves the obvious-noise images into `_filtered_out/` so the UI grid
only shows likely-archviz candidates.

Permissive threshold = we want to KEEP borderline cases (the user filters
the final ❤️ pass) but DROP obvious non-archviz (Trump, llamas, anime,
abstract art, etc.).

Usage:
    .venv/bin/python apps/render-service/scripts/filter_curate_pool.py \
        --threshold 0.10
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

# Strict domain filter: KEEP only what's useful for promoteurs immobiliers
# + architectes (building exteriors, archviz renders, urban context, facade
# details, plans). REJECT everything else aggressively.
POSITIVE_PROMPTS = (
    # Collective residential — high weight (multiple variants)
    "an architectural visualization render of a multi-story residential apartment building",
    "a photograph of an apartment building with multiple floors and balconies",
    "an exterior view of a mid-rise residential block",
    "a collective housing development in a city",
    "a mixed-use building with shops at ground floor and apartments above",
    "an apartment building facade with windows on multiple floors",
    "a modern social housing project exterior",
    "a real estate marketing render of a residential development",
    "a row of urban apartment buildings on a street",
    "an architectural project rendering of a residential complex with people on the street",
    "a permit application exterior render of a collective housing project",
    "a contemporary apartment building with brick or concrete or metal facade",
    # Mid-tier helpful but lower weight
    "a contemporary office building exterior",
    "an architectural model of an urban housing project",
    "a building site plan or section drawing",
    "a building under construction with scaffolding",
    "a row of townhouses or terraced houses",
)
NEGATIVE_PROMPTS = (
    # people / portraits / celebrities
    "a portrait photograph of a person",
    "a close-up of a person's face",
    "a politician giving a speech at a podium",
    "donald trump or joe biden or vladimir putin",
    "a celebrity at a red carpet event",
    "a fashion model posing",
    "a group of people posing for a selfie",
    "a child playing or smiling",
    # animals
    "a llama or alpaca standing in a field",
    "a horse running in a pasture",
    "a dog or cat lying on the ground",
    "a wild animal like a bear or lion",
    "birds flying in the sky",
    "a farm animal grazing",
    # stylized / non-photoreal / pop culture
    "an anime or manga illustration",
    "a cartoon drawing or pixar character",
    "concept art for a science fiction video game",
    "a fantasy painting with castles and dragons and wizards",
    "a comic book panel",
    "a child's crayon drawing",
    "a graphic design poster or logo",
    "an abstract painting with colors and shapes",
    # interiors
    "an interior view of a kitchen with cabinets",
    "an interior of a living room with sofa",
    "a bedroom interior with bed and lamp",
    "a bathroom interior",
    "a hotel room interior",
    "a restaurant or cafe interior with tables",
    "an empty room with white walls",
    # food / events / lifestyle / sports
    "food on a plate or in a bowl",
    "a wedding ceremony with bride and groom",
    "a sports event with athletes",
    "a music concert with stage lights",
    "a birthday party or celebration",
    # nature / landscape / outdoors without buildings
    "a forest with trees and no buildings",
    "a mountain range with snow",
    "a beach with sand and ocean",
    "a flower garden close-up",
    "a sunset over the ocean",
    "a single tree in a field",
    # vehicles / tech / machinery
    "a car or truck close-up exterior",
    "a vintage classic car",
    "an airplane in the sky",
    "a smartphone or laptop screen",
    "industrial machinery or factory equipment",
    # misc noise
    "a watermarked stock photo with text overlay",
    "a screenshot of a webpage or app interface",
    "a 19th century historical painting",
    "a black and white historical photograph",
    "a map or satellite view",
    "a clothing item like a dress or shirt",
    "a piece of jewelry",
    "a book cover or magazine page",
    # under-represented in our target — small detached houses / heritage are nice
    # but ArchiClaude promotes collective housing for promoteurs
    "a small single-family detached house in a garden",
    "a country cottage with a thatched roof",
    "a victorian or gothic style heritage mansion",
    "a tropical resort villa with palm trees",
    "a luxury private mansion estate",
    "a tiny house or cabin",
    "a wooden chalet in the mountains",
)

logger = logging.getLogger("archfr.curate.filter")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-dir", type=Path, default=DEFAULT_POOL_DIR)
    ap.add_argument("--threshold", type=float, default=0.10,
                    help="Min (POS - NEG) score. Higher=stricter. 0.10 = moderate.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--regenerate-ui", action="store_true", default=True)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    manifest_path = args.pool_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d items from manifest", len(manifest))

    try:
        import torch
        import open_clip
        from PIL import Image
        import numpy as np
    except ImportError as e:
        logger.error("Missing deps : %s", e)
        return

    logger.info("Loading CLIP : ViT-B-32 laion2b_s34b_b79K")
    device = "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k", device=device,
    )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval()

    prompts = list(POSITIVE_PROMPTS) + list(NEGATIVE_PROMPTS)
    n_pos = len(POSITIVE_PROMPTS)
    with torch.no_grad():
        tok = tokenizer(prompts)
        text_feats = model.encode_text(tok)
        text_feats = text_feats / text_feats.norm(dim=-1, keepdim=True)

    filtered_dir = args.pool_dir / "_filtered_out"
    filtered_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    kept = []
    dropped = []
    for i, item in enumerate(manifest):
        full_path = args.pool_dir / item["full"]
        if not full_path.exists():
            continue
        try:
            img = preprocess(Image.open(full_path).convert("RGB")).unsqueeze(0).to(device)
        except Exception as e:
            logger.warning("PIL fail %s : %s", full_path.name, e)
            continue
        with torch.no_grad():
            img_feat = model.encode_image(img)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            sims = (img_feat @ text_feats.T).squeeze(0)  # (n_prompts,)
        pos_max = sims[:n_pos].max().item()
        neg_max = sims[n_pos:].max().item()
        score = pos_max - neg_max
        item["clip_pos"] = round(pos_max, 4)
        item["clip_neg"] = round(neg_max, 4)
        item["clip_score"] = round(score, 4)
        if score >= args.threshold:
            kept.append(item)
        else:
            dropped.append(item)
            # Move into _filtered_out for audit
            if not args.dry_run:
                for sub in ("full", "thumb"):
                    src = args.pool_dir / item[sub]
                    if src.exists():
                        dst = filtered_dir / item[sub]
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.move(str(src), str(dst))
                        except Exception:
                            pass
        if (i + 1) % 100 == 0:
            logger.info("  %d/%d processed (kept=%d dropped=%d)",
                        i + 1, len(manifest), len(kept), len(dropped))

    if not args.dry_run:
        # Rewrite manifest with only kept items
        manifest_path.write_text(json.dumps(kept, indent=2), encoding="utf-8")
        logger.info("Manifest rewritten with %d kept items", len(kept))

    dt = time.time() - t0
    logger.info("DONE in %.0fs : kept=%d dropped=%d (threshold=%.2f)",
                dt, len(kept), len(dropped), args.threshold)

    if args.regenerate_ui and not args.dry_run:
        # Re-run the UI generator
        import subprocess
        result = subprocess.run(
            [str(REPO_ROOT / "apps" / "render-service" / ".venv" / "bin" / "python"),
             str(REPO_ROOT / "apps" / "render-service" / "scripts" / "generate_curate_ui.py")],
            capture_output=True, text=True,
        )
        print(result.stdout)

    print(f"\n✅ Filtered: {len(kept)} kept, {len(dropped)} moved to _filtered_out/")
    print(f"   Reload curate.html in your browser to see the cleaner pool")


if __name__ == "__main__":
    main()
