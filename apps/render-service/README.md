# ArchiClaude render-service (SP2-v2b)

Internal AI rendering engine. Replaces external APIs (Rendair, ReRender) with
a self-hosted SDXL/FLUX + ControlNet pipeline.

## Phases

| Phase | Hardware | Model | Latency / 1024² | Cost |
|---|---|---|---|---|
| **A — dev** | Apple Silicon M3 16 GB (MPS) | SDXL Lightning 4-step | 10-15 s | €0 |
| **B — prod** | NVIDIA RTX 4090 (Runpod cloud) | FLUX.1-dev | 8-15 s | ~$0.35/h |
| **C — owned** | NVIDIA RTX 4090/5090 desktop | FLUX.1-dev + custom LoRA | 5-10 s | one-shot HW |

## Setup (Phase A — M3 dev)

```bash
cd apps/render-service
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# First run downloads ~7 GB of weights (SDXL base + Lightning UNet)
uvicorn src.main:app --host 127.0.0.1 --port 8001 --reload
```

## Day 1 — hello-world test

```bash
curl -X POST http://127.0.0.1:8001/render/test \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "modern French residential building, brick facade, balconies, urban context"}'
# → 10-15 s on M3, returns {render_id, elapsed_s, url}
# Then open the returned url to view the image:
# http://127.0.0.1:8001/static/{render_id}.png
```

## Roadmap

- Day 1 ✓ — render service skeleton + /render/test (text-to-image only)
- Day 2 — BM → depth map + canny edges (Three.js headless)
- Day 3 — ControlNet integration (depth + canny + reference)
- Day 4 — 4 camera angles (rue Est, rue Sud, oiseau, entrée) + caching
- Day 5 — Frontend Photomontages tab UI

## Architecture

```
[backend FastAPI :8000]   [frontend :3010]
        │                        │
        └─ proxy /render/* ──────┴──> [render-service :8001]
                                         ├─ diffusers pipeline
                                         ├─ ControlNet
                                         └─ output PNG → ~/Library/Application Support/ArchiClaude/renders/
```

## Configuration (env vars)

| Var | Default | Notes |
|---|---|---|
| `RENDER_DEVICE` | auto-detect | `mps`, `cuda`, `cpu` |
| `RENDER_MODEL` | `ByteDance/SDXL-Lightning` | swap to `black-forest-labs/FLUX.1-dev` in Phase B |
| `RENDER_BASE_MODEL` | `stabilityai/stable-diffusion-xl-base-1.0` | only used when MODEL is a UNet-only checkpoint |
| `RENDER_STEPS` | `4` | Lightning needs exactly 4 |
| `RENDER_GUIDANCE` | `0` | Lightning is CFG-free (0) |
| `RENDER_OUTPUT_DIR` | `~/Library/Application Support/ArchiClaude/renders` | TCC-free path |
| `RENDER_HOST` / `RENDER_PORT` | `127.0.0.1:8001` | local dev only |
