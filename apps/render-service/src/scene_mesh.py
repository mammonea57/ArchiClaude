"""Scene mesh : clip building footprint to parcel + voirie strips + voisinage.

Mirrors the visual logic of `apps/frontend/src/components/plans/PlanMasse.tsx`
which renders :
  - Parcelle = real cadastral polygon
  - Building = footprint envelope CLIPPED to parcelle (the BM solver
    produces axis-aligned rects that may extend past the cadastre — we
    clip in-place to match what the plan-masse displays)
  - Voirie = 6 m-wide strip on the BM `voirie_orientations` sides
  - Pleine terre = parcelle ∖ footprint (rendered as ground, depth = 0)

The output Quads are appended to the building mesh + BDTopo voisins so the
depth map fed to FLUX matches the real urban implantation.
"""
from __future__ import annotations

from typing import Sequence

from shapely.geometry import LineString as ShLineString
from shapely.geometry import MultiPolygon as ShMultiPolygon
from shapely.geometry import Polygon as ShPolygon
from shapely.geometry import box as sh_box

from .depth_map import Coord2, Quad, _extrude_simple


def far_ground_quad(
    parcelle: Sequence[Coord2],
    radius_m: float = 120.0,
    elevation_m: float = 0.0,
    *,
    patch_size_m: float = 6.0,
    jitter_m: float = 0.02,
    camera_pos_xy: tuple[float, float] | None = None,
    camera_target_xy: tuple[float, float] | None = None,
) -> list[Quad]:
    """Tiled ground plane centred on the parcelle, extending `radius_m`.

    Without ground here, depth pixels around the building are empty and
    FLUX hallucinates a panoramic horizon. With a SINGLE flat quad, FLUX
    reads the uniform plane as a glassy water surface and paints sky
    reflections. We tile the ground in `patch_size_m` patches with a
    deterministic micro-jitter so the depth has texture (FLUX reads it
    as "rough ground" instead of "mirror water").
    """
    if not parcelle:
        return []
    cx = sum(p[0] for p in parcelle) / len(parcelle)
    cy = sum(p[1] for p in parcelle) / len(parcelle)
    quads: list[Quad] = []
    has_camera = camera_pos_xy is not None and camera_target_xy is not None
    if not has_camera:
        ring = [(cx - radius_m, cy - radius_m), (cx + radius_m, cy - radius_m),
                (cx + radius_m, cy + radius_m), (cx - radius_m, cy + radius_m)]
        quads.append(Quad(
            v0=(ring[0][0], ring[0][1], elevation_m),
            v1=(ring[1][0], ring[1][1], elevation_m),
            v2=(ring[2][0], ring[2][1], elevation_m),
            v3=(ring[3][0], ring[3][1], elevation_m),
        ))
        return quads
    fx = camera_target_xy[0] - camera_pos_xy[0]
    fy = camera_target_xy[1] - camera_pos_xy[1]
    fL = (fx * fx + fy * fy) ** 0.5
    if fL < 1e-6:
        return []
    fx, fy = fx / fL, fy / fL
    rx, ry = fy, -fx
    half_w = radius_m

    def _quad_at(start_d: float, end_d: float) -> Quad:
        s_pt = (camera_pos_xy[0] + fx * start_d, camera_pos_xy[1] + fy * start_d)
        e_pt = (camera_pos_xy[0] + fx * end_d, camera_pos_xy[1] + fy * end_d)
        return Quad(
            v0=(s_pt[0] - rx * half_w, s_pt[1] - ry * half_w, elevation_m),
            v1=(s_pt[0] + rx * half_w, s_pt[1] + ry * half_w, elevation_m),
            v2=(e_pt[0] + rx * half_w, e_pt[1] + ry * half_w, elevation_m),
            v3=(e_pt[0] - rx * half_w, e_pt[1] - ry * half_w, elevation_m),
        )

    # SPLIT ground in two parts to skip the building zone (~fL ± 15 m).
    near_end = max(2.5, fL - 15.0)
    quads.append(_quad_at(2.0, near_end))
    quads.append(_quad_at(fL + 15.0, fL + 15.0 + radius_m))
    return quads


def pleine_terre_quads(
    parcelle: Sequence[Coord2],
    footprint: Sequence[Coord2],
    elevation_m: float = 0.05,
) -> list[Quad]:
    """Triangulate parcelle ∖ footprint as a flat ground slab.

    The slab sits at z=elevation_m so it's distinguishable from voirie
    (z=0.15m curb) in the depth map but still reads as ground level. This
    gives FLUX a clear horizontal surface to render as garden / pleine
    terre instead of leaving the parcel side empty (sky in depth).
    """
    parc = ShPolygon(_dedupe(parcelle))
    fp = ShPolygon(_dedupe(footprint))
    if not parc.is_valid:
        parc = parc.buffer(0)
    if not fp.is_valid:
        fp = fp.buffer(0)
    diff = parc.difference(fp)
    if diff.is_empty:
        return []
    polys: list[ShPolygon] = []
    if diff.geom_type == "Polygon":
        polys.append(diff)
    elif diff.geom_type == "MultiPolygon":
        polys.extend(list(diff.geoms))
    quads: list[Quad] = []
    for poly in polys:
        ring = list(poly.exterior.coords[:-1])
        if len(ring) < 3:
            continue
        # Fan triangulation from ring[0]. Each "triangle" is encoded as a
        # degenerate Quad (v3 == v0) so the rasterizer handles it via its
        # split-quad-into-2-triangles code path.
        v0 = ring[0]
        for i in range(1, len(ring) - 1):
            a = ring[i]
            b = ring[i + 1]
            quads.append(Quad(
                v0=(v0[0], v0[1], elevation_m),
                v1=(a[0], a[1], elevation_m),
                v2=(b[0], b[1], elevation_m),
                v3=(v0[0], v0[1], elevation_m),
            ))
    return quads


def rdc_bandeau_quads(
    footprint: Sequence[Coord2],
    *,
    hauteur_rdc_m: float = 3.2,
    bandeau_height_m: float = 0.3,
    bandeau_protrusion_m: float = 0.35,
) -> list[Quad]:
    """Continuous horizontal cornice band on top of the RDC, all around the
    building. The protruding lip clearly marks the boundary between the
    massive solid ground floor and the upper floors with their balconies,
    so FLUX cannot read the R+1 balcony underside as a covered walkway
    with pedestrians under it.
    """
    fp = _dedupe(footprint)
    n = len(fp)
    if n < 3:
        return []
    quads: list[Quad] = []
    for i in range(n):
        a = fp[i]
        b = fp[(i + 1) % n]
        ex = b[0] - a[0]
        ey = b[1] - a[1]
        L = (ex * ex + ey * ey) ** 0.5
        if L < 0.5:
            continue
        nx = ey / L      # outward normal (CCW)
        ny = -ex / L
        a_out = (a[0] + nx * bandeau_protrusion_m, a[1] + ny * bandeau_protrusion_m)
        b_out = (b[0] + nx * bandeau_protrusion_m, b[1] + ny * bandeau_protrusion_m)
        z_top = hauteur_rdc_m
        z_bot = z_top - bandeau_height_m
        # Top of bandeau (visible from above)
        quads.append(Quad(
            v0=(a[0], a[1], z_top),
            v1=(b[0], b[1], z_top),
            v2=(b_out[0], b_out[1], z_top),
            v3=(a_out[0], a_out[1], z_top),
        ))
        # Bottom of bandeau
        quads.append(Quad(
            v0=(a[0], a[1], z_bot),
            v1=(a_out[0], a_out[1], z_bot),
            v2=(b_out[0], b_out[1], z_bot),
            v3=(b[0], b[1], z_bot),
        ))
        # Outer face (the visible horizontal lip)
        quads.append(Quad(
            v0=(a_out[0], a_out[1], z_bot),
            v1=(b_out[0], b_out[1], z_bot),
            v2=(b_out[0], b_out[1], z_top),
            v3=(a_out[0], a_out[1], z_top),
        ))
    return quads


def rdc_windows_quads(
    footprint: Sequence[Coord2],
    voirie_sides: list[str],
    *,
    hauteur_rdc_m: float = 3.2,
    window_width_m: float = 1.2,
    window_height_m: float = 1.6,
    window_pitch_m: float = 3.0,
    sill_height_m: float = 0.9,
    recess_depth_m: float = 0.25,
) -> list[Quad]:
    """Recessed (depth-sunken) RDC windows on every voirie facade.

    Without these, FLUX sees an unbroken 3 m of plain wall at ground level
    and often reads it as a sunken parking ramp / basement entrance,
    painting cars/people "under" the building. Punched windows tell FLUX
    "this is a residential facade", same as the upper floors.
    """
    if not footprint or not voirie_sides:
        return []
    fp = _dedupe(footprint)
    n = len(fp)
    if n < 3:
        return []
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    quads: list[Quad] = []
    for side in voirie_sides:
        s = side.lower()
        for i in range(n):
            a = fp[i]
            b = fp[(i + 1) % n]
            ex = b[0] - a[0]
            ey = b[1] - a[1]
            length = (ex * ex + ey * ey) ** 0.5
            if length < window_width_m + 1.0:
                continue
            horizontal = abs(ex) > abs(ey)
            mx = (a[0] + b[0]) / 2
            my = (a[1] + b[1]) / 2
            keep = (
                (s in ("sud", "south", "s") and horizontal and (my - miny) < 2.0)
                or (s in ("nord", "north", "n") and horizontal and (maxy - my) < 2.0)
                or (s in ("est", "east", "e") and not horizontal and (maxx - mx) < 2.0)
                or (s in ("ouest", "west", "w") and not horizontal and (mx - minx) < 2.0)
            )
            if not keep:
                continue
            tx = ex / length
            ty = ey / length
            nx = ey / length
            ny = -ex / length
            if s in ("sud", "south", "s") and ny > 0:
                nx, ny = -nx, -ny
            elif s in ("nord", "north", "n") and ny < 0:
                nx, ny = -nx, -ny
            elif s in ("est", "east", "e") and nx < 0:
                nx, ny = -nx, -ny
            elif s in ("ouest", "west", "w") and nx > 0:
                nx, ny = -nx, -ny

            n_windows = max(1, int(length // window_pitch_m))
            for k in range(n_windows):
                t_centre = (k + 0.5) / n_windows
                cx = a[0] + t_centre * ex
                cy = a[1] + t_centre * ey
                # Window rectangle on the facade — recessed by recess_depth_m.
                half_w = window_width_m / 2
                p_left = (cx - tx * half_w, cy - ty * half_w)
                p_right = (cx + tx * half_w, cy + ty * half_w)
                # The recessed window is a small rectangle pulled INTO the
                # facade — a vertical face at facade-recess_depth, framed
                # by visible jambs (the surrounding wall).
                p_left_in = (p_left[0] - nx * recess_depth_m, p_left[1] - ny * recess_depth_m)
                p_right_in = (p_right[0] - nx * recess_depth_m, p_right[1] - ny * recess_depth_m)
                z_top = sill_height_m + window_height_m
                # Window inner face
                quads.append(Quad(
                    v0=(p_left_in[0], p_left_in[1], sill_height_m),
                    v1=(p_right_in[0], p_right_in[1], sill_height_m),
                    v2=(p_right_in[0], p_right_in[1], z_top),
                    v3=(p_left_in[0], p_left_in[1], z_top),
                ))
                # Top reveal (lintel)
                quads.append(Quad(
                    v0=(p_left[0], p_left[1], z_top),
                    v1=(p_right[0], p_right[1], z_top),
                    v2=(p_right_in[0], p_right_in[1], z_top),
                    v3=(p_left_in[0], p_left_in[1], z_top),
                ))
                # Bottom reveal (sill)
                quads.append(Quad(
                    v0=(p_left[0], p_left[1], sill_height_m),
                    v1=(p_left_in[0], p_left_in[1], sill_height_m),
                    v2=(p_right_in[0], p_right_in[1], sill_height_m),
                    v3=(p_right[0], p_right[1], sill_height_m),
                ))
    return quads


def parked_cars_quads(
    parcelle: Sequence[Coord2],
    voirie_sides: list[str],
    *,
    car_length_m: float = 4.4,
    car_width_m: float = 1.8,
    car_height_m: float = 1.4,
    spacing_m: float = 1.0,
    inset_m: float = 0.6,
) -> list[Quad]:
    """Stationnement parallèle de quelques voitures le long du kerb.

    Place des cuboïdes à dimensions automobile (4.4 × 1.8 × 1.4 m) sur la
    chaussée, parallèles au trottoir, avec un retrait `inset_m` de 0,6 m
    par rapport à la limite parcelle. FLUX rend ces volumes comme de
    vraies voitures stationnées (pas comme des plots de parking). Les
    voitures cassent aussi le pattern "parking lot" en remplaçant les
    places vides par des véhicules réels.
    """
    if not parcelle or not voirie_sides:
        return []
    xs = [p[0] for p in parcelle]
    ys = [p[1] for p in parcelle]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    quads: list[Quad] = []
    for side in voirie_sides:
        s = side.lower()
        if s in ("sud", "south", "s"):
            length = maxx - minx
            n_cars = max(1, int((length - 1.0) // (car_length_m + spacing_m)))
            for k in range(n_cars):
                cx = minx + 1.0 + k * (car_length_m + spacing_m) + car_length_m / 2
                cy = miny - inset_m - car_width_m / 2 - 1.5    # 1.5 m past kerb (on chaussée)
                ring = [(cx - car_length_m / 2, cy - car_width_m / 2),
                        (cx + car_length_m / 2, cy - car_width_m / 2),
                        (cx + car_length_m / 2, cy + car_width_m / 2),
                        (cx - car_length_m / 2, cy + car_width_m / 2)]
                quads.extend(_extrude_simple(ring, car_height_m))
        elif s in ("est", "east", "e"):
            length = maxy - miny
            n_cars = max(1, int((length - 1.0) // (car_length_m + spacing_m)))
            for k in range(n_cars):
                cy = miny + 1.0 + k * (car_length_m + spacing_m) + car_length_m / 2
                cx = maxx + inset_m + car_width_m / 2 + 1.5
                ring = [(cx - car_width_m / 2, cy - car_length_m / 2),
                        (cx + car_width_m / 2, cy - car_length_m / 2),
                        (cx + car_width_m / 2, cy + car_length_m / 2),
                        (cx - car_width_m / 2, cy + car_length_m / 2)]
                quads.extend(_extrude_simple(ring, car_height_m))
    return quads


def lampposts_quads(
    parcelle: Sequence[Coord2],
    voirie_sides: list[str],
    *,
    spacing_m: float = 12.0,
    height_m: float = 4.5,
    radius_m: float = 0.08,
    sidewalk_offset_m: float = 1.5,
) -> list[Quad]:
    """Vertical thin posts on the sidewalk to act as Parisian-style lampposts.

    A regular grid of slim vertical cylinders (rendered as octagonal prisms
    for cheap depth meshing) along the kerb edge of each voirie side.
    FLUX paints them as real lampposts thanks to the prompt cue. They
    add vertical rhythm to the foreground that signals "real street",
    not "empty parking lot".
    """
    if not parcelle or not voirie_sides:
        return []
    xs = [p[0] for p in parcelle]
    ys = [p[1] for p in parcelle]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    def _post_quads(cx: float, cy: float) -> list[Quad]:
        # Octagonal prism approx of a thin pole
        out: list[Quad] = []
        ring = []
        for k in range(8):
            theta = k * 2 * 3.14159265 / 8
            ring.append((cx + radius_m * (1 if k % 2 else 0.92) * (1 if theta < 3.14 else -1) * 0.5,
                         cy + radius_m * 0.5))
        # Simpler : square prism
        ring = [(cx - radius_m, cy - radius_m),
                (cx + radius_m, cy - radius_m),
                (cx + radius_m, cy + radius_m),
                (cx - radius_m, cy + radius_m)]
        out.extend(_extrude_simple(ring, height_m))
        return out

    quads: list[Quad] = []
    for side in voirie_sides:
        s = side.lower()
        if s in ("sud", "south", "s"):
            length = maxx - minx
            n_posts = max(1, int(length // spacing_m))
            for k in range(n_posts):
                t = (k + 0.5) / n_posts
                cx = minx + t * length
                cy = miny - sidewalk_offset_m
                quads.extend(_post_quads(cx, cy))
        elif s in ("est", "east", "e"):
            length = maxy - miny
            n_posts = max(1, int(length // spacing_m))
            for k in range(n_posts):
                t = (k + 0.5) / n_posts
                cy = miny + t * length
                cx = maxx + sidewalk_offset_m
                quads.extend(_post_quads(cx, cy))
    return quads


def entrance_canopy_quad(
    footprint: Sequence[Coord2],
    voirie_sides: list[str],
    *,
    canopy_width_m: float = 1.6,
    canopy_depth_m: float = 1.0,
    canopy_z_top_m: float = 3.4,
    canopy_z_base_m: float = 3.0,
) -> list[Quad]:
    """Small canopy slab marking the building's main entrance.

    Without an entrance feature in the depth, FLUX places the door
    randomly or omits it. We place a small horizontal canopy on the
    primary voirie facade, at the midpoint, jutting out 1 m. This is
    a strong depth cue that "the door is here".
    """
    if not voirie_sides or not footprint:
        return []
    fp = _dedupe(footprint)
    n = len(fp)
    if n < 3:
        return []
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    primary = voirie_sides[0].lower()
    if primary in ("sud", "south", "s"):
        cx = (minx + maxx) / 2
        # Find the actual y of the south facade at cx
        y0 = miny
        a = (cx - canopy_width_m / 2, y0)
        b = (cx + canopy_width_m / 2, y0)
        nx, ny = 0.0, -1.0
    elif primary in ("nord", "north", "n"):
        cx = (minx + maxx) / 2
        y0 = maxy
        a = (cx - canopy_width_m / 2, y0)
        b = (cx + canopy_width_m / 2, y0)
        nx, ny = 0.0, 1.0
    elif primary in ("est", "east", "e"):
        cy = (miny + maxy) / 2
        x0 = maxx
        a = (x0, cy - canopy_width_m / 2)
        b = (x0, cy + canopy_width_m / 2)
        nx, ny = 1.0, 0.0
    elif primary in ("ouest", "west", "w"):
        cy = (miny + maxy) / 2
        x0 = minx
        a = (x0, cy - canopy_width_m / 2)
        b = (x0, cy + canopy_width_m / 2)
        nx, ny = -1.0, 0.0
    else:
        return []
    a_out = (a[0] + nx * canopy_depth_m, a[1] + ny * canopy_depth_m)
    b_out = (b[0] + nx * canopy_depth_m, b[1] + ny * canopy_depth_m)
    out: list[Quad] = []
    # Top of canopy
    out.append(Quad(
        v0=(a[0], a[1], canopy_z_top_m),
        v1=(b[0], b[1], canopy_z_top_m),
        v2=(b_out[0], b_out[1], canopy_z_top_m),
        v3=(a_out[0], a_out[1], canopy_z_top_m),
    ))
    # Bottom of canopy
    out.append(Quad(
        v0=(a[0], a[1], canopy_z_base_m),
        v1=(a_out[0], a_out[1], canopy_z_base_m),
        v2=(b_out[0], b_out[1], canopy_z_base_m),
        v3=(b[0], b[1], canopy_z_base_m),
    ))
    # Front edge
    out.append(Quad(
        v0=(a_out[0], a_out[1], canopy_z_base_m),
        v1=(b_out[0], b_out[1], canopy_z_base_m),
        v2=(b_out[0], b_out[1], canopy_z_top_m),
        v3=(a_out[0], a_out[1], canopy_z_top_m),
    ))
    return out


def rooftop_terrace_quads(
    inset_footprint: Sequence[Coord2],
    roof_z: float,
    *,
    garde_corps_height_m: float = 1.1,
    planter_pitch_m: float = 4.0,
    planter_width_m: float = 1.4,
    planter_depth_m: float = 0.9,
    planter_height_m: float = 0.7,
    pergola_height_m: float = 2.6,
) -> list[Quad]:
    """Furniture for the rooftop attique terrace : garde-corps + planters + pergola.

    Without these, the roof is a flat blank slab and FLUX renders it as
    a featureless white roof. The relief reads as a usable rooftop garden.
    """
    fp = _dedupe(inset_footprint)
    n = len(fp)
    if n < 3:
        return []
    quads: list[Quad] = []

    # Garde-corps : thin perimeter wall on every roof edge.
    for i in range(n):
        a = fp[i]
        b = fp[(i + 1) % n]
        ex = b[0] - a[0]
        ey = b[1] - a[1]
        L = (ex * ex + ey * ey) ** 0.5
        if L < 0.5:
            continue
        nx = ey / L      # outward normal (CCW footprint)
        ny = -ex / L
        d = 0.05         # 10cm-thick rail volume
        for sign in (-1.0, +1.0):
            ox = nx * d * sign
            oy = ny * d * sign
            quads.append(Quad(
                v0=(a[0] + ox, a[1] + oy, roof_z),
                v1=(b[0] + ox, b[1] + oy, roof_z),
                v2=(b[0] + ox, b[1] + oy, roof_z + garde_corps_height_m),
                v3=(a[0] + ox, a[1] + oy, roof_z + garde_corps_height_m),
            ))

    # Planters : extruded boxes around the perimeter, every planter_pitch_m.
    for i in range(n):
        a = fp[i]
        b = fp[(i + 1) % n]
        ex = b[0] - a[0]
        ey = b[1] - a[1]
        L = (ex * ex + ey * ey) ** 0.5
        if L < planter_pitch_m + planter_width_m:
            continue
        tx = ex / L
        ty = ey / L
        nx = ey / L      # outward
        ny = -ex / L
        # Place planters offset INWARD by planter_depth_m so they sit on the roof.
        n_planters = max(1, int(L // planter_pitch_m))
        for k in range(n_planters):
            t = (k + 0.5) / n_planters
            cx_ = a[0] + t * ex
            cy_ = a[1] + t * ey
            # Centre 1.0m inside the edge
            inset = 1.0
            ix = cx_ - nx * inset
            iy = cy_ - ny * inset
            # Rectangle aligned with edge tangent.
            half_w = planter_width_m / 2
            half_d = planter_depth_m / 2
            corners = [
                (ix - tx * half_w - nx * half_d, iy - ty * half_w - ny * half_d),
                (ix + tx * half_w - nx * half_d, iy + ty * half_w - ny * half_d),
                (ix + tx * half_w + nx * half_d, iy + ty * half_w + ny * half_d),
                (ix - tx * half_w + nx * half_d, iy - ty * half_w + ny * half_d),
            ]
            quads.extend(_extrude_simple(corners, planter_height_m))
            # Translate Z so planter sits on the roof.
            for q in quads[-len(_extrude_simple(corners, planter_height_m)):]:
                pass  # _extrude_simple uses z=0 base — adjust below
            # We need them on the roof — rebuild with offset:
            quads = quads[:-len(_extrude_simple(corners, planter_height_m))]
            # Use raw quads at z_roof:
            for j in range(4):
                a2 = corners[j]
                b2 = corners[(j + 1) % 4]
                quads.append(Quad(
                    v0=(a2[0], a2[1], roof_z),
                    v1=(b2[0], b2[1], roof_z),
                    v2=(b2[0], b2[1], roof_z + planter_height_m),
                    v3=(a2[0], a2[1], roof_z + planter_height_m),
                ))
            # Top of planter (foliage indicator).
            quads.append(Quad(
                v0=(corners[0][0], corners[0][1], roof_z + planter_height_m),
                v1=(corners[1][0], corners[1][1], roof_z + planter_height_m),
                v2=(corners[2][0], corners[2][1], roof_z + planter_height_m),
                v3=(corners[3][0], corners[3][1], roof_z + planter_height_m),
            ))

    # Central pergola : a single elevated horizontal slab in the middle of
    # the roof, on 4 thin posts.
    cx = sum(p[0] for p in fp) / n
    cy = sum(p[1] for p in fp) / n
    half = 2.5
    pergola_corners = [
        (cx - half, cy - half), (cx + half, cy - half),
        (cx + half, cy + half), (cx - half, cy + half),
    ]
    # Thin posts
    for px, py in pergola_corners:
        post = [(px - 0.1, py - 0.1), (px + 0.1, py - 0.1),
                (px + 0.1, py + 0.1), (px - 0.1, py + 0.1)]
        for j in range(4):
            a2 = post[j]
            b2 = post[(j + 1) % 4]
            quads.append(Quad(
                v0=(a2[0], a2[1], roof_z),
                v1=(b2[0], b2[1], roof_z),
                v2=(b2[0], b2[1], roof_z + pergola_height_m),
                v3=(a2[0], a2[1], roof_z + pergola_height_m),
            ))
    # Pergola top slab
    quads.append(Quad(
        v0=(pergola_corners[0][0], pergola_corners[0][1], roof_z + pergola_height_m),
        v1=(pergola_corners[1][0], pergola_corners[1][1], roof_z + pergola_height_m),
        v2=(pergola_corners[2][0], pergola_corners[2][1], roof_z + pergola_height_m),
        v3=(pergola_corners[3][0], pergola_corners[3][1], roof_z + pergola_height_m),
    ))
    return quads


def jardins_rdc_quads(
    footprint: Sequence[Coord2],
    voirie_sides: list[str],
    *,
    apartment_pitch_m: float = 6.0,
    garden_depth_m: float = 3.0,
    partition_height_m: float = 1.8,
    add_trees: bool = False,
) -> list[Quad]:
    """Privacy partitions between RDC private gardens along voirie facades.

    Each apartment at ground level has its own private garden between the
    facade and the parcel boundary. We extrude vertical solid panels every
    `apartment_pitch_m` perpendicular to the facade, from z=0 up to
    `partition_height_m` (typical haie or wooden trellis), so that each
    garden reads as a separate enclosed space in the depth map.
    """
    if not footprint or not voirie_sides:
        return []
    fp = _dedupe(footprint)
    n = len(fp)
    if n < 3:
        return []
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    quads: list[Quad] = []
    for side in voirie_sides:
        s = side.lower()
        TOL = 2.0
        edges: list[tuple[Coord2, Coord2]] = []
        for i in range(n):
            a = fp[i]
            b = fp[(i + 1) % n]
            mx = (a[0] + b[0]) / 2
            my = (a[1] + b[1]) / 2
            ex = b[0] - a[0]
            ey = b[1] - a[1]
            length = (ex * ex + ey * ey) ** 0.5
            if length < 0.5:
                continue
            horizontal = abs(ex) > abs(ey)
            keep = (
                (s in ("sud", "south", "s") and horizontal and (my - miny) < TOL)
                or (s in ("nord", "north", "n") and horizontal and (maxy - my) < TOL)
                or (s in ("est", "east", "e") and not horizontal and (maxx - mx) < TOL)
                or (s in ("ouest", "west", "w") and not horizontal and (mx - minx) < TOL)
            )
            if keep:
                edges.append((a, b))

        for a, b in edges:
            ex = b[0] - a[0]
            ey = b[1] - a[1]
            length = (ex * ex + ey * ey) ** 0.5
            if length < 0.5:
                continue
            nx = ey / length
            ny = -ex / length
            if s in ("sud", "south", "s") and ny > 0:
                nx, ny = -nx, -ny
            elif s in ("nord", "north", "n") and ny < 0:
                nx, ny = -nx, -ny
            elif s in ("est", "east", "e") and nx < 0:
                nx, ny = -nx, -ny
            elif s in ("ouest", "west", "w") and nx > 0:
                nx, ny = -nx, -ny

            if length <= apartment_pitch_m:
                continue
            n_part = int(length // apartment_pitch_m)
            for k in range(1, n_part + 1):
                t = k / (n_part + 1)
                ix = a[0] + t * (b[0] - a[0])
                iy = a[1] + t * (b[1] - a[1])
                ox = ix + nx * garden_depth_m
                oy = iy + ny * garden_depth_m
                # Vertical hedge slab from facade outward into the garden.
                # 0.2 m thick volume so it reads in depth.
                d_thick = 0.1
                # Perpendicular to garden axis : same as edge tangent (tx, ty).
                tx = ex / length
                ty = ey / length
                for sign in (-1.0, +1.0):
                    px = tx * d_thick * sign
                    py = ty * d_thick * sign
                    quads.append(Quad(
                        v0=(ix + px, iy + py, 0.0),
                        v1=(ox + px, oy + py, 0.0),
                        v2=(ox + px, oy + py, partition_height_m),
                        v3=(ix + px, iy + py, partition_height_m),
                    ))
            # Add ornamental trees in the garden between cloisons. Each tree
            # is a 1.5 m × 1.5 m × 4 m volume (trunk + canopy mass) — enough
            # to read in depth as a "tree volume" between the bahut and
            # the building, breaking the flat front-garden look.
            if add_trees:
                n_trees = max(1, int(length // (apartment_pitch_m * 1.2)))
                tree_h = 4.0
                tree_half = 0.7
                for k in range(n_trees):
                    t = (k + 0.7) / max(1, n_trees)
                    cx_t = a[0] + t * ex
                    cy_t = a[1] + t * ey
                    # Centre of tree : 1.5 m inside (toward the building)
                    inset = 1.5
                    cxn = cx_t + nx * inset
                    cyn = cy_t + ny * inset
                    tree_corners = [
                        (cxn - tree_half, cyn - tree_half),
                        (cxn + tree_half, cyn - tree_half),
                        (cxn + tree_half, cyn + tree_half),
                        (cxn - tree_half, cyn + tree_half),
                    ]
                    for j in range(4):
                        a2 = tree_corners[j]
                        b2 = tree_corners[(j + 1) % 4]
                        quads.append(Quad(
                            v0=(a2[0], a2[1], 0.0),
                            v1=(b2[0], b2[1], 0.0),
                            v2=(b2[0], b2[1], tree_h),
                            v3=(a2[0], a2[1], tree_h),
                        ))
    return quads


def balcons_filants_quads(
    footprint: Sequence[Coord2],
    voirie_sides: list[str],
    *,
    niveaux: int,
    hauteur_rdc_m: float = 3.5,
    hauteur_etage_m: float = 2.7,
    depth_m: float = 1.6,
    slab_thickness_m: float = 0.18,
    railing_height_m: float = 1.0,
    apartment_pitch_m: float = 6.0,   # privacy partition every ~6 m
    partition_height_m: float = 1.4,
) -> list[Quad]:
    """Filant balconies along each voirie side at every floor above RDC.

    Mirrors `BalconsJardinsLayer.tsx` (frontend) : each storey above the
    RDC and below the attique gets a continuous balcony slab on every
    voirie-facing facade, plus a metal railing extruded above the slab.

    The geometry is purely a horizontal protrusion + a thin vertical
    railing — it gives FLUX the silhouette of "balcons à chaque étage"
    so the rendered facade no longer drops the railings on most floors.
    """
    if niveaux <= 1 or not voirie_sides:
        return []

    fp = _dedupe(footprint)
    n = len(fp)
    if n < 3:
        return []

    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    quads: list[Quad] = []

    # Balconies on every storey above RDC (R+1 to R+(N-2), skip attique).
    # The R+1 balcony is rendered with a SHALLOW depth (0.3 m, juliette-like)
    # while higher floors get the full depth_m saillant — this prevents the
    # overhang above the sidewalk that FLUX read as a "parking under the
    # building".
    floor_levels = []
    z_cur = hauteur_rdc_m
    for floor_idx in range(1, niveaux - 1):
        floor_levels.append(z_cur)
        z_cur += hauteur_etage_m
    # R+1 gets a shorter balcony (0.9 m, visible but not overhanging) and
    # all higher floors get the full depth_m. This gives every floor a
    # clearly visible balcony band while keeping the foreground readable.
    floor_depths = [0.9 if i == 0 else depth_m for i in range(len(floor_levels))]

    for side in voirie_sides:
        s = side.lower()
        # Collect facade edges that face the side. We test :
        #   1. edge midpoint within TOL of the bbox boundary, AND
        #   2. edge orientation roughly parallel to that boundary
        # to handle clipped footprints whose post-clip edges may sit a few
        # metres inside (re-entrant corner) but still face the right way.
        TOL = 2.0
        edges: list[tuple[Coord2, Coord2]] = []
        for i in range(n):
            a = fp[i]
            b = fp[(i + 1) % n]
            mx = (a[0] + b[0]) / 2
            my = (a[1] + b[1]) / 2
            ex = b[0] - a[0]
            ey = b[1] - a[1]
            length = (ex * ex + ey * ey) ** 0.5
            if length < 0.5:
                continue
            horizontal = abs(ex) > abs(ey)   # mostly along x → faces N or S
            if s in ("sud", "south", "s") and horizontal and (my - miny) < TOL:
                edges.append((a, b))
            elif s in ("nord", "north", "n") and horizontal and (maxy - my) < TOL:
                edges.append((a, b))
            elif s in ("est", "east", "e") and not horizontal and (maxx - mx) < TOL:
                edges.append((a, b))
            elif s in ("ouest", "west", "w") and not horizontal and (mx - minx) < TOL:
                edges.append((a, b))

        for a, b in edges:
            # Outward normal of edge (a→b), pointing AWAY from building.
            ex = b[0] - a[0]
            ey = b[1] - a[1]
            length = (ex * ex + ey * ey) ** 0.5
            if length < 0.5:
                continue
            # Normal = rotate edge -90° (right of travel direction).
            # The footprint is CCW so right-of-travel is OUTWARD.
            nx = ey / length
            ny = -ex / length
            # Sanity check : outward normal should point toward the side.
            mid_x = (a[0] + b[0]) / 2
            mid_y = (a[1] + b[1]) / 2
            if s in ("sud", "south", "s") and ny > 0:
                nx, ny = -nx, -ny
            elif s in ("nord", "north", "n") and ny < 0:
                nx, ny = -nx, -ny
            elif s in ("est", "east", "e") and nx < 0:
                nx, ny = -nx, -ny
            elif s in ("ouest", "west", "w") and nx > 0:
                nx, ny = -nx, -ny

            tx = (b[0] - a[0]) / length
            ty = (b[1] - a[1]) / length
            a_orig = a
            b_orig = b

            for floor_idx, z_floor in enumerate(floor_levels):
                d = floor_depths[floor_idx]
                # Per-floor outer edge (depth d, possibly shallow at R+1).
                a_out = (a_orig[0] + nx * d, a_orig[1] + ny * d)
                b_out = (b_orig[0] + nx * d, b_orig[1] + ny * d)
                # Extend along edge tangent for corner continuity (only for
                # full-depth balconies, not the juliette R+1).
                ext = d
                a_e = (a_orig[0] - tx * ext, a_orig[1] - ty * ext)
                b_e = (b_orig[0] + tx * ext, b_orig[1] + ty * ext)
                a_out_e = (a_out[0] - tx * ext, a_out[1] - ty * ext)
                b_out_e = (b_out[0] + tx * ext, b_out[1] + ty * ext)

                z_top = z_floor + slab_thickness_m
                # Slab top
                quads.append(Quad(
                    v0=(a_e[0], a_e[1], z_top),
                    v1=(b_e[0], b_e[1], z_top),
                    v2=(b_out_e[0], b_out_e[1], z_top),
                    v3=(a_out_e[0], a_out_e[1], z_top),
                ))
                # Slab bottom
                quads.append(Quad(
                    v0=(a_e[0], a_e[1], z_floor),
                    v1=(a_out_e[0], a_out_e[1], z_floor),
                    v2=(b_out_e[0], b_out_e[1], z_floor),
                    v3=(b_e[0], b_e[1], z_floor),
                ))
                # Slab front face
                quads.append(Quad(
                    v0=(a_out_e[0], a_out_e[1], z_floor),
                    v1=(b_out_e[0], b_out_e[1], z_floor),
                    v2=(b_out_e[0], b_out_e[1], z_top),
                    v3=(a_out_e[0], a_out_e[1], z_top),
                ))
                # Railing
                z_rail = z_top + railing_height_m
                quads.append(Quad(
                    v0=(a_out_e[0], a_out_e[1], z_top),
                    v1=(b_out_e[0], b_out_e[1], z_top),
                    v2=(b_out_e[0], b_out_e[1], z_rail),
                    v3=(a_out_e[0], a_out_e[1], z_rail),
                ))
                # Apartment partitions (use original edge for position).
                z_part = z_top + partition_height_m
                if length > apartment_pitch_m:
                    n_part = int(length // apartment_pitch_m)
                    for k in range(1, n_part + 1):
                        t = k / (n_part + 1)
                        ix = a_orig[0] + t * (b_orig[0] - a_orig[0])
                        iy = a_orig[1] + t * (b_orig[1] - a_orig[1])
                        ox = ix + nx * d
                        oy = iy + ny * d
                        quads.append(Quad(
                            v0=(ix, iy, z_top),
                            v1=(ox, oy, z_top),
                            v2=(ox, oy, z_part),
                            v3=(ix, iy, z_part),
                        ))
    return quads


def clip_footprint_to_parcelle(
    footprint: Sequence[Coord2],
    parcelle: Sequence[Coord2],
) -> list[list[Coord2]]:
    """Compute footprint ∩ parcelle. Returns a list of polygon rings (each
    a list of (x, y) tuples). Multiple rings if the intersection is
    disjoint (rare for orthogonal parcels)."""
    fp = ShPolygon(_dedupe(footprint))
    pc = ShPolygon(_dedupe(parcelle))
    if not fp.is_valid:
        fp = fp.buffer(0)
    if not pc.is_valid:
        pc = pc.buffer(0)
    inter = fp.intersection(pc)
    if inter.is_empty:
        return [list(footprint)]   # fallback : raw footprint
    rings: list[list[Coord2]] = []
    if inter.geom_type == "Polygon":
        rings.append([(x, y) for x, y in inter.exterior.coords[:-1]])
    elif inter.geom_type == "MultiPolygon":
        for g in inter.geoms:
            rings.append([(x, y) for x, y in g.exterior.coords[:-1]])
    return rings


def _dedupe(ring: Sequence[Coord2]) -> list[Coord2]:
    """Drop duplicate consecutive points (incl. closing duplicate)."""
    out: list[Coord2] = []
    for p in ring:
        if not out or (p[0] != out[-1][0] or p[1] != out[-1][1]):
            out.append((p[0], p[1]))
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def parcelle_voirie_segments(
    parcelle: Sequence[Coord2],
    sides: list[str],
) -> list[tuple[Coord2, Coord2]]:
    """Return the parcel-edge segments that face a voirie side.

    Instead of using the parcelle bounding box (which produces a hard
    90° corner at SE even when the cadastral parcel has a chamfered or
    curved corner), we walk the actual parcel polygon and keep the
    segments whose midpoint lies near the SE corner — that gives the
    bahut wall the real cadastral footprint, including the corner
    chamfer / curve that makes the implantation look natural.
    """
    if not parcelle:
        return []
    fp = _dedupe(parcelle)
    n = len(fp)
    if n < 3:
        return []
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    sides_lower = {s.lower() for s in sides}
    has_sud = any(s in ("sud", "south", "s") for s in sides_lower)
    has_nord = any(s in ("nord", "north", "n") for s in sides_lower)
    has_est = any(s in ("est", "east", "e") for s in sides_lower)
    has_ouest = any(s in ("ouest", "west", "w") for s in sides_lower)

    out: list[tuple[Coord2, Coord2]] = []
    # Margin = how close the segment midpoint must be to a bbox edge to
    # count as "facing that side". A 25 % margin keeps the SE chamfer.
    span_x = maxx - minx
    span_y = maxy - miny
    for i in range(n):
        a = fp[i]
        b = fp[(i + 1) % n]
        mx = (a[0] + b[0]) / 2
        my = (a[1] + b[1]) / 2
        # Closeness to each edge of the bbox
        d_south = (my - miny) / max(1e-6, span_y)
        d_north = (maxy - my) / max(1e-6, span_y)
        d_east = (maxx - mx) / max(1e-6, span_x)
        d_west = (mx - minx) / max(1e-6, span_x)
        keep = (
            (has_sud and d_south < 0.25) or
            (has_nord and d_north < 0.25) or
            (has_est and d_east < 0.25) or
            (has_ouest and d_west < 0.25)
        )
        if keep:
            out.append((a, b))
    return out


def voirie_strip_quads(
    parcelle: Sequence[Coord2],
    sides: list[str],
    thickness_m: float = 6.0,
    *,
    trottoir_width_m: float = 3.0,
    bahut_height_m: float = 0.6,
    grille_height_m: float = 1.4,
    pedestrian_barrier_height_m: float = 1.1,
    emit_flat_ground: bool = True,
    parcel_retreat_m: float = 0.15,
) -> list[Quad]:
    """Trottoir + chaussée + mur bahut + grille + barrière piéton.

    Mirrors a typical French residential urban setup (Île-de-France) :

        parcelle | mur bahut 1m + grille 0.8m above |  trottoir 3m  |  chaussée
        ─────────│────── on the parcel boundary ───│── briques ───│── asphalt ──
                                                   │   (curb)     │  + barriere

    All elevations are realistic so the depth map captures :
      * mur bahut + grille  → 1.8 m vertical mass on the limit
      * trottoir            → 0.18 m curb above asphalt (clear edge)
      * chaussée            → 0.10 m above ground (visible to ControlNet,
                              prevents FLUX from rendering it as sky/horizon)
      * pedestrian barrier  → 1.1 m railing on the trottoir/road interface
    """
    if not parcelle:
        return []
    xs = [p[0] for p in parcelle]
    ys = [p[1] for p in parcelle]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    chaussee_width = max(0.5, thickness_m - trottoir_width_m)
    quads: list[Quad] = []
    curb_h = 0.30         # trottoir curb (boosted 0.22→0.30 for FLUX foreground
                          # contrast — Grok suggested 0.25-0.35 visible)
    chaussee_h = 0.10     # chaussée slightly raised (lowered from 0.15 so curb
                          # step is more pronounced relative to road)
    crossing_h = 0.20     # zebra crossing band height (boosted 0.18→0.20)
                          # on the road so it can't read it as panoramic vista
    barrier_inset = 0.4   # pedestrian barrier sits 40cm inside trottoir

    def _vertical_wall(p1: Coord2, p2: Coord2,
                       z0: float, z1: float, thickness: float = 0.3) -> list[Quad]:
        """Thin vertical wall (volume of `thickness` m) extruded between z0..z1
        along edge p1→p2. Used for mur bahut, grille and pedestrian barrier."""
        out: list[Quad] = []
        ex = p2[0] - p1[0]
        ey = p2[1] - p1[1]
        L = (ex * ex + ey * ey) ** 0.5
        if L < 0.5:
            return out
        nx = ey / L
        ny = -ex / L
        d = thickness / 2.0
        for sign in (-1.0, +1.0):
            ox = nx * d * sign
            oy = ny * d * sign
            out.append(Quad(
                v0=(p1[0] + ox, p1[1] + oy, z0),
                v1=(p2[0] + ox, p2[1] + oy, z0),
                v2=(p2[0] + ox, p2[1] + oy, z1),
                v3=(p1[0] + ox, p1[1] + oy, z1),
            ))
        return out

    # Extend bahut walls 0.5 m past each end so adjacent voirie sides
    # (e.g. sud + est at the SE corner) overlap and form a continuous
    # masonry mass with no gap at the corner.
    BAHUT_OVERLAP = 0.5
    # parcel_retreat_m : retreat the bahut/grille INSIDE the parcel by this
    # margin so it never sits on the public trottoir (mairie refuse this).
    R = parcel_retreat_m
    for side in sides:
        s = side.lower()
        if s in ("sud", "south", "s"):
            y0 = miny + R          # retreat inside parcel
            y_trott = miny - trottoir_width_m
            y_chauss = y_trott - chaussee_width
            y_barrier = y_trott + 0.05
            trottoir = [(minx - 1.0, y_trott), (maxx + 1.0, y_trott),
                        (maxx + 1.0, miny),   (minx - 1.0, miny)]
            chaussee = [(minx - 1.0, y_chauss), (maxx + 1.0, y_chauss),
                        (maxx + 1.0, y_trott), (minx - 1.0, y_trott)]
            wall_p1 = (minx + R - BAHUT_OVERLAP, y0)
            wall_p2 = (maxx - R + BAHUT_OVERLAP, y0)
            barrier_p1 = (minx - 1.0, y_trott + barrier_inset)
            barrier_p2 = (maxx + 1.0, y_trott + barrier_inset)
        elif s in ("nord", "north", "n"):
            y0 = maxy - R
            y_trott = maxy + trottoir_width_m
            y_chauss = y_trott + chaussee_width
            trottoir = [(minx - 1.0, maxy), (maxx + 1.0, maxy),
                        (maxx + 1.0, y_trott), (minx - 1.0, y_trott)]
            chaussee = [(minx - 1.0, y_trott), (maxx + 1.0, y_trott),
                        (maxx + 1.0, y_chauss), (minx - 1.0, y_chauss)]
            wall_p1 = (minx + R - BAHUT_OVERLAP, y0)
            wall_p2 = (maxx - R + BAHUT_OVERLAP, y0)
            barrier_p1 = (minx - 1.0, y_trott - barrier_inset)
            barrier_p2 = (maxx + 1.0, y_trott - barrier_inset)
        elif s in ("est", "east", "e"):
            x0 = maxx - R
            x_trott = maxx + trottoir_width_m
            x_chauss = x_trott + chaussee_width
            trottoir = [(maxx, miny - 1.0), (x_trott, miny - 1.0),
                        (x_trott, maxy + 1.0), (maxx, maxy + 1.0)]
            chaussee = [(x_trott, miny - 1.0), (x_chauss, miny - 1.0),
                        (x_chauss, maxy + 1.0), (x_trott, maxy + 1.0)]
            wall_p1 = (x0, miny + R - BAHUT_OVERLAP)
            wall_p2 = (x0, maxy - R + BAHUT_OVERLAP)
            barrier_p1 = (x_trott - barrier_inset, miny - 1.0)
            barrier_p2 = (x_trott - barrier_inset, maxy + 1.0)
        elif s in ("ouest", "west", "w"):
            x0 = minx + R
            x_trott = minx - trottoir_width_m
            x_chauss = x_trott - chaussee_width
            trottoir = [(x_trott, miny - 1.0), (minx, miny - 1.0),
                        (minx, maxy + 1.0), (x_trott, maxy + 1.0)]
            chaussee = [(x_chauss, miny - 1.0), (x_trott, miny - 1.0),
                        (x_trott, maxy + 1.0), (x_chauss, maxy + 1.0)]
            wall_p1 = (x0, miny + R - BAHUT_OVERLAP)
            wall_p2 = (x0, maxy - R + BAHUT_OVERLAP)
            barrier_p1 = (x_trott + barrier_inset, miny - 1.0)
            barrier_p2 = (x_trott + barrier_inset, maxy + 1.0)
        else:
            continue
        # Trottoir + chaussée + parallel joint lines (read as concrete pavers).
        # `emit_flat_ground=False` skips them when BDTopo TRONCON_DE_ROUTE
        # provides the real cadastral asphalt + sidewalk geometry — the
        # voirie strip then only emits vertical structures (bahut, grille,
        # walkway, piers, gate) which sit ON TOP of the BDTopo ground.
        if emit_flat_ground:
            quads.extend(_extrude_simple(trottoir, curb_h))
            quads.extend(_extrude_simple(chaussee, chaussee_h))
            joint_h = curb_h + 0.005
            joint_thickness = 0.04
            if s in ("sud", "south", "s"):
                for joint_y in [y_trott + 0.5, y_trott + 1.5, y_trott + 2.5]:
                    jq = [(minx - 1.0, joint_y - joint_thickness/2),
                          (maxx + 1.0, joint_y - joint_thickness/2),
                          (maxx + 1.0, joint_y + joint_thickness/2),
                          (minx - 1.0, joint_y + joint_thickness/2)]
                    quads.extend(_extrude_simple(jq, joint_h))
            elif s in ("est", "east", "e"):
                for joint_x in [x_trott - 0.5, x_trott - 1.5, x_trott - 2.5]:
                    jq = [(joint_x - joint_thickness/2, miny - 1.0),
                          (joint_x + joint_thickness/2, miny - 1.0),
                          (joint_x + joint_thickness/2, maxy + 1.0),
                          (joint_x - joint_thickness/2, maxy + 1.0)]
                    quads.extend(_extrude_simple(jq, joint_h))

    # Walk real parcel edges that face any voirie side, including the
    # corner chamfer / curve. We split the longest segment of the primary
    # voirie side to leave a 2 m GAP for the main pedestrian entrance,
    # then a paved approach path between that gap and the building's
    # south facade. FLUX paints a real entrance gate + walkway.
    real_segs = parcelle_voirie_segments(parcelle, sides)
    # Identify the longest segment on the primary voirie side : that's
    # where the entrance gate goes.
    primary = sides[0].lower() if sides else "sud"
    longest_idx = -1
    longest_len = 0.0
    for idx, (a, b) in enumerate(real_segs):
        L = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if L > longest_len:
            longest_len = L
            longest_idx = idx
    GATE_W = 3.5
    walkway_quads: list[Quad] = []
    for idx, (a, b) in enumerate(real_segs):
        if idx == longest_idx and longest_len > GATE_W + 1.0:
            ex = b[0] - a[0]
            ey = b[1] - a[1]
            L = (ex * ex + ey * ey) ** 0.5
            tx = ex / L
            ty = ey / L
            cx = (a[0] + b[0]) / 2
            cy = (a[1] + b[1]) / 2
            half = GATE_W / 2
            gp1 = (cx - tx * half, cy - ty * half)
            gp2 = (cx + tx * half, cy + ty * half)
            # Two wall segments either side of the gap
            quads.extend(_vertical_wall(a, gp1, 0.0, bahut_height_m, thickness=0.25))
            quads.extend(_vertical_wall(a, gp1, bahut_height_m, grille_height_m, thickness=0.25))
            quads.extend(_vertical_wall(gp2, b, 0.0, bahut_height_m, thickness=0.25))
            quads.extend(_vertical_wall(gp2, b, bahut_height_m, grille_height_m, thickness=0.25))
            # Paved walkway : a low quad (z=0.05m) from the gate inward,
            # 2 m wide × 4 m deep, leading to the building.
            nx = ey / L      # inward of CCW polygon → toward the building
            ny = -ex / L
            # We want the inward direction (away from voirie, into the
            # parcel). The CCW polygon convention means nx,ny points
            # outside; flip it.
            ix = -nx
            iy = -ny
            # Walkway : 1.6 m wide × 4 m long, raised 12 cm so it reads
            # as a clear pedestrian path from the gate to the building.
            walkway_half = 1.25      # 2.5 m wide (more visible)
            walkway_len = 6.0        # crosses the full front garden
            walkway_h = 0.80         # raised 80 cm — VERY tall so FLUX
                                     # can't lose the walkway in the R+5 depth
                                     # norm. Reads as a clearly-elevated paved
                                     # path leading from gate to building entry.
            walk_in1 = (cx - tx * walkway_half, cy - ty * walkway_half)
            walk_in2 = (cx + tx * walkway_half, cy + ty * walkway_half)
            walk_in3 = (walk_in2[0] + ix * walkway_len, walk_in2[1] + iy * walkway_len)
            walk_in4 = (walk_in1[0] + ix * walkway_len, walk_in1[1] + iy * walkway_len)
            walkway_quads.append(Quad(
                v0=(walk_in1[0], walk_in1[1], walkway_h),
                v1=(walk_in2[0], walk_in2[1], walkway_h),
                v2=(walk_in3[0], walk_in3[1], walkway_h),
                v3=(walk_in4[0], walk_in4[1], walkway_h),
            ))
            # Two PROMINENT piers framing the gate to mark the entrance clearly.
            # Bumped from 30cm × 30cm × (bahut+grille) to 50cm × 50cm × (bahut+grille+0.5)
            # so they project as obvious vertical markers that FLUX renders
            # as distinct masonry pillars on each side of the gate.
            pier_h = bahut_height_m + grille_height_m + 0.5
            for pier_p in (gp1, gp2):
                pier_corners = [
                    (pier_p[0] - 0.25, pier_p[1] - 0.25),
                    (pier_p[0] + 0.25, pier_p[1] - 0.25),
                    (pier_p[0] + 0.25, pier_p[1] + 0.25),
                    (pier_p[0] - 0.25, pier_p[1] + 0.25),
                ]
                for j in range(4):
                    pa = pier_corners[j]
                    pb = pier_corners[(j + 1) % 4]
                    quads.append(Quad(
                        v0=(pa[0], pa[1], 0.0),
                        v1=(pb[0], pb[1], 0.0),
                        v2=(pb[0], pb[1], pier_h),
                        v3=(pa[0], pa[1], pier_h),
                    ))
        else:
            quads.extend(_vertical_wall(a, b, 0.0, bahut_height_m, thickness=0.25))
            quads.extend(_vertical_wall(a, b, bahut_height_m, grille_height_m,
                                        thickness=0.10))
    quads.extend(walkway_quads)
    return quads


def opposing_street_quads(
    parcelle: Sequence[Coord2],
    sides: list[str],
    *,
    near_trottoir_m: float = 3.0,
    chaussee_m: float = 7.0,
    far_trottoir_m: float = 3.0,
    far_facade_depth_m: float = 6.0,
    far_facade_height_m: float = 14.0,
    far_facade_setback_m: float = 0.5,
    lateral_extend_m: float = 40.0,
    emit_chaussee: bool = True,
    emit_far_trottoir: bool = True,
    emit_far_facade: bool = True,
) -> list[Quad]:
    """Close the urban street canyon on the opposite side of each voirie side.

    The on-parcel voirie strip (built by voirie_strip_quads) only renders
    the parcel-side of the street : near sidewalk + a 3 m chaussée + bahut.
    The far side is empty geometry, so the depth-map foreground is black,
    and FLUX hallucinates a panoramic cityscape miniature.

    This function adds the OPPOSITE side of the street : a far sidewalk,
    a row of low-rise facades (R+4 ≈ 14 m, the typical Nogent faubourg
    pattern across Rue des Héros). FLUX then reads the foreground as a
    closed urban canyon and paints actual road + sidewalks + facing
    apartments, never an aerial city.

    Layout (looking outward from the parcel) :

        parcel | near trottoir 3m | chaussée 7m | far trottoir 3m | far facades 14m tall
        ───────┴── on-parcel ────┴── road ─────┴── across street ┴── opposite buildings

    All geometry is extruded so it shows up clearly in the depth map.
    """
    if not parcelle or not sides:
        return []
    xs = [p[0] for p in parcelle]
    ys = [p[1] for p in parcelle]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    quads: list[Quad] = []
    far_curb_h = 0.22       # raised kerb on the far side
    far_road_h = 0.05       # subtle asphalt elevation
    LE = lateral_extend_m
    near_offset = near_trottoir_m
    chaussee_offset = near_offset + chaussee_m
    far_trott_offset = chaussee_offset + far_trottoir_m
    far_setback = far_trott_offset + far_facade_setback_m
    far_back = far_setback + far_facade_depth_m

    for side in sides:
        s = side.lower()
        if s in ("sud", "south", "s"):
            y0 = miny
            # Outward (south) is negative y.
            y_chauss_in = y0 - near_offset
            y_chauss_out = y0 - chaussee_offset
            y_far_trott_out = y0 - far_trott_offset
            y_far_facade_in = y0 - far_setback
            y_far_facade_back = y0 - far_back
            chaussee = [
                (minx - LE, y_chauss_out),
                (maxx + LE, y_chauss_out),
                (maxx + LE, y_chauss_in),
                (minx - LE, y_chauss_in),
            ]
            far_trottoir = [
                (minx - LE, y_far_trott_out),
                (maxx + LE, y_far_trott_out),
                (maxx + LE, y_chauss_out),
                (minx - LE, y_chauss_out),
            ]
            far_block = [
                (minx - LE, y_far_facade_back),
                (maxx + LE, y_far_facade_back),
                (maxx + LE, y_far_facade_in),
                (minx - LE, y_far_facade_in),
            ]
        elif s in ("nord", "north", "n"):
            y0 = maxy
            y_chauss_in = y0 + near_offset
            y_chauss_out = y0 + chaussee_offset
            y_far_trott_out = y0 + far_trott_offset
            y_far_facade_in = y0 + far_setback
            y_far_facade_back = y0 + far_back
            chaussee = [
                (minx - LE, y_chauss_in),
                (maxx + LE, y_chauss_in),
                (maxx + LE, y_chauss_out),
                (minx - LE, y_chauss_out),
            ]
            far_trottoir = [
                (minx - LE, y_chauss_out),
                (maxx + LE, y_chauss_out),
                (maxx + LE, y_far_trott_out),
                (minx - LE, y_far_trott_out),
            ]
            far_block = [
                (minx - LE, y_far_facade_in),
                (maxx + LE, y_far_facade_in),
                (maxx + LE, y_far_facade_back),
                (minx - LE, y_far_facade_back),
            ]
        elif s in ("est", "east", "e"):
            x0 = maxx
            x_chauss_in = x0 + near_offset
            x_chauss_out = x0 + chaussee_offset
            x_far_trott_out = x0 + far_trott_offset
            x_far_facade_in = x0 + far_setback
            x_far_facade_back = x0 + far_back
            chaussee = [
                (x_chauss_in, miny - LE),
                (x_chauss_out, miny - LE),
                (x_chauss_out, maxy + LE),
                (x_chauss_in, maxy + LE),
            ]
            far_trottoir = [
                (x_chauss_out, miny - LE),
                (x_far_trott_out, miny - LE),
                (x_far_trott_out, maxy + LE),
                (x_chauss_out, maxy + LE),
            ]
            far_block = [
                (x_far_facade_in, miny - LE),
                (x_far_facade_back, miny - LE),
                (x_far_facade_back, maxy + LE),
                (x_far_facade_in, maxy + LE),
            ]
        elif s in ("ouest", "west", "w"):
            x0 = minx
            x_chauss_in = x0 - near_offset
            x_chauss_out = x0 - chaussee_offset
            x_far_trott_out = x0 - far_trott_offset
            x_far_facade_in = x0 - far_setback
            x_far_facade_back = x0 - far_back
            chaussee = [
                (x_chauss_out, miny - LE),
                (x_chauss_in, miny - LE),
                (x_chauss_in, maxy + LE),
                (x_chauss_out, maxy + LE),
            ]
            far_trottoir = [
                (x_far_trott_out, miny - LE),
                (x_chauss_out, miny - LE),
                (x_chauss_out, maxy + LE),
                (x_far_trott_out, maxy + LE),
            ]
            far_block = [
                (x_far_facade_back, miny - LE),
                (x_far_facade_in, miny - LE),
                (x_far_facade_in, maxy + LE),
                (x_far_facade_back, maxy + LE),
            ]
        else:
            continue
        # Each component is opt-in : the chaussée + far_trottoir flat
        # extrusions trigger a "parking lot" hallucination in FLUX even
        # at 0.05/0.22m elevation. The far_facade alone (without flat
        # ground in front of it) gives FLUX a "build facades here" hint
        # without creating the parking pattern. Far_ground covers the
        # ground floor instead.
        if emit_chaussee:
            quads.extend(_extrude_simple(chaussee, far_road_h))
        if emit_far_trottoir:
            quads.extend(_extrude_simple(far_trottoir, far_curb_h))
        if emit_far_facade:
            quads.extend(_extrude_simple(far_block, far_facade_height_m))
    return quads


def synthetic_voirie_roads_quads(
    parcelle: Sequence[Coord2],
    voirie_sides: list[str],
    *,
    chaussee_width_m: float = 5.0,
    trottoir_width_m: float = 1.5,
    extension_m: float = 30.0,
    chaussee_z: float = 0.05,
    trottoir_z: float = 0.20,
) -> tuple[list[Quad], list[Quad], list[Quad]]:
    """Synthesize clean rectangular roads along voirie sides of parcel.

    Returns (chaussee_quads, trottoir_quads, lane_marking_quads).

    Use case : when BDTopo cadastral roads are inconsistent with BM
    parcel polygon (e.g. roads crossing through parcel due to imprecise
    auto-generated parcel rectangle), this provides a clean, predictable
    "roads along voirie" rendering that matches the BM's declared
    voirie_orientations.

    For each voirie side ('est', 'sud', etc.), places a chaussée +
    trottoir strip along the parcel boundary on that side, extending
    `extension_m` past the parcel corners to form intersections.
    """
    if not parcelle or not voirie_sides:
        return [], [], []
    fp = _dedupe(parcelle)
    xs = [p[0] for p in fp]; ys = [p[1] for p in fp]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    chaussee_qs: list[Quad] = []
    trottoir_qs: list[Quad] = []
    lane_qs: list[Quad] = []

    # Detect which voirie sides exist for proper intersection clipping
    has_sud = any(s.lower().startswith(("sud", "s")) for s in voirie_sides)
    has_nord = any(s.lower().startswith(("nord", "n")) for s in voirie_sides)
    has_est = any(s.lower().startswith(("est", "e")) for s in voirie_sides)
    has_ouest = any(s.lower().startswith(("ouest", "o", "w")) for s in voirie_sides)
    tw = trottoir_width_m

    # CORRECT ORDER from parcel outward : parcel → trottoir → chaussée.
    # CRITICAL : trottoir is CLIPPED to parcel range + tw past corners
    # to avoid extending OVER perpendicular chaussée at intersections
    # (which would create gray strips on the road = "bicolore" bug).
    # Chaussée extends FULL extension_m past parcel (street continues).
    #
    # iter #303 — Z-STAGGER per side : the 2 perpendicular chaussée quads
    # were both at chaussee_z (0.05) → z-fight where they overlap at the
    # X-intersection center → renderer flipped between two faces with
    # different normal-derived shading → BLACK SQUARE artifact at the X
    # center. Fix : each side gets cz = chaussee_z + idx * 0.001 m (1 mm
    # stagger). Highest-index side wins at intersection, uniformly. Lane
    # markings stay 1 mm above their chaussée (cz + 0.001).
    for idx, side in enumerate(voirie_sides):
        s = side.lower()
        cz = chaussee_z + idx * 0.001
        lane_z = cz + 0.001
        if s in ("sud", "south", "s"):
            y_trottoir_top = miny
            y_trottoir_bot = miny - tw
            y_chaussee_top = y_trottoir_bot
            y_chaussee_bot = y_chaussee_top - chaussee_width_m
            x_left  = minx - extension_m
            x_right = maxx + extension_m
            # Trottoir clipped : extend just past parcel corners by tw
            # (to align with perpendicular trottoirs), NOT extension_m.
            t_x_left  = (minx - tw) if has_ouest else x_left
            t_x_right = (maxx + tw) if has_est else x_right
            trottoir_qs.append(Quad(
                v0=(t_x_left,  y_trottoir_bot, trottoir_z),
                v1=(t_x_right, y_trottoir_bot, trottoir_z),
                v2=(t_x_right, y_trottoir_top, trottoir_z),
                v3=(t_x_left,  y_trottoir_top, trottoir_z),
            ))
            chaussee_qs.append(Quad(
                v0=(x_left,  y_chaussee_bot, cz),
                v1=(x_right, y_chaussee_bot, cz),
                v2=(x_right, y_chaussee_top, cz),
                v3=(x_left,  y_chaussee_top, cz),
            ))
            y_center = (y_chaussee_top + y_chaussee_bot) / 2
            # Lane markings : skip in intersection area to avoid + cross
            for x_dash in range(int(x_left), int(x_right), 6):
                in_intersection = (
                    (has_est and maxx - tw <= x_dash <= maxx + chaussee_width_m + tw) or
                    (has_ouest and minx - chaussee_width_m - tw <= x_dash <= minx + tw)
                )
                if in_intersection: continue
                lane_qs.append(Quad(
                    v0=(x_dash, y_center - 0.075, lane_z),
                    v1=(x_dash + 3.0, y_center - 0.075, lane_z),
                    v2=(x_dash + 3.0, y_center + 0.075, lane_z),
                    v3=(x_dash, y_center + 0.075, lane_z),
                ))
        elif s in ("nord", "north", "n"):
            y_trottoir_bot = maxy
            y_trottoir_top = maxy + tw
            y_chaussee_bot = y_trottoir_top
            y_chaussee_top = y_chaussee_bot + chaussee_width_m
            x_left = minx - extension_m
            x_right = maxx + extension_m
            t_x_left  = (minx - tw) if has_ouest else x_left
            t_x_right = (maxx + tw) if has_est else x_right
            trottoir_qs.append(Quad(
                v0=(t_x_left,  y_trottoir_bot, trottoir_z),
                v1=(t_x_right, y_trottoir_bot, trottoir_z),
                v2=(t_x_right, y_trottoir_top, trottoir_z),
                v3=(t_x_left,  y_trottoir_top, trottoir_z),
            ))
            chaussee_qs.append(Quad(
                v0=(x_left,  y_chaussee_bot, cz),
                v1=(x_right, y_chaussee_bot, cz),
                v2=(x_right, y_chaussee_top, cz),
                v3=(x_left,  y_chaussee_top, cz),
            ))
            y_center = (y_chaussee_top + y_chaussee_bot) / 2
            for x_dash in range(int(x_left), int(x_right), 6):
                in_intersection = (
                    (has_est and maxx - tw <= x_dash <= maxx + chaussee_width_m + tw) or
                    (has_ouest and minx - chaussee_width_m - tw <= x_dash <= minx + tw)
                )
                if in_intersection: continue
                lane_qs.append(Quad(
                    v0=(x_dash, y_center - 0.075, lane_z),
                    v1=(x_dash + 3.0, y_center - 0.075, lane_z),
                    v2=(x_dash + 3.0, y_center + 0.075, lane_z),
                    v3=(x_dash, y_center + 0.075, lane_z),
                ))
        elif s in ("est", "east", "e"):
            x_trottoir_left = maxx
            x_trottoir_right = maxx + tw
            x_chaussee_left = x_trottoir_right
            x_chaussee_right = x_chaussee_left + chaussee_width_m
            y_bot = miny - extension_m
            y_top = maxy + extension_m
            t_y_bot = (miny - tw) if has_sud else y_bot
            t_y_top = (maxy + tw) if has_nord else y_top
            trottoir_qs.append(Quad(
                v0=(x_trottoir_left,  t_y_bot, trottoir_z),
                v1=(x_trottoir_right, t_y_bot, trottoir_z),
                v2=(x_trottoir_right, t_y_top, trottoir_z),
                v3=(x_trottoir_left,  t_y_top, trottoir_z),
            ))
            chaussee_qs.append(Quad(
                v0=(x_chaussee_left,  y_bot, cz),
                v1=(x_chaussee_right, y_bot, cz),
                v2=(x_chaussee_right, y_top, cz),
                v3=(x_chaussee_left,  y_top, cz),
            ))
            x_center = (x_chaussee_left + x_chaussee_right) / 2
            for y_dash in range(int(y_bot), int(y_top), 6):
                in_intersection = (
                    (has_sud and miny - chaussee_width_m - tw <= y_dash <= miny + tw) or
                    (has_nord and maxy - tw <= y_dash <= maxy + chaussee_width_m + tw)
                )
                if in_intersection: continue
                lane_qs.append(Quad(
                    v0=(x_center - 0.075, y_dash, lane_z),
                    v1=(x_center + 0.075, y_dash, lane_z),
                    v2=(x_center + 0.075, y_dash + 3.0, lane_z),
                    v3=(x_center - 0.075, y_dash + 3.0, lane_z),
                ))
        elif s in ("ouest", "west", "w"):
            x_trottoir_right = minx
            x_trottoir_left = minx - tw
            x_chaussee_right = x_trottoir_left
            x_chaussee_left = x_chaussee_right - chaussee_width_m
            y_bot = miny - extension_m
            y_top = maxy + extension_m
            t_y_bot = (miny - tw) if has_sud else y_bot
            t_y_top = (maxy + tw) if has_nord else y_top
            trottoir_qs.append(Quad(
                v0=(x_trottoir_left,  t_y_bot, trottoir_z),
                v1=(x_trottoir_right, t_y_bot, trottoir_z),
                v2=(x_trottoir_right, t_y_top, trottoir_z),
                v3=(x_trottoir_left,  t_y_top, trottoir_z),
            ))
            chaussee_qs.append(Quad(
                v0=(x_chaussee_left,  y_bot, cz),
                v1=(x_chaussee_right, y_bot, cz),
                v2=(x_chaussee_right, y_top, cz),
                v3=(x_chaussee_left,  y_top, cz),
            ))
            x_center = (x_chaussee_left + x_chaussee_right) / 2
            for y_dash in range(int(y_bot), int(y_top), 6):
                in_intersection = (
                    (has_sud and miny - chaussee_width_m - tw <= y_dash <= miny + tw) or
                    (has_nord and maxy - tw <= y_dash <= maxy + chaussee_width_m + tw)
                )
                if in_intersection: continue
                lane_qs.append(Quad(
                    v0=(x_center - 0.075, y_dash, lane_z),
                    v1=(x_center + 0.075, y_dash, lane_z),
                    v2=(x_center + 0.075, y_dash + 3.0, lane_z),
                    v3=(x_center - 0.075, y_dash + 3.0, lane_z),
                ))
    # KERB removed — too thin to be visible at camera POV 40m+ away.
    # The chaussée/trottoir height differential (0.05m vs 0.20m = 15cm step)
    # already provides natural bordure shadow at this scale.
    return chaussee_qs, trottoir_qs, lane_qs


def lane_markings_quads(
    roads: list[dict],
    parcelle: Sequence[Coord2],
    *,
    dash_length_m: float = 3.0,
    gap_length_m: float = 3.0,
    line_width_m: float = 0.12,
    z_offset_m: float = 0.06,
    max_distance_from_parcelle_m: float = 50.0,
) -> list[Quad]:
    """Dashed white center lines on each road centerline (lane markings).

    For each road polyline, generate alternating dash/gap white rectangles
    along the centerline, slightly offset above the chaussée surface.
    These read as 'real road' to FLUX and to the human eye.
    """
    from shapely.geometry import LineString as _SL, Point as _SP, Polygon as _SP2
    if not roads or not parcelle:
        return []
    parc_geom = _SP2(_dedupe(parcelle))
    if not parc_geom.is_valid:
        parc_geom = parc_geom.buffer(0)
    quads: list[Quad] = []
    for r in roads:
        pl = r.get("polyline") or []
        if len(pl) < 2:
            continue
        ls = _SL(pl)
        if ls.distance(parc_geom) > max_distance_from_parcelle_m:
            continue
        chaussee_m = float(r.get("chaussee_m") or 0.0)
        if chaussee_m < 2.0:
            continue
        # Walk along the polyline placing dashes.
        total_length = ls.length
        s = 0.0
        period = dash_length_m + gap_length_m
        while s < total_length:
            s_end = min(s + dash_length_m, total_length)
            # Sample two points along centerline.
            try:
                p_a = ls.interpolate(s)
                p_b = ls.interpolate(s_end)
            except Exception:
                break
            ax, ay = p_a.x, p_a.y
            bx, by = p_b.x, p_b.y
            ex, ey = bx - ax, by - ay
            eL = (ex * ex + ey * ey) ** 0.5 or 1.0
            tx, ty = ex / eL, ey / eL
            nx, ny = -ty, tx
            half_w = line_width_m / 2.0
            p0 = (ax - nx * half_w, ay - ny * half_w)
            p1 = (bx - nx * half_w, by - ny * half_w)
            p2 = (bx + nx * half_w, by + ny * half_w)
            p3 = (ax + nx * half_w, ay + ny * half_w)
            # Skip dashes that fall inside the parcelle (they shouldn't
            # be on private property).
            mid = _SP(((ax + bx) / 2, (ay + by) / 2))
            if not parc_geom.contains(mid):
                quads.append(Quad(
                    v0=(p0[0], p0[1], z_offset_m),
                    v1=(p1[0], p1[1], z_offset_m),
                    v2=(p2[0], p2[1], z_offset_m),
                    v3=(p3[0], p3[1], z_offset_m),
                ))
            s += period
    return quads


def zebra_crossing_quads(
    roads: list[dict],
    parcelle: Sequence[Coord2],
    *,
    stripe_width_m: float = 0.5,
    stripe_length_m: float = 4.0,
    n_stripes: int = 5,
    z_offset_m: float = 0.06,
) -> list[Quad]:
    """Place zebra-crossing white stripes at T-junctions.

    Detects T-junctions by finding road centerline endpoints that touch
    another road. At each junction, places a zebra crossing perpendicular
    to the ENDING road, near the parcelle so it appears in the foreground.

    A zebra is N parallel white stripes 0.5 m × 4.0 m, separated by 0.5 m
    of asphalt (gap). Result : visible black/white checkerboard at the
    corner — the most distinctive foreground cue of the real scene.
    """
    from shapely.geometry import LineString as _SL, Point as _SP, Polygon as _SP2
    if not roads or not parcelle:
        return []
    parc_geom = _SP2(_dedupe(parcelle))
    if not parc_geom.is_valid:
        parc_geom = parc_geom.buffer(0)

    quads: list[Quad] = []

    # Collect all road endpoints + their tangent directions.
    endpoints: list[tuple] = []   # (xy, tangent, road_idx)
    for ri, r in enumerate(roads):
        pl = r.get("polyline") or []
        if len(pl) < 2:
            continue
        # Start endpoint
        a, b = pl[0], pl[1]
        ex, ey = b[0] - a[0], b[1] - a[1]
        eL = (ex * ex + ey * ey) ** 0.5 or 1.0
        endpoints.append((a, (ex / eL, ey / eL), ri))
        # End endpoint
        a, b = pl[-1], pl[-2]
        ex, ey = a[0] - b[0], a[1] - b[1]
        eL = (ex * ex + ey * ey) ** 0.5 or 1.0
        endpoints.append((a, (ex / eL, ey / eL), ri))

    # Deduplicate : within 3m, keep only the first endpoint (don't stack
    # zebras at the same junction). Multiple BDTopo road segments often
    # converge at a junction with all endpoints touching the same point;
    # we want ONE zebra per junction, not 4 stacked on top of each other.
    deduped_endpoints: list[tuple] = []
    for ep, tan, ri in endpoints:
        already = False
        for ep_kept, _, _ in deduped_endpoints:
            d = ((ep[0] - ep_kept[0]) ** 2 + (ep[1] - ep_kept[1]) ** 2) ** 0.5
            if d < 3.0:
                already = True
                break
        if not already:
            deduped_endpoints.append((ep, tan, ri))

    # For each endpoint, check if another road's polyline passes within 5m.
    for ep, (tx, ty), ri in deduped_endpoints:
        # Distance from this endpoint to parcelle.
        dist_to_parc = parc_geom.distance(_SP(ep))
        if dist_to_parc > 30.0:
            continue   # too far from project, not interesting
        is_junction = False
        for rj, r2 in enumerate(roads):
            if rj == ri:
                continue
            pl2 = r2.get("polyline") or []
            if len(pl2) < 2:
                continue
            ls2 = _SL(pl2)
            if ls2.distance(_SP(ep)) < 4.0:
                is_junction = True
                break
        if not is_junction:
            continue
        # Place a zebra crossing : N stripes perpendicular to the ending road.
        # Perpendicular = (-ty, tx) (rotate tangent +90°).
        nx, ny = -ty, tx
        # Centre the zebra slightly back from the endpoint (toward the road)
        # so it sits ON the road, not at the junction crossing.
        cx = ep[0] - tx * 1.5
        cy = ep[1] - ty * 1.5
        gap = stripe_width_m   # equal gap between stripes
        total = n_stripes * stripe_width_m + (n_stripes - 1) * gap
        for k in range(n_stripes):
            u_offset = (-total / 2.0) + k * (stripe_width_m + gap)
            # Stripe rectangle : (cx, cy) + tangent × u → centre of stripe.
            scx = cx + tx * (u_offset + stripe_width_m / 2.0)
            scy = cy + ty * (u_offset + stripe_width_m / 2.0)
            # Corners along normal (perp), length stripe_length_m.
            half_l = stripe_length_m / 2.0
            half_w = stripe_width_m / 2.0
            p0 = (scx - tx * half_w + nx * half_l, scy - ty * half_w + ny * half_l)
            p1 = (scx + tx * half_w + nx * half_l, scy + ty * half_w + ny * half_l)
            p2 = (scx + tx * half_w - nx * half_l, scy + ty * half_w - ny * half_l)
            p3 = (scx - tx * half_w - nx * half_l, scy - ty * half_w - ny * half_l)
            quads.append(Quad(
                v0=(p0[0], p0[1], z_offset_m),
                v1=(p1[0], p1[1], z_offset_m),
                v2=(p2[0], p2[1], z_offset_m),
                v3=(p3[0], p3[1], z_offset_m),
            ))
    return quads


def roads_bdtopo_to_quads(
    roads: list[dict],
    parcelle: Sequence[Coord2],
    *,
    trottoir_width_m: float = 2.5,
    chaussee_height_m: float = 0.05,
    trottoir_height_m: float = 0.20,
    skip_overlap_with: Sequence[Coord2] | None = None,
    max_distance_from_parcelle_m: float = 50.0,
) -> list[Quad]:
    """Convert BDTopo road polylines to chaussée + trottoir quads.

    For each road polyline (centerline) :
      1. Buffer the LineString by chaussee_m/2 → chaussée polygon (asphalt)
      2. Buffer it by chaussee_m/2 + trottoir_width_m → outer polygon
      3. Subtract chaussée from outer → trottoir polygon (sidewalk on each side)
      4. Subtract the project parcelle from both (avoid overlapping our parcel)
      5. Extrude chaussée at chaussee_height_m, trottoir at trottoir_height_m

    The result is a real-cadastral road geometry (varied widths, curves,
    intersections) that fills the depth-map foreground without triggering
    the "uniform plane = parking pattern" hallucination.

    `roads` is the list returned by voisinage_mesh.roads_to_local_polylines.
    """
    if not roads:
        return []
    from shapely.ops import unary_union

    # Build the parcelle geometry once for distance + overlap operations.
    parcelle_geom = ShPolygon(_dedupe(parcelle))
    if not parcelle_geom.is_valid:
        parcelle_geom = parcelle_geom.buffer(0)

    skip_geom = None
    if skip_overlap_with:
        skip_geom = ShPolygon(_dedupe(skip_overlap_with))
        if not skip_geom.is_valid:
            skip_geom = skip_geom.buffer(0)

    # Step 1 : collect chaussée + outer (chaussée+trottoir) polygons per road.
    chaussee_polys = []
    outer_polys = []
    for road in roads:
        polyline = road.get("polyline") or []
        chaussee_m = float(road.get("chaussee_m") or 0.0)
        if len(polyline) < 2 or chaussee_m < 1.5:
            continue
        line = ShLineString(polyline)
        if line.distance(parcelle_geom) > max_distance_from_parcelle_m:
            continue
        chaussee_polys.append(line.buffer(chaussee_m / 2.0, cap_style=2, join_style=2))
        outer_polys.append(line.buffer(chaussee_m / 2.0 + trottoir_width_m, cap_style=2, join_style=2))

    if not chaussee_polys:
        return []

    # Step 2 : UNION all chaussées into ONE polygon, all outers into ONE.
    # This MERGES overlapping road buffers so adjacent road segments form
    # a SINGLE asphalt surface instead of multiple parallel strips
    # (the "multi-lane highway" bug).
    chaussee_unified = unary_union(chaussee_polys)
    outer_unified = unary_union(outer_polys)
    trottoir_unified = outer_unified.difference(chaussee_unified)

    if skip_geom is not None:
        chaussee_unified = chaussee_unified.difference(skip_geom)
        trottoir_unified = trottoir_unified.difference(skip_geom)

    # Step 3 : extrude each unified polygon at its height.
    quads: list[Quad] = []
    for poly, height in [(chaussee_unified, chaussee_height_m),
                         (trottoir_unified, trottoir_height_m)]:
        if poly.is_empty:
            continue
        polygons = list(poly.geoms) if isinstance(poly, ShMultiPolygon) else [poly]
        for sp in polygons:
            if sp.is_empty:
                continue
            ring = list(sp.exterior.coords)
            if len(ring) < 4:
                continue
            ring2 = [(p[0], p[1]) for p in ring[:-1]]
            quads.extend(_extrude_simple(ring2, height))
    return quads
