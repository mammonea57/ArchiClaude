"""Project BDTOPO LOD2 buildings + parcelle into a depth map for ControlNet.

Pure-Python (NumPy + Pillow) — no Blender needed. ~2s per scene.

Outputs:
    refs/photogrammetry/<project>/depth_<view>.png         (16-bit grayscale depth)
    refs/photogrammetry/<project>/depth_<view>.preview.jpg (8-bit preview)
    refs/photogrammetry/<project>/depth_<view>_camera.json (camera params for repro)

The depth map is normalized so that:
    - 0 (black)   = closest (in front of camera)
    - 255 (white) = farthest (background sky)

This matches the convention expected by SDXL ControlNet depth models.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class CameraPose:
    """Eye-level urban camera looking at parcelle. Lambert93 local coords."""
    eye_x: float
    eye_y: float
    eye_z: float           # in metres above NGF ground
    target_x: float
    target_y: float
    target_z: float
    fov_deg: float = 35.0
    up_x: float = 0.0
    up_y: float = 0.0
    up_z: float = 1.0


def _project_world_to_screen(
    pts_world, eye, target, up, fov_deg, width, height,
):
    """Project 3D points (Nx3) to 2D screen (Nx2) + per-point z in camera space."""
    import numpy as np
    eye = np.asarray(eye, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)

    # Camera basis (right-handed, looking from eye toward target)
    forward = target - eye
    forward /= np.linalg.norm(forward) + 1e-9
    right = np.cross(forward, up)
    right /= np.linalg.norm(right) + 1e-9
    cam_up = np.cross(right, forward)

    pts = np.asarray(pts_world, dtype=np.float64)
    rel = pts - eye[None, :]

    # Camera-space coordinates : x=right, y=up, z=forward (into the screen)
    cam_x = rel @ right
    cam_y = rel @ cam_up
    cam_z = rel @ forward

    # Perspective projection
    fov_rad = math.radians(fov_deg)
    aspect = width / max(1, height)
    f = 1.0 / math.tan(fov_rad / 2.0)
    # screen-space x in [-1,1] left-right ; y in [-1,1] bottom-top
    eps = 1e-3
    safe_z = np.where(cam_z > eps, cam_z, eps)
    sx = (f / aspect) * cam_x / safe_z
    sy = f * cam_y / safe_z

    # To pixel coordinates
    px = (sx + 1.0) * 0.5 * width
    py = (1.0 - (sy + 1.0) * 0.5) * height   # flip Y
    return np.stack([px, py], axis=1), cam_z


def _rasterize_triangle(img, z_buf, tri_xy, tri_z, w, h):
    """Z-buffered scanline rasterization of one triangle (numpy in-place)."""
    import numpy as np
    x0, y0 = tri_xy[0]
    x1, y1 = tri_xy[1]
    x2, y2 = tri_xy[2]
    z0, z1, z2 = tri_z

    xs = [x0, x1, x2]
    ys = [y0, y1, y2]
    xmin = max(0, int(math.floor(min(xs))))
    xmax = min(w - 1, int(math.ceil(max(xs))))
    ymin = max(0, int(math.floor(min(ys))))
    ymax = min(h - 1, int(math.ceil(max(ys))))
    if xmax < xmin or ymax < ymin:
        return

    # Edge function denominator
    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denom) < 1e-9:
        return

    grid_x, grid_y = np.meshgrid(
        np.arange(xmin, xmax + 1), np.arange(ymin, ymax + 1),
    )
    w0 = ((y1 - y2) * (grid_x - x2) + (x2 - x1) * (grid_y - y2)) / denom
    w1 = ((y2 - y0) * (grid_x - x2) + (x0 - x2) * (grid_y - y2)) / denom
    w2 = 1.0 - w0 - w1
    inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not np.any(inside):
        return
    z = w0 * z0 + w1 * z1 + w2 * z2
    sub_z_buf = z_buf[ymin:ymax + 1, xmin:xmax + 1]
    closer = inside & (z < sub_z_buf)
    sub_z_buf[closer] = z[closer]


def _walk_polygons(geom_coords):
    """Yield outer rings from a Polygon or MultiPolygon GeoJSON geometry."""
    if not isinstance(geom_coords, list) or not geom_coords:
        return
    first = geom_coords[0]
    # MultiPolygon — list of polygons (each polygon = list of rings)
    if (isinstance(first, list) and first and isinstance(first[0], list)
            and first[0] and isinstance(first[0][0], list)):
        for poly in geom_coords:
            if poly:
                yield poly[0]
    # Polygon — list of rings
    elif isinstance(first, list) and first and isinstance(first[0], list):
        yield first[0]


def render_depth(
    bdtopo_geojson: dict,
    parcelle_center_lambert93: tuple[float, float],
    parcelle_center_lambert93_ground_z: float,
    width: int = 1024,
    height: int = 1024,
    eye_dist_m: float = 60.0,
    eye_height_m: float = 1.7,
    eye_azimuth_deg: float = -135.0,
    fov_deg: float = 35.0,
):
    """Render a depth map looking at the parcelle from a street-eye camera."""
    import numpy as np
    from pyproj import Transformer

    cx, cy = parcelle_center_lambert93
    az_rad = math.radians(eye_azimuth_deg)
    eye = (
        cx + eye_dist_m * math.cos(az_rad),
        cy + eye_dist_m * math.sin(az_rad),
        parcelle_center_lambert93_ground_z + eye_height_m,
    )
    target = (cx, cy, parcelle_center_lambert93_ground_z + 8.0)  # aim at building mid-height
    up = (0.0, 0.0, 1.0)

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

    z_buf = np.full((height, width), np.inf, dtype=np.float32)

    n_buildings = 0
    n_skipped = 0
    for feature in bdtopo_geojson.get("features", []):
        coords = feature.get("geometry", {}).get("coordinates", [])
        for ring_lnglatz in _walk_polygons(coords):
            # Extract z + base + footprint
            pts_lambert = []
            zs = []
            seen = set()
            for vertex in ring_lnglatz:
                if not isinstance(vertex, list) or len(vertex) < 3:
                    continue
                lng, lat, z = float(vertex[0]), float(vertex[1]), float(vertex[2])
                if z < -100:   # IGN sentinel for "no height"
                    continue
                x, y = transformer.transform(lng, lat)
                key = (round(x, 2), round(y, 2))
                if key in seen:
                    continue
                seen.add(key)
                pts_lambert.append((x, y))
                zs.append(z)
            if len(pts_lambert) < 3:
                n_skipped += 1
                continue
            z_top = max(zs)
            z_base = parcelle_center_lambert93_ground_z   # extrude from common ground

            # Build 3D points : footprint at z_base + footprint at z_top
            n = len(pts_lambert)
            base_pts = np.array([(p[0], p[1], z_base) for p in pts_lambert])
            top_pts = np.array([(p[0], p[1], z_top) for p in pts_lambert])

            # Quick-reject : if entire building behind camera, skip
            relx = (base_pts[:, 0] - eye[0])
            rely = (base_pts[:, 1] - eye[1])
            forward_x = math.cos(az_rad + math.pi)
            forward_y = math.sin(az_rad + math.pi)
            in_front = (relx * forward_x + rely * forward_y) > 0
            if not np.any(in_front):
                continue
            n_buildings += 1

            # Project both rings
            screen_base, z_base_arr = _project_world_to_screen(
                base_pts, eye, target, up, fov_deg, width, height,
            )
            screen_top, z_top_arr = _project_world_to_screen(
                top_pts, eye, target, up, fov_deg, width, height,
            )

            # Triangulate side walls : for each footprint edge → 2 triangles
            for k in range(n):
                k1 = (k + 1) % n
                # Skip triangles whose all corners are behind the camera
                if z_base_arr[k] <= 0 and z_base_arr[k1] <= 0 and z_top_arr[k] <= 0:
                    continue
                tri = np.stack([screen_base[k], screen_base[k1], screen_top[k]])
                z = (z_base_arr[k], z_base_arr[k1], z_top_arr[k])
                _rasterize_triangle(None, z_buf, tri, z, width, height)
                if z_base_arr[k1] <= 0 and z_top_arr[k1] <= 0 and z_top_arr[k] <= 0:
                    continue
                tri = np.stack([screen_base[k1], screen_top[k1], screen_top[k]])
                z = (z_base_arr[k1], z_top_arr[k1], z_top_arr[k])
                _rasterize_triangle(None, z_buf, tri, z, width, height)

            # Triangulate roof (fan from first top vertex)
            for k in range(1, n - 1):
                tri = np.stack([screen_top[0], screen_top[k], screen_top[k + 1]])
                z = (z_top_arr[0], z_top_arr[k], z_top_arr[k + 1])
                _rasterize_triangle(None, z_buf, tri, z, width, height)

    return z_buf, n_buildings, n_skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True,
                    help="ArchiClaude project UUID (matches refs/photogrammetry/<id>/)")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lng", type=float, required=True)
    ap.add_argument("--ground-z", type=float, default=57.5,
                    help="Estimated NGF z of the parcelle ground")
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--eye-dist", type=float, default=60.0)
    ap.add_argument("--eye-height", type=float, default=1.7)
    ap.add_argument("--eye-azimuth", type=float, default=-135.0)
    ap.add_argument("--fov", type=float, default=35.0)
    ap.add_argument("--view-name", type=str, default="threequarter")
    args = ap.parse_args()

    import numpy as np
    from PIL import Image
    from pyproj import Transformer

    refs = REPO_ROOT / "refs" / "photogrammetry" / args.project_id
    bdtopo_path = refs / "bdtopo_buildings.geojson"
    if not bdtopo_path.exists():
        print(f"BDTOPO not found at {bdtopo_path}", file=sys.stderr)
        sys.exit(1)
    bdtopo = json.loads(bdtopo_path.read_text(encoding="utf-8"))
    print(f"loaded {len(bdtopo.get('features', []))} BDTOPO features")

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    cx, cy = transformer.transform(args.lng, args.lat)

    z_buf, n_used, n_skip = render_depth(
        bdtopo_geojson=bdtopo,
        parcelle_center_lambert93=(cx, cy),
        parcelle_center_lambert93_ground_z=args.ground_z,
        width=args.width,
        height=args.height,
        eye_dist_m=args.eye_dist,
        eye_height_m=args.eye_height,
        eye_azimuth_deg=args.eye_azimuth,
        fov_deg=args.fov,
    )
    print(f"rasterized: {n_used} buildings used, {n_skip} skipped")

    # Normalize z-buffer to [0..1] over [close..far], with sky=1 (white)
    finite = np.isfinite(z_buf)
    if not np.any(finite):
        print("EMPTY z_buf — camera not pointing at any geometry?", file=sys.stderr)
        sys.exit(2)
    near = float(z_buf[finite].min())
    far = float(z_buf[finite].max())
    depth_norm = np.ones_like(z_buf)
    depth_norm[finite] = (z_buf[finite] - near) / max(1e-3, far - near)

    # Save 16-bit depth + 8-bit preview
    depth_u16 = (depth_norm * 65535.0).astype(np.uint16)
    depth_u8 = (depth_norm * 255.0).astype(np.uint8)

    out_depth = refs / f"depth_{args.view_name}.png"
    out_preview = refs / f"depth_{args.view_name}.preview.jpg"
    out_cam = refs / f"depth_{args.view_name}_camera.json"
    Image.fromarray(depth_u16).save(out_depth)
    Image.fromarray(depth_u8).save(out_preview, "JPEG", quality=90)

    az_rad = math.radians(args.eye_azimuth)
    cam = CameraPose(
        eye_x=cx + args.eye_dist * math.cos(az_rad),
        eye_y=cy + args.eye_dist * math.sin(az_rad),
        eye_z=args.ground_z + args.eye_height,
        target_x=cx, target_y=cy,
        target_z=args.ground_z + 8.0,
        fov_deg=args.fov,
    )
    out_cam.write_text(json.dumps({
        "view_name": args.view_name,
        "n_buildings_used": n_used,
        "n_buildings_skipped": n_skip,
        "near_z": near, "far_z": far,
        "camera": asdict(cam),
        "width": args.width, "height": args.height,
    }, indent=2), encoding="utf-8")

    print(f"depth saved : {out_depth} ({out_depth.stat().st_size // 1024} KB)")
    print(f"preview     : {out_preview}")
    print(f"camera meta : {out_cam}")


if __name__ == "__main__":
    main()
