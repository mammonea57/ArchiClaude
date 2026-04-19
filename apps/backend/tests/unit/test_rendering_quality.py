import io

import numpy as np
from PIL import Image

from core.rendering.quality_check import compute_mask_iou


def _make_png_from_array(arr: np.ndarray) -> bytes:
    """Convert numpy array to PNG bytes."""
    if arr.dtype != np.uint8:
        arr = (arr * 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_iou_perfect_match():
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:80, 20:80] = 255
    mask_bytes = _make_png_from_array(mask)
    rendered = _make_png_from_array(mask)
    iou = compute_mask_iou(rendered_bytes=rendered, mask_bytes=mask_bytes)
    assert iou > 0.95


def test_iou_no_overlap():
    mask1 = np.zeros((100, 100), dtype=np.uint8)
    mask1[0:30, 0:30] = 255
    mask2 = np.zeros((100, 100), dtype=np.uint8)
    mask2[60:90, 60:90] = 255
    iou = compute_mask_iou(
        rendered_bytes=_make_png_from_array(mask2),
        mask_bytes=_make_png_from_array(mask1),
    )
    assert iou < 0.1


def test_iou_partial_overlap():
    mask1 = np.zeros((100, 100), dtype=np.uint8)
    mask1[20:80, 20:80] = 255  # area 3600
    mask2 = np.zeros((100, 100), dtype=np.uint8)
    mask2[20:80, 40:100] = 255  # area 3600, overlap with mask1 = 2400
    iou = compute_mask_iou(
        rendered_bytes=_make_png_from_array(mask2),
        mask_bytes=_make_png_from_array(mask1),
    )
    # intersection 40*60=2400, union=3600+3600-2400=4800, iou=0.5
    assert 0.4 < iou < 0.6
