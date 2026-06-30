"""Enrichissement VIE + mobilier urbain (agent LIFE) — additif, fichier isolé.

But : peupler le carrefour comme la VRAIE rue (cf. AMBIANCE_REELLE.md) — passage
piéton zébré, lampadaires verts RAL6005, gens/vélos plus nombreux et PROCHES,
voitures garées des 2 côtés. Tout en GÉOMÉTRIE (Quad) pour que le canny le rende.

Contrat : add_life(...) renvoie {materiau: [Quad|nested, ...]} mergé par build().
Matériaux EXISTANTS : 'voisin' (gens/vélos), 'zinc_anthracite' (voitures/poteaux),
'enduit_blanc' (marquages/zébrures + van blanc), 'fer_forge'.
NE PAS toucher d'autres fichiers. Helpers : `from build_real_scenarios import _person, _car, _box, Quad`.
"""
from __future__ import annotations
import math


# ── helpers locaux (géométrie pure, aucune dépendance d'état) ─────────────
def _zebra_crossing(cx, cy, tx, ty, nx, ny, road_w, n_stripes=6,
                    stripe_w=0.45, stripe_gap=0.42, length=None, z=0.067):
    """Passage piéton ZÉBRÉ classique : bandes blanches // à l'axe de la rue,
    en travers de la chaussée. (tx,ty)=axe rue, (nx,ny)=travers. Z au-dessus
    de l'asphalte (z max chaussée ~0.056) et du damier (0.065) pour être lu."""
    out = []
    length = length if length is not None else road_w
    half = length / 2.0
    pitch = stripe_w + stripe_gap
    total = n_stripes * pitch
    start = -(total / 2.0)
    for k in range(n_stripes):
        s0 = start + k * pitch
        s1 = s0 + stripe_w
        corners = [(s0, -half), (s1, -half), (s1, half), (s0, half)]
        quad = []
        for (a, b) in corners:
            # a = le long de la rue (épaisseur des bandes), b = en travers
            x = cx + tx * a + nx * b
            y = cy + ty * a + ny * b
            quad.append((x, y, z))
        out.append(_Q(*quad))
    return out


def _stop_line(cx, cy, tx, ty, nx, ny, road_w, w=0.30, z=0.067):
    """Ligne d'arrêt blanche (bande pleine en travers de la rue)."""
    half = road_w / 2.0
    p = [(0.0, -half), (w, -half), (w, half), (0.0, half)]
    quad = [(cx + tx * a + nx * b, cy + ty * a + ny * b, z) for (a, b) in p]
    return [_Q(*quad)]


def _lamppost(x, y, arm_dir, h=5.2, arm_len=1.6, pole_w=0.14):
    """Lampadaire col-de-cygne : poteau vertical + bras courbé en arc vers la
    rue + tête luminaire. Géométrie sombre (zinc) ; le vert RAL6005 vient du
    prompt FLUX. arm_dir = (dx,dy) unitaire vers la chaussée."""
    out = []
    out += _box_l(x, y, pole_w, pole_w, 0.0, h)               # mât
    # bras en col-de-cygne : 3 segments qui montent puis s'inclinent vers la rue
    ax, ay = arm_dir
    pts = [
        (x, y, h),
        (x + ax * arm_len * 0.35, y + ay * arm_len * 0.35, h + 0.55),
        (x + ax * arm_len * 0.80, y + ay * arm_len * 0.80, h + 0.70),
        (x + ax * arm_len, y + ay * arm_len, h + 0.45),       # descente vers la tête
    ]
    aw = pole_w * 0.7
    for i in range(len(pts) - 1):
        (x0, y0, z0), (x1, y1, z1) = pts[i], pts[i + 1]
        # petit ruban orienté : 2 faces croisées pour lire de tous les angles
        out.append(_Q((x0 - aw, y0, z0), (x0 + aw, y0, z0),
                      (x1 + aw, y1, z1), (x1 - aw, y1, z1)))
        out.append(_Q((x0, y0 - aw, z0), (x0, y0 + aw, z0),
                      (x1, y1 + aw, z1), (x1, y1 - aw, z1)))
    # tête luminaire (petite boîte basse, projetée vers le bas)
    hx, hy = pts[-1][0], pts[-1][1]
    out += _box_l(hx, hy, 0.55, 0.30, h + 0.20, h + 0.46,
                  ang=math.atan2(ay, ax))
    return out


def _bike(x, y, ang, scale=1.0, rider=False):
    """Vélo : 2 roues (anneaux carrés croisés) + cadre + guidon, en plans
    verticaux pour lire de profil. Matériau voisin (neutre, FLUX colore).
    rider=True : ajoute un cycliste assis (silhouette mince) → vélo en mouvement."""
    out = []
    c, s = math.cos(ang), math.sin(ang)
    wheel_r = 0.34 * scale
    wb = 1.02 * scale                       # empattement
    seat_h = 1.0 * scale
    for sgn in (-1, 1):                      # 2 roues
        wx = x + c * (wb / 2) * sgn
        wy = y + s * (wb / 2) * sgn
        # roue = quad vertical aligné avec l'axe du vélo (lit comme un disque mince)
        out.append(_Q((wx - c * wheel_r, wy - s * wheel_r, 0.02),
                      (wx + c * wheel_r, wy + s * wheel_r, 0.02),
                      (wx + c * wheel_r, wy + s * wheel_r, wheel_r * 2),
                      (wx - c * wheel_r, wy - s * wheel_r, wheel_r * 2)))
    # cadre triangulaire (plan vertical le long de l'axe)
    fx0, fy0 = x - c * wb * 0.30, y - s * wb * 0.30
    fx1, fy1 = x + c * wb * 0.30, y + s * wb * 0.30
    out.append(_Q((fx0, fy0, wheel_r), (fx1, fy1, wheel_r),
                  (fx1, fy1, seat_h), (fx0, fy0, seat_h)))
    # selle + guidon (petites barres hautes)
    out += _box_l(x - c * wb * 0.35, y - s * wb * 0.35, 0.30, 0.10, seat_h, seat_h + 0.06, ang=ang)
    out += _box_l(x + c * wb * 0.42, y + s * wb * 0.42, 0.40, 0.10, seat_h - 0.05, seat_h + 0.05, ang=ang)
    return out


def _bench(x, y, ang, length=1.7, scale=1.0):
    """Banc public moderne sobre : assise + dossier bas + 2 pieds. Plans simples
    qui lisent de profil/face. Matériau sombre (zinc) — design contemporain."""
    out = []
    seat_h = 0.45 * scale
    seat_d = 0.45 * scale
    back_h = 0.85 * scale
    L = length * scale
    # assise (dalle horizontale)
    out += _box_l(x, y, L, seat_d, seat_h - 0.06, seat_h, ang=ang)
    # dossier (panneau vertical à l'arrière)
    c, s = math.cos(ang), math.sin(ang)
    bx = x - math.sin(ang) * 0 - (s) * 0  # garde axe
    # arrière = côté -normal le long du banc ; on décale d'une demi-profondeur
    nx, ny = -s, c
    out += _box_l(x - nx * seat_d * 0.45, y - ny * seat_d * 0.45,
                  L, 0.06, seat_h, back_h, ang=ang)
    # 2 pieds (petits poteaux sous l'assise)
    for sgn in (-1, 1):
        fx = x + c * (L * 0.40) * sgn
        fy = y + s * (L * 0.40) * sgn
        out += _box_l(fx, fy, 0.10, seat_d * 0.8, 0.0, seat_h - 0.06, ang=ang)
    return out


def _bollard(x, y, kind="bin", h=1.05):
    """Mobilier vertical sobre : borne (kind='bollard', basse) ou
    poubelle/corbeille de rue (kind='bin', cylindre carré sur mât). Zinc."""
    out = []
    if kind == "bollard":
        out += _box_l(x, y, 0.18, 0.18, 0.0, 0.95)
        out += _box_l(x, y, 0.22, 0.22, 0.95, 1.02)        # tête arrondie (proxy)
    else:  # corbeille de rue : mât + cuve
        out += _box_l(x, y, 0.10, 0.10, 0.0, h)             # mât
        out += _box_l(x, y, 0.40, 0.40, h - 0.55, h)        # cuve (réceptacle)
    return out


def _bus_shelter(x, y, ang, length=3.6, depth=1.4, h=2.4):
    """Abribus simple contemporain : toit plat sur 4 poteaux + paroi vitrée
    arrière (panneau). Lignes nettes pour le canny. Poteaux/toit sombres."""
    out = []
    c, s = math.cos(ang), math.sin(ang)
    nx, ny = -s, c
    L, D = length, depth
    # toit plat
    out += _box_l(x, y, L, D, h, h + 0.12, ang=ang)
    # 4 poteaux d'angle
    for la in (-0.45, 0.45):
        for da in (-0.45, 0.45):
            px = x + c * (L * la) + nx * (D * da)
            py = y + s * (L * la) + ny * (D * da)
            out += _box_l(px, py, 0.10, 0.10, 0.0, h, ang=ang)
    # paroi arrière vitrée (panneau plein, lit comme une plaque)
    out += _box_l(x - nx * D * 0.45, y - ny * D * 0.45, L, 0.05, 0.0, h, ang=ang)
    # banc intérieur (assise basse contre la paroi)
    out += _box_l(x - nx * D * 0.30, y - ny * D * 0.30, L * 0.85, 0.35, 0.40, 0.46, ang=ang)
    return out


def add_life(FP, SITE, JUNCTION) -> dict:
    """Peuple le carrefour : zébrures + lampadaires + gens proches + vélos +
    voitures garées 2 côtés (dont 1 van blanc). Tout en Quad → canny le rend.
    Retourne {materiau: [nested_quad]}. Ne duplique pas exactement street_life()
    (positions décalées via offsets/angles dérivés de JUNCTION)."""
    # imports tardifs : helpers + Quad du builder (évite tout cycle au load)
    from build_real_scenarios import _person, _car, Quad
    global _Q, _box_src
    _Q = Quad
    from build_real_scenarios import _box as _box_src
    globals()["_box_l"] = _box_src

    from shapely.geometry import LineString, Point

    jx, jy = JUNCTION
    jp = Point(jx, jy)

    white, zinc, people, frames = [], [], [], []

    # ── bras de rue proches du carrefour (dédoublonnés) ────────────────────
    arms = []                       # (LineString, t_junction, road_w)
    seen_dirs = []
    for r in SITE["roads"]:
        ls = LineString(r["polyline"])
        if ls.distance(jp) > 4.0:
            continue
        w = max(2.5, (r.get("chaussee_m") or 4.0))
        t_j = ls.project(jp)
        # direction sortante de l'axe au carrefour
        t1 = min(ls.length, t_j + 3.0)
        c = ls.interpolate(t_j); c2 = ls.interpolate(t1)
        dx, dy = c2.x - c.x, c2.y - c.y
        dn = math.hypot(dx, dy) or 1.0
        dirv = (dx / dn, dy / dn)
        # si l'axe au carrefour pointe vers le centre, prendre l'autre sens
        if math.hypot(c.x - jx, c.y - jy) < 0.5 and t_j > ls.length - 3.0:
            dirv = (-dirv[0], -dirv[1])
        if any(dirv[0] * sd[0] + dirv[1] * sd[1] > 0.93 for sd in seen_dirs):
            continue                # même direction qu'un bras déjà pris
        seen_dirs.append(dirv)
        arms.append((ls, t_j, w, dirv))

    # ── 1) ZÉBRURES + ligne d'arrêt sur chaque bras (~5.5 m du centre) ────
    for (ls, t_j, w, dirv) in arms:
        for dist in (5.5,):
            for sgn in (1, -1):
                t = t_j + sgn * dist
                if t < 0.5 or t > ls.length - 0.5:
                    continue
                c = ls.interpolate(t)
                c2 = ls.interpolate(min(ls.length, t + 0.6))
                tx, ty = c2.x - c.x, c2.y - c.y
                L = math.hypot(tx, ty) or 1.0
                tx, ty = tx / L, ty / L
                nx, ny = ty, -tx                      # travers de la rue
                white += _zebra_crossing(c.x, c.y, tx, ty, nx, ny, w,
                                         n_stripes=max(5, int(w / 0.9)),
                                         length=w + 0.6)
                # ligne d'arrêt juste avant la zébrure (côté carrefour)
                cs = ls.interpolate(max(0.5, t - sgn * 1.4))
                white += _stop_line(cs.x, cs.y, tx, ty, nx, ny, w)
                break                                  # 1 zébrure par bras

    # ── 2) LAMPADAIRES col-de-cygne (verts RAL6005 via prompt) ────────────
    # 1 GRAND au coin (le sommet du bâtiment au carrefour), bras vers la rue
    k = min(range(len(FP)), key=lambda i: math.hypot(FP[i][0] - jx, FP[i][1] - jy))
    corner = FP[k]
    # poteau posé sur le trottoir, légèrement EN DEHORS du bâtiment vers le carrefour
    cdx, cdy = jx - corner[0], jy - corner[1]
    cdn = math.hypot(cdx, cdy) or 1.0
    cdx, cdy = cdx / cdn, cdy / cdn
    lx, ly = corner[0] + cdx * 2.4, corner[1] + cdy * 2.4
    zinc += _lamppost(lx, ly, (cdx, cdy), h=6.1, arm_len=2.0, pole_w=0.17)
    # lampadaires secondaires le long de chaque bras (alternés sur les 2 trottoirs)
    for ai, (ls, t_j, w, dirv) in enumerate(arms):
        for dist in (9.0, 17.0):
            t = t_j + dist if (t_j + dist) < ls.length - 1.0 else t_j - dist
            if t < 0.5 or t > ls.length - 0.5:
                continue
            c = ls.interpolate(t)
            c2 = ls.interpolate(min(ls.length, t + 0.6))
            tx, ty = c2.x - c.x, c2.y - c.y
            L = math.hypot(tx, ty) or 1.0
            tx, ty = tx / L, ty / L
            nx, ny = ty, -tx
            side = 1 if (ai + int(dist)) % 2 == 0 else -1
            px, py = c.x + nx * (w / 2 + 1.3) * side, c.y + ny * (w / 2 + 1.3) * side
            zinc += _lamppost(px, py, (-nx * side, -ny * side), h=5.1, arm_len=1.5)

    # ── 3) GENS proches, naturels et bien répartis (3–11 m, sur trottoirs) ─
    # anti-chevauchement : on garde la trace des positions posées (rayon ~0.8 m)
    placed_pos = []

    def _free(px, py, rmin=0.85):
        return all((px - qx) ** 2 + (py - qy) ** 2 > rmin * rmin
                   for (qx, qy) in placed_pos)

    def _put_person(px, py, ang, sc):
        if not _free(px, py):
            return
        placed_pos.append((px, py))
        people.extend(_person(px, py, ang, scale=sc))

    # piétons solo échelonnés sur les trottoirs des bras (distances décalées
    # par bras pour casser l'alignement artificiel), tailles variées
    pid = 0
    for ai, (ls, t_j, w, dirv) in enumerate(arms):
        dists = [3.5, 7.0, 10.5] if ai % 2 == 0 else [4.8, 8.4]
        for di, dist in enumerate(dists):
            t = t_j + dist if (t_j + dist) < ls.length - 1.0 else t_j - dist
            if t < 0.5 or t > ls.length - 0.5:
                continue
            c = ls.interpolate(t)
            c2 = ls.interpolate(min(ls.length, t + 0.6))
            tx, ty = c2.x - c.x, c2.y - c.y
            L = math.hypot(tx, ty) or 1.0
            tx, ty = tx / L, ty / L
            nx, ny = ty, -tx
            side = 1 if (pid + ai) % 2 == 0 else -1
            # léger jitter latéral pour ne pas coller au cordeau
            jit = (0.25 if di % 2 else -0.2)
            px = c.x + nx * (w / 2 + 1.1 + jit) * side
            py = c.y + ny * (w / 2 + 1.1 + jit) * side
            walk = math.atan2(tx, ty) + (0.4 if pid % 2 else -0.4)  # le long du trottoir
            sc = 0.86 + (pid % 5) * 0.04      # adultes/ados : tailles variées
            _put_person(px, py, walk, sc)
            pid += 1
            # ~1 fois sur 2 : un 2e piéton juste à côté → groupe de 2 crédible
            if di % 2 == 0:
                cpx = px + tx * 0.65
                cpy = py + ty * 0.65
                _put_person(cpx, cpy, walk + 0.15, sc - 0.04)
                pid += 1

    # groupe au coin du pan coupé, TRÈS proche (lisible), légèrement éclaté
    gdx, gdy = cdx, cdy
    gtx, gty = -gdy, gdx                                 # tangente trottoir au coin
    for j, (off_a, off_t) in enumerate([(2.2, -0.9), (2.9, 0.6), (3.7, -0.1)]):
        gx = corner[0] + gdx * off_a + gtx * off_t
        gy = corner[1] + gdy * off_a + gty * off_t
        _put_person(gx, gy, math.atan2(gdy, gdx) + (j - 1) * 0.45,
                    0.90 + (j % 3) * 0.05)

    # 2 piétons traversant sur le passage piéton (proches du centre)
    if arms:
        ls0, t0, w0, _ = arms[0]
        cc = ls0.interpolate(min(ls0.length - 0.5, t0 + 5.5))
        c2 = ls0.interpolate(min(ls0.length, t0 + 5.5 + 0.6))
        tx, ty = c2.x - cc.x, c2.y - cc.y
        L = math.hypot(tx, ty) or 1.0
        tx, ty = tx / L, ty / L
        nx, ny = ty, -tx
        for kk, off in enumerate((-1.0, 0.8)):
            _put_person(cc.x + nx * off, cc.y + ny * off,
                        math.atan2(nx, ny), 0.92 + kk * 0.05)

    # ── 4) VÉLOS : 2-3, dont 1-2 cyclistes EN MOUVEMENT sur la chaussée ────
    # garés : contre le trottoir ; roulants : sur la voie, avec rider
    for bi, (ls, t_j, w, dirv) in enumerate(arms[:2]):
        # 1 vélo garé contre le trottoir
        t = t_j + 8.0 if (t_j + 8.0) < ls.length - 1.0 else t_j - 8.0
        if 0.5 < t < ls.length - 0.5:
            c = ls.interpolate(t)
            c2 = ls.interpolate(min(ls.length, t + 0.6))
            tx, ty = c2.x - c.x, c2.y - c.y
            L = math.hypot(tx, ty) or 1.0
            tx, ty = tx / L, ty / L
            nx, ny = ty, -tx
            bx = c.x + nx * (w / 2 + 0.55)
            by = c.y + ny * (w / 2 + 0.55)
            frames += _bike(bx, by, math.atan2(ty, tx))
        # 1 cycliste en mouvement sur la voie (proche bord, sens de circulation)
        tm = t_j + 12.0 if (t_j + 12.0) < ls.length - 1.0 else t_j - 12.0
        if 0.5 < tm < ls.length - 0.5:
            c = ls.interpolate(tm)
            c2 = ls.interpolate(min(ls.length, tm + 0.8))
            tx, ty = c2.x - c.x, c2.y - c.y
            L = math.hypot(tx, ty) or 1.0
            tx, ty = tx / L, ty / L
            nx, ny = ty, -tx
            side = 1 if bi == 0 else -1
            rx = c.x + nx * (w * 0.30) * side       # sur la chaussée, près du bord
            ry = c.y + ny * (w * 0.30) * side
            frames += _bike(rx, ry, math.atan2(ty, tx), rider=True)
            # cycliste assis (silhouette mince debout sur le vélo)
            people += _person(rx, ry + 0.0, math.atan2(ty, tx), scale=0.78)

    # ── 5) VOITURES : DÉSACTIVÉES ICI ────────────────────────────────────
    # Les voitures garées sont fournies (en FILE organisée) par enrich_street.py.
    # En ajouter ici EN PLUS de enrich_street + street_life entassait 3 sources
    # de voitures au premier plan droit → masse noire au canny. On laisse une
    # seule source (enrich_street). van conservé vide pour le reste du code.
    van = []

    # ── 6) MOBILIER URBAIN CONTEMPORAIN sobre le long des trottoirs ───────
    # 1-2 bancs modernes, 1 corbeille de rue, 1 borne, 1 abribus simple.
    # tout posé sur le trottoir réel (dérivé des bras), espacé, non chevauchant.
    if arms:
        # banc + corbeille sur le 1er bras (côté ensoleillé)
        ls0, t0, w0, _ = arms[0]
        for furn, dd, off_extra in [("bench", 6.0, 1.5), ("bin", 6.0, 1.5),
                                    ("bench", 14.0, 1.5)]:
            t = t0 + dd if (t0 + dd) < ls0.length - 1.0 else t0 - dd
            if not (0.5 < t < ls0.length - 0.5):
                continue
            c = ls0.interpolate(t)
            c2 = ls0.interpolate(min(ls0.length, t + 0.6))
            tx, ty = c2.x - c.x, c2.y - c.y
            L = math.hypot(tx, ty) or 1.0
            tx, ty = tx / L, ty / L
            nx, ny = ty, -tx
            px = c.x + nx * (w0 / 2 + off_extra)
            py = c.y + ny * (w0 / 2 + off_extra)
            if furn == "bench":
                zinc += _bench(px, py, math.atan2(ty, tx))
            else:
                # corbeille décalée le long du trottoir pour ne pas toucher le banc
                zinc += _bollard(px + tx * 1.2, py + ty * 1.2, kind="bin")
        # borne basse au coin du pan coupé (protection trottoir), à l'écart des gens
        zinc += _bollard(corner[0] + cdx * 1.4 - cdy * 1.6,
                         corner[1] + cdy * 1.4 + cdx * 1.6, kind="bollard")
        # abribus simple sur le 2e bras s'il existe (sinon sur le 1er, plus loin)
        ls_b, t_b, w_b, _ = arms[1] if len(arms) > 1 else arms[0]
        dd = 19.0
        t = t_b + dd if (t_b + dd) < ls_b.length - 2.0 else t_b - dd
        if 1.0 < t < ls_b.length - 1.0:
            c = ls_b.interpolate(t)
            c2 = ls_b.interpolate(min(ls_b.length, t + 1.0))
            tx, ty = c2.x - c.x, c2.y - c.y
            L = math.hypot(tx, ty) or 1.0
            tx, ty = tx / L, ty / L
            nx, ny = ty, -tx
            ax = c.x + nx * (w_b / 2 + 1.9)
            ay = c.y + ny * (w_b / 2 + 1.9)
            zinc += _bus_shelter(ax, ay, math.atan2(ty, tx))

    # ── nesting au format attendu par build().add() (listes de listes) ────
    def ql(qs):
        return [[list(q.v0), list(q.v1), list(q.v2), list(q.v3)] for q in qs]

    out = {}
    if white:  out["enduit_blanc"] = ql(white) + ql(van)   # marquages + van blanc
    if zinc:   out["zinc_anthracite"] = ql(zinc)            # poteaux + voitures sombres
    if people: out["voisin"] = ql(people) + ql(frames)      # gens + vélos
    return out
