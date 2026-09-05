"""3D interactive viewer for BDTOPO LOD2 + parcelle highlight.

Extrudes BDTOPO V3 building footprints (already in absolute NGF z) into
3D meshes, places parcelle outline on the ground plane, exports:
  - scene_3d_interactive.html : plotly figure (rotate/zoom/pan in browser)
  - scene_3d_<view>.png       : 4 fixed-angle screenshots
                                 (axonometric, NE, SW, top-down)

Coordinates are projected to local Lambert-93 metric system (EPSG:2154)
so distances on screen match reality. Highlighted parcelle is rendered
as a yellow extruded prism for visibility.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Render3DResult:
    project_id: str
    html_path: str
    png_paths: dict  # {view_name: path}
    n_buildings_rendered: int
    n_buildings_skipped: int
    z_ground_m: float
    bbox_local_m: tuple  # (x_min, x_max, y_min, y_max) local Lambert93


def _to_lambert93(lng: float, lat: float, transformer) -> tuple:
    x, y = transformer.transform(lng, lat)
    return x, y


def _ring_to_polygon_3d(
    ring: list,
    transformer,
    z_ground: float,
    origin_x: float,
    origin_y: float,
):
    """Extract footprint + roof from a BDTOPO LOD2 ring.

    The ring is a 3D polyline traversing the building outline at varying heights
    (LOD2 = stair-stepped walls). For a clean prismatic preview, we project the
    ring to 2D, dedupe consecutive points, and extrude from z_ground to z_max.
    """
    seen = set()
    footprint_x, footprint_y = [], []
    z_values = []
    for vertex in ring:
        if not isinstance(vertex, list) or len(vertex) < 3:
            continue
        lng, lat, z = float(vertex[0]), float(vertex[1]), float(vertex[2])
        x, y = transformer.transform(lng, lat)
        x_local, y_local = x - origin_x, y - origin_y
        key = (round(x_local, 2), round(y_local, 2))
        if key in seen:
            continue
        seen.add(key)
        footprint_x.append(x_local)
        footprint_y.append(y_local)
        if z > -100:  # filter sentinel -1000
            z_values.append(z)
    if not z_values or len(footprint_x) < 3:
        return None
    z_max = max(z_values)
    return (footprint_x, footprint_y, z_max)


def _building_mesh(footprint_x, footprint_y, z_ground, z_top):
    """Build vertex + face arrays for a prismatic extrusion (Plotly Mesh3d format).

    Returns dict with keys 'x','y','z','i','j','k' suitable for plotly Mesh3d.
    """
    import numpy as np
    n = len(footprint_x)
    # Vertices: n bottom + n top
    xs = list(footprint_x) + list(footprint_x)
    ys = list(footprint_y) + list(footprint_y)
    zs = [z_ground] * n + [z_top] * n
    # Side faces: each footprint edge → 2 triangles between bottom and top
    i_idx, j_idx, k_idx = [], [], []
    for k_e in range(n):
        b0 = k_e
        b1 = (k_e + 1) % n
        t0 = k_e + n
        t1 = (k_e + 1) % n + n
        # Triangle 1: b0, b1, t1
        i_idx.append(b0); j_idx.append(b1); k_idx.append(t1)
        # Triangle 2: b0, t1, t0
        i_idx.append(b0); j_idx.append(t1); k_idx.append(t0)
    # Roof: fan triangulation from vertex 0 (assumes convex-ish footprint, fine for LOD1)
    for k_e in range(1, n - 1):
        i_idx.append(n)             # vertex 0 of top
        j_idx.append(n + k_e)
        k_idx.append(n + k_e + 1)
    return {"x": xs, "y": ys, "z": zs, "i": i_idx, "j": j_idx, "k": k_idx}


def _sample_ortho_color(
    ortho_img,
    bbox_wgs84,
    lng_centroid: float,
    lat_centroid: float,
    sample_radius_px: int = 6,
) -> tuple:
    """Sample mean RGB color from an ortho PIL image at the WGS84 centroid.

    bbox_wgs84: (lat_min, lng_min, lat_max, lng_max) — must match the
    WMS GetMap params used to fetch the image (BBOX with axis order lat,lng).
    Returns (r, g, b) in 0-255 range, or None if outside the bbox.
    """
    import numpy as np
    lat_min, lng_min, lat_max, lng_max = bbox_wgs84
    if not (lng_min <= lng_centroid <= lng_max and lat_min <= lat_centroid <= lat_max):
        return None
    w, h = ortho_img.size
    px = int((lng_centroid - lng_min) / (lng_max - lng_min) * w)
    py = int((lat_max - lat_centroid) / (lat_max - lat_min) * h)
    px = max(sample_radius_px, min(w - sample_radius_px - 1, px))
    py = max(sample_radius_px, min(h - sample_radius_px - 1, py))
    arr = np.asarray(ortho_img)
    crop = arr[py - sample_radius_px : py + sample_radius_px + 1,
               px - sample_radius_px : px + sample_radius_px + 1, :3]
    return tuple(int(c) for c in crop.reshape(-1, 3).mean(axis=0))


def _load_obj_mesh(obj_path: Path):
    """Parse an OBJ file into (vertices Nx3 list, faces list of (i,j,k) triangles).

    Pure-Python parser to avoid a trimesh dep. Handles v/vn/f lines and
    quadrilateral faces via fan-triangulation.
    """
    vs: list = []
    faces: list = []
    with obj_path.open() as fp:
        for line in fp:
            if line.startswith("v "):
                parts = line.strip().split()
                vs.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif line.startswith("f "):
                parts = line.strip().split()[1:]
                # f tokens may be "v", "v/vt", "v//vn", "v/vt/vn" — keep the v index only
                vert_indices = [int(tok.split("/")[0]) - 1 for tok in parts]
                # Fan-triangulate n-gons
                for i in range(1, len(vert_indices) - 1):
                    faces.append((vert_indices[0], vert_indices[i], vert_indices[i + 1]))
    return vs, faces


def _add_lidar_meshes_to_figure(
    fig,
    lidar_meshes_dir: Path,
    origin_x: float,
    origin_y: float,
    radius_m: float,
    z_ground: float,
    ortho_img,
    ortho_drape_bbox_wgs84,
    transformer_back,
) -> int:
    """Load each Poisson OBJ in lidar_meshes_dir and add a Mesh3d trace.

    Meshes are in Lambert-93 absolute coordinates. We translate to local
    (origin_x, origin_y) then filter by radius_m. Roof colour is sampled from
    the BD ORTHO drape at the mesh XY centroid when available.
    """
    import plotly.graph_objects as go

    objs = sorted(lidar_meshes_dir.glob("building_*.obj"))
    if not objs:
        logger.warning("No building_*.obj in %s", lidar_meshes_dir)
        return 0
    n_added = 0
    for obj_path in objs:
        vs, faces = _load_obj_mesh(obj_path)
        if not vs or not faces:
            continue
        # Translate Lambert-93 absolute → local
        xs = [v[0] - origin_x for v in vs]
        ys = [v[1] - origin_y for v in vs]
        zs = [v[2] for v in vs]
        # Radius filter on the centroid
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        if max(abs(cx), abs(cy)) > radius_m + 50:
            continue
        # Sample roof colour from ortho drape if we have one
        roof_color = None
        if ortho_img is not None and ortho_drape_bbox_wgs84 is not None and transformer_back is not None:
            # Back-project local XY → Lambert93 → WGS84
            abs_x = cx + origin_x
            abs_y = cy + origin_y
            lng_c, lat_c = transformer_back.transform(abs_x, abs_y)
            roof_color = _sample_ortho_color(
                ortho_img, ortho_drape_bbox_wgs84, lng_c, lat_c
            )
        if roof_color is None:
            roof_color = (180, 165, 150)
        r, g, b = roof_color
        color = f"rgb({r},{g},{b})"
        i_idx = [f[0] for f in faces]
        j_idx = [f[1] for f in faces]
        k_idx = [f[2] for f in faces]
        fig.add_trace(
            go.Mesh3d(
                x=xs,
                y=ys,
                z=zs,
                i=i_idx,
                j=j_idx,
                k=k_idx,
                color=color,
                opacity=1.0,
                flatshading=True,
                lighting=dict(ambient=0.5, diffuse=0.7, specular=0.1),
                hoverinfo="skip",
                showlegend=False,
                name=obj_path.stem,
            )
        )
        n_added += 1
    logger.info("LiDAR Poisson meshes added: %d (from %s)", n_added, lidar_meshes_dir)
    return n_added


def render_scene_3d(
    project_id: str,
    bdtopo_geojson: dict,
    parcelle_geojson: Optional[dict],
    project_centroid: tuple,  # (lng, lat)
    output_dir: Path,
    radius_m: float = 200.0,
    save_screenshots: bool = True,
    ortho_drape_path: Optional[Path] = None,
    ortho_drape_bbox_wgs84: Optional[tuple] = None,
    lidar_meshes_dir: Optional[Path] = None,
    output_filename_prefix: str = "scene_3d",
) -> Render3DResult:
    """Render an interactive 3D scene of the quartier.

    Args:
        project_id: ArchiClaude project UUID
        bdtopo_geojson: FeatureCollection of LOD2 buildings (z in absolute NGF metres)
        parcelle_geojson: FeatureCollection of project parcelles
        project_centroid: (lng, lat) center of the rendering
        output_dir: where to write HTML + PNG
        radius_m: half-extent of the scene (filters buildings outside)
        save_screenshots: if True, render 4 fixed-angle PNGs (requires kaleido)
        lidar_meshes_dir: if set, replace BDTOPO extrusions with Poisson OBJ meshes
            in this directory. The ground plane + parcelle highlight are kept.
        output_filename_prefix: file prefix for HTML/PNG outputs (default 'scene_3d').
            Use e.g. 'scene_3d_lidar' when rendering with LiDAR meshes for A/B comparison.
    """
    import plotly.graph_objects as go
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    transformer_back = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    cen_lng, cen_lat = project_centroid
    origin_x, origin_y = transformer.transform(cen_lng, cen_lat)
    use_lidar = lidar_meshes_dir is not None and Path(lidar_meshes_dir).exists()

    # Optional ortho drape: load once and sample per-building color
    ortho_img = None
    if ortho_drape_path and ortho_drape_path.exists():
        from PIL import Image
        ortho_img = Image.open(ortho_drape_path).convert("RGB")
        logger.info("Ortho drape source: %s (%dx%d)", ortho_drape_path, *ortho_img.size)

    # Collect all valid building footprints + z + roof color
    raw_buildings = []
    n_skipped = 0
    for feature in bdtopo_geojson.get("features", []):
        coords = feature.get("geometry", {}).get("coordinates", [])
        feature_centroid_lng_lat = None
        # MultiPolygon: [[ring]]; each ring is a list of [lng,lat,z]
        for poly in coords:
            for ring in poly:
                result = _ring_to_polygon_3d(ring, transformer, 0, origin_x, origin_y)
                if result is None:
                    n_skipped += 1
                    continue
                fx, fy, z_max = result
                # Filter buildings outside the bbox radius
                if max(abs(min(fx)), abs(max(fx)), abs(min(fy)), abs(max(fy))) > radius_m:
                    continue
                # Sample roof color from ortho drape if available
                roof_color = None
                if ortho_img is not None and ortho_drape_bbox_wgs84:
                    lngs = [vertex[0] for vertex in ring if isinstance(vertex, list) and len(vertex) >= 2]
                    lats = [vertex[1] for vertex in ring if isinstance(vertex, list) and len(vertex) >= 2]
                    if lngs and lats:
                        roof_color = _sample_ortho_color(
                            ortho_img, ortho_drape_bbox_wgs84,
                            sum(lngs) / len(lngs), sum(lats) / len(lats),
                        )
                raw_buildings.append((fx, fy, z_max, roof_color))

    if not raw_buildings:
        raise RuntimeError("No buildings to render — empty BDTOPO data?")

    # Ground level = 5th percentile of all building z_max (proxy for sol moyen)
    import numpy as np
    z_max_arr = np.array([b[2] for b in raw_buildings])
    z_ground = float(np.percentile(z_max_arr, 5)) - 10.0
    bbox_local_min_x = min(min(b[0]) for b in raw_buildings)
    bbox_local_max_x = max(max(b[0]) for b in raw_buildings)
    bbox_local_min_y = min(min(b[1]) for b in raw_buildings)
    bbox_local_max_y = max(max(b[1]) for b in raw_buildings)
    # Use the BDTOPO z_min hint from features to better estimate ground:
    all_z = []
    for feature in bdtopo_geojson.get("features", []):
        coords = feature.get("geometry", {}).get("coordinates", [])
        for poly in coords:
            for ring in poly:
                for vertex in ring:
                    if isinstance(vertex, list) and len(vertex) >= 3 and vertex[2] > -100:
                        all_z.append(vertex[2])
    if all_z:
        z_ground = float(np.percentile(all_z, 2))
    logger.info("z_ground estimated at %.1f m NGF", z_ground)

    output_dir.mkdir(parents=True, exist_ok=True)

    fig = go.Figure()

    # Ground plane textured with BD ORTHO (sampled grid → vertex colors)
    if ortho_img is not None and ortho_drape_bbox_wgs84:
        grid_n = 64
        lat_min_g, lng_min_g, lat_max_g, lng_max_g = ortho_drape_bbox_wgs84
        # Build a regular lng/lat grid covering the ortho bbox
        lats_g = np.linspace(lat_max_g, lat_min_g, grid_n)  # top-down (matches image y)
        lngs_g = np.linspace(lng_min_g, lng_max_g, grid_n)
        ortho_arr = np.asarray(ortho_img)
        oh, ow = ortho_arr.shape[:2]
        # Convert each grid point to local Lambert93 + sample its color
        ground_xs = np.zeros((grid_n, grid_n))
        ground_ys = np.zeros((grid_n, grid_n))
        ground_colors = []
        for i, lat_g in enumerate(lats_g):
            for j, lng_g in enumerate(lngs_g):
                gx, gy = transformer.transform(lng_g, lat_g)
                ground_xs[i, j] = gx - origin_x
                ground_ys[i, j] = gy - origin_y
                px = min(ow - 1, max(0, int((lng_g - lng_min_g) / (lng_max_g - lng_min_g) * (ow - 1))))
                py = min(oh - 1, max(0, int((lat_max_g - lat_g) / (lat_max_g - lat_min_g) * (oh - 1))))
                ground_colors.append(ortho_arr[py, px, :3])
        ground_colors = np.array(ground_colors).reshape(grid_n, grid_n, 3)
        # Plotly Surface accepts surfacecolor as scalar + colorscale ; for true RGB
        # we use a per-vertex Mesh3d quad lattice → grid_n × grid_n vertices
        verts_x = ground_xs.flatten()
        verts_y = ground_ys.flatten()
        verts_z = np.full_like(verts_x, z_ground)
        # vertexcolor in plotly Mesh3d accepts list of "rgb(r,g,b)" strings
        vcolors = [f"rgb({c[0]},{c[1]},{c[2]})" for row in ground_colors for c in row]
        # Build triangulated quad grid (each quad → 2 triangles)
        i_idx, j_idx, k_idx = [], [], []
        for i in range(grid_n - 1):
            for j in range(grid_n - 1):
                v00 = i * grid_n + j
                v01 = i * grid_n + (j + 1)
                v10 = (i + 1) * grid_n + j
                v11 = (i + 1) * grid_n + (j + 1)
                i_idx.extend([v00, v00]); j_idx.extend([v01, v11]); k_idx.extend([v11, v10])
        fig.add_trace(
            go.Mesh3d(
                x=verts_x, y=verts_y, z=verts_z,
                i=i_idx, j=j_idx, k=k_idx,
                vertexcolor=vcolors,
                opacity=1.0,
                lighting=dict(ambient=0.95, diffuse=0.4, specular=0.05),
                hoverinfo="skip",
                showlegend=False,
                name="ground_ortho",
            )
        )
        logger.info("Ground plane textured: %d×%d grid, %d vertices", grid_n, grid_n, grid_n * grid_n)

    n_lidar_meshes = 0
    if use_lidar:
        n_lidar_meshes = _add_lidar_meshes_to_figure(
            fig,
            Path(lidar_meshes_dir),
            origin_x=origin_x,
            origin_y=origin_y,
            radius_m=radius_m,
            z_ground=z_ground,
            ortho_img=ortho_img,
            ortho_drape_bbox_wgs84=ortho_drape_bbox_wgs84,
            transformer_back=transformer_back,
        )
    else:
        # Render each building as a prism with ortho-sampled roof color (or height-gradient fallback)
        for fx, fy, z_top, roof_color in raw_buildings:
            height = max(2.0, z_top - z_ground)
            mesh = _building_mesh(fx, fy, z_ground, z_top)
            if roof_color is not None:
                r, g, b = roof_color
            else:
                color_intensity = min(1.0, height / 30.0)
                r = int(200 - color_intensity * 50)
                g = int(180 - color_intensity * 90)
                b = int(160 - color_intensity * 90)
            color = f"rgb({r},{g},{b})"
            fig.add_trace(
                go.Mesh3d(
                    **mesh,
                    color=color,
                    opacity=1.0,
                    flatshading=True,
                    lighting=dict(ambient=0.5, diffuse=0.7, specular=0.1),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # Parcelle highlight: yellow outline on the ground plane + small extrusion 1m
    if parcelle_geojson:
        features = parcelle_geojson.get("features", [parcelle_geojson]) if isinstance(parcelle_geojson, dict) else parcelle_geojson
        for feature in features:
            geom = feature.get("geometry") if isinstance(feature, dict) and "geometry" in feature else feature
            coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
            # Parcelles are 2D MultiPolygons (no z)
            for poly in coords:
                if not poly:
                    continue
                ring = poly[0] if isinstance(poly[0][0], list) else poly
                xs_p, ys_p = [], []
                for vertex in ring:
                    if isinstance(vertex, list) and len(vertex) >= 2:
                        x, y = transformer.transform(vertex[0], vertex[1])
                        xs_p.append(x - origin_x)
                        ys_p.append(y - origin_y)
                if len(xs_p) < 3:
                    continue
                # Yellow outline lifted above the ground texture so it stays visible
                z_marker = z_ground + 2.0
                fig.add_trace(
                    go.Scatter3d(
                        x=xs_p + [xs_p[0]],
                        y=ys_p + [ys_p[0]],
                        z=[z_marker] * (len(xs_p) + 1),
                        mode="lines",
                        line=dict(color="rgb(255, 220, 0)", width=14),
                        name="Parcelle projet",
                        showlegend=False,
                    )
                )
                # Transparent yellow extrusion 3 m tall to mark the parcelle volume in space
                parc_mesh = _building_mesh(xs_p, ys_p, z_ground + 0.5, z_marker + 1.0)
                fig.add_trace(
                    go.Mesh3d(
                        **parc_mesh,
                        color="rgb(255, 220, 0)",
                        opacity=0.55,
                        flatshading=True,
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

    # Scene layout
    fig.update_layout(
        title=f"ArchiClaude — Vue 3D LOD2 quartier projet {project_id[:8]}",
        scene=dict(
            xaxis_title="X local (m)",
            yaxis_title="Y local (m)",
            zaxis_title="Z NGF (m)",
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=-1.5, z=1.1)),
            bgcolor="rgb(220, 230, 240)",
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        paper_bgcolor="white",
    )

    html_path = output_dir / f"{output_filename_prefix}_interactive.html"
    fig.write_html(str(html_path), include_plotlyjs="cdn", full_html=True)
    logger.info("Interactive 3D scene: %s", html_path)

    png_paths = {}
    if save_screenshots:
        try:
            views = {
                "axonometric": dict(eye=dict(x=1.5, y=-1.5, z=1.1)),
                "ne":          dict(eye=dict(x=1.8, y=1.5,  z=0.6)),
                "sw":          dict(eye=dict(x=-1.8, y=-1.5, z=0.6)),
                "top":         dict(eye=dict(x=0.001, y=0.001, z=2.5)),
            }
            for view_name, camera in views.items():
                fig.update_layout(scene_camera=camera)
                png_path = output_dir / f"{output_filename_prefix}_{view_name}.png"
                fig.write_image(str(png_path), width=1600, height=1200, scale=1)
                png_paths[view_name] = str(png_path)
                logger.info("3D snapshot %s: %s", view_name, png_path)
        except Exception as exc:
            logger.warning("Screenshot rendering failed (need 'kaleido' for static export): %s", exc)

    n_rendered = n_lidar_meshes if use_lidar else len(raw_buildings)
    return Render3DResult(
        project_id=project_id,
        html_path=str(html_path),
        png_paths=png_paths,
        n_buildings_rendered=n_rendered,
        n_buildings_skipped=n_skipped,
        z_ground_m=z_ground,
        bbox_local_m=(bbox_local_min_x, bbox_local_max_x, bbox_local_min_y, bbox_local_max_y),
    )
