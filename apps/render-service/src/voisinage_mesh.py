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

Two sources are supported :
  * `bdtopo_legacy`     → live WFS fetch (`fetch_voisins_bdtopo`), heights
                          come from `properties.hauteur` only. This is the
                          original path that all renders before iter #500
                          went through and remains the default.
  * `ign_photogrammetry`→ load the cached `bdtopo_buildings.geojson` produced
                          by `photogrammetry.build_context.build_context_for_project`,
                          which is BDTOPO V3 LOD2 (z baked into each vertex).
                          Heights are derived from per-vertex z, with the
                          parcelle centroid's ground altitude subtracted so
                          the local frame matches the BM's z=0 ground.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .voisinage_cache import cached

# IGN BDTOPO V3 LOD2 sentinel : when no z is known, IGN writes -1000.
IGN_Z_SENTINEL_NULL = -1000.0


@dataclass(frozen=True)
class GeoOrigin:
    """Lat/lng of the project parcel centre, used as the local frame origin."""
    lat: float
    lng: float


def _geocode_uncached(address: str) -> dict:
    """Hit the BAN public API. Raises on network error / no result so the
    failure is never cached."""
    q = urllib.parse.quote_plus(address)
    url = f"https://api-adresse.data.gouv.fr/search/?q={q}&limit=1"
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.loads(r.read())
    if not d.get("features"):
        raise ValueError(f"no geocode result for {address!r}")
    f = d["features"][0]
    lng, lat = f["geometry"]["coordinates"]
    return {"lat": lat, "lng": lng}


def geocode_address(address: str) -> GeoOrigin:
    """Geocode a French address via the BAN public API. Returns lat/lng.

    Memoised on disk : the same address resolves to the same lat/lng forever,
    so we only ever hit BAN once per address.
    """
    d = cached("geocode", {"address": address}, lambda: _geocode_uncached(address))
    return GeoOrigin(lat=d["lat"], lng=d["lng"])


def fetch_voisins_bdtopo(origin: GeoOrigin, radius_m: float = 200.0) -> list[dict]:
    """Query IGN BDTopo WFS for buildings inside a bbox of `radius_m` around origin.

    Returns the raw GeoJSON features list.
    """
    return cached(
        "bdtopo_batiment",
        {"lat": origin.lat, "lng": origin.lng, "r": radius_m},
        lambda: _fetch_bdtopo_layer(origin, radius_m, "BDTOPO_V3:batiment", count=500),
    )


def _osm_street_lamps_uncached(origin: GeoOrigin, radius_m: float) -> list[list[float]]:
    """Hit Overpass for street lamps. Raises on network/parse error so a
    transient failure is never cached as an empty result."""
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
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    elems = d.get("elements", []) or []
    return [[float(e["lat"]), float(e["lon"])] for e in elems
            if e.get("type") == "node" and "lat" in e and "lon" in e]


def fetch_osm_street_lamps(origin: GeoOrigin, radius_m: float = 150.0) -> list[tuple[float, float]]:
    """Query OSM Overpass for man_made=street_lamp nodes around origin.

    Returns list of (lat, lng) for each street lamp. If OSM has no lamps
    mapped (street furniture often missing in Overpass), returns empty.
    Successful responses are memoised on disk ; transient failures are NOT
    cached — they fall back to [] without poisoning the cache.
    """
    try:
        raw = cached(
            "osm_street_lamps",
            {"lat": origin.lat, "lng": origin.lng, "r": radius_m},
            lambda: _osm_street_lamps_uncached(origin, radius_m),
        )
    except Exception as e:
        print(f"!! Overpass street_lamp fetch failed ({e})")
        return []
    return [(float(lat), float(lng)) for lat, lng in raw]


def _osm_trees_uncached(origin: GeoOrigin, radius_m: float) -> list[list[float]]:
    """Hit Overpass for trees. Raises on network/parse error so a transient
    failure is never cached as an empty result."""
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
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    elems = d.get("elements", []) or []
    return [[float(e["lat"]), float(e["lon"])] for e in elems
            if e.get("type") == "node" and "lat" in e and "lon" in e]


def fetch_osm_trees(origin: GeoOrigin, radius_m: float = 150.0) -> list[tuple[float, float]]:
    """Query OpenStreetMap Overpass API for natural=tree nodes around origin.

    Returns a list of (lat, lng) tuples for each individual tree mapped
    in OSM. If OSM has no trees nearby (residential street with sparse
    mapping), returns an empty list — DO NOT synthesize fake positions.
    Successful responses are memoised on disk ; transient failures are NOT
    cached — they fall back to [] without poisoning the cache.
    """
    try:
        raw = cached(
            "osm_trees",
            {"lat": origin.lat, "lng": origin.lng, "r": radius_m},
            lambda: _osm_trees_uncached(origin, radius_m),
        )
    except Exception as e:
        print(f"!! Overpass tree fetch failed ({e})")
        return []
    return [(float(lat), float(lng)) for lat, lng in raw]


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
    return cached(
        "bdtopo_routes",
        {"lat": origin.lat, "lng": origin.lng, "r": radius_m},
        lambda: _fetch_bdtopo_layer(origin, radius_m, "BDTOPO_V3:troncon_de_route", count=300),
    )


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
    forward_cone_cos: float = 0.25,
    min_camera_distance_ratio: float = 0.90,
    max_voisin_count: Optional[int] = None,
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
        project that would occlude the foreground :
          * `forward_cone_cos` — cosine of the half-angle of the forward cone
            (default 0.25 = ±75°). Lower it (e.g. -1.0) to keep all voisins
            including those behind the camera (useful for full-context USDA
            scenes consumed by Cycles/UE5).
          * `min_camera_distance_ratio` — drop voisins closer to the camera
            than `ratio × cam_to_project_distance` (default 0.90 — depth-map
            mode kills the foreground). Set to 0.0 to keep all foreground
            voisins (photoreal/USDA mode where foreground = context).

    Cap :
      - `max_voisin_count` — keep at most N voisins, ordered by ascending
        distance to the parcel centre. None = no cap. Useful to bound mesh
        count for Cycles perf when the full radius would yield 300+ buildings.
    """
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

    # Collect candidates with their distance to the parcel centre so we can
    # sort + cap deterministically (keep nearest N voisins).
    candidates: list[tuple[float, list[tuple[float, float]], float]] = []
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
            d_proj = 0.0
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
                # 1. Drop voisins BEHIND the camera (configurable cone).
                if cam_forward is not None and d_cam > 1e-6:
                    forward_dot = (vdx * cam_forward[0] + vdy * cam_forward[1]) / d_cam
                    if forward_dot < forward_cone_cos:
                        continue
                # 2. Drop voisins between camera and project (occluders).
                if min_camera_distance_ratio > 0.0 and d_cam < cam_to_proj * min_camera_distance_ratio:
                    continue
            candidates.append((d_proj, ring, float(h)))

    candidates.sort(key=lambda t: t[0])
    if max_voisin_count is not None and max_voisin_count > 0:
        candidates = candidates[: max_voisin_count]
    return [(ring, h) for _d, ring, h in candidates]


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


# ─── IGN photogrammetry source (Jour 4 — BDTOPO V3 LOD2 from disk) ──────


def _walk_z(node, out: list) -> None:
    """Collect every z value from a nested GeoJSON coordinates structure."""
    if isinstance(node, list) and node and isinstance(node[0], (int, float)) and len(node) >= 3:
        out.append(float(node[2]))
    elif isinstance(node, list):
        for child in node:
            _walk_z(child, out)


def _feature_z_range(feature: dict) -> Optional[tuple[float, float]]:
    """Return (z_min, z_max) for a single feature's outer rings, dropping
    IGN -1000 sentinels. Returns None if no valid z found."""
    zs: list[float] = []
    _walk_z(feature.get("geometry", {}).get("coordinates", []), zs)
    valid = [z for z in zs if z > IGN_Z_SENTINEL_NULL + 1]
    if not valid:
        return None
    return (min(valid), max(valid))


def load_ign_bdtopo_geojson(project_id: str, refs_root: Optional[Path] = None) -> dict:
    """Load the BDTOPO LOD2 GeoJSON saved on disk by build_context_for_project.

    Returns the parsed FeatureCollection. Raises FileNotFoundError if the
    context has never been built for this project.
    """
    if refs_root is None:
        # walk up from this module to repo root, then refs/photogrammetry
        refs_root = Path(__file__).resolve().parent.parent.parent.parent / "refs" / "photogrammetry"
    gj_path = Path(refs_root) / project_id / "bdtopo_buildings.geojson"
    if not gj_path.is_file():
        raise FileNotFoundError(
            f"IGN context not built for project {project_id}: missing {gj_path}. "
            f"Run photogrammetry.build_context.build_context_for_project first."
        )
    with open(gj_path, "r", encoding="utf-8") as f:
        return json.load(f)


def voisins_from_ign_geojson(
    project_id: str,
    origin: GeoOrigin,
    parcel_center_local: tuple[float, float],
    *,
    refs_root: Optional[Path] = None,
    skip_overlap_with: Sequence[tuple[float, float]] | None = None,
    camera_pos_xy: tuple[float, float] | None = None,
    block_camera_sight: bool = False,
    max_distance_m: float = 250.0,
    min_height_m: float = 2.5,
    max_height_m: float = 35.0,
    ground_z_ngf: Optional[float] = None,
) -> list[tuple[list[tuple[float, float]], float, float]]:
    """Load BDTOPO LOD2 buildings from the cached IGN photogrammetry GeoJSON
    and project them to the BM local frame, **using the per-vertex z** (true
    LOD2 roof altitude) instead of the flat `properties.hauteur` field.

    Returns a list of `(footprint_local, height_m, z_base_m)` triples where
    `z_base_m` is the building's ground altitude relative to the parcelle
    centroid's ground (i.e. the elevation difference of the voisin's foot
    relative to our z=0 plane). For Nogent, neighbouring streets vary by a
    few meters of slope; this lets the voisinage sit at correct elevations
    rather than all stamped at z=0.

    Filters mirror voisins_to_local_polygons (own building, distance, height
    band, behind-camera, occluders). When `ground_z_ngf` is None the smallest
    `altitude_minimale_sol` of any feature within 25 m of the parcel centroid
    is used as the reference ground.
    """
    geojson = load_ign_bdtopo_geojson(project_id, refs_root=refs_root)
    features = list(geojson.get("features", []))

    parcel_cx = parcel_cy = None
    if skip_overlap_with:
        parcel_cx = sum(p[0] for p in skip_overlap_with) / len(skip_overlap_with)
        parcel_cy = sum(p[1] for p in skip_overlap_with) / len(skip_overlap_with)

    # 1) Auto-detect ground z if not provided : take the altitude_minimale_sol
    #    of the closest valid feature to the parcel centroid.
    if ground_z_ngf is None:
        best_d = float("inf")
        for f in features:
            props = f.get("properties", {}) or {}
            sol = props.get("altitude_minimale_sol")
            if sol is None or sol <= IGN_Z_SENTINEL_NULL + 1:
                continue
            rings = project_to_parcel_frame(f, origin, parcel_center_local)
            for ring in rings:
                rcx = sum(p[0] for p in ring) / len(ring)
                rcy = sum(p[1] for p in ring) / len(ring)
                d = ((rcx - parcel_center_local[0]) ** 2 +
                     (rcy - parcel_center_local[1]) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    ground_z_ngf = float(sol)
        if ground_z_ngf is None:
            ground_z_ngf = 0.0

    cam_to_proj = None
    cam_forward = None
    if camera_pos_xy is not None and parcel_cx is not None:
        fx = parcel_cx - camera_pos_xy[0]
        fy = parcel_cy - camera_pos_xy[1]
        cam_to_proj = (fx * fx + fy * fy) ** 0.5
        if cam_to_proj > 1e-6:
            cam_forward = (fx / cam_to_proj, fy / cam_to_proj)

    out: list[tuple[list[tuple[float, float]], float, float]] = []
    dropped = {
        "sentinel": 0, "no_z": 0, "own_building": 0, "too_far": 0,
        "too_short": 0, "behind_cam": 0, "occluder": 0,
    }

    for f in features:
        z_range = _feature_z_range(f)
        if z_range is None:
            dropped["sentinel"] += 1
            continue
        z_min, z_max = z_range
        props = f.get("properties", {}) or {}
        sol = props.get("altitude_minimale_sol")
        if sol is not None and sol > IGN_Z_SENTINEL_NULL + 1:
            z_base_ngf = float(sol)
        else:
            z_base_ngf = z_min   # fallback : vertex min
        height_m = max(0.0, z_max - z_base_ngf)
        # Fallback to BDTopo 'hauteur' attribute when z range is degenerate
        # (e.g. parking, single-vertex polygon flagged with hauteur).
        if height_m < 0.5:
            h_attr = props.get("hauteur")
            if h_attr is not None:
                try:
                    height_m = float(h_attr)
                except (TypeError, ValueError):
                    pass
        if height_m < min_height_m:
            dropped["too_short"] += 1
            continue
        if height_m > max_height_m:
            height_m = max_height_m

        z_base_local = z_base_ngf - ground_z_ngf

        rings = project_to_parcel_frame(f, origin, parcel_center_local)
        if not rings:
            dropped["no_z"] += 1
            continue
        for ring in rings:
            rcx = sum(p[0] for p in ring) / len(ring)
            rcy = sum(p[1] for p in ring) / len(ring)
            if skip_overlap_with:
                d_proj = ((rcx - parcel_cx) ** 2 + (rcy - parcel_cy) ** 2) ** 0.5
                if d_proj < 5.0:
                    dropped["own_building"] += 1
                    continue
                if d_proj > max_distance_m:
                    dropped["too_far"] += 1
                    continue
            if cam_to_proj is not None and block_camera_sight and camera_pos_xy is not None:
                vdx = rcx - camera_pos_xy[0]
                vdy = rcy - camera_pos_xy[1]
                d_cam = (vdx * vdx + vdy * vdy) ** 0.5
                if cam_forward is not None and d_cam > 1e-6:
                    forward_dot = (vdx * cam_forward[0] + vdy * cam_forward[1]) / d_cam
                    if forward_dot < 0.25:
                        dropped["behind_cam"] += 1
                        continue
                if d_cam < cam_to_proj * 0.90:
                    dropped["occluder"] += 1
                    continue
            out.append((ring, float(height_m), float(z_base_local)))

    print(
        f"  IGN voisins kept : {len(out)} / {len(features)} "
        f"(ground NGF={ground_z_ngf:.1f} m, drops={dropped})"
    )
    return out
