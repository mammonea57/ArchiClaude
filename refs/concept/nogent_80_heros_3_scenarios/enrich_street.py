"""Enrichissement RUE / CHAUSSÉE + ambiance carrefour (agent STREET) — additif.

But : que le carrefour T (Rue des Héros × Rue de Plaisance) se LISE vraiment dans
le cadre — vraie chaussée asphalte des DEUX rues, marquages (axe, stop, bandes),
bordures de trottoir, voitures garées en file le long des rues réelles, ambiance.
Tout en GÉOMÉTRIE (Quad) → le canny FLUX cn0.70 le rend sans inventer.

Contrat : add_street(FP, SITE, JUNCTION) renvoie {materiau: [Quad|nested]} mergé
par build(). Matériaux existants : 'asphalte', 'enduit_blanc' (marquages/van),
'pavers_concrete' (bordures/trottoir), 'zinc_anthracite' (voitures sombres),
'pierre_kerb'. Helpers : `from build_real_scenarios import _box, _car, Quad`.
NE PAS toucher d'autres fichiers.

Conventions de hauteur (cohérence avec build_real_scenarios) :
  sidewalks_3d ~0.004 | roads_3d (asphalte base) ~0.02 | damier ~0.065
  → on pose : chaussée renforcée Z_ROAD=0.030 (au-dessus base, sous damier),
    marquages Z_MARK=0.048 (lisibles, sous le damier), bordure = chant vertical
    qui MONTE (trottoir surélevé) → la rue se creuse, lit comme une vraie rue.

On NE duplique PAS : roads_3d (asphalte général), sidewalks_3d, damier_*, ni la
vie de street_life — on la COMPLÈTE (voitures décalées, autres distances/côté).
"""
from __future__ import annotations
import math

Z_ROAD = 0.030          # bande d'asphalte renforcée des bras du carrefour
Z_MARK = 0.048          # marquages peints (au-dessus chaussée, sous damier 0.065)
Z_KERB_TOP = 0.14       # haut de la bordure béton (trottoir surélevé)
REACH = 30.0            # longueur (m) de chaussée renforcée depuis le carrefour
JUNCT_NEAR = 10.0       # une route fait partie du carrefour si <Xm du JUNCTION


def _quad(a, b, c, d, z):
    from build_real_scenarios import Quad
    return Quad((a[0], a[1], z), (b[0], b[1], z), (c[0], c[1], z), (d[0], d[1], z))


def _junction_roads(roads, junction):
    """Routes qui composent le carrefour (bras du T), avec leur LineString et
    l'abscisse curviligne du carrefour sur chacune."""
    from shapely.geometry import LineString, Point
    jp = Point(junction)
    out = []
    for r in roads:
        pl = r["polyline"]
        if len(pl) < 2:
            continue
        ls = LineString(pl)
        d = ls.distance(jp)
        if d > JUNCT_NEAR:
            continue
        t_j = ls.project(jp)
        w = max(2.5, float(r.get("chaussee_m") or 4.0))
        out.append((ls, t_j, w))
    return out


def _sample(ls, t):
    """Point + tangente unitaire de la polyligne à l'abscisse t (clampée)."""
    t = max(0.0, min(ls.length, t))
    c = ls.interpolate(t)
    c2 = ls.interpolate(min(ls.length, t + 0.6))
    if t + 0.6 > ls.length:
        c2 = ls.interpolate(max(0.0, t - 0.6))
        c, c2 = c2, c
    tx, ty = c2.x - c.x, c2.y - c.y
    L = math.hypot(tx, ty) or 1.0
    return (c.x, c.y), (tx / L, ty / L)


def add_street(FP, SITE, JUNCTION) -> dict:
    """RENFORCE la lecture de la chaussée + du carrefour T. Voir docstring module."""
    try:
        from build_real_scenarios import _car
    except Exception:
        _car = None

    out = {
        "asphalte": [],          # bande de roulement nette des 2 bras
        "enduit_blanc": [],      # marquages (axe, stop, bandes latérales) + 1 van clair
        "pavers_concrete": [],   # bordures de trottoir béton
        "pierre_kerb": [],       # chant vertical de la bordure (relief)
        "zinc_anthracite": [],   # voitures garées sombres
    }

    roads = SITE.get("roads", [])
    branches = _junction_roads(roads, JUNCTION)
    if not branches:
        return {}

    for (ls, t_j, w) in branches:
        half = w / 2.0
        # bornes le long du bras : du carrefour (au bord du damier ~7.5m) jusqu'à REACH,
        # des deux côtés du carrefour (avant/après l'abscisse t_j).
        for sense in (+1.0, -1.0):
            t_start = t_j + sense * 7.0       # on laisse la place au damier au centre
            t_end = t_j + sense * REACH
            t_lo, t_hi = sorted((t_start, t_end))
            t_lo = max(1.0, t_lo)
            t_hi = min(ls.length - 1.0, t_hi)
            if t_hi - t_lo < 3.0:
                continue

            # --- 1) bande d'asphalte renforcée (segmentée pour suivre les coudes) ---
            n_seg = max(2, int((t_hi - t_lo) // 4.0))
            ring = []
            prev = None
            tt = t_lo
            step = (t_hi - t_lo) / n_seg
            samples = []
            for k in range(n_seg + 1):
                t = t_lo + k * step
                (px, py), (tx, ty) = _sample(ls, t)
                nx, ny = ty, -tx
                samples.append(((px, py), (tx, ty), (nx, ny)))
            for k in range(n_seg):
                (pa, ta, na) = samples[k]
                (pb, tb, nb) = samples[k + 1]
                la = (pa[0] + na[0] * half, pa[1] + na[1] * half)
                ra = (pa[0] - na[0] * half, pa[1] - na[1] * half)
                lb = (pb[0] + nb[0] * half, pb[1] + nb[1] * half)
                rb = (pb[0] - nb[0] * half, pb[1] - nb[1] * half)
                out["asphalte"].append(_quad(la, lb, rb, ra, Z_ROAD))

            # --- 2) bordures de trottoir béton le long des 2 chants ---
            for side in (+1.0, -1.0):
                for k in range(n_seg):
                    (pa, ta, na) = samples[k]
                    (pb, tb, nb) = samples[k + 1]
                    o0 = half * side
                    o1 = (half + 0.22) * side
                    a0 = (pa[0] + na[0] * o0, pa[1] + na[1] * o0)
                    a1 = (pa[0] + na[0] * o1, pa[1] + na[1] * o1)
                    b0 = (pb[0] + nb[0] * o0, pb[1] + nb[1] * o0)
                    b1 = (pb[0] + nb[0] * o1, pb[1] + nb[1] * o1)
                    # dessus de la bordure (béton clair)
                    out["pavers_concrete"].append(_quad(a0, b0, b1, a1, Z_KERB_TOP))
                    # chant vertical côté chaussée (relief = la rue se creuse)
                    from build_real_scenarios import Quad
                    out["pierre_kerb"].append(Quad(
                        (a0[0], a0[1], Z_ROAD), (b0[0], b0[1], Z_ROAD),
                        (b0[0], b0[1], Z_KERB_TOP), (a0[0], a0[1], Z_KERB_TOP)))

            # --- 3) marquages ---
            # ligne axiale pointillée au centre de la chaussée
            dash = 1.4
            t = t_lo
            on = True
            while t < t_hi:
                t2 = min(t_hi, t + dash)
                if on and t2 - t > 0.4:
                    (pa, _, na) = None, None, None
                    (p1, _, n1) = _sample_full(ls, t)
                    (p2, _, n2) = _sample_full(ls, t2)
                    hwid = 0.09
                    a = (p1[0] + n1[0] * hwid, p1[1] + n1[1] * hwid)
                    b = (p1[0] - n1[0] * hwid, p1[1] - n1[1] * hwid)
                    c = (p2[0] - n2[0] * hwid, p2[1] - n2[1] * hwid)
                    d = (p2[0] + n2[0] * hwid, p2[1] + n2[1] * hwid)
                    out["enduit_blanc"].append(_quad(a, d, c, b, Z_MARK))
                on = not on
                t = t2

            # ligne d'arrêt épaisse en travers, juste avant le carrefour
            t_stop = t_j + sense * 7.6
            if 1.0 < t_stop < ls.length - 1.0:
                (ps, _, ns) = _sample_full(ls, t_stop)
                ts = (-ns[1], ns[0])  # tangente ⟂ normale
                # bande pleine sur la demi-chaussée d'arrivée, largeur 0.5m
                bw = 0.5
                # demi côté droit de la voie (sens d'arrivée)
                a = (ps[0] + ns[0] * 0.1, ps[1] + ns[1] * 0.1)
                b = (ps[0] + ns[0] * (half - 0.1), ps[1] + ns[1] * (half - 0.1))
                a2 = (a[0] - ts[0] * bw, a[1] - ts[1] * bw)
                b2 = (b[0] - ts[0] * bw, b[1] - ts[1] * bw)
                out["enduit_blanc"].append(_quad(a, b, b2, a2, Z_MARK))

            # bandes latérales de rive (filet blanc le long des 2 bords)
            for side in (+1.0, -1.0):
                for k in range(n_seg):
                    (pa, ta, na) = samples[k]
                    (pb, tb, nb) = samples[k + 1]
                    o = (half - 0.30) * side
                    a0 = (pa[0] + na[0] * o, pa[1] + na[1] * o)
                    b0 = (pb[0] + nb[0] * o, pb[1] + nb[1] * o)
                    a1 = (pa[0] + na[0] * (o + 0.10 * side), pa[1] + na[1] * (o + 0.10 * side))
                    b1 = (pb[0] + nb[0] * (o + 0.10 * side), pb[1] + nb[1] * (o + 0.10 * side))
                    out["enduit_blanc"].append(_quad(a0, b0, b1, a1, Z_MARK))

            # --- 4) voitures garées EN FILE serrée contre la bordure ---
            # street_life place déjà ses voitures côté +n à dd=(12,20,28) avec un
            # offset 3.2 (au milieu de la voie → mur de boîtes). On pose UNE file
            # PROPRE le long de la bordure côté -n, bien espacée (~7m), démarrant
            # assez loin du damier pour ne pas l'empiler. Pas de double rangée.
            if _car is not None:
                offset = half - 0.85     # voiture serrée le long de la bordure
                d = 11.0                 # commence après le damier + ligne d'arrêt
                idx = 0
                while d < REACH - 3.0:
                    t = t_j + sense * d
                    if 1.0 < t < ls.length - 1.0:
                        (pc, (tx, ty), nrm) = _sample_full(ls, t)
                        ang = math.atan2(ty, tx)
                        cx = pc[0] - nrm[0] * offset
                        cy = pc[1] - nrm[1] * offset
                        cars = _car(cx, cy, ang)
                        # 1 van clair de temps en temps, le reste sombre
                        if idx % 3 == 2:
                            out["enduit_blanc"] += cars
                        else:
                            out["zinc_anthracite"] += cars
                        idx += 1
                    d += 7.0             # ~7m centre-à-centre → pas de chevauchement

    # nettoyage : pas de listes vides
    return {m: q for m, q in out.items() if q}


def _sample_full(ls, t):
    """Comme _sample mais renvoie (point, tangente, normale)."""
    t = max(0.0, min(ls.length, t))
    c = ls.interpolate(t)
    c2 = ls.interpolate(min(ls.length, t + 0.6))
    if t + 0.6 > ls.length:
        c2 = ls.interpolate(max(0.0, t - 0.6))
        c, c2 = c2, c
    tx, ty = c2.x - c.x, c2.y - c.y
    L = math.hypot(tx, ty) or 1.0
    tx, ty = tx / L, ty / L
    return (c.x, c.y), (tx, ty), (ty, -tx)
