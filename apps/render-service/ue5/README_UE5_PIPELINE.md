# ArchiClaude → UE5 Pipeline

End-to-end : `BM JSON → scene_mesh → .usda → UE5 → Megascans → Lumen render → PNG`

## Current state (Phase 1 + 2 done, Phase 3 awaits UE5 cloud)

| Component | Status | Location |
|---|---|---|
| **Visual regression tests** | ✅ Done | `tests/test_visual_regression.py` |
| **iter #320 baseline** | ✅ Snapshotted | `refs/baselines/iter-320/` |
| **USD export module** | ✅ Done | `src/scene_to_usd.py` |
| **Auto USD export in Blender pipeline** | ✅ Wired | `src/modal_blender_endpoint.py` main() |
| **UE5 import script** | ✅ Drafted | `ue5/import_scene_to_ue5.py` |
| **RunPod cloud GPU** | ⏳ User setting up | https://runpod.io |
| **UE5 install** | ⏳ Next step | Inside RunPod |
| **First UE5 render** | ⏳ Awaits | After UE5 install |

## Run the pipeline (current Blender path with USD side-export)

Just runs as before — USD export happens automatically post-Blender :

```bash
source apps/render-service/.venv/bin/activate
BLENDER_ITER=321 modal run apps/render-service/src/modal_blender_endpoint.py
# Outputs : /tmp/blender_<preset>_<seed>.png + /tmp/blender_<preset>_<seed>.usda
#           refs/renders/<ts>_iter321_blender_*.png
#           refs/renders/<ts>_iter321_scene_*.usda  ← USD scene, ready for UE5
```

## Regression check

Every FLUX render auto-validates against iter #320 baseline. Manual run :

```bash
python3 apps/render-service/tests/test_visual_regression.py \
    --render-path refs/renders/<latest>.png
```

5 metrics : shadow-free chaussée + trottoir distinct + vegetation present + setback ≥ 5m + building silhouette intact.

## Phase 3 — When RunPod is ready

### 1. Install UE5 on the RunPod pod

Sign in to Epic Games + link GitHub. Then on the pod :
```bash
cd /workspace
git clone --depth=1 -b 5.4 https://github.com/EpicGames/UnrealEngine.git
cd UnrealEngine
./Setup.sh        # downloads ~30GB
./GenerateProjectFiles.sh
make UnrealEditor # ~45 min compile on RTX 4090
```

### 2. Enable required plugins (one-time in Editor)

1. **USD Importer** (Edit → Plugins → search "USD" → enable)
2. **Quixel Bridge** (Edit → Plugins → search "Megascans")
3. **Movie Render Queue** (already in 5.4 default)
4. **Python Editor Script Plugin** (Edit → Plugins → search "Python")

Restart Editor.

### 3. Pre-download Megascans assets (one-time)

The slugs in `import_scene_to_ue5.py` correspond to Quixel Megascans assets — download via Quixel Bridge UI once. Free for UE5 users.

Or use a different approach : download by Bridge "collection" of typical French residential materials.

### 4. Push a USD scene to the pod + render

```bash
# Local : generate scene with USD output
BLENDER_ITER=test modal run apps/render-service/src/modal_blender_endpoint.py
scp refs/renders/<ts>_iter_test_scene_*.usda \
    pod-user@<runpod-ip>:/workspace/scene.usda

# On the pod : run UE5 with our import script
cd /workspace/UnrealEngine/Engine/Binaries/Linux
./UnrealEditor /workspace/ArchiClaudeProject.uproject \
    -ExecutePythonScript=/workspace/repo/apps/render-service/ue5/import_scene_to_ue5.py \
    -ExecuteScript_ResetOnRestart -Unattended -NullRHI=false

# UE5 then writes : /workspace/ue5_render.png
scp pod-user@<runpod-ip>:/workspace/ue5_render.png ./refs/renders/<ts>_ue5.png
```

### 5. Validate UE5 render vs baseline

```bash
python3 apps/render-service/tests/test_visual_regression.py \
    --render-path refs/renders/<ts>_ue5.png
```

## File map

```
apps/render-service/
├── src/
│   ├── scene_to_usd.py           # USDA export from quads_by_material
│   ├── modal_blender_endpoint.py # Blender pipeline + USD side-export
│   ├── modal_flux_endpoint.py    # FLUX pipeline + auto-regression check
│   └── scene_mesh.py             # BM → geometry (renderer-agnostic)
├── tests/
│   └── test_visual_regression.py # 5-metric regression suite
└── ue5/
    ├── README_UE5_PIPELINE.md         # this file
    ├── import_scene_to_ue5.py         # UE5 Python : import USDA + apply
    │                                  # Megascans + Lumen + render (runs INSIDE UE5)
    ├── run_ue5_headless.py            # Cross-platform launcher : starts UE5
    │                                  # headless with our Python script
    ├── run_pipeline_ue5.py            # End-to-end orchestrator :
    │                                  # Blender→USD→UE5→regression→persist
    ├── compare_side_by_side.py        # Side-by-side iter#320 vs new render
    └── run_pipeline.bat               # Windows double-click launcher (MSI)

refs/baselines/iter-320/
├── iter320_reference.png         # Visual baseline for regression tests
├── iter320_reference.meta.json
└── source/                       # Snapshot of pipeline code at iter #320
    ├── modal_blender_endpoint.py
    ├── modal_flux_endpoint.py
    ├── scene_mesh.py
    └── prompt_context/
```

## Quick start (after UE5 is installed)

**One command, complete pipeline :**
```bash
# Mac/Linux
python apps/render-service/ue5/run_pipeline_ue5.py --iter 500

# Windows (MSI)
apps\render-service\ue5\run_pipeline.bat 500
```

What happens :
1. Modal Blender renders scene + exports `.usda` (~30 sec)
2. UE5 headless imports USDA, applies Megascans, Lumen render (~2-5 min)
3. Regression tests vs iter #320 baseline (~5 sec)
4. Persists final PNG + meta.json + side-by-side comparison
5. Refreshes gallery

**Mock mode** (test on Mac before UE5 ready) :
```bash
python apps/render-service/ue5/run_pipeline_ue5.py --iter 500 --mock-ue5
```
Uses Blender PNG as fake UE5 output to validate the orchestrator end-to-end.

## Material name mapping (current → Megascans target)

| Our material | sRGB color (iter #320) | Megascans target asset |
|---|---|---|
| enduit_blanc | (0.92, 0.86, 0.74) | White plaster wall |
| brique_rouge | (0.55, 0.22, 0.12) | Red brick wall |
| pierre_taille | (0.82, 0.74, 0.58) | Limestone wall (cream) |
| zinc_anthracite | (0.16, 0.16, 0.18) | Zinc anthracite panel |
| asphalte | (0.16, 0.16, 0.16) | Asphalt road weathered |
| pavers_concrete | (0.58, 0.58, 0.55) | Concrete floor paving |
| vegetation | (0.28, 0.52, 0.18) | Grass lawn short |
| voisin | (0.50, 0.45, 0.38) | Old plaster wall (worn) |
| terre_neutre | (0.42, 0.40, 0.36) | Soil dry dusty |
| ... | ... | (see MEGASCANS_ASSETS dict in script) |

## Next iteration order (when UE5 is online)

1. **Verify USD import** — first run, just check the building shows up in UE5
2. **Apply 2-3 Megascans manually** — sanity check material mapping
3. **Automate via Python script** — full BM → UE5 → render pipeline
4. **Add Speedtree / Quixel plants** — proper 3D vegetation (jardin trees, ivy, hedges)
5. **Add MetaHuman silhouettes** — 2-3 figures for human scale
6. **Tune Lumen quality settings** — sample count, GI bounces
7. **Movie Render Queue automation** — headless rendering via cmd-line
8. **Cloud render service integration** — modal-like API for triggering renders

## Phase 4+ : iterative quality push

Once UE5 produces a baseline render :
- Tag as `iter-ue5-baseline`
- Add to regression tests
- Push toward references (Image 1 façade jardin, Image 4 plaza, etc.)
- AI polish pass at end (FLUX img2img strength 0.15-0.20) if needed
