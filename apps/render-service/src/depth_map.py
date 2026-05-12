"""Depth-map renderer for the BuildingModel — pure NumPy.

Day 2 of SP2-v2b. Inputs : BM footprint (xy polygon, world meters) + heights.
Outputs : grayscale depth map PNG (white = near, black = far) ready to feed
ControlNet-depth on Day 3.

Why no pyrender / Open3D : both require GL/Mesa backends that are painful
on macOS arm64 in 2026. NumPy z-buffer rasterisation is ~100 LoC and gives
us full control of the output range (0..1 normalised).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from PIL import Image


# ─── Types ────────────────────────────────────────────────────────────

Vec3 = tuple[float, float, float]
Coord2 = tuple[float, float]


@dataclass
class Camera:
    """Pinhole camera in world space (Y-up)."""
    position: Vec3        # camera location in world meters
    target: Vec3          # point the camera is looking at
    up: Vec3 = (0, 0, 1)  # world up = +Z (we treat z as the vertical axis to match the BM convention where building height is z)
    fov_deg: float = 45.0
    width: int = 1024
    height: int = 1024


@dataclass
class CameraPreset:
    """Named preset placing the camera relative to the building BBOX.

    Each preset specifies which side of the bbox to anchor on (east/west/
    north/south/centre) plus a distance OUTSIDE that side, plus the camera
    height z and an optional perpendicular offset to break symmetry.
    """
    name: str
    description: str
    # Anchor side : "e" / "w" / "n" / "s" / "ne" / "se" / "nw" / "sw" / "center".
    side: str
    # Distance in meters OUTSIDE the bbox edge (always positive).
    distance: float
    # Lateral offset along the bbox edge (perp to anchor) — meters.
    lateral: float = 0.0
    height_z: float = 1.7
    look_at_height: float = 8.0   # look at mid-height of building
    fov_deg: float = 45.0


PRESETS: dict[str, CameraPreset] = {
    "oiseau_iso": CameraPreset(
        name="oiseau_iso",
        description="3/4 bird's-eye SE, ~50m above + 25m back, classic archi presentation",
        side="se", distance=25.0, height_z=50.0,
        look_at_height=8.0, fov_deg=35.0,
    ),
    "rue_est_proche": CameraPreset(
        name="rue_est_proche",
        description="Street view from the east main road, eye level ~10m back",
        side="e", distance=10.0, height_z=1.7,
        look_at_height=8.0, fov_deg=55.0,
    ),
    "rue_est_eloignee": CameraPreset(
        name="rue_est_eloignee",
        description="Street view east, ~30m back — full building visible",
        side="e", distance=30.0, lateral=-5.0, height_z=1.7,
        look_at_height=8.0, fov_deg=45.0,
    ),
    "rue_sud": CameraPreset(
        name="rue_sud",
        description="Street view from the south secondary road, ~15m back",
        side="s", distance=15.0, height_z=1.7,
        look_at_height=8.0, fov_deg=50.0,
    ),
    "ensemble_recule": CameraPreset(
        name="ensemble_recule",
        description="Wide urban shot ~60m SE, full block context",
        side="se", distance=60.0, height_z=8.0,
        look_at_height=8.0, fov_deg=35.0,
    ),
    "angle_3_4": CameraPreset(
        name="angle_3_4",
        description="Classic 3/4 SE angle, ~20m, slight elevation",
        side="se", distance=20.0, height_z=10.0,
        look_at_height=8.0, fov_deg=40.0,
    ),
    "entree_zoom": CameraPreset(
        name="entree_zoom",
        description="Entrance close-up — brique tower + porte",
        side="e", distance=8.0, height_z=1.7,
        look_at_height=2.5, fov_deg=60.0,
    ),
    "rue_se_eloignee": CameraPreset(
        name="rue_se_eloignee",
        description="Elevated 3/4 view (12m) — projet POV stable iter #243/244",
        side="se", distance=40.0, height_z=12.0,
        look_at_height=8.0, fov_deg=55.0,
    ),
    "aerial_check": CameraPreset(
        name="aerial_check",
        description="Aerial oblique 22m — check X-intersection geometry",
        side="se", distance=45.0, height_z=22.0,
        look_at_height=4.0, fov_deg=60.0,
    ),
    "rue_streetview": CameraPreset(
        name="rue_streetview",
        description="Pedestrian eye-level on Rue de Plaisance ~30m NW of corner",
        side="nw", distance=30.0, height_z=1.7,
        look_at_height=6.0, fov_deg=70.0,
    ),
    "junction_pov": CameraPreset(
        name="junction_pov",
        description="Camera at the X-intersection center, looking at building (parcel at SW corner of X)",
        side="center", distance=0.0, height_z=1.7,
        look_at_height=6.0, fov_deg=70.0,
    ),
    "rue_se_proche": CameraPreset(
        name="rue_se_proche",
        description="Pedestrian eye-level SE corner ~12m — close L 3/4 view",
        side="se", distance=12.0, height_z=1.7,
        look_at_height=8.0, fov_deg=55.0,
    ),
}


def camera_from_preset(footprint: Sequence[Coord2], building_height_m: float, preset: str | CameraPreset) -> Camera:
    """Resolve a preset against the building's bbox to produce an absolute Camera.

    Camera is placed OUTSIDE the bbox at the given anchor side + distance.
    Look-at point = bbox centre, at `look_at_height` meters above ground.
    """
    if isinstance(preset, str):
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}, available : {list(PRESETS)}")
        preset = PRESETS[preset]
    xs = [p[0] for p in footprint]
    ys = [p[1] for p in footprint]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    side = preset.side.lower()
    # Anchor point on bbox edge before adding distance outwards.
    if side == "e":
        anchor_x, anchor_y = maxx, cy + preset.lateral
        out_dx, out_dy = 1.0, 0.0
    elif side == "w":
        anchor_x, anchor_y = minx, cy + preset.lateral
        out_dx, out_dy = -1.0, 0.0
    elif side == "n":
        anchor_x, anchor_y = cx + preset.lateral, maxy
        out_dx, out_dy = 0.0, 1.0
    elif side == "s":
        anchor_x, anchor_y = cx + preset.lateral, miny
        out_dx, out_dy = 0.0, -1.0
    elif side in ("ne", "en"):
        anchor_x, anchor_y = maxx, maxy
        out_dx, out_dy = 0.7071, 0.7071
    elif side in ("se", "es"):
        anchor_x, anchor_y = maxx, miny
        out_dx, out_dy = 0.7071, -0.7071
    elif side in ("nw", "wn"):
        anchor_x, anchor_y = minx, maxy
        out_dx, out_dy = -0.7071, 0.7071
    elif side in ("sw", "ws"):
        anchor_x, anchor_y = minx, miny
        out_dx, out_dy = -0.7071, -0.7071
    else:
        anchor_x, anchor_y = cx, cy
        out_dx, out_dy = 0.0, 0.0
    pos_x = anchor_x + out_dx * preset.distance
    pos_y = anchor_y + out_dy * preset.distance
    return Camera(
        position=(pos_x, pos_y, preset.height_z),
        target=(cx, cy, preset.look_at_height),
        fov_deg=preset.fov_deg,
    )


# ─── Mesh builder : extrude L-shape footprint to 3D quads ─────────────

@dataclass
class Quad:
    """One quad face with 4 vertices in world space (CCW outward)."""
    v0: Vec3
    v1: Vec3
    v2: Vec3
    v3: Vec3


def _polygon_inset(poly: Sequence[Coord2], inset_m: float) -> list[Coord2]:
    """Shrink an orthogonal polygon by `inset_m` on every side.

    For our orthogonal L-shape footprints, this is implemented by translating
    each edge inward by `inset_m` along its inward normal, then re-intersecting
    consecutive edges to recover the corner vertices.

    Falls back to a centroid-shrink for non-orthogonal shapes (less accurate
    but always produces a smaller similar polygon — good enough as a setback
    silhouette).
    """
    n = len(poly)
    if n < 3:
        return list(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n

    # Build inward-normal-translated edges
    lines: list[tuple[float, float, float, float]] = []  # (px, py, dx, dy) where (px,py) is start of shifted edge
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = (ex * ex + ey * ey) ** 0.5
        if L < 1e-9:
            continue
        # Edge direction (unit)
        ex /= L
        ey /= L
        # Right-hand normal of edge direction
        nx, ny = ey, -ex
        # Decide which normal is INWARD by checking against centroid
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if (cx - mx) * nx + (cy - my) * ny < 0:
            nx, ny = -nx, -ny  # flip
        # Translate edge endpoints by inset along inward normal
        ax2 = a[0] + nx * inset_m
        ay2 = a[1] + ny * inset_m
        bx2 = b[0] + nx * inset_m
        by2 = b[1] + ny * inset_m
        lines.append((ax2, ay2, bx2 - ax2, by2 - ay2))

    if len(lines) < 3:
        return list(poly)

    # Intersect consecutive translated edges to get the inset polygon vertices.
    out: list[Coord2] = []
    for i in range(len(lines)):
        x1, y1, dx1, dy1 = lines[i]
        x2, y2, dx2, dy2 = lines[(i + 1) % len(lines)]
        # Solve : (x1,y1) + t*(dx1,dy1) = (x2,y2) + s*(dx2,dy2)
        det = dx1 * (-dy2) - (-dx2) * dy1
        if abs(det) < 1e-9:
            # Parallel edges — fall back to translated endpoint
            out.append((x1 + dx1, y1 + dy1))
            continue
        rhs_x = x2 - x1
        rhs_y = y2 - y1
        t = (rhs_x * (-dy2) - (-dx2) * rhs_y) / det
        out.append((x1 + t * dx1, y1 + t * dy1))

    # Sanity check : ensure inset polygon doesn't self-intersect or invert.
    # If the bbox shrunk by less than inset_m, fall back to centroid-shrink.
    bx_orig = max(p[0] for p in poly) - min(p[0] for p in poly)
    bx_inset = max(p[0] for p in out) - min(p[0] for p in out)
    if bx_inset > bx_orig - 0.5 * inset_m or bx_inset < 0:
        # Fallback : centroid shrink (less accurate but always valid)
        scale = max(0.0, 1.0 - 2 * inset_m / max(bx_orig, 1.0))
        return [(cx + (p[0] - cx) * scale, cy + (p[1] - cy) * scale) for p in poly]
    return out


def _ground_plane_quads(footprint: Sequence[Coord2], extend_m: float = 100.0) -> list["Quad"]:
    """Wide ground plane that extends past the camera frustum.

    Empirical : 8m was too close (concentrated horizon line at building base),
    30m hit at mid-frame (= split horizon), 100m extends past the camera's
    field of view so no horizon edge appears in the rendered depth map.
    """
    xs = [p[0] for p in footprint]
    ys = [p[1] for p in footprint]
    minx, maxx = min(xs) - extend_m, max(xs) + extend_m
    miny, maxy = min(ys) - extend_m, max(ys) + extend_m
    return [Quad(
        v0=(minx, miny, 0.0),
        v1=(maxx, miny, 0.0),
        v2=(maxx, maxy, 0.0),
        v3=(minx, maxy, 0.0),
    )]


def extrude_footprint(
    footprint: Sequence[Coord2],
    total_height_m: float,
    *,
    rdc_height_m: float = 3.5,
    attique_inset_m: float = 1.5,
    enable_strates: bool = True,
    add_ground: bool = False,          # disabled : we use depth-fill post-process instead
) -> list[Quad]:
    """Extrude the closed footprint polygon into a stratified 3D building mesh.

    The geometry is built in three vertical zones :

        ┌─────────────┐          ← total_height_m (top of attique)
        │  attique    │             retrait of attique_inset_m
        │  (setback)  │
        ├─────────────┤          ← attique_z = total_height_m - 2.5m typical
        │  courant    │
        │             │
        ├─────────────┤          ← rdc_z = rdc_height_m (3.5m default)
        │  RDC        │
        └─────────────┘          ← ground (z=0)

    The "shoulder" between the courant and the attique is a horizontal annular
    ring that ControlNet-depth captures as a clear setback edge — solving the
    "flat L extrusion" failure mode where the model couldn't tell where the
    attique starts.

    Set `enable_strates=False` to revert to a single-zone extrusion (legacy).
    """
    n = len(footprint)
    if n < 3:
        return []
    if footprint[0] == footprint[-1]:
        footprint = footprint[:-1]
        n -= 1

    # Ground-plane prefix (sidewalk + street) so the model doesn't render the
    # building as floating in space.
    base: list[Quad] = _ground_plane_quads(footprint) if add_ground else []

    # Falls back to single-zone if the building is too short for a meaningful setback.
    attique_z = max(rdc_height_m + 1.0, total_height_m - 2.5)
    if not enable_strates or attique_z >= total_height_m - 0.5:
        return base + _extrude_simple(footprint, total_height_m)

    # Inset footprint for the attique
    setback = _polygon_inset(footprint, attique_inset_m)
    if len(setback) != n:
        # Inset failed (degenerate polygon) — fallback to single zone.
        return _extrude_simple(footprint, total_height_m)

    quads: list[Quad] = []
    # Lower walls (0 → attique_z) — full footprint
    for i in range(n):
        a = footprint[i]
        b = footprint[(i + 1) % n]
        quads.append(Quad(
            v0=(a[0], a[1], 0.0),
            v1=(b[0], b[1], 0.0),
            v2=(b[0], b[1], attique_z),
            v3=(a[0], a[1], attique_z),
        ))
    # Shoulder ring : R+(N-1) rooftop terrace, the annular slab between the
    # full footprint and the attique-inset setback at z=attique_z. Pairing
    # quads edge-by-edge fails for L-shape footprints (non-convex
    # trapezoids → broken slabs). We compute the boolean difference
    # shapely(footprint) − shapely(setback) and tessellate the result.
    try:
        from shapely.geometry import Polygon as _ShPoly
        outer_poly = _ShPoly(footprint)
        inner_poly = _ShPoly(setback)
        if not outer_poly.is_valid:
            outer_poly = outer_poly.buffer(0)
        if not inner_poly.is_valid:
            inner_poly = inner_poly.buffer(0)
        ring = outer_poly.difference(inner_poly)
        if not ring.is_empty:
            polys = [ring] if ring.geom_type == "Polygon" else list(ring.geoms)
            for poly in polys:
                if poly.geom_type != "Polygon":
                    continue
                exterior = list(poly.exterior.coords[:-1])
                if len(exterior) >= 3:
                    quads.extend(_polygon_top_quads(exterior, attique_z))
    except ImportError:
        # Fallback : edge-pair quads (works for convex polygons only).
        for i in range(n):
            a_out = footprint[i]
            b_out = footprint[(i + 1) % n]
            a_in = setback[i]
            b_in = setback[(i + 1) % n]
            quads.append(Quad(
                v0=(a_out[0], a_out[1], attique_z),
                v1=(b_out[0], b_out[1], attique_z),
                v2=(b_in[0], b_in[1], attique_z),
                v3=(a_in[0], a_in[1], attique_z),
            ))
    # Attique walls (attique_z → total_height_m) — inset footprint
    for i in range(n):
        a = setback[i]
        b = setback[(i + 1) % n]
        quads.append(Quad(
            v0=(a[0], a[1], attique_z),
            v1=(b[0], b[1], attique_z),
            v2=(b[0], b[1], total_height_m),
            v3=(a[0], a[1], total_height_m),
        ))
    # Top roof (inset polygon) — shapely triangulation works for L-shape
    # and any concave polygon (fan triangulation fails on those).
    quads.extend(_polygon_top_quads(setback, total_height_m))
    # Lower roof shoulder ring covers the strip between full footprint
    # and attique inset (already added above as a flat ring) — also add
    # the inner top so the rooftop terrace floor is closed.
    return base + quads


def _polygon_top_quads(ring: Sequence[Coord2], z: float) -> list[Quad]:
    """Tessellate a (possibly concave) polygon flat at height z.

    `shapely.ops.triangulate(poly)` triangulates the CONVEX HULL — for an
    L-shape this leaves concave gaps where centroid-filtered triangles
    were dropped, which becomes visible as a hole in the rooftop in the
    final render. We instead clip each hull-triangle back to the polygon
    via `poly.intersection`, then fan-triangulate the (convex) clipped
    pieces. This guarantees full coverage with no gaps.
    """
    try:
        from shapely.geometry import Polygon as ShPolygon
        from shapely.ops import triangulate
    except ImportError:
        return []
    poly = ShPolygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    out: list[Quad] = []
    for tri in triangulate(poly):
        clipped = poly.intersection(tri)
        if clipped.is_empty:
            continue
        pieces: list = []
        if clipped.geom_type == "Polygon":
            pieces.append(clipped)
        elif clipped.geom_type == "MultiPolygon":
            pieces.extend(list(clipped.geoms))
        else:
            continue
        for piece in pieces:
            coords = list(piece.exterior.coords[:-1])
            if len(coords) < 3:
                continue
            v0 = coords[0]
            for j in range(1, len(coords) - 1):
                a = coords[j]
                b = coords[j + 1]
                out.append(Quad(
                    v0=(v0[0], v0[1], z),
                    v1=(a[0], a[1], z),
                    v2=(b[0], b[1], z),
                    v3=(v0[0], v0[1], z),
                ))
    return out


def _extrude_simple(footprint: Sequence[Coord2], total_height_m: float) -> list[Quad]:
    """Legacy single-zone extrusion (no stratification)."""
    n = len(footprint)
    quads: list[Quad] = []
    for i in range(n):
        a = footprint[i]
        b = footprint[(i + 1) % n]
        quads.append(Quad(
            v0=(a[0], a[1], 0.0),
            v1=(b[0], b[1], 0.0),
            v2=(b[0], b[1], total_height_m),
            v3=(a[0], a[1], total_height_m),
        ))
    v0 = footprint[0]
    for i in range(1, n - 1):
        a = footprint[i]
        b = footprint[i + 1]
        quads.append(Quad(
            v0=(v0[0], v0[1], total_height_m),
            v1=(a[0], a[1], total_height_m),
            v2=(b[0], b[1], total_height_m),
            v3=(v0[0], v0[1], total_height_m),
        ))
    return quads


# ─── Camera math ──────────────────────────────────────────────────────

def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _view_matrix(cam: Camera) -> np.ndarray:
    """4x4 world→view matrix (right-handed, looks down -z in view space)."""
    eye = np.array(cam.position, dtype=np.float64)
    tgt = np.array(cam.target, dtype=np.float64)
    up = np.array(cam.up, dtype=np.float64)
    f = _normalize(tgt - eye)
    r = _normalize(np.cross(f, up))
    u = np.cross(r, f)
    m = np.eye(4)
    m[0, :3] = r
    m[1, :3] = u
    m[2, :3] = -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def _proj_matrix(cam: Camera, near: float = 0.1, far: float = 500.0) -> np.ndarray:
    """4x4 perspective projection (OpenGL-style, NDC [-1,1])."""
    aspect = cam.width / cam.height
    f = 1.0 / math.tan(math.radians(cam.fov_deg) / 2)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1
    return m


# ─── Rasterizer : scanline z-buffer ───────────────────────────────────

def _project_quads(quads: Iterable[Quad], cam: Camera) -> list[tuple[np.ndarray, np.ndarray]]:
    """For each quad, return (screen_xy [4,2], view_z [4]) clipped to NDC."""
    view = _view_matrix(cam)
    proj = _proj_matrix(cam)
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for q in quads:
        verts = np.array([q.v0, q.v1, q.v2, q.v3], dtype=np.float64)  # (4,3)
        homog = np.hstack([verts, np.ones((4, 1))])           # (4,4)
        view_h = (view @ homog.T).T                            # (4,4) -> view space
        view_z = -view_h[:, 2]                                  # +Z = away from camera
        # Skip quads entirely behind camera
        if (view_z <= 0.05).all():
            continue
        clip = (proj @ view_h.T).T                             # (4,4) clip space
        w = clip[:, 3].copy()
        # Avoid division by ~0 ; clamp clip-w to a small positive
        w[w == 0] = 1e-6
        ndc = clip[:, :3] / w[:, None]                         # (4,3) ndc xyz
        # NDC → screen
        screen = np.empty((4, 2))
        screen[:, 0] = (ndc[:, 0] * 0.5 + 0.5) * cam.width
        screen[:, 1] = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * cam.height
        out.append((screen, view_z))
    return out


def _rasterize_triangle(zbuf: np.ndarray, tri_xy: np.ndarray, tri_z: np.ndarray) -> None:
    """Rasterise one triangle into the z-buffer (depth = distance from camera).

    `zbuf` is a (H, W) float array : we keep the SMALLEST view_z (closest)
    per pixel. Initialise zbuf to +inf.
    """
    h, w = zbuf.shape
    x0, x1, x2 = tri_xy[:, 0]
    y0, y1, y2 = tri_xy[:, 1]
    z0, z1, z2 = tri_z

    minx = max(0, int(math.floor(min(x0, x1, x2))))
    maxx = min(w - 1, int(math.ceil(max(x0, x1, x2))))
    miny = max(0, int(math.floor(min(y0, y1, y2))))
    maxy = min(h - 1, int(math.ceil(max(y0, y1, y2))))
    if minx > maxx or miny > maxy:
        return

    # Edge function for inside-triangle test + barycentrics.
    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denom) < 1e-9:
        return
    ys, xs = np.mgrid[miny:maxy + 1, minx:maxx + 1]
    px = xs.astype(np.float64) + 0.5
    py = ys.astype(np.float64) + 0.5
    w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
    w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
    w2 = 1 - w0 - w1
    inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not inside.any():
        return
    z = w0 * z0 + w1 * z1 + w2 * z2
    sub = zbuf[miny:maxy + 1, minx:maxx + 1]
    mask = inside & (z < sub)
    sub[mask] = z[mask]


def render_depth_map(
    footprint: Sequence[Coord2],
    total_height_m: float,
    camera: Camera,
    voisins: list[tuple[list[Coord2], float]] | None = None,
    extra_quads: list[Quad] | None = None,
    background_quads: list[Quad] | None = None,
) -> np.ndarray:
    """Render a depth map of the extruded footprint + voisins + extra quads.

    Args :
        voisins : (footprint_local, hauteur_m) pairs for BDTopo neighbouring buildings.
        extra_quads : pre-built quads (e.g. voirie strips, ground furniture)
            added as-is without extrusion.

    Returns (H, W) float in [0, 1] where 1 = closest, 0 = farthest / sky.
    """
    main_quads = extrude_footprint(footprint, total_height_m)
    extra_all: list[Quad] = []
    if voisins:
        for v_fp, v_h in voisins:
            extra_all.extend(_extrude_simple(v_fp, v_h))
    if extra_quads:
        extra_all.extend(extra_quads)

    # Rasterize main building into its own zbuf so we can anchor the
    # normalisation on the building's z-range. Without this, a voirie strip
    # at z=0.15m or a far voisin at 90m saturates z_min/z_max and crushes
    # the building into uniform grey.
    main_zbuf = np.full((camera.height, camera.width), np.inf, dtype=np.float64)
    for screen, view_z in _project_quads(main_quads, camera):
        for idx in [(0, 1, 2), (0, 2, 3)]:
            tri_xy = screen[list(idx)]
            tri_z = view_z[list(idx)]
            _rasterize_triangle(main_zbuf, tri_xy, tri_z)
    main_finite = np.isfinite(main_zbuf)
    if not main_finite.any():
        return np.zeros((camera.height, camera.width), dtype=np.float32)
    z_min = float(main_zbuf[main_finite].min())
    z_max = float(main_zbuf[main_finite].max())

    # Final zbuf : main + extras (excluding background ground).
    zbuf = main_zbuf.copy()
    for screen, view_z in _project_quads(extra_all, camera):
        for idx in [(0, 1, 2), (0, 2, 3)]:
            tri_xy = screen[list(idx)]
            tri_z = view_z[list(idx)]
            _rasterize_triangle(zbuf, tri_xy, tri_z)
    finite = np.isfinite(zbuf)
    span_main = max(1.0, z_max - z_min)
    z_lo = z_min - span_main * 0.5
    far_extras = zbuf[finite].max() if finite.any() else z_max
    z_hi = max(z_max + span_main * 1.0, far_extras)
    span = z_hi - z_lo
    out = np.zeros_like(zbuf, dtype=np.float32)
    norm = 1.0 - ((zbuf[finite] - z_lo) / span)
    out[finite] = np.clip(norm, 0.0, 1.0)

    # Background ground : raster ONLY into pixels that are still empty AND
    # sit below the horizon line. Without the horizon clip, far ground
    # patches that project above the horizon (where they wrap into the
    # sky region of the frame) appear as oblique grey bands that FLUX
    # interprets as glass reflections / horizon stripes.
    if background_quads:
        bg_zbuf = np.full((camera.height, camera.width), np.inf, dtype=np.float64)
        for screen, view_z in _project_quads(background_quads, camera):
            for idx in [(0, 1, 2), (0, 2, 3)]:
                tri_xy = screen[list(idx)]
                tri_z = view_z[list(idx)]
                _rasterize_triangle(bg_zbuf, tri_xy, tri_z)
        bg_finite = np.isfinite(bg_zbuf)
        # Horizon line in screen Y : project a faraway ground point along
        # the camera's forward direction and use its screen Y as the cap.
        horizon_y = camera.height // 2   # safe default
        try:
            view = _view_matrix(camera)
            proj = _proj_matrix(camera)
            fwd = np.array([camera.target[0] - camera.position[0],
                            camera.target[1] - camera.position[1], 0.0])
            n = float(np.linalg.norm(fwd))
            if n > 1e-6:
                fwd = fwd / n
                far = np.array([camera.position[0] + fwd[0] * 500.0,
                                camera.position[1] + fwd[1] * 500.0,
                                0.0, 1.0])
                view_far = view @ far
                clip_far = proj @ view_far
                if clip_far[3] > 1e-6:
                    ndc_y = clip_far[1] / clip_far[3]
                    horizon_y = int((1 - ndc_y) * 0.5 * camera.height)
        except Exception:
            pass
        # 8 % vertical margin below horizon : ground patches near the
        # projected horizon line bleed into the sky region in perspective,
        # producing mottled-blue / pixelated sky artefacts. Pushing the
        # cut-off down keeps the sky pure.
        margin = int(camera.height * 0.08)
        ys = np.arange(camera.height).reshape(-1, 1).repeat(camera.width, axis=1)
        below_horizon = ys >= horizon_y + margin
        fill_mask = bg_finite & ~finite & below_horizon
        if fill_mask.any():
            bg_z = bg_zbuf[fill_mask]
            bg_lo = float(bg_z.min())
            bg_hi = float(bg_z.max())
            bg_span = max(1.0, bg_hi - bg_lo)
            # Map ground depth into [0.05, 0.35] — kept dim and far so FLUX
            # reads it as "ground extending toward horizon" (not as a second
            # building's facade as happened with [0.25, 0.55] / [0.10, 0.42]).
            ground_norm = 0.35 - 0.30 * ((bg_z - bg_lo) / bg_span)
            out[fill_mask] = ground_norm.astype(np.float32)
            finite |= fill_mask

    empty = ~finite
    out[empty] = 0.0
    return out


def depth_to_png(depth: np.ndarray, path: str) -> None:
    """Save a (H, W) depth array in [0,1] as an 8-bit grayscale PNG."""
    img8 = np.clip(depth * 255.0, 0, 255).astype(np.uint8)
    Image.fromarray(img8, mode="L").save(path, format="PNG", optimize=True)


def depth_to_pil(depth: np.ndarray) -> Image.Image:
    """Convert depth array → PIL Image (8-bit grayscale) without writing to disk."""
    img8 = np.clip(depth * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(img8, mode="L")
