#!/usr/bin/env python3
"""Planche de contrôle render→photo : 16 lignes (photo | canny | depth)
échantillonnées sur tout le manifest (du meilleur au moins bon score CLIP)."""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "refs"
OUT = REFS / "render_engine_rd" / "dataset"
PREVIEW = REFS / "render_engine_rd" / "dataset_preview.png"


def main():
    rows = [json.loads(l) for l in (OUT / "manifest.jsonl").read_text().splitlines() if l.strip()]
    if not rows:
        return
    n = 16
    step = max(1, len(rows) // n)
    sel = rows[::step][:n]
    cell = 224
    pad = 4
    has_depth = any(r.get("depth") for r in sel)
    cols = 3 if has_depth else 2
    W = cols * cell + (cols + 1) * pad
    H = len(sel) * (cell + pad) + pad
    canvas = Image.new("RGB", (W, H), (18, 18, 18))
    for i, r in enumerate(sel):
        y = pad + i * (cell + pad)
        tiles = [REFS / r["image"], REFS / r["canny"]]
        if has_depth and r.get("depth"):
            tiles.append(REFS / r["depth"])
        for j, t in enumerate(tiles):
            x = pad + j * (cell + pad)
            try:
                im = Image.open(t).convert("RGB").resize((cell, cell))
                canvas.paste(im, (x, y))
            except Exception:
                pass
    canvas.save(PREVIEW)
    print(f"[preview] ✓ {len(sel)} lignes (photo|canny{'|depth' if has_depth else ''}) → {PREVIEW}")


if __name__ == "__main__":
    main()
