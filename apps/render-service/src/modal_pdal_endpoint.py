"""Modal endpoint — Poisson surface reconstruction on IGN LiDAR HD building points.

Pipeline Jour 3:
    /cache/filtered/<tile>/building.laz (from modal_lidar_endpoint)
      → laspy read + bbox crop
      → DBSCAN cluster (eps=2.0 m, min_samples=30) to separate buildings
      → per-cluster: Open3D PointCloud + normal estimation
      → Poisson surface reconstruction (depth=9, scale=1.1)
      → trim low-density vertices (bottom 5%)
      → export OBJ to /cache/meshes/<tile>/building_<cluster_id>.obj
      → return manifest JSON

Open3D vs PDAL: Open3D ships with native Poisson reconstruction (Kazhdan 2013),
installs cleanly via pip on Linux, and is the standard for the laspy→mesh path.
PDAL would need micromamba and adds dependencies for marginal gain here.

Usage:
    .venv/bin/modal run src/modal_pdal_endpoint.py \\
        --tile-name LHD_FXX_0662_6860_PTS_LAMB93_IGN69 \\
        --bbox-lambert93 "662308,6859795,662708,6860195"
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-pdal-mesh")

# Open3D 0.18+ ships pre-built wheels for Linux x86_64 Python 3.11.
# scikit-learn for DBSCAN, laspy for LAZ I/O, numpy as glue.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgomp1", "libgl1", "libglib2.0-0")
    .pip_install(
        "open3d>=0.18",
        "laspy[lazrs]>=2.5.4",
        "numpy>=1.26,<2.0",  # open3d 0.18 still requires numpy<2 as of 2026-Q1
        "scikit-learn>=1.4",
    )
)

# Reuse the same volume as modal_lidar_endpoint
lidar_cache = modal.Volume.from_name("archfr-lidar-hd-cache", create_if_missing=True)

CACHE_MOUNT = "/cache"
CACHE_FILTERED_DIR = f"{CACHE_MOUNT}/filtered"
CACHE_MESHES_DIR = f"{CACHE_MOUNT}/meshes"


@dataclass
class ClusterMeshStat:
    cluster_id: int
    n_points: int
    mesh_vertices: int
    mesh_faces: int
    bbox_lambert93: tuple  # (x_min, y_min, z_min, x_max, y_max, z_max)
    centroid_lambert93: tuple  # (x, y, z)
    obj_path: str
    poisson_density_p5: float


@dataclass
class PoissonReconstructionResult:
    tile_name: str
    bbox_lambert93: tuple
    n_points_input: int
    n_clusters_total: int
    n_clusters_meshed: int
    n_clusters_skipped: int
    clusters: list  # list[ClusterMeshStat as dict]
    duration_s: float
    poisson_depth: int


@app.function(
    image=image,
    volumes={CACHE_MOUNT: lidar_cache},
    timeout=1800,
    cpu=4,
    memory=16384,
)
def reconstruct_meshes(
    tile_name: str,
    bbox_lambert93: tuple,
    poisson_depth: int = 9,
    dbscan_eps: float = 2.0,
    dbscan_min_samples: int = 30,
    min_cluster_points: int = 100,
    density_trim_percentile: float = 5.0,
) -> dict:
    """Cluster a LiDAR building point cloud and Poisson-reconstruct each cluster.

    Args:
        tile_name: name of the IGN tile (e.g. LHD_FXX_0662_6860_PTS_LAMB93_IGN69)
        bbox_lambert93: (x_min, y_min, x_max, y_max) Lambert-93 crop bbox
        poisson_depth: octree depth (9 = ~2 m resolution for an urban scene)
        dbscan_eps: DBSCAN neighbourhood radius in metres
        dbscan_min_samples: DBSCAN min core-point neighbours
        min_cluster_points: skip clusters below this size
        density_trim_percentile: drop vertices with density below this percentile

    Returns asdict(PoissonReconstructionResult).
    """
    import time
    import numpy as np
    import laspy
    import open3d as o3d
    from sklearn.cluster import DBSCAN

    t0 = time.time()
    laz_path = Path(CACHE_FILTERED_DIR) / tile_name / "building.laz"
    if not laz_path.exists():
        raise FileNotFoundError(
            f"Filtered building.laz missing at {laz_path}. "
            "Run modal_lidar_endpoint.fetch_and_filter first."
        )

    print(f"[laspy] reading {laz_path}")
    with laspy.open(str(laz_path)) as src:
        las = src.read()
    x = np.asarray(las.x)
    y = np.asarray(las.y)
    z = np.asarray(las.z)

    x_min, y_min, x_max, y_max = bbox_lambert93
    bbox_mask = (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)
    pts = np.stack([x[bbox_mask], y[bbox_mask], z[bbox_mask]], axis=1)
    n_pts = pts.shape[0]
    print(f"[crop] {n_pts:,} points in bbox")
    if n_pts < min_cluster_points:
        raise RuntimeError(f"Not enough points after bbox crop: {n_pts}")

    # DBSCAN in 2D (x,y) to avoid splitting vertical stacks of facade samples.
    print(
        f"[dbscan] running eps={dbscan_eps} min_samples={dbscan_min_samples} on XY plane"
    )
    db = DBSCAN(eps=dbscan_eps, min_samples=dbscan_min_samples, n_jobs=-1)
    labels = db.fit_predict(pts[:, :2])
    unique = sorted(set(int(label) for label in labels))
    n_clusters = sum(1 for label in unique if label != -1)
    print(
        f"[dbscan] {n_clusters} clusters + {int((labels == -1).sum()):,} noise points"
    )

    meshes_dir = Path(CACHE_MESHES_DIR) / tile_name
    meshes_dir.mkdir(parents=True, exist_ok=True)
    # Clean up any stale meshes from a previous run on the same tile
    for stale in meshes_dir.glob("building_*.obj"):
        stale.unlink()

    cluster_stats: list = []
    n_skipped = 0
    n_meshed = 0

    for cluster_id in unique:
        if cluster_id == -1:
            continue
        mask = labels == cluster_id
        cluster_pts = pts[mask]
        if cluster_pts.shape[0] < min_cluster_points:
            n_skipped += 1
            continue

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(cluster_pts)

        # Estimate normals; orient towards "up" since LiDAR is top-down dominant.
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=2.0, max_nn=30)
        )
        pcd.orient_normals_to_align_with_direction(
            orientation_reference=np.array([0.0, 0.0, 1.0])
        )

        try:
            mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=poisson_depth, scale=1.1, linear_fit=False
            )
        except Exception as exc:
            print(f"[poisson] cluster {cluster_id} failed: {exc}")
            n_skipped += 1
            continue

        # Trim low-density vertices — these are the "bubble" extensions that
        # Poisson creates when fitting a watertight surface to sparse data.
        densities = np.asarray(densities)
        if densities.size == 0:
            n_skipped += 1
            continue
        density_threshold = float(np.percentile(densities, density_trim_percentile))
        vertices_to_remove = densities < density_threshold
        mesh.remove_vertices_by_mask(vertices_to_remove)
        mesh.remove_degenerate_triangles()
        mesh.remove_unreferenced_vertices()

        if len(mesh.triangles) == 0:
            n_skipped += 1
            continue

        # Crop the mesh to the cluster XY bbox padded by 2 m to drop wild Poisson
        # tendrils far outside the actual building.
        c_xmin, c_ymin = cluster_pts[:, :2].min(axis=0) - 2.0
        c_xmax, c_ymax = cluster_pts[:, :2].max(axis=0) + 2.0
        c_zmin = float(cluster_pts[:, 2].min()) - 1.0
        c_zmax = float(cluster_pts[:, 2].max()) + 3.0
        aabb = o3d.geometry.AxisAlignedBoundingBox(
            min_bound=(c_xmin, c_ymin, c_zmin),
            max_bound=(c_xmax, c_ymax, c_zmax),
        )
        mesh = mesh.crop(aabb)
        if len(mesh.triangles) == 0:
            n_skipped += 1
            continue

        obj_path = meshes_dir / f"building_{cluster_id:04d}.obj"
        o3d.io.write_triangle_mesh(str(obj_path), mesh, write_ascii=True)

        v = np.asarray(mesh.vertices)
        centroid = v.mean(axis=0)
        cluster_stats.append(
            asdict(
                ClusterMeshStat(
                    cluster_id=int(cluster_id),
                    n_points=int(cluster_pts.shape[0]),
                    mesh_vertices=int(len(mesh.vertices)),
                    mesh_faces=int(len(mesh.triangles)),
                    bbox_lambert93=(
                        float(v[:, 0].min()),
                        float(v[:, 1].min()),
                        float(v[:, 2].min()),
                        float(v[:, 0].max()),
                        float(v[:, 1].max()),
                        float(v[:, 2].max()),
                    ),
                    centroid_lambert93=(
                        float(centroid[0]),
                        float(centroid[1]),
                        float(centroid[2]),
                    ),
                    obj_path=str(obj_path),
                    poisson_density_p5=density_threshold,
                )
            )
        )
        n_meshed += 1
        if n_meshed % 10 == 0:
            print(
                f"[poisson] meshed {n_meshed} clusters so far "
                f"(last: {cluster_id} → {len(mesh.triangles)} tri)"
            )

    lidar_cache.commit()

    result = PoissonReconstructionResult(
        tile_name=tile_name,
        bbox_lambert93=tuple(bbox_lambert93),
        n_points_input=int(n_pts),
        n_clusters_total=int(n_clusters),
        n_clusters_meshed=int(n_meshed),
        n_clusters_skipped=int(n_skipped),
        clusters=cluster_stats,
        duration_s=round(time.time() - t0, 2),
        poisson_depth=int(poisson_depth),
    )
    manifest_path = meshes_dir / "manifest.json"
    manifest_path.write_text(json.dumps(asdict(result), indent=2))
    lidar_cache.commit()
    print(
        f"[done] meshed {n_meshed}/{n_clusters} clusters "
        f"in {result.duration_s:.1f}s → {manifest_path}"
    )
    return asdict(result)


@app.function(image=image, volumes={CACHE_MOUNT: lidar_cache}, timeout=120)
def list_meshes() -> dict:
    """List meshes produced per tile."""
    meshes_dir = Path(CACHE_MESHES_DIR)
    out = []
    if meshes_dir.exists():
        for tile_dir in sorted(meshes_dir.iterdir()):
            if not tile_dir.is_dir():
                continue
            objs = sorted(tile_dir.glob("building_*.obj"))
            out.append(
                {
                    "tile": tile_dir.name,
                    "n_meshes": len(objs),
                    "size_mb": round(
                        sum(p.stat().st_size for p in objs) / 1e6, 2
                    ),
                }
            )
    return {"tiles_with_meshes": out}


@app.local_entrypoint()
def main(
    tile_name: str = "",
    bbox_lambert93: str = "",
    poisson_depth: int = 9,
    list_only: bool = False,
):
    """CLI entrypoint.

    Example for Nogent 80 Rue des Héros:
      modal run src/modal_pdal_endpoint.py \\
        --tile-name LHD_FXX_0662_6860_PTS_LAMB93_IGN69 \\
        --bbox-lambert93 "662308,6859795,662708,6860195"
    """
    if list_only or not tile_name:
        print(json.dumps(list_meshes.remote(), indent=2))
        return
    parts = [float(p.strip()) for p in bbox_lambert93.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox-lambert93 expects 'x_min,y_min,x_max,y_max'")
    bbox = (parts[0], parts[1], parts[2], parts[3])
    result = reconstruct_meshes.remote(
        tile_name=tile_name,
        bbox_lambert93=bbox,
        poisson_depth=poisson_depth,
    )
    # Print a condensed view (full manifest is on the Volume)
    summary = {
        k: v
        for k, v in result.items()
        if k != "clusters"
    }
    summary["n_clusters_meshed"] = result["n_clusters_meshed"]
    print("\n=== Poisson reconstruction summary ===")
    print(json.dumps(summary, indent=2))
    print(f"clusters[0:3] preview: {json.dumps(result['clusters'][:3], indent=2)}")
