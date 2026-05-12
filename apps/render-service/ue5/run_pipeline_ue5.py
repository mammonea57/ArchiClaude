"""End-to-end ArchiClaude UE5 pipeline orchestrator.

One command from project ID to a validated photoreal UE5 PNG :

    python run_pipeline_ue5.py \\
        --project-id e9a960c8-081f-4c42-a65b-619610a61134 \\
        --preset rue_se_eloignee \\
        --seed 11 \\
        --iter 401

Steps :
  1. Run modal Blender endpoint → produces .usda + Blender PNG
  2. Run UE5 headless (run_ue5_headless.py) → produces UE5 PNG
  3. Run visual regression tests on UE5 PNG → validate vs iter #320 baseline
  4. Save UE5 PNG to refs/renders/ with iter tag + meta.json
  5. Refresh gallery

Supports --mock-ue5 for testing the orchestrator on Mac before UE5 ready :
in mock mode, the UE5 step is skipped and the Blender PNG is used as the
"UE5 output" so the rest of the pipeline can be tested end-to-end.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RENDER_SERVICE_ROOT = REPO_ROOT / "apps" / "render-service"
RENDERS_DIR = REPO_ROOT / "refs" / "renders"
BASELINE_PNG = REPO_ROOT / "refs" / "baselines" / "iter-320" / "iter320_reference.png"
TEST_SUITE = RENDER_SERVICE_ROOT / "tests" / "test_visual_regression.py"
UE5_LAUNCHER = RENDER_SERVICE_ROOT / "ue5" / "run_ue5_headless.py"
BLENDER_ENDPOINT = RENDER_SERVICE_ROOT / "src" / "modal_blender_endpoint.py"


def log(msg: str) -> None:
    print(f"[pipeline] {msg}", flush=True)


def run_blender_step(iter_tag: int) -> tuple[Path, Path]:
    """Trigger modal blender endpoint. Returns (blender_png_path, usda_path)."""
    log(f"Step 1/4 : Blender + USD export (iter #{iter_tag}) …")
    env = os.environ.copy()
    env["BLENDER_ITER"] = str(iter_tag)
    venv_python = RENDER_SERVICE_ROOT / ".venv" / "bin" / "python3"
    if not venv_python.exists():
        venv_python = Path(sys.executable)
    cmd = [
        str(venv_python.parent / "modal"),
        "run",
        str(BLENDER_ENDPOINT),
    ]
    log(f"  command : {' '.join(cmd)}")
    proc = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"Blender step failed (exit {proc.returncode})")
    # Find the latest persisted Blender PNG + USDA
    blender_png = next(iter(sorted(
        RENDERS_DIR.glob(f"*iter{iter_tag}_blender_*.png"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )), None)
    usda = next(iter(sorted(
        RENDERS_DIR.glob(f"*iter{iter_tag}_scene_*.usda"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )), None)
    if blender_png is None or usda is None:
        raise RuntimeError(
            f"Blender step ran but expected outputs not found.\n"
            f"  Looking for *iter{iter_tag}_blender_*.png and *iter{iter_tag}_scene_*.usda"
        )
    log(f"  ✓ Blender PNG : {blender_png.name}")
    log(f"  ✓ USDA scene  : {usda.name}")
    return blender_png, usda


def run_ue5_step(usda: Path, output_png: Path, mock: bool, fallback_png: Path) -> Path:
    """Run UE5 headless. In mock mode, copy fallback_png as ue5 output for testing."""
    log(f"Step 2/4 : UE5 render →  {output_png.name}")
    if mock:
        log("  MOCK MODE — copying Blender PNG as UE5 output (no real UE5)")
        shutil.copy(fallback_png, output_png)
        return output_png
    cmd = [
        sys.executable,
        str(UE5_LAUNCHER),
        "--usda", str(usda),
        "--output", str(output_png),
    ]
    log(f"  command : {' '.join(cmd)}")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"UE5 step failed (exit {proc.returncode})")
    if not output_png.exists():
        raise RuntimeError(f"UE5 step completed but no output : {output_png}")
    return output_png


def run_regression_step(render_png: Path) -> dict:
    """Run the visual regression suite. Returns the summary dict."""
    log(f"Step 3/4 : Visual regression check vs iter #320 baseline …")
    cmd = [
        sys.executable, str(TEST_SUITE),
        "--render-path", str(render_png),
        "--baseline-path", str(BASELINE_PNG),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    # Parse "X/Y metrics passed" from output
    summary = {"raw_output": proc.stdout, "passed": False}
    for line in proc.stdout.splitlines():
        if "metrics passed" in line:
            try:
                fraction = line.strip().split(" metrics")[0]
                p, t = fraction.split("/")
                summary["n_pass"] = int(p)
                summary["n_total"] = int(t)
                summary["passed"] = int(p) == int(t)
            except Exception:
                pass
    return summary


def persist_and_meta(render_png: Path, iter_tag: int, regression: dict,
                     blender_png: Path, usda: Path, mock: bool) -> Path:
    """Copy the final render to refs/renders/ with a date-tagged name and
    write a meta.json that records the regression results."""
    log("Step 4/4 : Persist + meta.json + regen gallery …")
    ts = datetime.datetime.now().strftime("%Y-%m-%d")
    suffix = "_mockUE5" if mock else "_ue5"
    persisted = RENDERS_DIR / f"{ts}_iter{iter_tag}{suffix}.png"
    shutil.copy(render_png, persisted)
    meta = {
        "label": f"#{iter_tag} — {'MOCK' if mock else 'UE5'} pipeline run",
        "description": (
            f"End-to-end pipeline : BM → Blender USD → "
            f"{'mock copy (Blender PNG)' if mock else 'UE5 Lumen render'} → "
            f"regression vs iter #320 baseline. "
            f"Regression: {regression.get('n_pass', '?')}/{regression.get('n_total', '?')} passed."
        ),
        "verdict": "ok" if regression.get("passed") else "partial",
        "source_blender_png": blender_png.name,
        "source_usda": usda.name,
        "regression": regression,
    }
    meta_path = persisted.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))
    # Refresh gallery
    gallery_script = REPO_ROOT / "scripts" / "gen_render_gallery.py"
    if gallery_script.exists():
        try:
            subprocess.run([sys.executable, str(gallery_script)], check=True, timeout=15)
        except Exception as e:
            log(f"  !! gallery refresh failed ({e})")
    log(f"✓ Persisted → {persisted}")
    return persisted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iter", type=int, required=True,
                        help="Iteration number for naming (e.g. 401)")
    parser.add_argument("--mock-ue5", action="store_true",
                        help="Skip UE5 step (copy Blender PNG instead) — for testing.")
    args = parser.parse_args()

    log(f"ArchiClaude pipeline — iter #{args.iter} {'(MOCK UE5)' if args.mock_ue5 else ''}")
    try:
        blender_png, usda = run_blender_step(args.iter)
        ue5_png = RENDERS_DIR / f"ue5_tmp_iter{args.iter}.png"
        run_ue5_step(usda, ue5_png, args.mock_ue5, blender_png)
        regression = run_regression_step(ue5_png)
        final = persist_and_meta(ue5_png, args.iter, regression,
                                  blender_png, usda, args.mock_ue5)
        ue5_png.unlink(missing_ok=True)
        log(f"✓ Pipeline complete — final render : {final}")
        return 0 if regression.get("passed") else 1
    except Exception as e:
        log(f"✗ Pipeline failed : {e}")
        return 10


if __name__ == "__main__":
    sys.exit(main())
