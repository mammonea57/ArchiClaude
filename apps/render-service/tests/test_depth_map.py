"""Day-2 standalone test : generate a depth map from the Nogent UA1 project BM
without spinning up the full FastAPI service. Run with :

    cd apps/render-service && .venv/bin/python tests/test_depth_map.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `import src.…` when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from src.config import CONFIG
from src.depth_map import PRESETS, camera_from_preset, depth_to_pil, render_depth_map


PROJECT_ID = "e9a960c8-081f-4c42-a65b-619610a61134"


def fetch_bm(project_id: str) -> dict:
    url = f"{CONFIG.BACKEND_URL}/api/v1/projects/{project_id}/building_model"
    with httpx.Client(timeout=10.0) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def main() -> None:
    bm = fetch_bm(PROJECT_ID)
    model = bm["model_json"]
    env = model["envelope"]
    coords = env["footprint_geojson"]["coordinates"][0]
    footprint = [(float(p[0]), float(p[1])) for p in coords]
    height = float(env["hauteur_totale_m"])
    print(f"footprint : {len(footprint)} pts · height : {height} m")

    out_dir = CONFIG.RENDERS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    for preset_name in PRESETS:
        cam = camera_from_preset(footprint, height, preset_name)
        depth = render_depth_map(footprint, height, cam)
        out = out_dir / f"depth_{PROJECT_ID[:8]}_{preset_name}.png"
        depth_to_pil(depth).save(out, format="PNG", optimize=True)
        print(f"  ✓ {preset_name:20s} → {out.name} ({depth.min():.3f}…{depth.max():.3f})")
    print(f"\noutputs in : {out_dir}")


if __name__ == "__main__":
    main()
