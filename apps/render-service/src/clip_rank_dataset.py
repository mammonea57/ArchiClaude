"""CLIP-rank a candidate dataset against a moodboard of reference images.

For each candidate, compute the cosine similarity of its CLIP embedding
to the average embedding of the moodboard. Output is a ranked CSV
(highest similarity first) so we can keep the top-N for downstream
strict-filtering.

Use case : we scraped 2750 archviz pins ; we want to keep only the
~1000 that visually match the top-26 consensus reference pins identified
by the 9-sub-agent moodboard analysis. CLIP alone is not strict enough
(it ranks aesthetic similarity, not 10 hard criteria) but it's perfect
to drop the bottom 60% before the expensive VLM strict-filter pass.

Usage :
    python -m src.clip_rank_dataset \
        --candidates /tmp/dataset_to_filter \
        --moodboard /Users/.../refs/moodboards/consensus_top26 \
        --out-csv /tmp/clip_ranked.csv \
        --top-keep-dir /tmp/dataset_clip_top1000 \
        --keep-top 1000
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def _load_clip(model_name: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k"):
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained, device="cpu",
    )
    model.eval()
    return model, preprocess


def _embed(path: Path, model, preprocess):
    import torch
    from PIL import Image
    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:
        print(f"  !! cannot open {path.name} ({e})", flush=True)
        return None
    with torch.no_grad():
        x = preprocess(img).unsqueeze(0)
        emb = model.encode_image(x).squeeze(0)
        emb = emb / emb.norm()
    return emb


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", type=Path, required=True,
                    help="Directory of candidate images (rglob)")
    ap.add_argument("--moodboard", type=Path, required=True,
                    help="Directory of reference moodboard images")
    ap.add_argument("--out-csv", type=Path, default=Path("/tmp/clip_ranked.csv"))
    ap.add_argument("--keep-top", type=int, default=0,
                    help="If >0, also copy/symlink top-N candidates")
    ap.add_argument("--top-keep-dir", type=Path, default=None)
    ap.add_argument("--copy", action="store_true")
    args = ap.parse_args()

    print(f"[clip] loading model … (CPU)", flush=True)
    model, preprocess = _load_clip()

    print(f"[clip] embed moodboard from {args.moodboard}", flush=True)
    refs = sorted(p for p in args.moodboard.rglob("*")
                  if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not refs:
        sys.exit(f"no images in moodboard {args.moodboard}")
    import torch
    ref_embs = []
    for p in refs:
        e = _embed(p, model, preprocess)
        if e is not None:
            ref_embs.append(e)
    ref_stack = torch.stack(ref_embs)
    ref_avg = ref_stack.mean(dim=0)
    ref_avg = ref_avg / ref_avg.norm()
    print(f"[clip] moodboard avg ready ({len(ref_embs)} refs)", flush=True)

    print(f"[clip] scoring candidates from {args.candidates}", flush=True)
    cands = sorted(p for p in args.candidates.rglob("*")
                   if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not cands:
        sys.exit(f"no candidates in {args.candidates}")
    print(f"  {len(cands)} candidates to rank", flush=True)

    rows = []
    for i, p in enumerate(cands, 1):
        e = _embed(p, model, preprocess)
        if e is None:
            continue
        score = float(torch.dot(e, ref_avg).item())
        rows.append({"path": str(p), "basename": p.name, "score": score})
        if i % 100 == 0 or i == len(cands):
            print(f"  [{i}/{len(cands)}] last={p.name} score={score:+.4f}", flush=True)

    rows.sort(key=lambda r: r["score"], reverse=True)

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "score", "basename", "path"])
        w.writeheader()
        for rank, r in enumerate(rows, 1):
            w.writerow({"rank": rank, "score": f"{r['score']:.6f}",
                        "basename": r["basename"], "path": r["path"]})
    print(f"\n✓ ranked CSV : {args.out_csv}")

    if args.keep_top > 0 and args.top_keep_dir is not None:
        args.top_keep_dir.mkdir(parents=True, exist_ok=True)
        top = rows[: args.keep_top]
        for r in top:
            src = Path(r["path"])
            dest = args.top_keep_dir / src.name
            if args.copy:
                shutil.copy2(src, dest)
            else:
                try:
                    if dest.exists() or dest.is_symlink():
                        dest.unlink()
                    dest.symlink_to(src.resolve())
                except FileExistsError:
                    pass
        print(f"✓ kept top-{args.keep_top} in {args.top_keep_dir}")


if __name__ == "__main__":
    main()
