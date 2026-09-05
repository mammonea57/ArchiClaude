"""Art Director Agent — VLM critic + N-seed batch + CLIP auto-select.

Closes the « designer's eye » gap identified in the 2026-06-03 ArchiBrain
lesson « Plateau qualité — 7 leviers qu'on rate » (lever #7).

Two complementary uses :

1. **CLIP auto-select** : given N candidate renders + a moodboard of K refs,
   compute the cosine similarity of each render to the average ref embedding
   and pick the top-3. Cheap quantitative gate. Lever #1 in the lesson.

2. **VLM critique** : given a render + the prompt that was used, ask
   Claude Vision to produce 5 actionable critiques (composition, lighting,
   story, weak zones, materials). Output is JSON the next iter can act on.
   Lever #7 in the lesson.

Both helpers run locally (no Modal). VLM uses `claude-opus-4-7` via
the anthropic SDK ; CLIP scoring uses open_clip via CPU (slow ~3s/img,
acceptable for N=20 batches).

Usage :

    from src.art_director import (
        ArtDirector,
        select_top_k,
        critique_render,
    )

    # CLIP auto-select
    top3 = select_top_k(
        candidates=[Path(...), ...],
        moodboard_dir=Path("refs/moodboards/brick_tier/"),
        k=3,
    )

    # VLM critique
    critique = critique_render(
        render_path=Path(...),
        prompt="...",
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
    )
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image


# ─── CLIP scoring ─────────────────────────────────────────────────────────


_CLIP_CACHE: dict[str, object] = {}


def _load_clip(model_name: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k"):
    """Lazy-load open_clip model + preprocess. CPU-only.

    open_clip ViT-B/32 laion2b is the standard archviz aesthetic gate
    (decent style sensitivity, fast on CPU).
    """
    if "model" in _CLIP_CACHE:
        return _CLIP_CACHE["model"], _CLIP_CACHE["preprocess"], _CLIP_CACHE["tokenizer"]
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained, device="cpu",
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer(model_name)
    _CLIP_CACHE["model"] = model
    _CLIP_CACHE["preprocess"] = preprocess
    _CLIP_CACHE["tokenizer"] = tokenizer
    return model, preprocess, tokenizer


def _image_embedding(path: Path):
    """Return a normalised CLIP image embedding (torch.Tensor (D,))."""
    import torch
    model, preprocess, _ = _load_clip()
    img = Image.open(path).convert("RGB")
    with torch.no_grad():
        x = preprocess(img).unsqueeze(0)
        emb = model.encode_image(x).squeeze(0)
        emb = emb / emb.norm()
    return emb


def select_top_k(candidates: list[Path], moodboard_dir: Path, k: int = 3,
                 verbose: bool = True) -> list[tuple[Path, float]]:
    """Rank `candidates` by cosine similarity to the average moodboard
    embedding. Returns top-k with their scores.

    moodboard_dir : a folder of K reference images that defines the
    target aesthetic (Brick Visual, MIR, Forbes Massie style refs).
    """
    import torch
    refs = sorted(p for p in moodboard_dir.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    if not refs:
        raise FileNotFoundError(f"no images in moodboard {moodboard_dir}")
    ref_embs = torch.stack([_image_embedding(p) for p in refs])
    ref_avg = ref_embs.mean(dim=0)
    ref_avg = ref_avg / ref_avg.norm()

    scored: list[tuple[Path, float]] = []
    for cand in candidates:
        emb = _image_embedding(cand)
        score = float(torch.dot(emb, ref_avg).item())
        scored.append((cand, score))
        if verbose:
            print(f"  CLIP={score:+.4f}  {cand.name}")
    scored.sort(key=lambda r: r[1], reverse=True)
    return scored[:k]


# ─── VLM critique (Claude Vision) ─────────────────────────────────────────


CRITIC_SYSTEM = """You are an Art Director for architectural visualization.
You review a rendered image and produce 5 SHORT actionable critiques.
Each critique targets one of : composition, lighting, story, weak-zone,
materials. Be specific, terse, and pragmatic. Each critique = ONE line.
Output ONLY a JSON array of 5 objects, no prose.

Format :
[
  {"axis": "composition", "issue": "...", "fix": "..."},
  {"axis": "lighting",    "issue": "...", "fix": "..."},
  ...
]
"""


def _b64_image(path: Path) -> tuple[str, str]:
    """Read an image and return (base64_data, media_type)."""
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    ext = path.suffix.lower()
    mt = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    return data, mt


def critique_render(render_path: Path, prompt: str,
                    anthropic_api_key: Optional[str] = None,
                    model: str = "claude-opus-4-7") -> list[dict]:
    """Ask Claude Vision for 5 actionable critiques on a render.

    Returns a list of {axis, issue, fix} dicts (5 items).
    """
    from anthropic import Anthropic
    api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env var or anthropic_api_key arg required")
    client = Anthropic(api_key=api_key)
    data, mt = _b64_image(render_path)
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        system=CRITIC_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": mt, "data": data,
                    }},
                    {"type": "text", "text":
                     f"Prompt used to generate this render :\n{prompt}\n\n"
                     "Give 5 actionable critiques."},
                ],
            },
        ],
    )
    text = msg.content[0].text.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"VLM output not valid JSON :\n{text}") from e


# ─── End-to-end Art Director loop ─────────────────────────────────────────


@dataclass
class ArtDirector:
    """One-shot Art Director : rank candidates by CLIP + critique top-1.

    Use this after a multi-seed batch (e.g. N=20 seeds rendered with
    `modal_controlnet_endpoint::sweep_cli`) to pick the best image and
    get 5 critiques that can feed the next iter's prompt boost.
    """
    moodboard_dir: Path
    candidates: list[Path] = field(default_factory=list)
    k_top: int = 3
    anthropic_api_key: Optional[str] = None

    def run(self, prompt: str) -> dict:
        if not self.candidates:
            raise ValueError("no candidates provided")
        ranked = select_top_k(self.candidates, self.moodboard_dir, k=self.k_top, verbose=True)
        best_path, best_score = ranked[0]
        crit = critique_render(best_path, prompt, anthropic_api_key=self.anthropic_api_key)
        return {
            "ranked": [{"path": str(p), "score": s} for p, s in ranked],
            "best": str(best_path),
            "best_score": best_score,
            "critiques": crit,
        }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("candidates_dir", type=Path,
                    help="Directory containing the N candidate PNGs (rglob).")
    ap.add_argument("--moodboard", type=Path, required=True,
                    help="Directory of reference images defining the target style.")
    ap.add_argument("--prompt", type=str, default="archviz brick brochure",
                    help="Prompt used to generate the candidates (for the VLM critique).")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("/tmp/art_director.json"))
    args = ap.parse_args()

    candidates = sorted(p for p in args.candidates_dir.rglob("*.png"))
    if not candidates:
        raise SystemExit(f"no PNG in {args.candidates_dir}")
    print(f"ArtDirector : {len(candidates)} candidates vs moodboard {args.moodboard}")
    director = ArtDirector(moodboard_dir=args.moodboard, candidates=candidates, k_top=args.k)
    result = director.run(args.prompt)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n→ Best : {result['best']}  (CLIP={result['best_score']:+.4f})")
    print("→ Critiques :")
    for c in result["critiques"]:
        print(f"  · [{c['axis']}] {c['issue']}  →  {c['fix']}")
    print(f"\n✓ saved {args.out}")
