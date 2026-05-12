"""Build a 3D mesh of the neighbouring buildings (BDTopo) so the depth map
gives ControlNet a real urban context — not just our project floating in
empty space.

Pipeline :
  1. Geocode the project address (BAN) → lat/lng.
  2. Query IGN BDTopo WFS for buildings in radius around (lat, lng).
  3. Project each WGS84 polygon to local meters relative to the parcel
     centre (matches the BM's local frame).
  4. Extrude each to its `hauteur` value to produce Quads.
  5. Concatenate with the project building's Quads in render_depth_map.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class GeoOrigin:
    """Lat/lng of the project parcel centre, used as the local frame origin."""
    lat: float
    lng: float


def geocode_address(address: str) -> GeoOrigin:
    """Geocode a French address via the BAN public API. Returns lat/lng."""
    q = urllib.parse.quote_plus(address)
    url = f"https://api-adresse.data.gouv.fr/search/?q={q}&limit=1"
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.loads(r.read())
    if not d.get("features"):
        raise ValueError(f"no geocode result for {address!r}")
    f = d["features"][0]
    lng, lat = f["geometry"]["coordinates"]
    return GeoOrigin(lat=lat, lng=lng)


def fetch_voisins_bdtopo(origin: GeoOrigin, radius_m: float = 200.0) -> list[dict]:
    """Query IGN BDTopo WFS for buildings inside a bbox of `radius_m` around origin.

    Returns the raw GeoJSON features list.
    """
    return _fetch_bdtopo_layer(origin, radius_m, "BDTOPO_V3:batiment", count=500)


def fetch_osm_street_lamps(origin: GeoOrigin, radius_m: float = 150.0) -> list[tuple[float, float]]:
    """Query OSM Overpass for man_made=street_lamp nodes around origin.

    Returns list of (lat, lng) for each street lamp. If OSM has no lamps
    mapped (street furniture often missing in Overpass), returns empty.
    """
    deg_per_m_lat = 1.0 / 111320.0
    deg_per_m_lng = 1.0 / (111320.0 * math.cos(math.radians(origin.lat)))
    dlat = radius_m * deg_per_m_lat
    dlng = radius_m * deg_per_m_lng
    minlat, maxlat = origin.lat - dlat, origin.lat + dlat
    minlng, maxlng = origin.lng - dlng, origin.lng + dlng
    overpass_q = (
        "[out:json][timeout:15];"
        f'(node["highway"="street_lamp"]({minlat},{minlng},{maxlat},{maxlng});'
        f'node["man_made"="street_lamp"]({minlat},{minlng},{maxlat},{maxlng}););'
        "out body;"
    )
    body = urllib.parse.urlencode({"data": overpass_q}).encode()
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=body,
        headers={"User-Agent": "ArchiClaude/1.0 (PC dossier renderer)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
    except Exception as e:
        print(f"!! Overpass street_lamp fetch failed ({e})")
        return []
    elems = d.get("elements", []) or []
    return [(float(e["lat"]), float(e["lon"])) for e in elems
            if e.get("type") == "node" and "lat" in e and "lon" in e]


def fetch_osm_trees(origin: GeoOrigin, radius_m: float = 150.0) -> list[tuple[float, float]]:
    """Query OpenStreetMap Overpass API for natural=tree nodes around origin.

    Returns a list of (lat, lng) tuples for each individual tree mapped
    in OSM. If OSM has no trees nearby (residential street with sparse
    mapping), returns an empty list — DO NOT synthesize fake positions.
    """
    deg_per_m_lat = 1.0 / 111320.0
    deg_per_m_lng = 1.0 / (111320.0 * math.cos(math.radians(origin.lat)))
    dlat = radius_m * deg_per_m_lat
    dlng = radius_m * deg_per_m_lng
    minlat = origin.lat - dlat
    maxlat = origin.lat + dlat
    minlng = origin.lng - dlng
    maxlng = origin.lng + dlng
    overpass_q = (
        "[out:json][timeout:15];"
        f'(node["natural"="tree"]({minlat},{minlng},{maxlat},{maxlng}););'
        "out body;"
    )
    body = urllib.parse.urlencode({"data": overpass_q}).encode()
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=body,
        headers={"User-Agent": "ArchiClaude/1.0 (PC dossier renderer)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
    except Exception as e:
        print(f"!! Overpass tree fetch failed ({e})")
        return []
    elems = d.get("elements", []) or []
    return [(float(e["lat"]), float(e["lon"])) for e in elems
            if e.get("type") == "node" and "lat" in e and "lon" in e]


def fetch_roads_bdtopo(origin: GeoOrigin, radius_m: float = 200.0) -> list[dict]:
    """Query IGN BDTopo WFS for road segments inside a bbox of `radius_m`.

    Each feature is a LineString (road centerline) with attributes :
      - `largeur_de_chaussee` (chaussée width in meters)
      - `nombre_de_voies` (number of lanes)
      - `nature` ("Route à 1 chaussée", "Sentier", "Bretelle", ...)
      - `position_par_rapport_au_sol` (-1 = tunnel, 0 = ground, 1+ = bridge)
      - `nom_collaboratif_gauche` / `nom_collaboratif_droite` (street name)

    Returns the raw GeoJSON features list. Filtering of tunnels/bridges
    is left to the caller (typically only `position == 0` is rendered).
    """
    return _fetch_bdtopo_layer(origin, radius_m, "BDTOPO_V3:troncon_de_route", count=300)


def _fetch_bdtopo_layer(origin: GeoOrigin, radius_m: float, type_name: str, count: int) -> list[dict]:
    """Generic BDTopo WFS query for a given layer in a bbox around origin."""
    # 1° lat ≈ 111 320 m ; 1° lng at our latitude ≈ cos(lat) * 111 320 m
    deg_per_m_lat = 1.0 / 111320.0
    deg_per_m_lng = 1.0 / (111320.0 * math.cos(math.radians(origin.lat)))
    dlat = radius_m * deg_per_m_lat
    dlng = radius_m * deg_per_m_lng
    minx = origin.lng - dlng
    maxx = origin.lng + dlng
    miny = origin.lat - dlat
    maxy = origin.lat + dlat
    url = (
        "https://data.geopf.fr/wfs/ows"
        "?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeNames={type_name}&srsName=EPSG:4326"
        f"&bbox={minx},{miny},{maxx},{maxy},EPSG:4326"
        f"&outputFormat=application/json&count={count}"
    )
    with urllib.request.urlopen(url, timeout=20) as r:
        d = json.loads(r.read())
    return list(d.get("features", []))


def wgs84_to_local(lat: float, lng: float, origin: GeoOrigin) -> tuple[float, float]:
    """Project a WGS84 lat/lng to local meters with origin at parcel centre."""
    cos_lat = math.cos(math.radians(origin.lat))
    dx = (lng - origin.lng) * 111320.0 * cos_lat   # east → +x
    dy = (lat - origin.lat) * 111320.0             # north → +y
    return dx, dy


def project_to_parcel_frame(
    feature: dict,
    origin: GeoOrigin,
    parcel_center_local: tuple[float, float],
) -> list[list[tuple[float, float]]]:
    """Convert one BDTopo feature's geometry to a list of polygon rings in
    the BM's local meter frame.

    BDTopo features can be Polygon OR MultiPolygon, with 3D coordinates
    (lng, lat, altitude). We extract all outer rings (skip holes) and drop
    the altitude component.
    """
    geom = feature.get("geometry") or {}
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])
    if not coords:
        return []

    # Normalise to a list of polygons (each = list of rings).
    if gtype == "Polygon":
        polygons = [coords]
    elif gtype == "MultiPolygon":
        polygons = coords
    else:
        return []

    cx, cy = parcel_center_local
    out: list[list[tuple[float, float]]] = []
    for poly in polygons:
        if not poly:
            continue
        outer_ring = poly[0]   # outer ring only ; ignore holes
        ring: list[tuple[float, float]] = []
        for pt in outer_ring:
            # 3D points come as (lng, lat, alt) — slice to 2D.
            lng, lat = pt[0], pt[1]
            dx, dy = wgs84_to_local(lat, lng, origin)
            ring.append((cx + dx, cy + dy))
        if len(ring) >= 4:
            out.append(ring)
    return out


def _polygon_contains_xy(ring: list[tuple[float, float]], pt: tuple[float, float]) -> bool:
    """Ray-cast point-in-polygon test (axis-aligned ray going +x)."""
    x, y = pt
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            xt = (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            if x < xt:
                inside = not inside
        j = i
    return inside


def voisins_to_local_polygons(
    features: list[dict],
    origin: GeoOrigin,
    parcel_center_local: tuple[float, float],
    skip_overlap_with: Sequence[tuple[float, float]] | None = None,
    *,
    camera_pos_xy: tuple[float, float] | None = None,
    block_camera_sight: bool = True,
    max_distance_m: float = 80.0,
    min_height_m: float = 3.0,
    max_height_m: float = 20.0,
) -> list[tuple[list[tuple[float, float]], float]]:
    """Convert BDTopo features to (footprint_local, hauteur_m) pairs.

    Filters :
      - drops the project's own building (centroid within 5 m of parcel centre)
      - drops buildings farther than `max_distance_m` from the project centre
        (avoids cluttering the depth map with far-away buildings that would
        produce thin/stripe artefacts at oblique angles)
      - drops buildings shorter than `min_height_m` (small sheds, kiosks)
        which produce noise in the depth map without context value
      - when `block_camera_sight=True`, drops buildings between camera and
        project that would occlude the foreground.
    """
    out: list[tuple[list[tuple[float, float]], float]] = []
    parcel_cx = parcel_cy = None
    if skip_overlap_with:
        parcel_cx = sum(p[0] for p in skip_overlap_with) / len(skip_overlap_with)
        parcel_cy = sum(p[1] for p in skip_overlap_with) / len(skip_overlap_with)

    cam_to_proj = None
    cam_forward = None
    if camera_pos_xy is not None and parcel_cx is not None:
        fx = parcel_cx - camera_pos_xy[0]
        fy = parcel_cy - camera_pos_xy[1]
        cam_to_proj = (fx * fx + fy * fy) ** 0.5
        if cam_to_proj > 1e-6:
            cam_forward = (fx / cam_to_proj, fy / cam_to_proj)

    for f in features:
        rings = project_to_parcel_frame(f, origin, parcel_center_local)
        if not rings:
            continue
        h = f.get("properties", {}).get("hauteur") or 6.0
        if h < min_height_m:
            continue
        # Cap height : voisins taller than the project building (~17 m) get
        # capped here so they never project above the building's roof line
        # in the depth map — preventing FLUX from rendering "skyscraper
        # silhouettes" / mottled artefacts in the sky region of the frame.
        if h > max_height_m:
            h = max_height_m
        for ring in rings:
            rcx = sum(p[0] for p in ring) / len(ring)
            rcy = sum(p[1] for p in ring) / len(ring)
            if skip_overlap_with:
                d_proj = ((rcx - parcel_cx) ** 2 + (rcy - parcel_cy) ** 2) ** 0.5
                if d_proj < 5.0:
                    continue
                if d_proj > max_distance_m:
                    continue
            if cam_to_proj is not None and block_camera_sight:
                vdx = rcx - camera_pos_xy[0]
                vdy = rcy - camera_pos_xy[1]
                d_cam = (vdx * vdx + vdy * vdy) ** 0.5
                # 1. Drop voisins BEHIND the camera : their view_z is negative
                #    so they project as garbage and saturate the depth map.
                if cam_forward is not None and d_cam > 1e-6:
                    forward_dot = (vdx * cam_forward[0] + vdy * cam_forward[1]) / d_cam
                    # cos(75°) — keep a wide ±75° forward cone : flanking
                    # voisins fill the horizon, but anything behind the
                    # camera plane (negative view_z) is rejected so it
                    # doesn't pollute the zbuf.
                    if forward_dot < 0.25:
                        continue
                # 2. Drop voisins between camera and project (occluders) :
                #    must be at least 90 % as far from camera as the project.
                if d_cam < cam_to_proj * 0.90:
                    continue
            out.append((ring, float(h)))
    return out


def roads_to_local_polylines(
    features: list[dict],
    origin: GeoOrigin,
    parcel_center_local: tuple[float, float],
    *,
    require_ground_level: bool = True,
    min_chaussee_width_m: float = 2.0,
) -> list[dict]:
    """Convert BDTopo road LineString features to local polylines + width.

    Returns a list of dicts :
      { "polyline" : list[(x, y)] in local meters,
        "chaussee_m" : float chaussée width,
        "name" : str street name (best-effort) }

    Filters :
      - require_ground_level=True drops position_par_rapport_au_sol != 0
        (excludes tunnels and bridges that would project as garbage at
        our camera height of 5 m).
      - min_chaussee_width_m drops sentier/walkway segments < 2 m wide
        (they create thin lines in depth that FLUX renders as cracks).
    """
    cx, cy = parcel_center_local
    out: list[dict] = []
    drops = {"position": 0, "chaussee_none": 0, "chaussee_parse": 0,
             "chaussee_small": 0, "geom_type": 0, "coords_short": 0}
    for f in features:
        props = f.get("properties", {}) or {}
        if require_ground_level:
            # API returns position as string ("-1", "0", "1", ...) — coerce
            # to int. Anything that fails parsing is treated as ground.
            try:
                pos = int(props.get("position_par_rapport_au_sol") or 0)
            except (TypeError, ValueError):
                pos = 0
            if pos != 0:
                drops["position"] += 1
                continue
        chaussee = props.get("largeur_de_chaussee")
        if chaussee is None:
            drops["chaussee_none"] += 1
            continue
        try:
            chaussee = float(chaussee)
        except (TypeError, ValueError):
            drops["chaussee_parse"] += 1
            continue
        if chaussee < min_chaussee_width_m:
            drops["chaussee_small"] += 1
            continue
        geom = f.get("geometry") or {}
        if geom.get("type") != "LineString":
            drops["geom_type"] += 1
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            drops["coords_short"] += 1
            continue
        polyline: list[tuple[float, float]] = []
        for pt in coords:
            lng, lat = pt[0], pt[1]
            dx, dy = wgs84_to_local(lat, lng, origin)
            # The BM frame origin is offset from BAN by ~ -parcel_centroid;
            # i.e. BAN is located at (cx, cy) in BM frame. So adding
            # (cx, cy) shifts geocode-meters → BM frame correctly.
            polyline.append((cx + dx, cy + dy))
        name = props.get("nom_collaboratif_gauche") or props.get("nom_collaboratif_droite") or ""
        out.append({
            "polyline": polyline,
            "chaussee_m": chaussee,
            "nature": props.get("nature", ""),
            "name": name,
        })
    if features and not out:
        print(f"   roads_to_local_polylines drops: {drops}")
    return out
