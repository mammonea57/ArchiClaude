"""Render service configuration — env-driven, sane defaults for M3 dev."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal


# Detect the best available compute device on this machine.
# On Apple Silicon → MPS (Metal Performance Shaders, ~6x faster than CPU).
# On NVIDIA → CUDA (production target, ~30x faster than M3).
def detect_device() -> Literal["cuda", "mps", "cpu"]:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


class Config:
    """Singleton-style config block — read once at startup."""

    DEVICE: Literal["cuda", "mps", "cpu"] = os.getenv("RENDER_DEVICE", detect_device())  # type: ignore[assignment]
    # Phase A: SDXL Lightning 4-step (Apple-Silicon friendly, ~7 GB weights, 10-15s/render on M3).
    # Phase B (CB available): FLUX.1-dev (~24 GB, requires RTX 4090).
    MODEL_ID: str = os.getenv("RENDER_MODEL", "ByteDance/SDXL-Lightning")
    BASE_MODEL_ID: str = os.getenv("RENDER_BASE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
    # Inference defaults
    NUM_INFERENCE_STEPS: int = int(os.getenv("RENDER_STEPS", "4"))   # 4 for Lightning
    GUIDANCE_SCALE: float = float(os.getenv("RENDER_GUIDANCE", "0"))  # 0 for Lightning
    WIDTH: int = int(os.getenv("RENDER_WIDTH", "1024"))
    HEIGHT: int = int(os.getenv("RENDER_HEIGHT", "1024"))
    # Storage
    RENDERS_DIR: Path = Path(
        os.getenv("RENDER_OUTPUT_DIR", str(Path.home() / "Library/Application Support/ArchiClaude/renders"))
    )
    # Backend communication
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    # Service
    HOST: str = os.getenv("RENDER_HOST", "127.0.0.1")
    PORT: int = int(os.getenv("RENDER_PORT", "8001"))


CONFIG = Config()

# Ensure renders directory exists.
CONFIG.RENDERS_DIR.mkdir(parents=True, exist_ok=True)
