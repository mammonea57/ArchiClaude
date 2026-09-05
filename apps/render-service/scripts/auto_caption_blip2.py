"""Auto-caption manual_refs images with BLIP-2 for LoRA training pickup.

BLIP-2 produces objective descriptions of images. Each caption is saved as a
.txt sidecar matching the LoRA training convention. Pre-existing .txt files
(Pinterest RSS captions) are kept untouched.

Runs on CPU (no GPU required) at ~10-20 sec/image with blip2-opt-2.7b.
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
logger = logging.getLogger("blip2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", type=Path, default=MANUAL_REFS_DIR)
    ap.add_argument("--model", type=str, default="Salesforce/blip2-opt-2.7b",
                    help="HuggingFace model id")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--prompt-prefix", type=str,
                    default="a photo of",
                    help="Conditional caption prompt prefix")
    args = ap.parse_args()

    images = sorted(args.input_dir.glob("*.jpg"))
    if not images:
        logger.error("No .jpg images in %s", args.input_dir)
        sys.exit(1)

    # Pre-filter: skip images that already have a non-empty .txt
    if not args.overwrite:
        to_caption = []
        for img in images:
            txt = img.with_suffix(".txt")
            if txt.exists() and txt.stat().st_size > 5:
                continue
            to_caption.append(img)
        logger.info("Found %d images, %d already captioned, %d to caption",
                    len(images), len(images) - len(to_caption), len(to_caption))
        images = to_caption

    if not images:
        logger.info("All images already captioned — nothing to do.")
        sys.exit(0)

    logger.info("Loading BLIP-2 model : %s (will download ~5GB on first run)", args.model)
    from transformers import Blip2Processor, Blip2ForConditionalGeneration
    import torch
    from PIL import Image

    processor = Blip2Processor.from_pretrained(args.model)
    model = Blip2ForConditionalGeneration.from_pretrained(
        args.model, torch_dtype=torch.float32,
    )
    device = "cpu"
    model.to(device)
    model.eval()
    logger.info("Model loaded on %s. Captioning %d images.", device, len(images))

    t0 = time.time()
    n_done = 0
    for img_path in images:
        try:
            img = Image.open(img_path).convert("RGB")
            inputs = processor(images=img, text=args.prompt_prefix, return_tensors="pt").to(device)
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=50,
                                     num_beams=3, do_sample=False)
            caption = processor.batch_decode(out, skip_special_tokens=True)[0].strip()
            # Strip the prompt prefix if BLIP-2 includes it
            for stub in (args.prompt_prefix, args.prompt_prefix.strip()):
                if caption.lower().startswith(stub.lower()):
                    caption = caption[len(stub):].strip()
            if not caption:
                caption = "an architectural exterior view of a residential building"
            # Save the caption alongside the image
            img_path.with_suffix(".txt").write_text(caption, encoding="utf-8")
            n_done += 1
            if n_done % 10 == 0:
                dt = time.time() - t0
                rate = dt / n_done
                eta = (len(images) - n_done) * rate
                logger.info("  %d/%d done, %.1fs/img, ETA %.0fs (caption: %s)",
                            n_done, len(images), rate, eta, caption[:60])
        except Exception as e:
            logger.warning("Fail %s : %s", img_path.name, e)

    dt = time.time() - t0
    logger.info("DONE in %.0fs : captioned %d images", dt, n_done)


if __name__ == "__main__":
    main()
