"""ArchiClaude render service — FastAPI entrypoint.

Day 1: hello-world endpoint /render/test that generates a SDXL Lightning
image from a text prompt and returns it as PNG. Validates the full stack
(diffusers + MPS + SDXL Lightning) on M3 16 GB.

Run with: uvicorn src.main:app --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

import io
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import CONFIG
from .pipeline import render_text2image
from .depth_map import (
    PRESETS,
    camera_from_preset,
    depth_to_pil,
    render_depth_map,
)
from .controlnet_pipeline import render_with_controlnet
from .sd15_controlnet_pipeline import render_with_sd15_controlnet
from .prompt_templates import build_prompt
from .prompt_context.synthesizer import synthesize_prompt
import httpx
import os

# Phase A (M3 dev) → use SD 1.5 (stable on MPS).
# Phase B (cloud GPU CUDA) → switch via env var to SDXL/FLUX.
RENDER_BACKEND = os.getenv("RENDER_BACKEND", "sd15")  # "sd15" | "sdxl"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("render_service")

app = FastAPI(title="ArchiClaude render service", version="0.1.0")

# Allow the frontend (localhost:3010) and the backend (localhost:8000) to call
# this service. Wide-open in dev — tighten via env var when deploying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3010",
        "http://127.0.0.1:3010",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Liveness probe. Reports the configured device + model — does NOT load weights."""
    return {
        "status": "ok",
        "device": CONFIG.DEVICE,
        "model": CONFIG.MODEL_ID,
        "renders_dir": str(CONFIG.RENDERS_DIR),
    }


class RenderTestRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=500)
    negative_prompt: str | None = None
    seed: int | None = None


class RenderTestResponse(BaseModel):
    render_id: str
    elapsed_s: float
    url: str
    file_path: str


@app.post("/render/test", response_model=RenderTestResponse)
def render_test(req: RenderTestRequest):
    """Day-1 hello-world : generate a PNG from a text prompt.

    Returns metadata + a URL the frontend can fetch to display the image.
    """
    render_id = uuid.uuid4().hex[:12]
    out_path = CONFIG.RENDERS_DIR / f"{render_id}.png"
    t0 = time.time()
    try:
        image = render_text2image(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            seed=req.seed,
        )
    except Exception as e:
        logger.exception("render_text2image failed")
        raise HTTPException(status_code=500, detail=f"render failed: {e!s}") from e
    elapsed = time.time() - t0
    image.save(out_path, format="PNG", optimize=True)
    logger.info("render_id=%s elapsed=%.1fs prompt=%r", render_id, elapsed, req.prompt[:60])
    return RenderTestResponse(
        render_id=render_id,
        elapsed_s=round(elapsed, 2),
        url=f"/static/{render_id}.png",
        file_path=str(out_path),
    )


# Serve generated PNGs directly so the frontend can <img src="..." /> them.
app.mount("/static", StaticFiles(directory=str(CONFIG.RENDERS_DIR)), name="static")


# Convenience: also expose a single render by id (for non-static-mount setups).
@app.get("/render/{render_id}.png")
def get_render(render_id: str):
    path = CONFIG.RENDERS_DIR / f"{render_id}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="render not found")
    return FileResponse(path, media_type="image/png")


# ─── Day 2 — depth map endpoints ─────────────────────────────────────


@app.get("/render/presets")
def list_presets():
    """List the available camera presets (used by frontend to populate the
    Photomontages UI in Day 5)."""
    return {
        "presets": [
            {"name": p.name, "description": p.description, "fov_deg": p.fov_deg}
            for p in PRESETS.values()
        ]
    }


def _fetch_bm(project_id: str) -> dict:
    """Fetch the latest BuildingModel from the backend."""
    url = f"{CONFIG.BACKEND_URL}/api/v1/projects/{project_id}/building_model"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"backend BM fetch failed: {e!s}") from e


def _extract_footprint(bm_payload: dict) -> tuple[list[tuple[float, float]], float]:
    """Extract footprint xy ring + total height from a BM response payload.

    Backend returns {model_json: {envelope: {footprint_geojson: ..., hauteur_totale_m: ...}}}.
    """
    model = bm_payload.get("model_json", bm_payload)
    env = model.get("envelope", {})
    fp = env.get("footprint_geojson", {})
    coords = fp.get("coordinates", [[]])
    if not coords or not coords[0]:
        raise HTTPException(status_code=422, detail="BM has no footprint_geojson")
    ring = [(float(p[0]), float(p[1])) for p in coords[0]]
    h = float(env.get("hauteur_totale_m", 17.0))
    return ring, h


@app.get("/render/depth-map")
def render_depth_map_endpoint(project_id: str, preset: str = "oiseau_iso"):
    """Generate a depth map PNG from the project's BM + a camera preset.

    Day-2 endpoint — validates the depth pipeline before plugging it into
    ControlNet on Day 3.
    """
    bm = _fetch_bm(project_id)
    footprint, height = _extract_footprint(bm)
    cam = camera_from_preset(footprint, height, preset)
    depth = render_depth_map(footprint, height, cam)
    out_path = CONFIG.RENDERS_DIR / f"depth_{project_id[:8]}_{preset}.png"
    depth_to_pil(depth).save(out_path, format="PNG", optimize=True)
    logger.info("depth_map project=%s preset=%s → %s", project_id[:8], preset, out_path.name)
    return FileResponse(out_path, media_type="image/png")


# ─── Day 3 — depth-conditioned photoreal render ──────────────────────


class PerspectiveRequest(BaseModel):
    project_id: str
    preset: str = "ensemble_recule"
    extra_prompt: str | None = None
    seed: int | None = None
    controlnet_strength: float = Field(default=0.8, ge=0.0, le=2.0)
    lora_scale: float | None = Field(default=None, ge=0.0, le=1.5)


class PerspectiveResponse(BaseModel):
    render_id: str
    elapsed_s: float
    url: str
    file_path: str
    prompt_used: str


@app.post("/render/perspective", response_model=PerspectiveResponse)
def render_perspective(req: PerspectiveRequest):
    """Generate a photorealistic perspective from BM + camera preset.

    Pipeline : BM → depth map (numpy) → ControlNet-depth + SDXL Lightning → PNG.
    """
    import time
    import uuid

    bm = _fetch_bm(req.project_id)
    footprint, height = _extract_footprint(bm)
    cam = camera_from_preset(footprint, height, req.preset)
    depth = render_depth_map(footprint, height, cam)
    depth_pil = depth_to_pil(depth)

    # Use the BM-grounded synthesizer instead of the hardcoded STYLE_BASE.
    # This reads the actual project's facade style, roof type, height, etc.
    # so the prompt matches the design data instead of contradicting it.
    prompt, negative = synthesize_prompt(
        bm_payload=bm,
        preset=req.preset,
        extra=req.extra_prompt or "",
        project_id=req.project_id,
    )
    render_id = uuid.uuid4().hex[:12]
    out_path = CONFIG.RENDERS_DIR / f"persp_{req.project_id[:8]}_{req.preset}_{render_id}.png"
    t0 = time.time()
    render_fn = render_with_sd15_controlnet if RENDER_BACKEND == "sd15" else render_with_controlnet
    try:
        kwargs = dict(
            prompt=prompt,
            depth_map=depth_pil,
            negative_prompt=negative,
            seed=req.seed,
            controlnet_conditioning_scale=req.controlnet_strength,
        )
        if req.lora_scale is not None and RENDER_BACKEND == "sd15":
            kwargs["lora_scale"] = req.lora_scale
        image = render_fn(**kwargs)
    except Exception as e:
        logger.exception("perspective render failed (backend=%s)", RENDER_BACKEND)
        raise HTTPException(status_code=500, detail=f"render failed: {e!s}") from e
    elapsed = time.time() - t0
    image.save(out_path, format="PNG", optimize=True)
    logger.info("perspective project=%s preset=%s elapsed=%.1fs → %s", req.project_id[:8], req.preset, elapsed, out_path.name)
    return PerspectiveResponse(
        render_id=render_id,
        elapsed_s=round(elapsed, 2),
        url=f"/static/{out_path.name}",
        file_path=str(out_path),
        prompt_used=prompt,
    )
