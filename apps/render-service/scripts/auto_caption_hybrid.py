"""Hybrid BLIP-2 + curated CLIP-Interrogator captioning for LoRA training.

BLIP-2 generates the objective description of the building.
A simplified "CLIP-Interrogator-lite" then matches the image against a
CURATED archviz tag dictionary (styles, materials, lighting, time-of-day,
viewpoint, context) and appends the top-K most relevant tags.

Output format (LoRA-friendly):
    <BLIP-2 description>, <material1>, <material2>, <lighting>, <style>, <viewpoint>

This is faster than full CLIP-Interrogator (which scans 100k+ tokens)
because we restrict to ~200 archviz-relevant terms — ~0.5s per image
on CPU instead of 1-2 min.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MANUAL_REFS_DIR = REPO_ROOT / "refs" / "style_dataset" / "manual_refs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("caption_hybrid")


# ---- Curated archviz tag dictionary ----------------------------------------
TAGS_BY_GROUP = {
    "materials": [
        "brick facade", "concrete facade", "wood cladding", "metal cladding",
        "glass facade", "stone facade", "rendered plaster", "zinc roof",
        "terracotta tiles", "weathering steel", "limestone", "marble",
        "corten steel", "white concrete", "exposed concrete", "stucco",
        "ceramic tiles", "natural stone", "polished concrete", "white render",
    ],
    "lighting": [
        "golden hour lighting", "blue hour", "overcast lighting",
        "bright sunny day", "soft daylight", "warm interior glow",
        "dramatic shadows", "twilight ambient", "civil twilight",
        "morning light", "afternoon sun", "rainy atmospheric light",
    ],
    "style": [
        "modernist architecture", "contemporary design", "minimalist style",
        "brutalist architecture", "haussmannian style", "industrial style",
        "scandinavian design", "biophilic design", "sustainable architecture",
        "passive house design", "art deco style", "mediterranean style",
        "vernacular architecture", "high-tech style", "deconstructivist",
    ],
    "typology": [
        "residential apartment building", "mixed-use development",
        "social housing block", "mid-rise apartment", "low-rise residential",
        "high-rise tower", "collective housing", "row of townhouses",
        "loft building", "courtyard housing", "single-family detached house",
        "semi-detached residential",
    ],
    "viewpoint": [
        "eye-level street view", "aerial view", "three-quarter perspective",
        "low-angle exterior", "facade-on view", "corner view at intersection",
        "approaching the entrance", "viewed from across the street",
        "drone perspective", "bird's-eye view",
    ],
    "context": [
        "with trees and vegetation", "in a city street",
        "with people walking", "with parked cars",
        "with balconies and plants", "with rooftop garden",
        "with ground-floor shops", "with sidewalk and bike lane",
        "by a river or canal", "in a residential neighborhood",
        "in a paved plaza", "with surrounding low-rise buildings",
        "with vertical greenery", "with terraces and planters",
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", type=Path, default=MANUAL_REFS_DIR)
    ap.add_argument("--blip2-model", type=str, default="Salesforce/blip2-opt-2.7b")
    ap.add_argument("--clip-model", type=str, default="ViT-B-32")
    ap.add_argument("--clip-pretrained", type=str, default="laion2b_s34b_b79k")
    ap.add_argument("--top-k", type=int, default=2,
                    help="Top-K tags to pick from each group")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    images = sorted(args.input_dir.glob("*.jpg"))
    if not images:
        logger.error("No .jpg images in %s", args.input_dir)
        sys.exit(1)

    if not args.overwrite:
        to_caption = []
        for img in images:
            txt = img.with_suffix(".txt")
            if txt.exists() and txt.stat().st_size > 20:
                continue  # already has a real caption (>20 chars)
            to_caption.append(img)
        logger.info("Found %d images, %d already captioned (>20 chars), %d to caption",
                    len(images), len(images) - len(to_caption), len(to_caption))
        images = to_caption

    if not images:
        logger.info("All images already captioned — nothing to do.")
        sys.exit(0)

    # ---- Load BLIP-2 -------------------------------------------------------
    logger.info("Loading BLIP-2 : %s (~5 GB download on first run)", args.blip2_model)
    from transformers import Blip2Processor, Blip2ForConditionalGeneration
    import torch
    from PIL import Image

    processor = Blip2Processor.from_pretrained(args.blip2_model)
    model = Blip2ForConditionalGeneration.from_pretrained(
        args.blip2_model, torch_dtype=torch.float32,
    )
    device = "cpu"
    model.to(device).eval()
    logger.info("BLIP-2 loaded on %s", device)

    # ---- Load CLIP for tag matching ----------------------------------------
    logger.info("Loading CLIP : %s/%s", args.clip_model, args.clip_pretrained)
    import open_clip
    clip_model, _, clip_preprocess = open_clip.create_model_and_transforms(
        args.clip_model, pretrained=args.clip_pretrained, device=device,
    )
    clip_tokenizer = open_clip.get_tokenizer(args.clip_model)
    clip_model.eval()
    # Pre-compute text features for all tags grouped
    tag_features = {}
    for group, tags in TAGS_BY_GROUP.items():
        with torch.no_grad():
            tok = clip_tokenizer(tags)
            feats = clip_model.encode_text(tok)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        tag_features[group] = (tags, feats)
    logger.info("CLIP tag dictionary ready : %d groups, %d total tags",
                len(TAGS_BY_GROUP), sum(len(v) for v in TAGS_BY_GROUP.values()))

    t0 = time.time()
    n_done = 0
    for img_path in images:
        try:
            img = Image.open(img_path).convert("RGB")

            # ---- BLIP-2 base description ----
            inputs = processor(images=img, text="a photo of",
                               return_tensors="pt").to(device)
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=40,
                                     num_beams=3, do_sample=False)
            description = processor.batch_decode(out, skip_special_tokens=True)[0].strip()
            for stub in ("a photo of", "a photograph of"):
                if description.lower().startswith(stub):
                    description = description[len(stub):].strip()
            if not description:
                description = "an architectural exterior view of a building"

            # ---- CLIP tag matching ----
            with torch.no_grad():
                clip_img = clip_preprocess(img).unsqueeze(0).to(device)
                img_feat = clip_model.encode_image(clip_img)
                img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)

            tag_results = []
            for group, (tags, feats) in tag_features.items():
                with torch.no_grad():
                    sims = (img_feat @ feats.T).squeeze(0)
                top_idx = sims.topk(min(args.top_k, len(tags))).indices.tolist()
                top_tags = [tags[i] for i in top_idx]
                # Take just the top 1 per group except materials/context (top 2)
                k = args.top_k if group in ("materials", "context") else 1
                tag_results.extend(top_tags[:k])

            # ---- Combine ----
            full_caption = description.rstrip(".") + ", " + ", ".join(tag_results)
            img_path.with_suffix(".txt").write_text(full_caption, encoding="utf-8")
            n_done += 1

            if n_done % 5 == 0:
                dt = time.time() - t0
                rate = dt / n_done
                eta = (len(images) - n_done) * rate
                logger.info("  %d/%d done, %.1fs/img, ETA %.0fs | %s",
                            n_done, len(images), rate, eta, full_caption[:100])
        except Exception as e:
            logger.warning("Fail %s : %s", img_path.name, e)

    dt = time.time() - t0
    logger.info("DONE in %.0fs (avg %.1fs/img) : captioned %d images",
                dt, dt / max(n_done, 1), n_done)


if __name__ == "__main__":
    main()
