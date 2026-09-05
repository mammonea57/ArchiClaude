#!/usr/bin/env bash
# Multi-view ControlNet Tile pass on N Cycles renders of the same building.
# Each input → ControlNet Tile cn=0.4 + SAME prompt + SAME LoRA + SAME seed.
# Goal : visually validate that material/lighting coherence holds across angles.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="${OUT_DIR:-../../refs/renders/multiview_cn04}"
LORA="${LORA:-archfr_brick_v2/epoch_1}"
SEED="${SEED:-42}"
CN_SCALE="${CN_SCALE:-0.4}"
GUIDANCE="${GUIDANCE:-7.5}"
PROMPT_DEFAULT='a photorealistic 3D archviz render of a modern apartment building with red brick facade, balconies with green plants, golden hour lighting, contemporary residential architecture, eye-level street view, with people walking, dramatic warm sky, brochure quality'
PROMPT="${PROMPT:-$PROMPT_DEFAULT}"

# Inputs : list of cycles renders (one per preset/view)
# Pass via $@ ; defaults to last 4 distinct seed11 renders in refs/renders.
if [ "$#" -eq 0 ]; then
  mapfile -t INPUTS < <(ls -t ../../refs/renders/2026-06-05_*_blender_*_seed11.png 2>/dev/null | head -4)
else
  INPUTS=("$@")
fi

if [ "${#INPUTS[@]}" -eq 0 ]; then
  echo "[multiview] no inputs found — pass paths as args or render seed11 angles first" >&2
  exit 2
fi

echo "[multiview] ${#INPUTS[@]} inputs → ControlNet Tile cn=$CN_SCALE seed=$SEED"
for f in "${INPUTS[@]}"; do echo "  - $f"; done

for f in "${INPUTS[@]}"; do
  echo "→ ControlNet pass : $(basename "$f")"
  .venv/bin/modal run src/modal_controlnet_endpoint.py::sweep_cli \
    --input-path "$f" \
    --controlnet-type tile \
    --cn-scales "$CN_SCALE" \
    --guidance-scale "$GUIDANCE" \
    --lora-name "$LORA" \
    --seed "$SEED" \
    --out-dir "$OUT_DIR" \
    --prompt "$PROMPT"
done

echo "[multiview] DONE — outputs in $OUT_DIR"
ls -la "$OUT_DIR" 2>/dev/null || true
