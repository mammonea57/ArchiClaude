"""Strict target-tier filter via Claude Vision.

Each candidate image gets a binary keep/reject decision based on 10
hard criteria. The goal : eliminate the noise that polluted the v1 LoRA
training (Pinterest random scrape included Dubai luxury, Indian villas,
Asian shophouses, AI watermark renders — none of which match the user's
actual production : French mid-rise residential brick infill).

Criteria (image MUST satisfy ALL of these to be kept) :
  M1  Mid-rise R+3 to R+7 (3 to 7 floors)
  M2  European urban context (Berlin / Paris / London / Amsterdam / Nordic / Italian / Belgian / Dutch)
  M3  Materials = brick OR raw concrete OR wood louvers/slats dominant
  M4  Photoreal quality (real photo OR top-tier CGI Brick-Visual+)
  M5  Composition = human-eye 3/4 corner OR street-level hero (NOT pure aerial / NOT floor plan)
  M6  Building visible from outside (NOT pure interior shot)
  M7  No visible watermark / studio logo overlay
  M8  Building proportions architecturally credible (NOT AI-warped)
  M9  Context shows urban infill or mitoyen neighbours (NOT isolated villa / NOT skyscraper)
  M10 Aesthetic register = calm European editorial (NOT Dubai luxury / NOT Miami tropical / NOT Indian commercial / NOT Vietnamese shophouse)

Output : JSON per image with {keep: bool, reasons_reject: [str], confidence: float}.

Usage :
    python -m src.strict_target_filter <input_dir> --out-keep <keep_dir> --out-reject <reject_dir>
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional


CRITERIA_SYSTEM = """You are a brutal archviz curator filtering training data for a French residential mid-rise LoRA.

REJECT any image that fails ANY of these 10 criteria :

  M1  Mid-rise R+3 to R+7 (3 to 7 floors). Reject single-family houses, villas, skyscrapers, low-rise <3 floors.
  M2  European urban context. Reject Dubai / Gulf / Indian / Vietnamese / Asian / Miami / tropical resort / desert.
  M3  Materials = brick OR raw concrete OR wood louvers/slats dominant facade. Reject all-glass curtain wall, all-metal, all-stucco-painted-bright-colors.
  M4  Photoreal quality. Reject AI-obvious renders (warped geometry, blobby people, hallucinated details), low-res thumbnails, hand-drawn sketches.
  M5  Composition = human-eye 3/4 corner OR street-level hero. Reject pure aerial top-down, floor plans, axonometric massing diagrams, interior-only shots.
  M6  Building visible from outside.
  M7  No visible watermark, logo overlay, studio signature, Pinterest UI screenshot, Instagram UI overlay.
  M8  Building proportions architecturally credible. Reject obvious AI warping (balconies that don't align, walls that bend, perspective broken).
  M9  Urban infill context or mitoyen neighbours visible OR clearly fits European city street. Reject isolated villas in nature, skyscrapers, suburban single-detached.
  M10 Aesthetic register = calm European editorial (Berlin / Paris / Amsterdam / Brick Visual / MIR / Forbes Massie / Studio Voyager style). Reject Dubai luxury supercars staging, Miami pastels, Indian commercial signage, Vietnamese tube houses, parametric Zaha-style.

Output ONLY a JSON object, no prose :
{
  "keep": true|false,
  "reasons_reject": ["M1: ...", "M9: ..."]  (empty array if keep=true),
  "confidence": 0.0-1.0  (your confidence in the decision)
}

Be brutal. Default to REJECT when uncertain. We need a strict dataset, not a permissive one. False negatives are fine; false positives pollute the LoRA.
"""


def _b64(path: Path) -> tuple[str, str]:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    ext = path.suffix.lower()
    mt = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp"}.get(ext, "image/jpeg")
    return data, mt


def classify_image(path: Path, client, model: str = "claude-haiku-4-5-20251001") -> dict:
    data, mt = _b64(path)
    msg = client.messages.create(
        model=model,
        max_tokens=400,
        system=CRITERIA_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": mt, "data": data,
                }},
                {"type": "text", "text": "Classify this image strictly."},
            ],
        }],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"keep": False, "reasons_reject": ["INVALID_JSON_OUTPUT"], "confidence": 0.0, "_raw": text[:200]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_dir", type=Path)
    ap.add_argument("--out-keep", type=Path, required=True)
    ap.add_argument("--out-reject", type=Path, required=True)
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--copy", action="store_true",
                    help="Copy files instead of symlinking")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process at most N images (0 = all)")
    ap.add_argument("--log", type=Path, default=Path("/tmp/strict_filter.jsonl"))
    args = ap.parse_args()

    from anthropic import Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY env var required")
    client = Anthropic(api_key=api_key)

    pngs = sorted(p for p in args.input_dir.rglob("*")
                  if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if args.limit:
        pngs = pngs[: args.limit]
    if not pngs:
        sys.exit(f"no images in {args.input_dir}")

    args.out_keep.mkdir(parents=True, exist_ok=True)
    args.out_reject.mkdir(parents=True, exist_ok=True)
    log_handle = args.log.open("w")

    n_keep, n_reject = 0, 0
    print(f"strict-filter {len(pngs)} imgs from {args.input_dir} (workers={args.max_workers})", flush=True)

    def process(p: Path):
        try:
            verdict = classify_image(p, client)
            verdict["path"] = str(p)
            verdict["basename"] = p.name
            return p, verdict
        except Exception as e:
            return p, {"keep": False, "reasons_reject": [f"ERROR: {type(e).__name__}: {e}"], "confidence": 0.0, "path": str(p), "basename": p.name}

    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        futs = [ex.submit(process, p) for p in pngs]
        for i, fut in enumerate(as_completed(futs), 1):
            p, verdict = fut.result()
            log_handle.write(json.dumps(verdict, ensure_ascii=False) + "\n")
            log_handle.flush()
            dest_dir = args.out_keep if verdict.get("keep") else args.out_reject
            dest = dest_dir / p.name
            if args.copy:
                shutil.copy2(p, dest)
            else:
                try:
                    if dest.exists() or dest.is_symlink():
                        dest.unlink()
                    dest.symlink_to(p.resolve())
                except FileExistsError:
                    pass
            if verdict.get("keep"):
                n_keep += 1
            else:
                n_reject += 1
            if i % 20 == 0 or i == len(pngs):
                print(f"  [{i}/{len(pngs)}] keep={n_keep} reject={n_reject}", flush=True)

    log_handle.close()
    print(f"\n✓ done : {n_keep} kept / {n_reject} rejected ({n_keep + n_reject} total)")
    print(f"  keep dir   : {args.out_keep}")
    print(f"  reject dir : {args.out_reject}")
    print(f"  log        : {args.log}")


if __name__ == "__main__":
    main()
