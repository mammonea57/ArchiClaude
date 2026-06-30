#!/usr/bin/env python3
"""Complète le dataset render→photo avec les depth maps DPT.
Séparé du build principal car le download HF de dpt-large peut staller (Xet).
Lit le manifest, écrit refs/render_engine_rd/dataset/depth/*.png, met à jour le
champ "depth" du manifest. Idempotent (skip si depth déjà présent)."""
import json
import os
from pathlib import Path

# Xet (le nouveau backend HF) stalle souvent sur ce Mac → forcer HTTP classique.
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "refs"
OUT = REFS / "render_engine_rd" / "dataset"
MAN = OUT / "manifest.jsonl"


def main():
    import numpy as np
    import torch
    import cv2
    from PIL import Image
    from transformers import DPTForDepthEstimation, DPTImageProcessor

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[depth] device={device} ; load Intel/dpt-large …", flush=True)
    dpt = DPTForDepthEstimation.from_pretrained("Intel/dpt-large").eval().to(device)
    proc = DPTImageProcessor.from_pretrained("Intel/dpt-large")
    print("[depth] modèle chargé", flush=True)

    rows = [json.loads(l) for l in MAN.read_text().splitlines() if l.strip()]
    done = 0
    for i, r in enumerate(rows):
        img_p = REFS / r["image"]
        depth_p = OUT / "depth" / (Path(r["image"]).stem + ".png")
        if depth_p.exists() and r.get("depth"):
            done += 1
            continue
        im = Image.open(img_p).convert("RGB")
        side = im.size[0]
        with torch.no_grad():
            inp = proc(images=im, return_tensors="pt").to(device)
            pred = dpt(**inp).predicted_depth.cpu()  # bicubic non impl. sur MPS
            pred = torch.nn.functional.interpolate(
                pred.unsqueeze(1), size=(side, side),
                mode="bicubic", align_corners=False).squeeze().numpy()
        dnorm = (pred - pred.min()) / (pred.max() - pred.min() + 1e-8)
        cv2.imwrite(str(depth_p), (dnorm * 255).astype(np.uint8))
        r["depth"] = str(depth_p.relative_to(REFS))
        done += 1
        if done % 25 == 0:
            print(f"[depth] {done}/{len(rows)}", flush=True)

    MAN.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    print(f"[depth] ✓ {done} depth maps, manifest mis à jour", flush=True)


if __name__ == "__main__":
    main()
