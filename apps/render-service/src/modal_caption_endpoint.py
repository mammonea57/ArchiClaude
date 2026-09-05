"""Modal GPU endpoint — BLIP-2 + CLIP-Interrogator hybrid captioning.

Replaces the painfully slow CPU loop (6+ min/image) with an A10G GPU run
(~1-2 s/image, total ~5-8 min for 220 images, cost ~$0.30).

Pipeline:
1. Mount `archfr-lora-images` Modal Volume (contains manual_refs/*.jpg)
2. Load BLIP-2 OPT-2.7b + open_clip ViT-B-32 (both fp16 on GPU)
3. For each image without a .txt sidecar:
   - BLIP-2 generates description
   - CLIP picks top-K archviz tags from our curated dictionary
   - Combined caption written as .txt next to the image
4. User downloads .txt back via `modal volume get`

Usage from Mac :
    cd apps/render-service
    .venv/bin/modal volume put archfr-lora-images \\
        /Users/anthonymammone/Desktop/ArchiClaude/refs/style_dataset/manual_refs \\
        /manual_refs
    .venv/bin/modal run src/modal_caption_endpoint.py
    .venv/bin/modal volume get archfr-lora-images /manual_refs ./refs/style_dataset/
"""
from __future__ import annotations

import io
from pathlib import Path

import modal

app = modal.App("archfr-caption-blip2")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch==2.5.1",                  # bump for transformers compat
        "torchvision==0.20.1",
        "transformers==4.46.3",
        "tokenizers>=0.20.3",            # latest tokenizer JSON format
        "accelerate==1.1.1",
        "Pillow>=10",
        "open-clip-torch==2.30.0",
        "safetensors>=0.4.5",
    )
)

# Volumes
images_volume = modal.Volume.from_name("archfr-lora-images", create_if_missing=True)
hf_cache = modal.Volume.from_name("archfr-hf-cache", create_if_missing=True)


# ---- Curated CLIP-Interrogator tag dictionary (mirrors auto_caption_hybrid.py) ----
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


@app.cls(
    image=image,
    gpu="A10G",                      # 24GB VRAM, $1.10/h — plenty for BLIP-2 OPT-2.7b fp16
    timeout=1800,                    # 30 min hard cap
    scaledown_window=120,
    volumes={
        "/images": images_volume,
        "/root/.cache/huggingface": hf_cache,
    },
)
class CaptionPipeline:
    @modal.enter()
    def load(self):
        import torch
        from transformers import Blip2Processor, Blip2ForConditionalGeneration
        import open_clip

        self.device = "cuda"
        self.dtype = torch.float16

        print("[load] BLIP-2 OPT-2.7b fp16 → GPU")
        self.blip_processor = Blip2Processor.from_pretrained(
            "Salesforce/blip2-opt-2.7b"
        )
        self.blip_model = Blip2ForConditionalGeneration.from_pretrained(
            "Salesforce/blip2-opt-2.7b", torch_dtype=self.dtype,
        ).to(self.device).eval()

        print("[load] open_clip ViT-B-32 laion2b → GPU")
        self.clip_model, _, self.clip_preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k", device=self.device,
        )
        self.clip_tokenizer = open_clip.get_tokenizer("ViT-B-32")
        self.clip_model = self.clip_model.to(self.dtype).eval()

        # Pre-compute tag text features
        self.tag_features = {}
        with torch.no_grad():
            for group, tags in TAGS_BY_GROUP.items():
                tok = self.clip_tokenizer(tags).to(self.device)
                feats = self.clip_model.encode_text(tok)
                feats = feats / feats.norm(dim=-1, keepdim=True)
                self.tag_features[group] = (tags, feats)
        print(f"[load] tags ready: {sum(len(v[0]) for v in self.tag_features.values())} tags")

    @modal.method()
    def caption_one(self, image_bytes: bytes, prompt_prefix: str = "a photo of") -> str:
        """Caption a single image. Useful for ad-hoc calls."""
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return self._caption_pil(img, prompt_prefix)

    @modal.method()
    def caption_volume(
        self,
        manual_refs_subdir: str = "manual_refs",
        overwrite: bool = False,
        top_k_per_group: int = 2,
        log_every: int = 5,
    ) -> dict:
        """Caption every .jpg in /images/<manual_refs_subdir> that lacks a .txt sidecar.

        Returns a dict {n_processed, n_skipped, n_failed, elapsed_s}.
        """
        import time
        from PIL import Image as PILImage
        root = Path("/images") / manual_refs_subdir
        if not root.is_dir():
            return {"error": f"directory not found: {root}"}

        images = sorted(root.glob("*.jpg"))
        to_do = []
        for img in images:
            txt = img.with_suffix(".txt")
            if overwrite or not txt.is_file() or txt.stat().st_size <= 20:
                to_do.append(img)
                continue
            # Detect HTML-laden captions (Pinterest RSS leftovers) and re-caption
            head = txt.read_text(encoding="utf-8", errors="ignore")[:200].lower()
            if "&lt;" in head or "<a href" in head or "&quot;" in head or "<img" in head:
                to_do.append(img)
                continue

        print(f"[caption_volume] {len(images)} jpgs total, {len(to_do)} need captioning")
        if not to_do:
            return {"n_processed": 0, "n_skipped": len(images), "n_failed": 0, "elapsed_s": 0}

        t0 = time.time()
        n_done = 0
        n_failed = 0
        for img_path in to_do:
            try:
                pil = PILImage.open(img_path).convert("RGB")
                caption = self._caption_pil(pil, "a photo of", top_k_per_group)
                img_path.with_suffix(".txt").write_text(caption, encoding="utf-8")
                n_done += 1
                if n_done % log_every == 0:
                    dt = time.time() - t0
                    rate = dt / n_done
                    eta = (len(to_do) - n_done) * rate
                    print(f"  {n_done}/{len(to_do)} done, {rate:.2f}s/img, ETA {eta:.0f}s — last: {caption[:100]}")
            except Exception as e:
                print(f"  fail {img_path.name}: {e}")
                n_failed += 1

        # Commit the volume so caller can fetch .txt back
        images_volume.commit()
        return {
            "n_processed": n_done,
            "n_skipped": len(images) - len(to_do),
            "n_failed": n_failed,
            "elapsed_s": round(time.time() - t0, 1),
        }

    # ---- internal helpers -------------------------------------------------
    def _caption_pil(self, pil_img, prompt_prefix: str = "a photo of",
                     top_k_per_group: int = 2) -> str:
        import torch

        # BLIP-2 description
        inputs = self.blip_processor(
            images=pil_img, text=prompt_prefix, return_tensors="pt"
        ).to(self.device, self.dtype if hasattr(self, "dtype") else None)
        # Use fp16 on input ids only doesn't work — patch:
        inputs = {k: (v.to(self.dtype) if v.dtype.is_floating_point else v)
                  for k, v in inputs.items()}
        with torch.no_grad():
            out = self.blip_model.generate(
                **inputs, max_new_tokens=40, num_beams=3, do_sample=False,
            )
        description = self.blip_processor.batch_decode(out, skip_special_tokens=True)[0].strip()
        for stub in ("a photo of", "a photograph of"):
            if description.lower().startswith(stub):
                description = description[len(stub):].strip()
        if not description:
            description = "an architectural exterior view of a building"

        # CLIP tag matching
        with torch.no_grad():
            clip_img = self.clip_preprocess(pil_img).unsqueeze(0).to(self.device, self.dtype)
            img_feat = self.clip_model.encode_image(clip_img)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)

        tags_picked = []
        for group, (tag_list, feats) in self.tag_features.items():
            with torch.no_grad():
                sims = (img_feat @ feats.T).squeeze(0)
            k = top_k_per_group if group in ("materials", "context") else 1
            top_idx = sims.topk(min(k, len(tag_list))).indices.tolist()
            tags_picked.extend(tag_list[i] for i in top_idx)

        return description.rstrip(".") + ", " + ", ".join(tags_picked)


@app.local_entrypoint()
def main(
    subdir: str = "manual_refs",
    overwrite: bool = False,
):
    pipeline = CaptionPipeline()
    result = pipeline.caption_volume.remote(
        manual_refs_subdir=subdir, overwrite=overwrite,
    )
    print("\n=== Result ===")
    print(result)
