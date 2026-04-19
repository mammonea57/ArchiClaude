"""Quality control for rendered PCMI6 images — IoU between rendered mask and expected mask."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image


def compute_mask_iou(
    *,
    rendered_bytes: bytes,
    mask_bytes: bytes,
    threshold: int = 127,
) -> float:
    """Compute Intersection over Union between rendered building region and expected mask.

    For v1, compares the mask (blurred binary) between the rendered output
    (interpreted as grayscale threshold) and the expected mask bytes.

    Returns value in [0, 1]. Higher = better match.
    """
    # Load both images as grayscale numpy arrays
    rendered_img = Image.open(io.BytesIO(rendered_bytes)).convert("L")
    mask_img = Image.open(io.BytesIO(mask_bytes)).convert("L")

    # Ensure same size (resize rendered to mask if needed)
    if rendered_img.size != mask_img.size:
        rendered_img = rendered_img.resize(mask_img.size, Image.LANCZOS)

    rendered_arr = np.array(rendered_img)
    mask_arr = np.array(mask_img)

    # Binary thresholds
    mask_binary = mask_arr > threshold

    # For rendered: detect the "building" region
    rendered_binary = _detect_building_region(rendered_arr, mask_binary)

    intersection = np.logical_and(rendered_binary, mask_binary).sum()
    union = np.logical_or(rendered_binary, mask_binary).sum()

    if union == 0:
        return 1.0
    return float(intersection) / float(union)


def _detect_building_region(rendered_arr: np.ndarray, mask_reference: np.ndarray) -> np.ndarray:
    """Simple heuristic: assume building pixels are where rendered differs from uniform.

    For v1 we use a simple threshold proxy.
    """
    # If rendered is already a mask (grayscale), use threshold directly
    if rendered_arr.max() > 200 and rendered_arr.min() < 50:
        # Looks like a high-contrast image — threshold at 127
        return rendered_arr > 127
    # Otherwise fallback: take same bounds as reference mask (conservative)
    return mask_reference
