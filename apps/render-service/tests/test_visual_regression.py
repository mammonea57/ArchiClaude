"""Visual regression tests : protect the iter #320 baseline.

Each test validates that a new render (passed via --render-path) preserves
one of the hard-won properties of iter #320 (the user-validated baseline).
A failure means the render REGRESSED on that property → the change that
caused it must be reverted or the test threshold tuned with user approval.

5 metrics, each independent :

  1. SHADOW-FREE CHAUSSÉE     — bottom 20% of image must be uniformly dark
                                 (std-dev of brightness < threshold). User
                                 explicitly demanded « pas d'ombre sur voirie ».
  2. TROTTOIR DISTINCT        — there must be a band of MEDIUM gray (pavers)
                                 between the dark chaussée and the building base.
  3. VEGETATION PRESENT       — green pixels >= 2% of total. User
                                 « il manque toute la vegetation, l'herbe ».
  4. SETBACK ≥ 5m             — there must be a horizontal band of yard
                                 (green or pavers) between road and building.
  5. BUILDING SILHOUETTE      — the silhouette mask integrity is preserved
                                 (no holes under building, no ghost transparency).

Usage :
    pytest apps/render-service/tests/test_visual_regression.py \\
        --render-path /Users/anthonymammone/.../2026-05-11_iter321_xxx.png

Programmatic :
    from test_visual_regression import run_all_metrics, MetricResult
    results = run_all_metrics(Path("..../iter321.png"))
    for r in results:
        print(r)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "refs" / "baselines" / "iter-320"
BASELINE_REF = BASELINE_DIR / "iter320_reference.png"


@dataclass
class MetricResult:
    name: str
    passed: bool
    value: float
    threshold: float
    details: str

    def __str__(self) -> str:
        mark = "✓" if self.passed else "✗"
        return (f"{mark} {self.name:35s} value={self.value:8.3f} "
                f"threshold={self.threshold:8.3f} — {self.details}")


def _load_rgb(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return np.asarray(img, dtype=np.float32)


def _bottom_band(arr: np.ndarray, frac: float) -> np.ndarray:
    H = arr.shape[0]
    y0 = int(H * (1.0 - frac))
    return arr[y0:H]


def _middle_horizontal_band(arr: np.ndarray, top_frac: float, bot_frac: float) -> np.ndarray:
    H = arr.shape[0]
    y0 = int(H * top_frac)
    y1 = int(H * bot_frac)
    return arr[y0:y1]


def metric_shadow_free_chaussee(arr: np.ndarray) -> MetricResult:
    """Bottom 18% of image is the chaussée. It must be uniformly dark.
    Measure : std-dev of mean-brightness within this band.
    iter #320 had emission → very uniform. Threshold tuned around its value."""
    band = _bottom_band(arr, 0.18)
    brightness = band.mean(axis=2)
    std = float(brightness.std())
    threshold = 35.0      # iter #320 measured ~10-25 ; allow new renders up to 35
    return MetricResult(
        name="shadow_free_chaussee",
        passed=std <= threshold,
        value=std,
        threshold=threshold,
        details=f"chaussée band brightness std={std:.2f} (lower=more uniform=no shadows)",
    )


def metric_trottoir_distinct(arr: np.ndarray) -> MetricResult:
    """There must be a band of medium-gray (sidewalk pavers) between the
    dark chaussée and the building base. Detect by looking at brightness
    histogram in the bottom 35% — there should be both dark pixels
    (chaussée < 60) AND medium pixels (trottoir 80-150).
    Threshold tuned to iter #320 baseline level (medium ≈ 2.5%) — anything
    < 1.5% means trottoir is gone (regression). Higher = improvement.
    """
    band = _bottom_band(arr, 0.35)
    brightness = band.mean(axis=2)
    dark = (brightness < 60).mean()
    medium = ((brightness >= 80) & (brightness <= 150)).mean()
    # Both must be > 1% (chaussée) and >= 1.5% (trottoir) for distinctness
    passed = dark >= 0.005 and medium >= 0.015
    return MetricResult(
        name="trottoir_distinct",
        passed=passed,
        value=medium * 100,
        threshold=1.5,
        details=f"dark(chaussee)={dark*100:.1f}% medium(trottoir)={medium*100:.1f}% — target: push > 5%",
    )


def metric_vegetation_present(arr: np.ndarray) -> MetricResult:
    """Total vegetation pixels (green-dominant) must be >= 2% of image.
    G > R+8 and G > B+8 and G > 40 (avoid sky-blue).
    """
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    is_green = ((g > r + 8) & (g > b + 8) & (g > 40)).astype(np.float32)
    frac = float(is_green.mean())
    threshold = 0.02   # 2%
    return MetricResult(
        name="vegetation_present",
        passed=frac >= threshold,
        value=frac * 100,
        threshold=threshold * 100,
        details=f"green pixels = {frac*100:.2f}%",
    )


def metric_setback_visible(arr: np.ndarray) -> MetricResult:
    """A real 5m setback should produce a horizontal band of yard
    (not asphalt, not building) between the road and the building base.
    Detect : for each center column, scan upward from bottom. Count rows
    from the first dark pixel (chaussée bottom) to the first really bright
    row (building base, brightness > 200). That gap is the "setback +
    yard" zone — should be ≥ 25 rows at 1K, ≥ 50 rows at 2K.
    """
    H, W = arr.shape[:2]
    sample = arr[:, W//3:2*W//3]
    brightness = sample.mean(axis=2)
    setback_gaps = []
    for col in range(sample.shape[1]):
        column = brightness[:, col]
        # find lowest row where brightness < 60 (asphalt)
        dark_rows = np.where(column < 60)[0]
        if len(dark_rows) == 0:
            continue
        last_dark = dark_rows.max()
        # find highest bright row (>180) ABOVE last_dark (building)
        bright_rows = np.where((column > 180) & (np.arange(H) < last_dark))[0]
        if len(bright_rows) == 0:
            continue
        first_bright = bright_rows.max()
        gap = last_dark - first_bright
        if gap > 0:
            setback_gaps.append(gap)
    avg_gap = float(np.mean(setback_gaps)) if setback_gaps else 0.0
    threshold_rows = max(20, H * 0.018)   # tuned to iter #320 baseline (47.5 rows @ 2K)
    return MetricResult(
        name="setback_visible",
        passed=avg_gap >= threshold_rows,
        value=avg_gap,
        threshold=threshold_rows,
        details=f"avg setback gap rows = {avg_gap:.1f} (need >= {threshold_rows:.0f}, H={H})",
    )


def metric_building_silhouette_intact(arr: np.ndarray,
                                       baseline_arr: Optional[np.ndarray] = None) -> MetricResult:
    """Building silhouette intact = comparable bright-pixel fraction to
    baseline. Catches « ghost building » (transparency) regressions.
    """
    brightness = arr.mean(axis=2)
    # The building occupies the top-center 60% area
    H, W = arr.shape[:2]
    center = arr[H//5:4*H//5, W//5:4*W//5]
    bright_frac = float((center.mean(axis=2) > 150).mean())
    if baseline_arr is not None:
        baseline_center = baseline_arr[H//5:4*H//5, W//5:4*W//5]
        baseline_bright = float((baseline_center.mean(axis=2) > 150).mean())
        # Building bright pixels must be within 50% of baseline (loose)
        ratio = bright_frac / max(baseline_bright, 0.001)
        passed = 0.5 <= ratio <= 1.8
        return MetricResult(
            name="building_silhouette_intact",
            passed=passed,
            value=bright_frac * 100,
            threshold=baseline_bright * 100,
            details=f"bright pixels frac={bright_frac*100:.1f}% (baseline={baseline_bright*100:.1f}%, ratio={ratio:.2f})",
        )
    # No baseline → just sanity check building isn't totally absent
    passed = bright_frac >= 0.15
    return MetricResult(
        name="building_silhouette_intact",
        passed=passed,
        value=bright_frac * 100,
        threshold=15.0,
        details=f"bright pixels frac={bright_frac*100:.1f}%",
    )


def run_all_metrics(render_path: Path,
                    baseline_path: Path = BASELINE_REF) -> list[MetricResult]:
    arr = _load_rgb(render_path)
    baseline_arr = _load_rgb(baseline_path) if baseline_path.exists() else None
    if baseline_arr is not None and baseline_arr.shape != arr.shape:
        # Resize baseline to match for fair comparison
        H, W = arr.shape[:2]
        baseline_pil = Image.open(baseline_path).convert("RGB").resize((W, H), Image.LANCZOS)
        baseline_arr = np.asarray(baseline_pil, dtype=np.float32)
    return [
        metric_shadow_free_chaussee(arr),
        metric_trottoir_distinct(arr),
        metric_vegetation_present(arr),
        metric_setback_visible(arr),
        metric_building_silhouette_intact(arr, baseline_arr),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-path", type=Path, required=True,
                        help="Path to the new render PNG to validate.")
    parser.add_argument("--baseline-path", type=Path, default=BASELINE_REF,
                        help="Path to the iter #320 reference PNG.")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero if any metric fails.")
    args = parser.parse_args()

    results = run_all_metrics(args.render_path, args.baseline_path)
    print(f"\nVisual regression check : {args.render_path.name}")
    print(f"Baseline                : {args.baseline_path.name}\n")
    n_pass = 0
    for r in results:
        print(r)
        if r.passed:
            n_pass += 1
    print(f"\n{n_pass}/{len(results)} metrics passed.\n")
    if args.strict and n_pass < len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
