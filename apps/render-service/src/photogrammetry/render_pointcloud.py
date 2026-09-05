"""Point cloud viewer — overlays LiDAR HD classes on the BDTOPO 3D scene.

Reads filtered LAZ point clouds (output by modal_lidar_endpoint), subsamples
to a target point budget, colorises by class, and renders an interactive
plotly figure with optional building footprints in wireframe overlay.

Goal: show the user the *real* 3D geometry captured by IGN's airborne LiDAR
(facades from oblique scans, tree canopies, terrain undulations).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


CLASS_COLORS = {
    "ground":          "rgb(140, 130, 110)",  # warm brown earth
    "building":        "rgb(170, 80, 60)",     # terracotta tile
    "high_vegetation": "rgb(50, 130, 60)",     # forest green
    "mid_vegetation":  "rgb(100, 160, 80)",    # shrubs
    "low_vegetation":  "rgb(160, 200, 100)",   # grass
    "water":           "rgb(40, 110, 180)",
    "bridge":          "rgb(80, 80, 90)",
}


@dataclass
class PointCloudViewerResult:
    project_id: str
    html_path: str
    png_paths: dict
    points_rendered_per_class: dict
    z_range_m: tuple


def _load_laz(path: Path, max_points: int):
    """Return (x, y, z) np arrays subsampled uniformly to ≤ max_points."""
    import laspy
    import numpy as np
    las = laspy.read(str(path))
    n = len(las.x)
    x = np.asarray(las.x)
    y = np.asarray(las.y)
    z = np.asarray(las.z)
    if n > max_points:
        idx = np.random.default_rng(seed=42).choice(n, size=max_points, replace=False)
        x, y, z = x[idx], y[idx], z[idx]
    return x, y, z


def render_pointcloud_3d(
    project_id: str,
    lidar_dir: Path,
    project_centroid_lambert93: tuple,  # (x, y) in EPSG:2154
    output_dir: Path,
    max_points_per_class: dict = None,
    save_screenshots: bool = True,
) -> PointCloudViewerResult:
    """Render LiDAR point cloud classes as plotly Scatter3d traces.

    Args:
        project_id: ArchiClaude project UUID
        lidar_dir: directory containing {ground,building,high_vegetation}.laz
        project_centroid_lambert93: parcelle centroid in Lambert93 metres
                                     (used to center the local coord system)
        output_dir: where to save scene_pointcloud_*.html / .png
        max_points_per_class: per-class subsample budgets, default:
            ground=80k, building=80k, high_veg=50k
        save_screenshots: whether to also render PNG snapshots
    """
    import numpy as np
    import plotly.graph_objects as go

    if max_points_per_class is None:
        max_points_per_class = {
            "ground": 80_000,
            "building": 80_000,
            "high_vegetation": 50_000,
        }

    origin_x, origin_y = project_centroid_lambert93
    output_dir.mkdir(parents=True, exist_ok=True)

    fig = go.Figure()
    points_per_class: dict = {}
    z_all: list = []

    for class_label, max_pts in max_points_per_class.items():
        laz_path = lidar_dir / f"{class_label}.laz"
        if not laz_path.exists():
            logger.warning("Missing LAZ for class %s at %s", class_label, laz_path)
            continue
        x, y, z = _load_laz(laz_path, max_pts)
        # Convert Lambert93 absolute → local metric (centered on parcelle)
        xl = x - origin_x
        yl = y - origin_y
        color = CLASS_COLORS.get(class_label, "rgb(120,120,120)")
        marker_size = 1.2 if class_label == "ground" else (1.8 if class_label == "building" else 1.5)
        fig.add_trace(
            go.Scatter3d(
                x=xl, y=yl, z=z,
                mode="markers",
                marker=dict(size=marker_size, color=color, opacity=0.85),
                name=class_label,
                hoverinfo="skip",
            )
        )
        points_per_class[class_label] = int(len(xl))
        z_all.extend(z.tolist())
        logger.info("Loaded %s : %d points", class_label, len(xl))

    if not z_all:
        raise RuntimeError("No LiDAR points loaded — empty LAZ files?")

    z_min, z_max = float(min(z_all)), float(max(z_all))
    logger.info("Scene z range: %.1f → %.1f m NGF", z_min, z_max)

    fig.update_layout(
        title=f"ArchiClaude — Point cloud LiDAR HD projet {project_id[:8]}",
        scene=dict(
            xaxis_title="X local (m, Lambert-93)",
            yaxis_title="Y local (m, Lambert-93)",
            zaxis_title="Z NGF (m)",
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=-1.5, z=1.1)),
            bgcolor="rgb(245, 245, 250)",
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        paper_bgcolor="white",
        legend=dict(itemsizing="constant", bgcolor="rgba(255,255,255,0.8)"),
    )

    html_path = output_dir / "scene_pointcloud_interactive.html"
    fig.write_html(str(html_path), include_plotlyjs="cdn", full_html=True)
    logger.info("Pointcloud HTML: %s", html_path)

    png_paths: dict = {}
    if save_screenshots:
        try:
            views = {
                "axonometric": dict(eye=dict(x=1.5, y=-1.5, z=1.1)),
                "ground_perspective": dict(eye=dict(x=0.8, y=-0.8, z=0.25)),
                "top":         dict(eye=dict(x=0.001, y=0.001, z=2.5)),
            }
            for view_name, camera in views.items():
                fig.update_layout(scene_camera=camera)
                png_path = output_dir / f"scene_pointcloud_{view_name}.png"
                fig.write_image(str(png_path), width=1600, height=1200, scale=1)
                png_paths[view_name] = str(png_path)
                logger.info("Pointcloud snapshot %s: %s", view_name, png_path)
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)

    return PointCloudViewerResult(
        project_id=project_id,
        html_path=str(html_path),
        png_paths=png_paths,
        points_rendered_per_class=points_per_class,
        z_range_m=(round(z_min, 1), round(z_max, 1)),
    )
