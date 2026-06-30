#!/usr/bin/env python3
"""Étape 2-3 du pivot : bâtiment détaillé sur la VRAIE emprise fusionnée +
vrais voisins/rues/arbres en 3D. Placement par ARÊTE (pas cardinal) →
universel pour toute parcelle FR, quelle que soit l'orientation.

Sort des configs JSON (quads_by_material + caméra) consommables par
render_from_json_cli (Cycles) puis polish ControlNet — pipeline déjà validé.
"""
import sys, json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/render-service"))
from src.depth_map import Quad  # noqa: E402

HERE = Path(__file__).resolve().parent
SITE = json.loads((HERE / "_real_site/real_site.json").read_text())
OUT = HERE / "configs_real"; OUT.mkdir(exist_ok=True)

# ── footprint réel (simplifié, CCW) ───────────────────────────────────
def _signed_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]; x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return s / 2.0

def _simplify(poly, tol=0.6):
    # drop near-duplicate/collinear points (Douglas-Peucker light)
    from shapely.geometry import Polygon
    p = Polygon(poly).simplify(tol, preserve_topology=True)
    ring = list(p.exterior.coords)[:-1]
    if _signed_area(ring) < 0:
        ring = ring[::-1]   # force CCW
    return ring

PARCEL = _simplify(SITE["fused_local"])
print(f"parcelle réelle simplifiée : {len(PARCEL)} sommets")

# ── empreinte L du SOLVEUR (emprise 57.3%, cour 541m²) ────────────────
# La cour (cœur d'îlot) vient de L_solver_results.json, convertie en frame
# local par convert (cour_local.json). Bâtiment = parcelle − cour, JAMAIS
# 100% de la parcelle (l'ancienne version extrudait toute la parcelle →
# zéro jardin possible + emprise illégale).
from shapely.geometry import Polygon as _Poly
_cour_pts = json.loads((HERE / "_real_site/cour_local.json").read_text())
COUR_POLY = _Poly(_cour_pts).buffer(0)
_L = _Poly(PARCEL).buffer(0).difference(COUR_POLY)
if _L.geom_type == "MultiPolygon":
    _L = max(_L.geoms, key=lambda g: g.area)   # drop slivers ~0m²
_L = _L.simplify(0.25, preserve_topology=True)
FP = list(_L.exterior.coords)[:-1]
if _signed_area(FP) < 0:
    FP = FP[::-1]

# ── carrefour (intersection des 2 rues) + PAN COUPÉ UA.6 3m ───────────
def _find_junction():
    from shapely.geometry import LineString
    import itertools
    parcel = _Poly(PARCEL).buffer(0)
    near = [LineString(r["polyline"]) for r in SITE["roads"]
            if LineString(r["polyline"]).distance(parcel) < 12]
    pts = []
    for a, b in itertools.combinations(near, 2):
        if a.distance(b) < 1.0:
            inter = a.intersection(b.buffer(0.5))
            if not inter.is_empty:
                pts.append(inter.centroid)
    assert pts, "carrefour introuvable"
    return (sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts))

JUNCTION = _find_junction()
print(f"carrefour local : ({JUNCTION[0]:.1f}, {JUNCTION[1]:.1f})")

def _pan_coupe(fp, junction, face=4.5):
    """Coupe le sommet du bâtiment le plus proche du carrefour par un pan de
    `face` m (UA.6). Universel : marche pour tout polygone."""
    k = min(range(len(fp)), key=lambda i: math.hypot(fp[i][0] - junction[0], fp[i][1] - junction[1]))
    v = fp[k]; prev = fp[(k - 1) % len(fp)]; nxt = fp[(k + 1) % len(fp)]
    def along(a, b, d):
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return (a[0] + (b[0] - a[0]) / L * d, a[1] + (b[1] - a[1]) / L * d)
    # demi-angle entre les 2 arêtes → recul le long de chaque arête pour une face de 3m
    d = face / math.sqrt(2.0)   # ~droit ; suffisant à 3m près
    p1 = along(v, prev, d); p2 = along(v, nxt, d)
    return fp[:k] + [p1, p2] + fp[k + 1:]

FP = _pan_coupe(FP, JUNCTION)
print(f"pan coupé 3m appliqué au coin carrefour ({len(FP)} sommets)")
print(f"empreinte L solveur : {len(FP)} sommets, {_L.area:.0f}m² "
      f"({_L.area / _Poly(PARCEL).area * 100:.1f}% emprise), cour {COUR_POLY.area:.0f}m²")

# ── helpers géométrie par arête ───────────────────────────────────────
def edge_normal(a, b):
    ex, ey = b[0] - a[0], b[1] - a[1]
    L = math.hypot(ex, ey) or 1.0
    # CCW polygon → outward normal = (ey,-ex)/L rotated... for CCW, right-hand
    nx, ny = ey / L, -ex / L
    return nx, ny, ex / L, ey / L, L

def extrude_walls(fp, z0, z1):
    out = []
    n = len(fp)
    for i in range(n):
        a, b = fp[i], fp[(i + 1) % n]
        out.append(Quad((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)))
    return out

def _seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy or 1.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

def classify_edges(fp, voisins, party_tol=2.2):
    """Pour chaque arête : mitoyenne (proche d'un voisin → mur aveugle) ou libre (rue/cour → fenêtres).
    Sert l'intimité (pas de baie face voisin, UA1 mitoyennete_sans_baie) + R.111-18."""
    n = len(fp)
    free = []
    for i in range(n):
        a, b = fp[i], fp[(i + 1) % n]
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        nx, ny, _, _, L = edge_normal(a, b)
        # sample a point just OUTSIDE the edge midpoint
        ox, oy = mx + nx * 1.2, my + ny * 1.2
        dmin = 1e9
        for poly, h in voisins:
            for j in range(len(poly)):
                dmin = min(dmin, _seg_dist((ox, oy), poly[j], poly[(j + 1) % len(poly)]))
        free.append(dmin > party_tol)   # True = libre (fenêtres), False = mitoyen (aveugle)
    return free

def windows_on_edges(fp, z_levels, edge_free, win_w=1.2, win_h=1.45, pitch=3.2, recess=-0.05):
    """Fenêtres sur les arêtes LIBRES seulement (rue/cour). Retourne (verre, cadres).
    recess NÉGATIF = vitrage en saillie devant le mur (sinon le mur plein
    extrudé masque totalement le verre en Cycles — bug du rendu v1/v2)."""
    glass, rev = [], []
    n = len(fp)
    for i in range(n):
        if not edge_free[i]:
            continue   # mur mitoyen aveugle → pas de baie (intimité)
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < win_w + 1.0:
            continue
        nwin = max(1, int(L // pitch))
        for (z0, z1) in z_levels:
            for k in range(nwin):
                t = (k + 0.5) / nwin
                cx, cy = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                hw = win_w / 2
                pl = (cx - tx * hw, cy - ty * hw); pr = (cx + tx * hw, cy + ty * hw)
                pli = (pl[0] - nx * recess, pl[1] - ny * recess)
                pri = (pr[0] - nx * recess, pr[1] - ny * recess)
                glass.append(Quad((pli[0], pli[1], z0), (pri[0], pri[1], z0),
                                  (pri[0], pri[1], z1), (pli[0], pli[1], z1)))
                rev.append(Quad((pl[0], pl[1], z1), (pr[0], pr[1], z1), (pri[0], pri[1], z1), (pli[0], pli[1], z1)))
                rev.append(Quad((pl[0], pl[1], z0), (pli[0], pli[1], z0), (pri[0], pri[1], z0), (pr[0], pr[1], z0)))
                rev.append(Quad((pl[0], pl[1], z0), (pl[0], pl[1], z1), (pli[0], pli[1], z1), (pli[0], pli[1], z0)))
                rev.append(Quad((pr[0], pr[1], z0), (pri[0], pri[1], z0), (pri[0], pri[1], z1), (pr[0], pr[1], z1)))
    return glass, rev

def juliet_rails_on_edges(fp, z_floors, edge_free, rail_h=0.85, depth=0.28):
    """Garde-corps juliette fins devant les arêtes LIBRES (pas sur murs mitoyens)."""
    out = []
    n = len(fp)
    for i in range(n):
        if not edge_free[i]:
            continue
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < 2.0:
            continue
        ax, ay = a[0] + nx * depth, a[1] + ny * depth
        bx, by = b[0] + nx * depth, b[1] + ny * depth
        for z in z_floors:
            out.append(Quad((ax, ay, z), (bx, by, z), (bx, by, z + rail_h), (ax, ay, z + rail_h)))
    return out

def mansarde(fp, h_eaves, h_ridge, inset=2.4):
    """Pans mansardés : chaque arête extérieure remonte+rentre (offset par sa
    normale) vers une ligne de faîte intérieure, puis dalle plane. Robuste
    sur polygone tourné/irrégulier (pas de pull vers centroïde)."""
    n = len(fp)
    inner = []   # ridge ring (chaque sommet = moyenne des offsets des 2 arêtes adjacentes)
    edge_off = []
    for i in range(n):
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, _, _, _ = edge_normal(a, b)
        edge_off.append((nx, ny))
    for i in range(n):
        a = fp[i]
        n0 = edge_off[(i - 1) % n]; n1 = edge_off[i]
        ox, oy = (n0[0] + n1[0]) / 2, (n0[1] + n1[1]) / 2
        m = math.hypot(ox, oy) or 1
        inner.append((a[0] - ox / m * inset, a[1] - oy / m * inset))
    slant = []
    for i in range(n):
        a, b = fp[i], fp[(i + 1) % n]
        ai, bi = inner[i], inner[(i + 1) % n]
        slant.append(Quad((a[0], a[1], h_eaves), (b[0], b[1], h_eaves),
                          (bi[0], bi[1], h_ridge), (ai[0], ai[1], h_ridge)))
    top = tri_cap(inner, h_ridge)
    return slant, top

def dormers_on_edges(fp, edge_free, h_eaves, h_ridge, inset=2.4, w=1.4, h=1.3, pitch=4.5):
    """Lucarnes sur les pans mansardés des façades LIBRES (rue/cour)."""
    out = []
    n = len(fp)
    for i in range(n):
        if not edge_free[i]:
            continue
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < w + 1.0:
            continue
        ndorm = max(1, int(L // pitch))
        zc = (h_eaves + h_ridge) / 2
        for k in range(ndorm):
            t = (k + 0.5) / ndorm
            cx, cy = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
            # petite boîte qui ressort du pan
            off = inset * 0.45
            px, py = cx - nx * off, cy - ny * off
            hw = w / 2
            l = (px - tx * hw, py - ty * hw); r = (px + tx * hw, py + ty * hw)
            lo = (l[0] + nx * 0.6, l[1] + ny * 0.6); ro = (r[0] + nx * 0.6, r[1] + ny * 0.6)
            out.append(Quad((lo[0], lo[1], zc - h/2), (ro[0], ro[1], zc - h/2), (ro[0], ro[1], zc + h/2), (lo[0], lo[1], zc + h/2)))
            out.append(Quad((l[0], l[1], zc + h/2), (r[0], r[1], zc + h/2), (ro[0], ro[1], zc + h/2), (lo[0], lo[1], zc + h/2)))
    return out

def tri_cap(fp, z, downward=False):
    """Dalle horizontale pour polygone QUELCONQUE (concave inclus) : Delaunay
    filtré par containment. Remplace les fans centroïde qui produisaient des
    triangles inversés/chevauchants (slivers noirs) sur les formes en L."""
    from shapely.geometry import Polygon
    from shapely.ops import triangulate
    if len(fp) < 3:
        return []
    poly = Polygon(fp).buffer(0)
    if poly.is_empty or poly.area < 0.5:
        return []
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    out = []
    for t in triangulate(poly):
        c = t.representative_point()
        if not poly.contains(c):
            continue
        ring = list(t.exterior.coords)[:-1]
        if (_signed_area(ring) < 0) != downward:   # CCW vu de dessus → normale +Z
            ring = ring[::-1]
        a, b, c3 = ring
        out.append(Quad((a[0], a[1], z), (b[0], b[1], z), (c3[0], c3[1], z), (c3[0], c3[1], z)))
    return out

def flat_roof(fp, z):
    return tri_cap(fp, z)

def chimneys(fp, z, n=5, size=0.9, h=1.7):
    """Cheminées sur le faîte : échantillonnées sur l'anneau intérieur du
    bâtiment (buffer −2.5m), PAS autour du centroïde (qui tombe dans la cour
    pour un L)."""
    from shapely.geometry import Polygon
    ring = Polygon(fp).buffer(0).buffer(-2.5)
    if ring.is_empty:
        return []
    if ring.geom_type == "MultiPolygon":
        ring = max(ring.geoms, key=lambda g: g.area)
    ext = ring.exterior
    out = []
    for k in range(n):
        p = ext.interpolate((k + 0.5) / n, normalized=True)
        x, y = p.x, p.y
        s = size / 2
        for (dx0, dy0, dx1, dy1) in [(-s,-s,s,-s),(s,-s,s,s),(s,s,-s,s),(-s,s,-s,-s)]:
            out.append(Quad((x+dx0,y+dy0,z),(x+dx1,y+dy1,z),(x+dx1,y+dy1,z+h),(x+dx0,y+dy0,z+h)))
    return out

# ── voisins réels 3D : habillés (fenêtres + toits + bandeaux) ─────────
def _voisin_windows(poly, h, recess=0.06, win_w=1.15, win_h=1.35,
                    pitch=2.9, sill0=1.1, floor_h=2.9, max_in_view=True):
    """Rangées de fenêtres (verre en LÉGÈRE saillie) + leurs feuillures sombres
    sur les façades d'un voisin. Le verre est posé devant le mur (recess>0)
    sinon le mur plein le masque en Cycles (même bug que windows_on_edges).
    Retourne (glass, frames)."""
    glass, frames = [], []
    nfloor = max(1, int((h - sill0) // floor_h))
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ex, ey) or 1.0
        if L < win_w + 0.8:
            continue
        tx, ty = ex / L, ey / L
        nx, ny = ey / L, -ex / L          # normale (CCW → extérieur), poly BDTopo orientation variable
        nwin = max(1, int(L // pitch))
        for fl in range(nfloor):
            zc = sill0 + fl * floor_h
            z0, z1 = zc, min(zc + win_h, h - 0.3)
            if z1 - z0 < 0.6:
                continue
            for k in range(nwin):
                t = (k + 0.5) / nwin
                cx, cy = a[0] + t * ex, a[1] + t * ey
                hw = win_w / 2
                pl = (cx - tx * hw, cy - ty * hw); pr = (cx + tx * hw, cy + ty * hw)
                # verre en saillie des DEUX côtés (orientation du poly inconnue)
                for s in (recess, -recess):
                    pli = (pl[0] + nx * s, pl[1] + ny * s)
                    pri = (pr[0] + nx * s, pr[1] + ny * s)
                    glass.append(Quad((pli[0], pli[1], z0), (pri[0], pri[1], z0),
                                      (pri[0], pri[1], z1), (pli[0], pli[1], z1)))
    return glass, frames


def _voisin_pitched_roof(poly, h_eaves, h_ridge, inset=1.6):
    """Toit 2 pentes simple : chaque arête remonte+rentre vers une ligne de
    faîte intérieure (réutilise la logique de mansarde mais 1 seule pente).
    Pour pavillons meulière nogentais R+2/3 → silhouette pentue lisible au canny."""
    n = len(poly)
    edge_off = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ex, ey) or 1.0
        edge_off.append((ey / L, -ex / L))
    inner = []
    for i in range(n):
        a = poly[i]
        n0 = edge_off[(i - 1) % n]; n1 = edge_off[i]
        ox, oy = (n0[0] + n1[0]) / 2, (n0[1] + n1[1]) / 2
        m = math.hypot(ox, oy) or 1.0
        inner.append((a[0] - ox / m * inset, a[1] - oy / m * inset))
    slant = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ai, bi = inner[i], inner[(i + 1) % n]
        slant.append(Quad((a[0], a[1], h_eaves), (b[0], b[1], h_eaves),
                          (bi[0], bi[1], h_ridge), (ai[0], ai[1], h_ridge)))
    slant += tri_cap(inner, h_ridge)
    return slant


def _voisin_bandeaux(poly, h, sill0=1.1, floor_h=2.9, proud=0.05):
    """Cordons d'étage fins (bandeaux horizontaux saillants) → rythme de façade
    visible au canny sur les immeubles. Léger débord des 2 côtés du mur."""
    out = []
    n = len(poly)
    nfloor = max(1, int((h - sill0) // floor_h))
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ex, ey) or 1.0
        if L < 2.0:
            continue
        nx, ny = ey / L, -ex / L
        for fl in range(1, nfloor):
            z = sill0 + fl * floor_h - 0.35
            for s in (proud, -proud):
                a2 = (a[0] + nx * s, a[1] + ny * s); b2 = (b[0] + nx * s, b[1] + ny * s)
                out.append(Quad((a2[0], a2[1], z), (b2[0], b2[1], z),
                                (b2[0], b2[1], z + 0.12), (a2[0], a2[1], z + 0.12)))
    return out


def _voisin_chimneys(poly, h_ridge, n=2, size=0.7, h=1.4):
    """Cheminées sur le faîte d'un toit pentu de voisin : petits prismes posés
    sur l'anneau intérieur du bâtiment (buffer −1.4m → sur la ligne de faîte,
    pas dans le vide). Signature des toits anciens nogentais (meulière/crème)."""
    from shapely.geometry import Polygon
    ring = Polygon(poly).buffer(0).buffer(-1.4)
    if ring.is_empty:
        return []
    if ring.geom_type == "MultiPolygon":
        ring = max(ring.geoms, key=lambda g: g.area)
    ext = ring.exterior
    out = []
    for k in range(n):
        p = ext.interpolate((k + 0.5) / n, normalized=True)
        out += _box(p.x, p.y, size, size, h_ridge - 0.2, h_ridge + h)
    return out


def _voisin_chainages(poly, h, w=0.40, proud=0.06):
    """Chaînages / encadrements BRIQUE en saillie aux ANGLES de la façade —
    évoque la meulière nogentaise (pierre brune + chaînages brique rouge,
    survey_3/4). Quads fins verticaux à chaque sommet du polygone (les 2
    arêtes adjacentes), légèrement en saillie + matériau brique au call site."""
    out = []
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b_next = poly[(i + 1) % n]
        b_prev = poly[(i - 1) % n]
        for b in (b_next, b_prev):
            ex, ey = b[0] - a[0], b[1] - a[1]
            L = math.hypot(ex, ey) or 1.0
            if L < 1.5:
                continue
            tx, ty = ex / L, ey / L
            nx, ny = ey / L, -ex / L
            # petit pilier vertical du sol au sommet, en léger débord des 2 côtés
            for s in (proud, -proud):
                p0 = (a[0] + nx * s, a[1] + ny * s)
                p1 = (a[0] + tx * w + nx * s, a[1] + ty * w + ny * s)
                out.append(Quad((p0[0], p0[1], 0.3), (p1[0], p1[1], 0.3),
                                (p1[0], p1[1], h - 0.2), (p0[0], p0[1], h - 0.2)))
    return out


def voisins_3d(voisins):
    """Voisins BD TOPO en 3D HABILLÉS pour qu'ils lisent comme de VRAIS immeubles
    nogentais après le canny (au lieu de boîtes grises fantômes) :
      - volumes extrudés à la hauteur BDTopo réelle (donnée RÉELLE, jamais inventée)
      - rangées de FENÊTRES (verre en saillie) sur chaque façade
      - TOIT : MAJORITÉ pentue tuile/ardoise + cheminées (caractère nogentais) ;
        seuls quelques immeubles modernes minoritaires gardent un toit plat
      - MEULIÈRE (~35%) : façade brune (voisin) + chaînages BRIQUE aux angles
      - ENDUIT CRÈME (~40%) : pierre/enduit clair, toit pentu tuile ou ardoise
      - bandeaux d'étage sur les immeubles → rythme de façade
    Palette VARIÉE déterministe (ambiance réelle survey_0/2/3/4, AMBIANCE_REELLE.md).
    Priorité d'habillage aux voisins EN VUE depuis le carrefour ; lointains simples."""
    from shapely.geometry import Polygon, Point
    parcel = _Poly(PARCEL).buffer(0)
    jx, jy = JUNCTION
    out = {"pierre_taille": [], "brique_rouge": [], "enduit_blanc": [],
           "zinc_anthracite": [], "voisin": [], "verre": []}

    # tri déterministe par distance au carrefour → les proches reçoivent l'index
    # le plus bas (et le plus de soin) ; clé stable = pas de random non-repro.
    kept = []
    for poly, h in voisins:
        try:
            vp = Polygon(poly).buffer(0)
            if vp.is_empty:
                continue
            if vp.intersection(parcel).area / vp.area > 0.5:
                continue   # bâtiment démoli (sur la parcelle du projet)
            d = vp.distance(parcel.exterior)
            if 0.005 < d < 0.6:   # WELD mitoyen (imprécision BD TOPO → ruelle hallucinée)
                from shapely.ops import nearest_points
                p_v, p_p = nearest_points(vp, parcel.exterior)
                dx, dy = p_p.x - p_v.x, p_p.y - p_v.y
                poly = [(x + dx, y + dy) for x, y in poly]
                vp = Polygon(poly).buffer(0)
        except Exception:
            continue
        c = vp.representative_point()
        dist_carr = math.hypot(c.x - jx, c.y - jy)
        kept.append((dist_carr, poly, max(3.0, min(h, 20.0))))
    kept.sort(key=lambda t: t[0])

    for vi, (dist_carr, poly, h) in enumerate(kept):
        in_view = dist_carr < 60.0      # proche du carrefour / le long des 2 rues
        # ── palette + typologie déterministes (ambiance réelle survey_0/2/3/4) ──
        # cycle de 5 : 2 meulière / 2 crème / 1 moderne blanc à toit plat
        #   → ~40% meulière, ~40% crème, ~20% moderne (minoritaire, toit plat).
        # Le caractère nogentais = MÉLANGE meulière+brique + enduit crème, toits
        # PENTUS tuile/ardoise + cheminées. Les blocs blancs plats sont l'exception.
        bucket = vi % 5
        meuliere = bucket in (0, 1)
        modern_flat = (bucket == 4) and h >= 11.0   # seul l'immeuble haut peut être moderne plat
        roof_tile = (vi % 2 == 0)                    # alternance tuile terracotta / ardoise-zinc
        roof_m = "brique_rouge" if roof_tile else "zinc_anthracite"

        if meuliere:
            wall_m = "voisin"                        # pierre brune mouchetée (meulière)
        elif bucket == 4:                            # moderne / crème clair
            wall_m = "enduit_blanc"
        else:                                        # enduit crème ancien
            wall_m = "pierre_taille"

        # murs extrudés (volume réel)
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            out[wall_m].append(Quad((a[0], a[1], 0), (b[0], b[1], 0),
                                    (b[0], b[1], h), (a[0], a[1], h)))

        # ── chaînages BRIQUE aux angles : signature meulière nogentaise ──
        if meuliere and in_view:
            out["brique_rouge"] += _voisin_chainages(poly, h)

        # ── toit : PENTU pour la majorité (tuile/ardoise) + cheminées ; ──
        #    seuls les rares immeubles modernes gardent un toit plat ────────
        if modern_flat:
            out["zinc_anthracite"] += tri_cap(poly, h)
            out["zinc_anthracite"] += _voisin_bandeaux(poly, h + 0.001, sill0=h - 0.4,
                                                       floor_h=99.0, proud=0.10)  # acrotère
        else:
            ridge_h = h + (2.4 if h < 9.5 else 2.9)  # faîte plus haut sur immeubles
            out[roof_m] += _voisin_pitched_roof(poly, h, ridge_h)
            if in_view:
                out[roof_m] += _voisin_chimneys(poly, ridge_h)

        # ── habillage façade (priorité aux voisins EN VUE) ──
        if in_view:
            glass, _ = _voisin_windows(poly, h, win_w=1.15, win_h=1.35,
                                       pitch=2.9, sill0=1.1, floor_h=2.9)
            out["verre"] += glass
            if h >= 9.5:   # immeuble : cordons d'étage (rythme de façade)
                out[wall_m] += _voisin_bandeaux(poly, h)
        elif dist_carr < 75.0:
            # demi-lointain : fenêtres seules, trame plus lâche
            glass, _ = _voisin_windows(poly, h, win_w=1.1, pitch=3.6,
                                       sill0=1.3, floor_h=3.0)
            out["verre"] += glass
        # au-delà : volume + toit nus suffisent (lointain)
    return out

def trees_3d(trees):
    """Feuillage : 3 plans verticaux croisés en étoile (X + diagonale) qui
    forment un volume foliaire arrondi, plus une couronne haute. Matériau
    vegetation. (Le tronc bois est émis séparément par tree_trunks_3d.)"""
    import math as _m
    out = []
    for i, (x, y) in enumerate(trees):
        r = 2.1 + (i % 3) * 0.3           # rayon canopée varié
        hb = 2.6                          # base du feuillage (sous = tronc nu)
        ht = 5.6 + (i % 2) * 0.7          # sommet
        # 3 plans verticaux croisés (0°, 60°, 120°) : silhouette de profil rue
        for a in (0.0, _m.pi/3, 2*_m.pi/3):
            dx, dy = _m.cos(a)*r, _m.sin(a)*r
            out.append(Quad((x-dx,y-dy,hb),(x+dx,y+dy,hb),
                            (x+dx,y+dy,ht),(x-dx,y-dy,ht)))
        # disques horizontaux empilés : la canopée lit en MASSE vue de dessus
        # (POV carrefour haut) — profil arrondi (petit en bas/haut, large milieu)
        layers = [(hb+0.3, r*0.62), ((hb+ht)/2-0.3, r*0.98),
                  ((hb+ht)/2+0.4, r*1.0), (ht-0.4, r*0.74), (ht, r*0.4)]
        for z, rr in layers:
            jx = (i % 2) * 0.15            # léger décalage organique
            out.append(Quad((x-rr,y-rr,z),(x+rr,y-rr,z),
                            (x+rr,y+rr,z),(x-rr,y+rr,z)))
    return out

def tree_trunks_3d(trees):
    """Troncs : fin prisme à 4 faces (~0.32 m) du sol jusqu'au feuillage.
    Matériau bois_clair (assigné au call site)."""
    out = []
    for i, (x, y) in enumerate(trees):
        w = 0.16                          # demi-largeur tronc
        htop = 2.7                        # rejoint la base du feuillage
        out += _box(x, y, w*2, w*2, 0.0, htop)
    return out

def roads_3d(roads):
    out = []
    for ri, r in enumerate(roads):
        pl = r["polyline"]; w = max(2.5, (r.get("chaussee_m") or 4)) / 2
        z = 0.02 + 0.0008 * ri   # z distinct par route : pas de z-fighting aux carrefours
        for i in range(len(pl) - 1):
            a, b = pl[i], pl[i + 1]
            ex, ey = b[0]-a[0], b[1]-a[1]; L = math.hypot(ex, ey) or 1
            nx, ny = ey/L*w, -ex/L*w
            out.append(Quad((a[0]+nx,a[1]+ny,z),(b[0]+nx,b[1]+ny,z),(b[0]-nx,b[1]-ny,z),(a[0]-nx,a[1]-ny,z)))
        # patch carré à chaque sommet intérieur : bouche la fente en coin
        # laissée par 2 rectangles de segments aux coudes de la polyligne.
        # z − epsilon : coplanaire avec ses propres segments = faces
        # superposées → noir Cycles (vu sur probe v2cible).
        zp = z - 0.0004
        for i in range(1, len(pl) - 1):
            x, y = pl[i]
            out.append(Quad((x-w, y-w, zp), (x+w, y-w, zp), (x+w, y+w, zp), (x-w, y+w, zp)))
    return out

def ql(qs): return [[list(q.v0), list(q.v1), list(q.v2), list(q.v3)] for q in qs]

# ── cour vivante + jardins privatifs RDC (cœur d'îlot) ────────────────
def cour_edges(fp, cour_poly, tol=1.2):
    """Indices des arêtes du bâtiment donnant sur la cour (sample extérieur)."""
    idx = []
    for i in range(len(fp)):
        a, b = fp[i], fp[(i + 1) % len(fp)]
        nx, ny, _, _, L = edge_normal(a, b)
        if L < 1.0:
            continue
        mx, my = (a[0] + b[0]) / 2 + nx * tol, (a[1] + b[1]) / 2 + ny * tol
        from shapely.geometry import Point
        if cour_poly.contains(Point(mx, my)):
            idx.append(i)
    return idx

def _massif(cx, cy, ux, uy, vx, vy, half_u, half_v, hedge_z=0.55):
    """Une haie taillée RECTANGULAIRE basse et nette (tout végétal), alignée sur
    le repère (u,v) de la cour — même lecture verte que la bande le long des
    façades (qui rend bien), pas de pierre qui blanchit en bloc béton.
    Retourne (quads_pierre, quads_vegetation) ; quads_pierre vide.
    Lecture 'haie/massif de jardin résidentiel', pas 'bac en gradins'."""
    def corners(hu, hv):
        return [(cx - ux*hu - vx*hv, cy - uy*hu - vy*hv),
                (cx + ux*hu - vx*hv, cy + uy*hu - vy*hv),
                (cx + ux*hu + vx*hv, cy + uy*hu + vy*hv),
                (cx - ux*hu + vx*hv, cy - uy*hu + vy*hv)]
    base = corners(half_u, half_v)
    top = corners(half_u - 0.10, half_v - 0.10)      # léger fruit (volume taillé)
    veg = []
    veg.append(Quad((top[0][0], top[0][1], hedge_z), (top[1][0], top[1][1], hedge_z),
                    (top[2][0], top[2][1], hedge_z), (top[3][0], top[3][1], hedge_z)))  # dessus
    for k in range(4):
        a, b = base[k], base[(k+1) % 4]
        ta, tb = top[k], top[(k+1) % 4]
        veg.append(Quad((a[0], a[1], 0.0), (b[0], b[1], 0.0), (tb[0], tb[1], hedge_z), (ta[0], ta[1], hedge_z)))  # flanc
    return [], veg


def cour_jardins(fp, cour_poly, garden_depth=4.5, hedge_h=1.15, pitch=6.0):
    """Cour-jardin COHÉRENTE en cœur d'îlot : UN seul niveau de pelouse au sol,
    une allée centrale pavée, et quelques massifs/haies RÉGULIERS bas alignés
    (plate-bandes paysagères, tout végétal), + arbres posés proprement dans la
    pelouse. Plus de haies/bacs verticaux à hauteurs aléatoires.
    Retourne dict matériau → [Quad]."""
    from shapely.geometry import Polygon, LineString, Point
    L_poly = Polygon(fp).buffer(0)
    path = cour_poly.intersection(L_poly.buffer(2.0)).buffer(0)        # bande pavée 2.0m le long des façades
    gazon = cour_poly.difference(L_poly.buffer(2.0)).buffer(0)
    out = {"pavers_concrete": [], "vegetation": [], "bois_clair": [], "pierre_taille": []}
    for g in (path.geoms if path.geom_type == "MultiPolygon" else [path]):
        out["pavers_concrete"] += tri_cap(list(g.exterior.coords)[:-1], 0.04)
    # sol unique de la cour : pelouse à plat (z léger au-dessus de la dalle)
    for g in (gazon.geoms if gazon.geom_type == "MultiPolygon" else [gazon]):
        out["vegetation"] += tri_cap(list(g.exterior.coords)[:-1], 0.03)

    # repère orienté de la cour (axe long = u, axe court = v) via OBB
    gg = max(gazon.geoms, key=lambda g: g.area) if gazon.geom_type == "MultiPolygon" else gazon
    if gg.is_empty or gg.area < 6.0:
        out["vegetation"] += trees_3d([(cour_poly.centroid.x, cour_poly.centroid.y)]) if not cour_poly.is_empty else []
        return out
    obb = gg.minimum_rotated_rectangle
    ob = list(obb.exterior.coords)[:4]
    e0 = (ob[1][0]-ob[0][0], ob[1][1]-ob[0][1]); l0 = math.hypot(*e0) or 1.0
    e1 = (ob[2][0]-ob[1][0], ob[2][1]-ob[1][1]); l1 = math.hypot(*e1) or 1.0
    if l0 >= l1:
        ux, uy = e0[0]/l0, e0[1]/l0; Lu = l0; Lv = l1
    else:
        ux, uy = e1[0]/l1, e1[1]/l1; Lu = l1; Lv = l0
    vx, vy = -uy, ux                                  # axe court orthogonal
    cx0, cy0 = gg.centroid.x, gg.centroid.y

    # allée centrale pavée le long de l'axe long (1.4m de large)
    aw = 1.4
    a_half = max(2.0, Lu/2 - 1.0)
    allee = Polygon([(cx0 - ux*a_half - vx*aw/2, cy0 - uy*a_half - vy*aw/2),
                     (cx0 + ux*a_half - vx*aw/2, cy0 + uy*a_half - vy*aw/2),
                     (cx0 + ux*a_half + vx*aw/2, cy0 + uy*a_half + vy*aw/2),
                     (cx0 - ux*a_half + vx*aw/2, cy0 - uy*a_half + vy*aw/2)]).buffer(0)
    allee = allee.intersection(gg.buffer(-0.3))
    for g in (allee.geoms if allee.geom_type == "MultiPolygon" else [allee]):
        if not g.is_empty and g.area > 0.5:
            out["pavers_concrete"] += tri_cap(list(g.exterior.coords)[:-1], 0.045)

    # massifs réguliers ALIGNÉS : 2 rangées (de part et d'autre de l'allée),
    # pas constant le long de l'axe long → grille ordonnée, lisible jardin.
    cell = 3.6                                        # pas longitudinal régulier
    n_cells = max(2, int((Lu - 2.0) // cell))
    half_u = cell * 0.32                              # massif ~2.3m de long
    half_v = min(1.6, Lv * 0.20)                      # ~3.2m de large max
    voff = (Lv * 0.5 - half_v - 0.9)                  # rangée décalée du centre
    voff = max(aw/2 + half_v + 0.3, voff)             # au-delà de l'allée
    for k in range(n_cells):
        t = (k + 0.5) / n_cells - 0.5                 # centré
        bu = t * (n_cells * cell)
        bcx, bcy = cx0 + ux*bu, cy0 + uy*bu
        for sgn in (+1.0, -1.0):
            mcx, mcy = bcx + vx*voff*sgn, bcy + vy*voff*sgn
            test = Polygon([(mcx - ux*half_u - vx*half_v, mcy - uy*half_u - vy*half_v),
                            (mcx + ux*half_u - vx*half_v, mcy + uy*half_u - vy*half_v),
                            (mcx + ux*half_u + vx*half_v, mcy + uy*half_u + vy*half_v),
                            (mcx - ux*half_u + vx*half_v, mcy - uy*half_u + vy*half_v)])
            # centroïde dans la pelouse + >=92% du massif sur le gazon : autorise
            # plus de plate-bandes alignées tout en restant à l'intérieur, propre.
            if not gg.buffer(-0.3).contains(Point(mcx, mcy)):
                continue
            if test.intersection(gg).area < 0.92 * test.area:
                continue
            stone, veg = _massif(mcx, mcy, ux, uy, vx, vy, half_u, half_v)
            out["pierre_taille"] += stone
            out["vegetation"] += veg

    # arbres posés proprement dans la pelouse (cœur de cour, jamais côté rue)
    pts = []
    for k in range(n_cells + 1):
        t = k / n_cells - 0.5
        bu = t * (n_cells * cell)
        cand = (cx0 + ux*bu, cy0 + uy*bu)
        if gg.buffer(-1.0).contains(Point(cand)) and all(math.hypot(cand[0]-p[0], cand[1]-p[1]) > 6.5 for p in pts):
            pts.append(cand)
    pts = pts[:3]
    if pts:
        out["vegetation"] += trees_3d(pts)
        out["bois_clair"] += tree_trunks_3d(pts)
    return out

# ── balcons filants (dalle + garde-corps) sur arêtes libres ───────────
def _free_runs(fp, edge_free):
    """Runs maximaux d'arêtes libres consécutives (indices), gère le wrap."""
    n = len(fp)
    if all(edge_free): return [list(range(n))]
    runs, cur = [], []
    start = next((i for i in range(n) if not edge_free[i]), 0)
    for k in range(n):
        i = (start + k) % n
        if edge_free[i]:
            cur.append(i)
        elif cur:
            runs.append(cur); cur = []
    if cur: runs.append(cur)
    return runs

def balcons_filants_edges(fp, z_floors, edge_free, depth=1.5, slab_t=0.16, rail_h=1.05, end_inset=0.12):
    """Balcon filant CONTINU qui TOURNE autour des angles (onglet/miter aux
    coins entre arêtes libres consécutives → plus de séparation au pan coupé).
    Dalle béton en porte-à-faux + garde-corps fer forgé."""
    slabs, rails = [], []
    n = len(fp)
    for run in _free_runs(fp, edge_free):
        # longueur totale du run trop courte → skip
        if sum(math.hypot(fp[(i+1)%n][0]-fp[i][0], fp[(i+1)%n][1]-fp[i][1]) for i in run) < 3.0:
            continue
        # sommets du run : v[0]..v[m]
        verts = [fp[run[0]]] + [fp[(i+1)%n] for i in run]
        m = len(verts)
        # normale extérieure par arête du run
        enorm = []
        for j in range(m-1):
            nx, ny, _, _, _ = edge_normal(verts[j], verts[j+1]); enorm.append((nx, ny))
        # direction d'offset par sommet : extrémités = normale arête ; interne = bissectrice (miter)
        off = []
        for j in range(m):
            if j == 0:   ox, oy = enorm[0]
            elif j == m-1: ox, oy = enorm[-1]
            else:
                ax, ay = enorm[j-1]; bx, by = enorm[j]
                ox, oy = ax+bx, ay+by; ln = math.hypot(ox,oy) or 1.0
                # miter : rallonge pour que les chants se rejoignent à l'angle
                cosang = max(0.35, (ax*bx+ay*by + 1)/2) ** 0.5
                ox, oy = ox/ln/cosang, oy/ln/cosang
            off.append((ox, oy))
        inner = verts
        outer = [(verts[j][0]+off[j][0]*depth, verts[j][1]+off[j][1]*depth) for j in range(m)]
        for z in z_floors:
            z0, z1 = z - slab_t, z
            for j in range(m-1):
                ia, ib = inner[j], inner[j+1]; oa, ob = outer[j], outer[j+1]
                slabs.append(Quad((ia[0],ia[1],z1),(ib[0],ib[1],z1),(ob[0],ob[1],z1),(oa[0],oa[1],z1)))  # dessus
                slabs.append(Quad((ia[0],ia[1],z0),(oa[0],oa[1],z0),(ob[0],ob[1],z0),(ib[0],ib[1],z0)))  # dessous
                slabs.append(Quad((oa[0],oa[1],z0),(oa[0],oa[1],z1),(ob[0],ob[1],z1),(ob[0],ob[1],z0)))  # chant ext (continu)
            # chants des 2 extrémités
            for ii in (0, m-1):
                inr, ou = inner[ii], outer[ii]
                slabs.append(Quad((inr[0],inr[1],z0),(inr[0],inr[1],z1),(ou[0],ou[1],z1),(ou[0],ou[1],z0)))
            # garde-corps continu le long de l'arête extérieure
            for rz0, rz1 in ((z + rail_h - 0.06, z + rail_h), (z + 0.45, z + 0.49)):
                for j in range(m-1):
                    oa, ob = outer[j], outer[j+1]
                    rails.append(Quad((oa[0],oa[1],rz0),(ob[0],ob[1],rz0),(ob[0],ob[1],rz1),(oa[0],oa[1],rz1)))
    return slabs, rails

# ── façade « cible A » : RDC commerce, bandeaux, corniche, soubassement ─
def juliets_per_window(fp, z_levels, edges_idx, pitch=3.2, win_w=1.2, rail_h=0.78, depth=0.14):
    """Garde-corps fins PAR FENÊTRE (pas pleine façade → bandes noires moches).
    Même placement que windows_on_edges (pitch identique)."""
    out = []
    n = len(fp)
    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < win_w + 1.0:
            continue
        nwin = max(1, int(L // pitch))
        for (z0, _z1) in z_levels:
            for k in range(nwin):
                t = (k + 0.5) / nwin
                cx, cy = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                hw = win_w / 2 + 0.08
                p0 = (cx - tx * hw + nx * depth, cy - ty * hw + ny * depth)
                p1 = (cx + tx * hw + nx * depth, cy + ty * hw + ny * depth)
                out.append(Quad((p0[0], p0[1], z0 - 0.05), (p1[0], p1[1], z0 - 0.05),
                                (p1[0], p1[1], z0 + rail_h - 0.45), (p0[0], p0[1], z0 + rail_h - 0.45)))
    return out

def chainages_d_angle(fp, edges_idx, h, w=0.45, proud=0.03, min_angle_deg=25.0):
    """Chaînages brique aux VRAIS angles des façades RUE seulement (angle
    entre arêtes > min_angle) — pas aux micro-cassures cadastrales, qui
    encombraient le coin entrée (feedback harmonie 2026-06-11)."""
    out = []
    n = len(fp)

    def vertex_angle(k):
        p0, p1, p2 = fp[(k - 1) % n], fp[k], fp[(k + 1) % n]
        a1 = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        a2 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        d = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
        return math.degrees(d)

    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < 2.5:
            continue
        corners = []
        if vertex_angle(i) >= min_angle_deg:
            corners.append((a[0], a[1], 1))
        if vertex_angle((i + 1) % n) >= min_angle_deg:
            corners.append((b[0], b[1], -1))
        for (px, py, sgn) in corners:
            q0 = (px + nx * proud, py + ny * proud)
            q1 = (px + tx * w * sgn + nx * proud, py + ty * w * sgn + ny * proud)
            out.append(Quad((q0[0], q0[1], 0.4), (q1[0], q1[1], 0.4),
                            (q1[0], q1[1], h), (q0[0], q0[1], h)))
    return out

def main_entrance(fp, junction, h_rdc, w_door=3.0):
    """ENTRÉE RÉSIDENTIELLE marquée au pan coupé : hall vitré quasi pleine
    hauteur RDC + 2 piliers pierre d'encadrement + MARQUISE (auvent) en
    porte-à-faux → lit clairement comme l'entrée, pas un commerce.
    Retourne dict matériau → quads."""
    k = min(range(len(fp)), key=lambda i: math.hypot(
        (fp[i][0] + fp[(i + 1) % len(fp)][0]) / 2 - junction[0],
        (fp[i][1] + fp[(i + 1) % len(fp)][1]) / 2 - junction[1]))
    a, b = fp[k], fp[(k + 1) % len(fp)]
    nx, ny, tx, ty, L = edge_normal(a, b)
    cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    hw = min(w_door, L - 0.8) / 2
    h_hall = h_rdc - 0.15
    pr = 0.05
    g0 = (cx - tx * hw + nx * pr, cy - ty * hw + ny * pr)
    g1 = (cx + tx * hw + nx * pr, cy + ty * hw + ny * pr)
    verre = [Quad((g0[0], g0[1], 0.0), (g1[0], g1[1], 0.0),
                  (g1[0], g1[1], h_hall), (g0[0], g0[1], h_hall))]
    # 2 piliers pierre d'encadrement
    piers = []
    for (px, py, sgn) in ((cx - tx*(hw+0.28), cy - ty*(hw+0.28), 1),
                          (cx + tx*(hw+0.28), cy + ty*(hw+0.28), 1)):
        q0 = (px - tx*0.28 + nx*0.07, py - ty*0.28 + ny*0.07)
        q1 = (px + tx*0.28 + nx*0.07, py + ty*0.28 + ny*0.07)
        piers.append(Quad((q0[0],q0[1],0.0),(q1[0],q1[1],0.0),(q1[0],q1[1],h_rdc),(q0[0],q0[1],h_rdc)))
    # MARQUISE : dalle fine en porte-à-faux au-dessus de la porte (~2.6m)
    zc0, zc1 = h_hall - 0.55, h_hall - 0.40
    d = 1.3
    m0 = (cx - tx*(hw+0.4), cy - ty*(hw+0.4)); m1 = (cx + tx*(hw+0.4), cy + ty*(hw+0.4))
    m0o = (m0[0]+nx*d, m0[1]+ny*d); m1o = (m1[0]+nx*d, m1[1]+ny*d)
    canopy = [
        Quad((m0[0],m0[1],zc1),(m1[0],m1[1],zc1),(m1o[0],m1o[1],zc1),(m0o[0],m0o[1],zc1)),  # dessus
        Quad((m0[0],m0[1],zc0),(m0o[0],m0o[1],zc0),(m1o[0],m1o[1],zc0),(m1[0],m1[1],zc0)),  # dessous
        Quad((m0o[0],m0o[1],zc0),(m0o[0],m0o[1],zc1),(m1o[0],m1o[1],zc1),(m1o[0],m1o[1],zc0)),  # chant
    ]
    return {"verre": verre, "pierre_taille": piers, "balcon_concrete": canopy}

def storefronts_on_edges(fp, edges_idx, h_rdc, travee=4.5, pilier_w=0.55):
    """RDC commerce sur arêtes RUE : vitrines toute hauteur entre piliers
    pierre + entablature anthracite au-dessus (cf. cible_A_ultra_safe)."""
    glass, piliers, entab = [], [], []
    n = len(fp)
    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < 3.0:
            continue
        ntr = max(1, int(L // travee))
        for k in range(ntr + 1):     # piliers aux bornes de travées
            t = k / ntr
            cx, cy = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
            hw = pilier_w / 2
            p0 = (cx - tx * hw + nx * 0.06, cy - ty * hw + ny * 0.06)
            p1 = (cx + tx * hw + nx * 0.06, cy + ty * hw + ny * 0.06)
            piliers.append(Quad((p0[0], p0[1], 0.0), (p1[0], p1[1], 0.0),
                                (p1[0], p1[1], h_rdc - 0.5), (p0[0], p0[1], h_rdc - 0.5)))
        for k in range(ntr):         # vitrines pleine travée
            t0 = (k + 0.0) / ntr; t1 = (k + 1.0) / ntr
            g0 = (a[0] + t0 * (b[0] - a[0]) + tx * (pilier_w / 2 + 0.05) + nx * 0.03,
                  a[1] + t0 * (b[1] - a[1]) + ty * (pilier_w / 2 + 0.05) + ny * 0.03)
            g1 = (a[0] + t1 * (b[0] - a[0]) - tx * (pilier_w / 2 + 0.05) + nx * 0.03,
                  a[1] + t1 * (b[1] - a[1]) - ty * (pilier_w / 2 + 0.05) + ny * 0.03)
            glass.append(Quad((g0[0], g0[1], 0.35), (g1[0], g1[1], 0.35),
                              (g1[0], g1[1], h_rdc - 0.55), (g0[0], g0[1], h_rdc - 0.55)))
        # entablature anthracite (bandeau de devanture)
        e0 = (a[0] + nx * 0.12, a[1] + ny * 0.12); e1 = (b[0] + nx * 0.12, b[1] + ny * 0.12)
        entab.append(Quad((e0[0], e0[1], h_rdc - 0.5), (e1[0], e1[1], h_rdc - 0.5),
                          (e1[0], e1[1], h_rdc + 0.05), (e0[0], e0[1], h_rdc + 0.05)))
        entab.append(Quad((a[0], a[1], h_rdc + 0.05), (b[0], b[1], h_rdc + 0.05),
                          (e1[0], e1[1], h_rdc + 0.05), (e0[0], e0[1], h_rdc + 0.05)))
    return glass, piliers, entab

def storefront_awnings(fp, edges_idx, h_rdc, travee=4.5, drop=0.45, proj=1.1):
    """Bannes/auvents en saillie au-dessus de chaque vitrine commerce (RDC
    vivant). Retourne quads (matériau accent, p.ex. brique/anthracite)."""
    out = []
    n = len(fp)
    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < 3.0:
            continue
        ntr = max(1, int(L // travee))
        zt = h_rdc - 0.55
        for k in range(ntr):
            t0 = (k + 0.08) / ntr; t1 = (k + 0.92) / ntr
            a0 = (a[0] + t0*(b[0]-a[0]) + nx*0.05, a[1] + t0*(b[1]-a[1]) + ny*0.05)
            a1 = (a[0] + t1*(b[0]-a[0]) + nx*0.05, a[1] + t1*(b[1]-a[1]) + ny*0.05)
            a0o = (a0[0]+nx*proj, a0[1]+ny*proj); a1o = (a1[0]+nx*proj, a1[1]+ny*proj)
            # banne inclinée : haute au mur, basse en avant
            out.append(Quad((a0[0],a0[1],zt),(a1[0],a1[1],zt),(a1o[0],a1o[1],zt-drop),(a0o[0],a0o[1],zt-drop)))
            out.append(Quad((a0o[0],a0o[1],zt-drop),(a0o[0],a0o[1],zt-drop-0.18),(a1o[0],a1o[1],zt-drop-0.18),(a1o[0],a1o[1],zt-drop)))  # lambrequin
    return out

def bands_on_edges(fp, edges_idx, z0, z1, proud=0.08):
    """Bandeau horizontal saillant (cordon d'étage / corniche) sur arêtes données."""
    out = []
    n = len(fp)
    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, _, _, L = edge_normal(a, b)
        if L < 1.0:
            continue
        a2 = (a[0] + nx * proud, a[1] + ny * proud); b2 = (b[0] + nx * proud, b[1] + ny * proud)
        out.append(Quad((a2[0], a2[1], z0), (b2[0], b2[1], z0), (b2[0], b2[1], z1), (a2[0], a2[1], z1)))
        out.append(Quad((a[0], a[1], z1), (b[0], b[1], z1), (b2[0], b2[1], z1), (a2[0], a2[1], z1)))
        out.append(Quad((a[0], a[1], z0), (a2[0], a2[1], z0), (b2[0], b2[1], z0), (b[0], b[1], z0)))
    return out

def pilastres_verticaux(fp, edges_idx, z0, z1, pitch=3.2, w=0.32, proud=0.10):
    """Refends/pilastres VERTICAUX fins entre les travées de fenêtres sur les
    façades RUE → casse l'horizontalité « caserne » et donne le rythme de
    travées des immeubles voisins (survey_9). Posés sur les MÊMES bornes que
    les fenêtres (entre deux baies, pitch identique à windows_on_edges) du socle
    RDC jusqu'à la corniche. Modénature pierre, coût géométrique nul."""
    out = []
    n = len(fp)
    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < pitch:
            continue
        nwin = max(1, int(L // pitch))
        hw = w / 2
        # un pilastre à CHAQUE séparation de travée (bornes k=0..nwin) → refends
        # encadrant chaque baie, comme une trame verticale continue
        for k in range(nwin + 1):
            t = k / nwin
            cx, cy = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
            p0 = (cx - tx * hw + nx * proud, cy - ty * hw + ny * proud)
            p1 = (cx + tx * hw + nx * proud, cy + ty * hw + ny * proud)
            i0 = (cx - tx * hw, cy - ty * hw); i1 = (cx + tx * hw, cy + ty * hw)
            out.append(Quad((p0[0], p0[1], z0), (p1[0], p1[1], z0),
                            (p1[0], p1[1], z1), (p0[0], p0[1], z1)))          # face avant
            out.append(Quad((i0[0], i0[1], z0), (i0[0], i0[1], z1),
                            (p0[0], p0[1], z1), (p0[0], p0[1], z0)))          # chant gauche
            out.append(Quad((i1[0], i1[1], z0), (p1[0], p1[1], z0),
                            (p1[0], p1[1], z1), (i1[0], i1[1], z1)))          # chant droit
    return out

def attique_inset_walls(fp, edges_idx, z0, z1, inset=0.7):
    """Mur du DERNIER étage rue reculé de `inset` m (attique léger en retrait) :
    signature contemporaine + ombre portée qui brise la verticalité plate.
    Reste un étage plein DANS le gabarit (≤ corniche, pas de penthouse au-dessus
    de 18m). Retourne (murs reculés, dalle de la terrasse-retrait au pied)."""
    walls, ledge = [], []
    n = len(fp)
    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, _, _, L = edge_normal(a, b)
        if L < 1.0:
            continue
        ar = (a[0] - nx * inset, a[1] - ny * inset)
        br = (b[0] - nx * inset, b[1] - ny * inset)
        walls.append(Quad((ar[0], ar[1], z0), (br[0], br[1], z0),
                          (br[0], br[1], z1), (ar[0], ar[1], z1)))
        # dalle horizontale (toit de l'étage courant devenu terrasse devant l'attique)
        ledge.append(Quad((a[0], a[1], z0), (b[0], b[1], z0),
                          (br[0], br[1], z0), (ar[0], ar[1], z0)))
    return walls, ledge

# ── trottoirs le long des chaussées ───────────────────────────────────
# ── VIE EN GÉOMÉTRIE (donne à FLUX la structure pour rendre la vie) ───
def balcony_planters(fp, floors, edges_idx, depth, box_h=0.45, box_d=0.32):
    """Bacs à plantes le long du garde-corps des balcons (proud = devant la
    façade, donc lus comme jardinières et pas comme mur vert)."""
    out = []
    n = len(fp)
    for i in edges_idx:
        a, b = fp[i], fp[(i + 1) % n]
        nx, ny, tx, ty, L = edge_normal(a, b)
        if L < 2.0:
            continue
        # ligne au bord extérieur du balcon
        ax, ay = a[0] + tx * 0.3 + nx * (depth - 0.1), a[1] + ty * 0.3 + ny * (depth - 0.1)
        bx, by = b[0] - tx * 0.3 + nx * (depth - 0.1), b[1] - ty * 0.3 + ny * (depth - 0.1)
        for z in floors:
            z0, z1 = z + 0.02, z + 0.02 + box_h
            # boîte végétale (4 faces visibles suffisent)
            o = box_d
            ai, bi = (ax + nx*o, ay + ny*o), (bx + nx*o, by + ny*o)
            out.append(Quad((ax,ay,z0),(bx,by,z0),(bx,by,z1),(ax,ay,z1)))         # face int
            out.append(Quad((ai[0],ai[1],z0),(ai[0],ai[1],z1),(bi[0],bi[1],z1),(bi[0],bi[1],z0)))  # ext
            out.append(Quad((ax,ay,z1),(bx,by,z1),(bi[0],bi[1],z1),(ai[0],ai[1],z1)))  # dessus (plantes)
    return out

def _box(cx, cy, w, d, z0, z1, ang=0.0):
    import math as _m
    c, s = _m.cos(ang), _m.sin(ang)
    cor = [(-w/2,-d/2),(w/2,-d/2),(w/2,d/2),(-w/2,d/2)]
    p = [(cx + dx*c - dy*s, cy + dx*s + dy*c) for dx,dy in cor]
    out = []
    for k in range(4):
        a, b = p[k], p[(k+1)%4]
        out.append(Quad((a[0],a[1],z0),(b[0],b[1],z0),(b[0],b[1],z1),(a[0],a[1],z1)))
    out.append(Quad((p[0][0],p[0][1],z1),(p[1][0],p[1][1],z1),(p[2][0],p[2][1],z1),(p[3][0],p[3][1],z1)))
    return out

def _person(x, y, ang=0.0, h=1.72, scale=1.0):
    """Silhouette piéton : 2 plans verticaux croisés (face + profil) à
    proportions humaines, + petite tête. Quads CCW, matériau voisin."""
    import math as _m
    h *= scale
    wsh = 0.52 * scale          # largeur épaules (plan de face)
    wpr = 0.34 * scale          # profondeur (plan de profil)
    hh  = h * 0.84              # base de tête
    out = []
    c, s = _m.cos(ang), _m.sin(ang)
    # plan de face (orienté ang)
    fx, fy = c*wsh/2, s*wsh/2
    out.append(Quad((x-fx,y-fy,0.0),(x+fx,y+fy,0.0),(x+fx,y+fy,hh),(x-fx,y-fy,hh)))
    # plan de profil (perpendiculaire)
    px, py = -s*wpr/2, c*wpr/2
    out.append(Quad((x-px,y-py,0.0),(x+px,y+py,0.0),(x+px,y+py,hh),(x-px,y-py,hh)))
    # épaules (petit quad horizontal) : masse vue de dessus, évite le « poteau »
    sw = wsh*0.5
    out.append(Quad((x-sw,y-sw,hh*0.78),(x+sw,y-sw,hh*0.78),
                    (x+sw,y+sw,hh*0.78),(x-sw,y+sw,hh*0.78)))
    # tête (petit volume) : 2 plans croisés + dessus
    th = 0.22 * scale; hw = 0.12 * scale
    out.append(Quad((x-fx*0.5,y-fy*0.5,hh),(x+fx*0.5,y+fy*0.5,hh),
                    (x+fx*0.5,y+fy*0.5,hh+th),(x-fx*0.5,y-fy*0.5,hh+th)))
    out.append(Quad((x-px*0.6,y-py*0.6,hh),(x+px*0.6,y+py*0.6,hh),
                    (x+px*0.6,y+py*0.6,hh+th),(x-px*0.6,y-py*0.6,hh+th)))
    out.append(Quad((x-hw,y-hw,hh+th),(x+hw,y-hw,hh+th),
                    (x+hw,y+hw,hh+th),(x-hw,y+hw,hh+th)))
    return out

def _car(cx, cy, ang, L=4.30, W=1.82):
    """Silhouette voiture : capot bas (avant+arrière) + habitacle plus court
    et plus haut au centre = 2 volumes empilés. Matériau zinc."""
    import math as _m
    out = []
    hbody = 0.78                # hauteur du corps (capot/coffre)
    hcab  = 1.46                # toit habitacle
    out += _box(cx, cy, L, W, 0.18, hbody, ang)        # corps complet bas
    # habitacle : centré, plus court, légèrement plus étroit, posé sur le corps
    cabL = L * 0.46
    cdx = -L * 0.04 * 0          # centré
    hx, hy = _m.cos(ang)*cdx, _m.sin(ang)*cdx
    out += _box(cx+hx, cy+hy, cabL, W*0.90, hbody, hcab, ang)
    return out

def street_life(roads, junction, fp):
    """Silhouettes piétons + voitures + terrasse café (proxies géo → FLUX rend
    la vie). Matériaux : people/cafe = voisin (neutre), cars = zinc."""
    from shapely.geometry import LineString, Point
    people, cars, cafe = [], [], []
    jx, jy = junction
    import math as _m
    # piétons : 18 silhouettes croisées, hauteurs/orientations variées
    for k in range(18):
        ang = 2*_m.pi*k/18 + (k % 3) * 0.4
        r = 5.5 + (k % 5) * 2.2
        x, y = jx + _m.cos(ang)*r, jy + _m.sin(ang)*r
        walk = ang + _m.pi/2 + (0.6 if k % 2 else -0.6)   # orientation marche
        sc = 0.92 + (k % 4) * 0.05                        # adulte/ado varié
        people += _person(x, y, walk, scale=sc)
    # voitures : le long des routes proches du carrefour
    jp = Point(jx, jy)
    placed = 0
    for r in roads:
        ls = LineString(r["polyline"])
        if ls.distance(jp) > 8 or placed >= 6:
            continue
        t0 = ls.project(jp)
        for dd in (12, 20, 28):
            for sgn in (1,):
                t = t0 + dd
                if t > ls.length - 2: continue
                c = ls.interpolate(t); c2 = ls.interpolate(min(ls.length, t+1))
                ang = _m.atan2(c2.y-c.y, c2.x-c.x)
                nx, ny = _m.sin(ang), -_m.cos(ang)
                cx, cy = c.x + nx*3.2, c.y + ny*3.2
                cars += _car(cx, cy, ang)
                placed += 1
    # terrasse café au pied du pan coupé (côté carrefour) : 5 tables + parasols
    k = min(range(len(fp)), key=lambda i: _m.hypot(fp[i][0]-jx, fp[i][1]-jy))
    corner = fp[k]
    dirx, diry = jx-corner[0], jy-corner[1]; dn=_m.hypot(dirx,diry) or 1; dirx,diry=dirx/dn,diry/dn
    for j in range(5):
        tx, ty = corner[0]+dirx*(2.5+j*1.6)+ (-diry)*(j-2)*1.4, corner[1]+diry*(2.5+j*1.6)+ (dirx)*(j-2)*1.4
        cafe += _box(tx, ty, 0.7, 0.7, 0.0, 0.74)                 # table
        cafe += _box(tx, ty, 1.8, 1.8, 2.1, 2.25)                # parasol (haut)
    return people, cars, cafe

def roof_terrace_garden(fp, z):
    """Jardin sur toit terrasse (Cbis) DENSE : bacs continus en périmètre +
    arbres + pergola centrale → atout Cbis bien visible."""
    from shapely.geometry import Polygon
    ring = Polygon(fp).buffer(-1.5)
    if ring.is_empty: return []
    if ring.geom_type == "MultiPolygon": ring = max(ring.geoms, key=lambda g:g.area)
    out = []
    ext = ring.exterior
    import math as _m
    # garde-corps verre périmètre (parapet vitré)
    pts = list(ext.coords)
    for j in range(len(pts)-1):
        a, b = pts[j], pts[j+1]
        out.append(Quad((a[0],a[1],z+0.02),(b[0],b[1],z+0.02),(b[0],b[1],z+1.1),(a[0],a[1],z+1.1)))
    # bacs périmétriques continus BAS (lecture "terrasse végétalisée" propre).
    # PAS de boîtes-arbres hautes : elles lisaient comme des tuyaux/évents au canny.
    nb = 16
    for k in range(nb):
        p = ext.interpolate((k+0.5)/nb, normalized=True)
        out += _box(p.x, p.y, 1.4, 0.85, z+0.05, z+0.65)         # bac végétal bas
    # quelques arbustes ORGANIQUES bas (canopée arrondie, pas une boîte-stub),
    # espacés, jamais en pic vertical.
    import math as _m2
    for k in range(0, nb, 5):
        p = ext.interpolate((k+0.5)/nb, normalized=True)
        cx, cy = p.x, p.y
        rr = 0.7
        for ang in (0.0, _m2.pi/3, 2*_m2.pi/3):
            dx, dy = _m2.cos(ang)*rr, _m2.sin(ang)*rr
            out.append(Quad((cx-dx,cy-dy,z+0.6),(cx+dx,cy+dy,z+0.6),
                            (cx+dx,cy+dy,z+1.5),(cx-dx,cy-dy,z+1.5)))
    return out

def sidewalks_3d(roads, width=1.8):
    out = []
    for ri, r in enumerate(roads):
        pl = r["polyline"]; half = max(2.5, (r.get("chaussee_m") or 4)) / 2
        z = 0.004 + 0.0003 * ri   # z distinct par route (z-fight trottoirs aux carrefours)
        for i in range(len(pl) - 1):
            a, b = pl[i], pl[i + 1]
            ex, ey = b[0]-a[0], b[1]-a[1]; L = math.hypot(ex, ey) or 1
            nx, ny = ey/L, -ex/L
            for side in (1, -1):
                o0, o1 = side * half, side * (half + width)
                out.append(Quad((a[0]+nx*o0, a[1]+ny*o0, z), (b[0]+nx*o0, b[1]+ny*o0, z),
                                (b[0]+nx*o1, b[1]+ny*o1, z), (a[0]+nx*o1, a[1]+ny*o1, z)))
    return out

# ── passages piétons DAMIER au carrefour (géométrie, pas prompt) ──────
def damier_junction_full(junction, radius=7.5, sq=0.62, z=0.066):
    """Le carrefour RÉEL de Nogent est ENTIÈREMENT en damier (vérifié Street
    View carrefour_se_sv.png) — pas seulement des bandes. Damier plein
    centré sur l'intersection."""
    out = []
    n = int((radius * 2) // sq)
    for ia in range(n):
        for ic in range(n):
            if (ia + ic) % 2:
                continue
            x0 = junction[0] - radius + ia * sq
            y0 = junction[1] - radius + ic * sq
            cx, cy = x0 + sq / 2, y0 + sq / 2
            if math.hypot(cx - junction[0], cy - junction[1]) > radius:
                continue
            out.append(Quad((x0, y0, z), (x0 + sq, y0, z),
                            (x0 + sq, y0 + sq, z), (x0, y0 + sq, z)))
    return out

def damier_crossings(roads, junction, dist_along=8.0, band_w=4.4, sq=0.6):
    """Damier (carreaux blancs alternés) en travers de chaque rue, à
    `dist_along` m du carrefour. Z=0.065 au-dessus des chaussées (z max 0.056)."""
    from shapely.geometry import LineString, Point
    out = []
    seen = []
    jp = Point(junction)
    for r in roads:
        ls = LineString(r["polyline"])
        if ls.distance(jp) > 6.0:
            continue
        w = max(2.5, (r.get("chaussee_m") or 4)) + 1.0
        t_j = ls.project(jp)
        for t in (t_j + dist_along, t_j - dist_along):
            if t < 1.0 or t > ls.length - 1.0:
                continue
            c = ls.interpolate(t)
            # direction locale de la rue
            c2 = ls.interpolate(min(ls.length, t + 0.5))
            tx, ty = c2.x - c.x, c2.y - c.y
            L = math.hypot(tx, ty) or 1.0
            tx, ty = tx / L, ty / L
            nx, ny = ty, -tx
            if any(math.hypot(c.x - sx, c.y - sy) < 5.0 for sx, sy in seen):
                continue
            seen.append((c.x, c.y))
            n_alo = max(2, int(band_w // sq)); n_acr = max(2, int(w // sq))
            for ia in range(n_alo):
                for ic in range(n_acr):
                    if (ia + ic) % 2:
                        continue   # carreau sombre = asphalte dessous
                    a0 = (ia - n_alo / 2) * sq; a1 = a0 + sq
                    c0 = (ic - n_acr / 2) * sq; c1 = c0 + sq
                    quad = []
                    for (ta, tc) in ((a0, c0), (a1, c0), (a1, c1), (a0, c1)):
                        quad.append((c.x + tx * ta + nx * tc, c.y + ty * ta + ny * tc, 0.065))
                    out.append(Quad(*quad))
    return out

# ── caméra POV ICONIQUE : en hauteur au-dessus du damier → pan coupé ──
def carrefour_haut_camera(fp, junction, h_building, back=21.0, z=17.5):
    """Vue du haut depuis le passage piéton du carrefour (réf user 23.53.01) :
    caméra au-dessus du carrefour qui regarde le COIN pan coupé. CADRAGE CENTRÉ :
    la cible vise le milieu visuel du bâtiment (entre coin et centroïde, à mi-hauteur)
    et l'azimut est calé pour centrer la masse bâtie dans le cadre."""
    k = min(range(len(fp)), key=lambda i: math.hypot(fp[i][0] - junction[0], fp[i][1] - junction[1]))
    corner = fp[k]
    cx = sum(p[0] for p in fp) / len(fp); cy = sum(p[1] for p in fp) / len(fp)
    dx, dy = junction[0] - cx, junction[1] - cy
    dn = math.hypot(dx, dy) or 1.0
    dx, dy = dx / dn, dy / dn                     # centroïde → carrefour
    cam = (junction[0] + dx * back, junction[1] + dy * back, z)
    # cible = milieu coin/centre, plus haut (mi-hauteur) → bâtiment centré + visible
    tgt = (corner[0] * 0.45 + cx * 0.55, corner[1] * 0.45 + cy * 0.55, h_building * 0.42)
    return cam, tgt

# ── caméra AÉRIENNE 3/4 : au-dessus de la cour, LOS vérifié ───────────
def aerial_camera(fp, cour_poly, voisins, h_building, elev_deg=42.0, fov=50.0):
    """Caméra 3/4 côté cour (montre L + cour + jardins + étages). Distance
    cadre la parcelle entière ; z relevé jusqu'à ce que la ligne de visée
    vers CHAQUE coin de parcelle passe au-dessus des toits voisins (+3m)."""
    from shapely.geometry import Polygon, Point
    cx = sum(p[0] for p in fp) / len(fp); cy = sum(p[1] for p in fp) / len(fp)
    cc = cour_poly.centroid
    dx, dy = cc.x - cx, cc.y - cy
    dn = math.hypot(dx, dy) or 1.0
    dx, dy = dx / dn, dy / dn                      # direction bâtiment → cour
    R = max(math.hypot(px - cx, py - cy) for px, py in PARCEL) + 4.0
    dist = R / math.tan(math.radians(fov / 2)) * 1.35   # recul large (jamais zoomé)
    tgt = (cx, cy, h_building * 0.35)
    # mêmes voisins que le rendu : SANS les bâtiments démolis sur la parcelle
    # (sinon les cibles dans la cour sont « dans » un voisin → LOS jamais clear)
    parcel_poly = _Poly(PARCEL).buffer(0)
    vpolys = []
    for poly, h in voisins:
        if len(poly) < 3:
            continue
        vp = Polygon(poly).buffer(0)
        if vp.is_empty or vp.intersection(parcel_poly).area / vp.area > 0.5:
            continue
        vpolys.append((vp, max(3.0, min(h, 20.0))))
    # cibles de visée = INTÉRIEUR de la cour (inset 3.5m — la lisière au pied
    # des murs mitoyens n'est visible qu'à la verticale) + corniches bâtiment
    inner = cour_poly.buffer(-3.5)
    if inner.is_empty:
        inner = cour_poly.buffer(-1.0)
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    targets = [(x, y, 0.5) for x, y in list(inner.exterior.coords)[::2]]
    targets += [(cour_poly.centroid.x, cour_poly.centroid.y, 0.5)]
    targets += [(x, y, h_building * 0.8) for x, y in fp[::2]]
    base_az = math.atan2(dy, dx)

    def los_clear(cam):
        for txp, typ, tzp in targets:
            for t in [i / 30 for i in range(1, 29)]:
                px = cam[0] + (txp - cam[0]) * t
                py = cam[1] + (typ - cam[1]) * t
                pz = cam[2] + (tzp - cam[2]) * t
                for vp, vh in vpolys:
                    if pz < vh + 1.5 and vp.contains(Point(px, py)):
                        return False
        return True

    # cherche la plongée la PLUS FAIBLE (vrai 3/4) en balayant aussi l'azimut
    # autour de la direction cour (±60°)
    best = None
    for elev in [elev_deg + 2 * k for k in range(int((60 - elev_deg) / 2) + 1)]:
        for az_off in (0, 15, -15, 30, -30, 45, -45, 60, -60):
            az = base_az + math.radians(az_off)
            horiz = dist * math.cos(math.radians(elev))
            camz = tgt[2] + dist * math.sin(math.radians(elev))
            cam = (cx + math.cos(az) * horiz, cy + math.sin(az) * horiz, camz)
            if los_clear(cam):
                best = (elev, az_off, cam)
                break
        if best:
            break
    if not best:
        elev = 60.0
        horiz = dist * math.cos(math.radians(elev))
        best = (elev, 0, (cx + dx * horiz, cy + dy * horiz, tgt[2] + dist * math.sin(math.radians(elev))))
    elev, az_off, cam = best
    print(f"  caméra aérienne : elev {elev:.0f}°, azimut cour{az_off:+d}°, pos {tuple(round(c,1) for c in cam)}")
    return cam, tgt

# ── caméra : coin rue (arête la plus proche d'une route) ──────────────
def street_camera(fp, edge_free, roads, voisins, h_building):
    """Caméra eye-level dans l'espace RUE ouvert. corner = sommet le plus
    proche d'une route ; on recule le long de corner→route MAIS on vérifie
    que la caméra n'est PAS dans un polygone voisin (sinon Cycles = noir)."""
    from shapely.geometry import Point, Polygon
    vpolys = [Polygon(poly) for poly, h in voisins if len(poly) >= 3]
    cx = sum(p[0] for p in fp) / len(fp); cy = sum(p[1] for p in fp) / len(fp)
    # corner rue + point de route le plus proche
    best = None
    for vx, vy in fp:
        for r in roads:
            for px, py in r["polyline"]:
                d = math.hypot(vx - px, vy - py)
                if best is None or d < best[0]:
                    best = (d, vx, vy, px, py)
    _, vx, vy, rpx, rpy = best
    # direction = du bâtiment vers la route (espace ouvert)
    dx, dy = rpx - cx, rpy - cy; dn = math.hypot(dx, dy) or 1
    dx, dy = dx / dn, dy / dn
    def inside_voisin(x, y):
        p = Point(x, y)
        return any(vp.contains(p) or vp.distance(p) < 1.0 for vp in vpolys)
    # cherche le plus grand recul (8..22m depuis le coin) qui reste hors voisins
    chosen = (vx + dx * 10, vy + dy * 10)
    for D in (22, 20, 18, 16, 14, 12, 10, 8):
        camx, camy = vx + dx * D, vy + dy * D
        if not inside_voisin(camx, camy):
            chosen = (camx, camy); break
    return (chosen[0], chosen[1], 7.0), (cx, cy, h_building * 0.45)

# ── scénarios ─────────────────────────────────────────────────────────
SCEN = {
    "A": dict(stories=4, h=14.0, roof="mansard", body="pierre_taille", soub="pierre_taille", trim="brique_rouge"),
    # B = CONTEMPORAIN FRANC (décision user 2026-06-23) : on abandonne le pastiche
    # haussmannien (mansarde + lucarnes + corniche/bandeaux lourds) pour coller aux
    # VRAIS voisins modernes de la rue (survey_0, survey_9 : immeubles blancs, pierre
    # claire lisse, balcons verre + métal noir fin, lignes épurées).
    #   roof="terrasse" → terrasse plate végétalisée + attique en retrait (build()
    #     branche flat_roof + roof_terrace_garden, supprime mansarde/lucarnes/cheminées)
    #   style="contemporain" → modénature MINIMALE (pas de corniche/bandeaux lourds),
    #     garde-corps métal noir fin, grandes baies verticales (cf. bloc build()).
    "B": dict(stories=5, h=18.0, roof="terrasse", body="pierre_taille", soub="pierre_taille",
              trim="pierre_taille", style="contemporain"),
    "Cbis": dict(stories=5, h=18.0, roof="terrasse", body="brique_rouge", soub="pierre_taille", trim="pierre_taille"),
}

def build(scen_key):
    s = SCEN[scen_key]
    contemporain = s.get("style") == "contemporain"   # B : épuré, pas haussmannien
    h_rdc = 3.5; stories = s["stories"]; h_total = s["h"]
    h_et = (h_total - h_rdc) / (stories - 1)
    h_eaves = h_rdc + (stories - 1) * h_et
    # window bands per floor
    z_levels = []
    z_floors = []
    for f in range(stories):
        base = 0 if f == 0 else h_rdc + (f - 1) * h_et
        if f == 0:
            z_levels.append((1.0, h_rdc - 0.5))  # RDC commerce tall
        else:
            sill = base + 0.9; z_levels.append((sill, min(sill + 1.45, base + h_et - 0.3)))
            z_floors.append(base + 0.15)
    edge_free = classify_edges(FP, SITE["voisins"])
    # façades sur cour = toujours libres (la cour est NOTRE parcelle ; le
    # classify les marquait mitoyennes car le sample 1.2m tombe à <2.2m des
    # voisins de l'autre côté de la limite séparative)
    idx_cour = set(cour_edges(FP, COUR_POLY))
    for i in idx_cour:
        edge_free[i] = True
    idx_rue = [i for i in range(len(FP)) if edge_free[i] and i not in idx_cour]
    rue_mask = [i in idx_rue for i in range(len(FP))]
    cour_mask = [i in idx_cour for i in range(len(FP))]
    print(f"  arêtes : {len(idx_rue)} rue / {len(idx_cour)} cour / {len(edge_free)-sum(edge_free)} mitoyennes")
    walls = extrude_walls(FP, 0, h_eaves)
    # ── RUE : hiérarchie des baies par étage (les fenêtres ne doivent PAS
    # toutes se ressembler) + balcons filants au 1er (noble) et au dernier ──
    glass, rev, rails = [], [], []
    balcon_floors = []      # étages courants + noble (balcon profond)
    att_floors = []         # attique (balcon plus fin, sur plan reculé)
    ATT_INSET = 0.7         # recul de l'attique (dernier étage rue)
    # plan reculé de l'attique : footprint rue translaté de -ATT_INSET vers l'intérieur
    att_walls, att_ledge = [], []
    # CONTEMPORAIN : grandes baies verticales toute hauteur, trame plus large
    # (pitch 4.0 → moins de travées mais plus généreuses, lit moderne pas caserne).
    win_pitch = 4.0 if contemporain else 3.6
    for f in range(1, stories):
        base = h_rdc + (f - 1) * h_et
        is_att = (f == stories - 1) and stories >= 3   # dernier étage = attique en retrait
        if f == 1:                          # étage noble : portes-fenêtres HAUTES + larges
            lvl = (base + 0.05, base + (2.65 if contemporain else 2.45))
            ww = 1.85 if contemporain else 1.55
            balcon_floors.append(base + 0.15)
        elif is_att:                        # attique : baies basses, mur reculé, balcon fin
            lvl = (base + 0.10, base + (2.20 if contemporain else 1.95))
            ww = 1.55 if contemporain else 1.05
            att_floors.append(base + 0.05)
            w_a, l_a = attique_inset_walls(FP, idx_rue, base + 0.05, h_eaves, inset=ATT_INSET)
            att_walls += w_a; att_ledge += l_a
        else:                               # étages courants
            lvl = (base + 0.08, base + (2.55 if contemporain else 2.15))
            ww = 1.75 if contemporain else 1.20
            balcon_floors.append(base + 0.15)
        # fenêtres : pour l'attique on les pousse sur le plan reculé (recess plus grand)
        # pitch = même trame que les refends verticaux → baies encadrées par les pilastres
        rcs = -0.05 if not is_att else (ATT_INSET + 0.05)
        g, r = windows_on_edges(FP, [lvl], rue_mask, win_w=ww, pitch=win_pitch, recess=rcs)
        glass += g; rev += r
    g2, r2 = windows_on_edges(FP, z_levels, cour_mask)                  # cour : tous niveaux
    glass += g2; rev += r2
    # ── RDC LOGEMENT surélevé (commerce NON obligatoire sur notre linéaire,
    # vérifié carte 4-4 → logement = +marge) : socle pierre +1m (intimité +
    # surélévation PPRI Marne hors-eau) + fenêtres résidentielles + jardinières.
    RDC_RAISE = 1.0
    soubass_rdc = bands_on_edges(FP, idx_rue, 0.0, RDC_RAISE, proud=0.06)   # socle pierre
    # CONTEMPORAIN : RDC logement surélevé à GRANDES baies vitrées (pas commerce)
    rdc_ww = 2.0 if contemporain else 1.2
    g_rdc, r_rdc = windows_on_edges(FP, [(RDC_RAISE + 0.5, h_rdc - 0.15)], rue_mask, win_w=rdc_ww, pitch=win_pitch)
    glass += g_rdc; rev += r_rdc
    rdc_planters = balcony_planters(FP, [RDC_RAISE], idx_rue, depth=0.45)   # jardinières pied de façade
    vitrines, piliers, entab, awnings = [], [], [], []                     # plus de commerce
    # balcons filants : RUE noble+courants (dalle profonde, garde-corps dessiné) +
    # attique (balcon FIN sur le plan reculé) + COUR (tous étages). User : balcon
    # filant à CHAQUE étage rue ET cour → jamais retirer.
    slabs, rails_r = balcons_filants_edges(FP, balcon_floors, rue_mask, depth=1.05, slab_t=0.14)
    rails += rails_r
    slabs_a, rails_a = balcons_filants_edges(FP, att_floors, rue_mask, depth=0.55, slab_t=0.12, rail_h=0.95)
    slabs += slabs_a; rails += rails_a
    slabs_c, rails_c = balcons_filants_edges(FP, z_floors, cour_mask)
    slabs += slabs_c; rails += rails_c
    # refends/pilastres VERTICAUX rue : trame de travées du socle RDC à la corniche
    # (casse l'effet caserne horizontal). Modénature pierre crème, coût géo nul.
    # CONTEMPORAIN : refends FINS (w 0.22, faible saillie) alignés sur la trame
    # large des grandes baies → lignes verticales épurées, pas pilastres classiques.
    pil_w = 0.22 if contemporain else 0.34
    pil_proud = 0.07 if contemporain else 0.13
    pilastres = pilastres_verticaux(FP, idx_rue, RDC_RAISE, h_eaves - 0.35,
                                    pitch=win_pitch, w=pil_w, proud=pil_proud)
    # jardinières sur balcons : CONTEMPORAIN = balcons RUE propres (verre/métal
    # net, comme les voisins modernes survey_0/9) → AUCUNE jardinière rue (elles
    # ceinturaient le bâtiment d'une bande brune en fouillis). Le vert vient du
    # TOIT-terrasse + des balcons COUR + des haies de rue. Côté cour conservé.
    rue_planter_floors = [] if contemporain else balcon_floors
    planters = balcony_planters(FP, rue_planter_floors, idx_rue, depth=1.05)
    planters += balcony_planters(FP, z_floors, list(idx_cour), depth=1.5)
    # CONTEMPORAIN : pas de chaînages brique d'angle (modénature classique).
    chainages = [] if contemporain else chainages_d_angle(FP, idx_rue, h_eaves - 0.4)
    entrance = main_entrance(FP, JUNCTION, h_rdc)   # entrée résidentielle marquée + marquise
    # MODÉNATURE : haussmannien = bandeaux d'étage + cordon noble + grosse corniche.
    # CONTEMPORAIN = on enlève les bandeaux/cordon lourds (lignes épurées) et la
    # corniche devient un acrotère FIN au sommet de la terrasse (proud minimal).
    bandeaux = []
    if not contemporain:
        for zf in z_floors:
            bandeaux += bands_on_edges(FP, idx_rue, zf - 0.18, zf, proud=0.08)
        # cordon NOBLE renforcé : bandeau marqué sous le 1er étage (sépare le socle
        # RDC de l'étage noble → hiérarchie lisible, signature mesurée)
        bandeaux += bands_on_edges(FP, idx_rue, h_rdc - 0.28, h_rdc, proud=0.16)
    corniche_proud = 0.10 if contemporain else 0.30   # acrotère fin vs corniche lourde
    corniche = bands_on_edges(FP, [i for i in range(len(FP)) if edge_free[i]],
                              h_eaves - 0.20, h_eaves, proud=corniche_proud)
    soubassement = bands_on_edges(FP, idx_rue, 0.0, 0.35, proud=0.05)
    jardins = cour_jardins(FP, COUR_POLY)
    if s["roof"] == "mansard":
        h_ridge = h_eaves + 2.8
        slant, top = mansarde(FP, h_eaves, h_ridge)
        dorm = dormers_on_edges(FP, edge_free, h_eaves, h_ridge)
        chim = chimneys(FP, h_ridge)
        roof_mat = "zinc_anthracite"
    else:
        slant, top = [], flat_roof(FP, h_eaves); dorm = []; chim = []
        roof_mat = "vegetation"
    qbm = {}
    def add(m, qs):
        if qs: qbm[m] = qbm.get(m, []) + (ql(qs) if qs and hasattr(qs[0], "v0") else qs)
    trim = s.get("trim", "brique_rouge")   # accent contrastant (encadrements, chaînages, bandeaux)
    add(s["body"], walls)
    add(trim, rev)                    # encadrements de baies : contraste corps/accent (cf. cible)
    add("verre", glass)
    add("balcon_concrete", slabs)
    # garde-corps : CONTEMPORAIN = métal noir fin (verre + métal des voisins
    # modernes) ; sinon fer forgé classique.
    add("metal_noir" if contemporain else "fer_forge", rails)
    add("pierre_taille", piliers)
    add("zinc_anthracite", entab)
    add(trim, chainages)
    add("zinc_anthracite", awnings)        # bannes commerces
    for _m, _q in entrance.items():         # entrée résidentielle (hall + piliers + marquise)
        add(_m, _q)
    add("vegetation", planters + rdc_planters)   # jardinières balcons + pied RDC
    add(trim, bandeaux + corniche)                     # bandeaux d'étage + corniche en pierre crème (cible)
    add("pierre_taille", soubassement + soubass_rdc)   # soubassement + socle RDC surélevé (toujours pierre)
    add(s["body"], att_walls)             # attique : mur reculé (même pierre que le corps)
    add("balcon_concrete", att_ledge)     # dalle de la terrasse-retrait au pied de l'attique
    add(trim, pilastres)                  # refends verticaux = trame de travées (anti-caserne)
    add(roof_mat, slant + top + dorm)
    add(s["body"], chim)
    for m, qs in jardins.items():
        add(m, qs)
    for m, qs in voisins_3d(SITE["voisins"]).items():
        add(m, qs)
    add("asphalte", roads_3d(SITE["roads"]))
    add("pavers_concrete", sidewalks_3d(SITE["roads"]))
    add("enduit_blanc", damier_crossings(SITE["roads"], JUNCTION)
        + damier_junction_full(JUNCTION))
    # POC moteur photoréaliste : POC_NOENTOURAGE=1 retire les PROXYS carton
    # (gens/voitures/arbres-rue/haies) → ils seront remplacés par de VRAIS assets
    # 3D. On garde la route (enrich_street), les voisins, la cour, le bâtiment.
    import os as _os_poc
    _POC = bool(_os_poc.environ.get("POC_NOENTOURAGE"))
    if not _POC:
        add("vegetation", trees_3d(SITE["trees"]))
        add("bois_clair", tree_trunks_3d(SITE["trees"]))   # troncs bois
    # ── ENRICHISSEMENT base (agents parallèles, modules isolés) : rue verte
    # réelle + vie/mobilier. try/except + reload pour itérer sans casser. ──
    try:
        import importlib
        import enrich_environment as _env, enrich_life as _life, enrich_street as _str
        importlib.reload(_env); importlib.reload(_life); importlib.reload(_str)
        if not _POC:
            for _m, _qs in _env.add_greenery(FP, SITE, JUNCTION, idx_rue, edge_free).items():
                add(_m, _qs)
            for _m, _qs in _life.add_life(FP, SITE, JUNCTION).items():
                add(_m, _qs)
        for _m, _qs in _str.add_street(FP, SITE, JUNCTION).items():   # route gardée (vraie chaussée)
            add(_m, _qs)
    except Exception as _e:
        print(f"  ⚠ enrich modules skipped: {_e}")
    # ── VIE : piétons, voitures, terrasse café, jardin de toit ───────
    if not _POC:
        people, cars, cafe = street_life(SITE["roads"], JUNCTION, FP)
        add("voisin", people)               # piétons (pas de terrasse café : RDC logement)
        add("zinc_anthracite", cars)        # voitures sombres
    if s["roof"] != "mansard":          # toit terrasse → jardin
        if contemporain:
            # CONTEMPORAIN : plantation RECULÉE au cœur du toit (buffer -1.6m) →
            # la silhouette de l'ATTIQUE épuré + la terrasse plate restent lisibles
            # au bord (pas de haie d'arbres qui masque l'attique). Acrotère fin déjà posé.
            from shapely.geometry import Polygon as _RP
            _roof_inner = _RP(FP).buffer(-1.6)
            if not _roof_inner.is_empty:
                if _roof_inner.geom_type == "MultiPolygon":
                    _roof_inner = max(_roof_inner.geoms, key=lambda g: g.area)
                _rfp = list(_roof_inner.exterior.coords)[:-1]
                add("vegetation", roof_terrace_garden(_rfp, h_eaves))
        else:
            add("vegetation", roof_terrace_garden(FP, h_eaves))
    # ground
    add("terre_neutre", [[[-200,-200,-0.05],[200,-200,-0.05],[200,200,-0.05],[-200,200,-0.05]]])
    tot = sum(len(v) for v in qbm.values())
    pos, tgt = street_camera(FP, edge_free, SITE["roads"], SITE["voisins"], h_total)
    cfg = {"option": scen_key, "quads_by_material": qbm, "camera_pos": list(pos),
           "camera_target": list(tgt), "camera_fov_deg": 62.0, "sun_direction": [0.65, 0.3, 0.22]}
    out = OUT / f"{scen_key}_real_corner.json"
    out.write_text(json.dumps(cfg))
    print(f"✓ {scen_key} corner: {tot} quads, mats={[(k,len(v)) for k,v in qbm.items()]} → {out.name}")
    apos, atgt = aerial_camera(FP, COUR_POLY, SITE["voisins"], h_total)
    acfg = dict(cfg, camera_pos=list(apos), camera_target=list(atgt), camera_fov_deg=50.0)
    aout = OUT / f"{scen_key}_real_aerial.json"
    aout.write_text(json.dumps(acfg))
    print(f"✓ {scen_key} aerial → {aout.name}")
    kpos, ktgt = carrefour_haut_camera(FP, JUNCTION, h_total)
    # SOLEIL depuis le CÔTÉ CAMÉRA → éclaire le coin/face que l'on VOIT (sinon le
    # soleil par défaut NE laisse la façade visible à l'ombre = bâtiment gris).
    # Le rake +22° (modal_blender) ajoute le modelé + l'ombre latérale.
    _sdx, _sdy = kpos[0] - ktgt[0], kpos[1] - ktgt[1]
    _sn = math.hypot(_sdx, _sdy) or 1.0
    kcfg = dict(cfg, camera_pos=list(kpos), camera_target=list(ktgt), camera_fov_deg=58.0,
                sun_direction=[_sdx / _sn, _sdy / _sn, 0.5])
    kout = OUT / f"{scen_key}_real_carrefour_haut.json"
    kout.write_text(json.dumps(kcfg))
    print(f"✓ {scen_key} carrefour_haut (POV iconique damier) → {kout.name}")
    return cfg

if __name__ == "__main__":
    for k in (sys.argv[1:] or ["A"]):
        build(k)
