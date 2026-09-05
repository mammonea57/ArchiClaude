"""Convert manual_refs/ into the format expected by modal_lora_endpoint.

modal_lora_endpoint.train_lora expects:
    <dataset_path>/
        captions.jsonl    # one line per sample: {"file_name": "...", "text": "..."}
        images/<file_name>

We have:
    manual_refs/
        <id>.jpg
        <id>.txt           # the caption text
        <id>.meta.json     # attribution metadata

This script builds an output `lora_dataset/` directory ready for upload to
the Modal `archfr-style-dataset` Volume.

Usage:
    python build_lora_dataset_manifest.py --output lora_dataset_v1
    python build_lora_dataset_manifest.py --output lora_dataset_pilot --max 50

Outputs to: refs/style_dataset/<output>/
    images/<id>.jpg     (symlink to source for space efficiency)
    captions.jsonl
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "refs" / "style_dataset" / "manual_refs"
OUT_BASE = REPO_ROOT / "refs" / "style_dataset"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="lora_dataset_v1",
                    help="Output subdir name under refs/style_dataset/")
    ap.add_argument("--max", type=int, default=0,
                    help="Cap on number of samples (0 = no cap)")
    ap.add_argument("--copy", action="store_true",
                    help="Hard-copy images (slow) instead of symlinking")
    args = ap.parse_args()

    out_dir = OUT_BASE / args.output
    images_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    captions_path = out_dir / "captions.jsonl"

    pairs = []
    for jpg in sorted(SRC_DIR.glob("*.jpg")):
        txt = jpg.with_suffix(".txt")
        if not txt.exists():
            continue
        caption = txt.read_text(encoding="utf-8").strip()
        if len(caption) < 5:
            continue
        # Reject any caption that still has HTML residue
        low = caption.lower()
        if "&lt;" in low or "<a href" in low or "<img" in low:
            print(f"  SKIP html caption {jpg.name}")
            continue
        pairs.append((jpg, caption))

    if args.max > 0:
        pairs = pairs[:args.max]

    print(f"Source : {len(list(SRC_DIR.glob('*.jpg')))} jpgs in manual_refs/")
    print(f"Usable : {len(pairs)} jpgs with valid captions")

    n_written = 0
    with captions_path.open("w", encoding="utf-8") as fp:
        for jpg, caption in pairs:
            dst = images_dir / jpg.name
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            if args.copy:
                shutil.copy2(jpg, dst)
            else:
                dst.symlink_to(jpg.resolve())
            row = {
                "file_name": f"images/{jpg.name}",
                "text": caption,
            }
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"\n✅ Wrote {n_written} samples to {out_dir}")
    print(f"   captions.jsonl : {captions_path}")
    print(f"   images/        : {images_dir}")
    print(f"\nNext steps :")
    print(f"  1. Audit a few captions :")
    print(f"     head -5 {captions_path}")
    print(f"  2. Upload to Modal volume :")
    print(f"     .venv/bin/modal volume put archfr-style-dataset \\")
    print(f"         {out_dir} /{args.output}")
    print(f"  3. Run modal_lora_endpoint with dataset_path=/{args.output}")


if __name__ == "__main__":
    main()
