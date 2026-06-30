"""Enrichissement RUE VERTE réelle (agent GREENERY) — additif, fichier isolé.

But : reproduire l'atmosphère VERTE de la vraie rue des Héros / Plaisance à
Nogent (haie taillée CONTINUE le long du trottoir, arbres de rue ALIGNÉS à
intervalle régulier, jardinets devant le soubassement). Tout en GÉOMÉTRIE (Quad)
pour que le canny FLUX cn0.70 le rende sans inventer.

PROBLÈME CORRIGÉ (2026-06-25) : l'ancienne version posait des « blocs verts
facettés empilés » au premier plan (haie = 2 faces + dessus PLAT, arbre = plans
croisés + disques carrés alignés sur les axes → cubes low-poly à 2K) et un AMAS
d'arbres au coin du carrefour. Réécriture :
  1. ORGANIQUE : haie multi-couches à dessus bombé/ondulé + faces ondulées ;
     arbre = canopée sphérique approchée par disques DÉCALÉS (jitter) + quads
     obliques multi-angles → lit comme du vrai feuillage après canny, pas un cube.
  2. COHÉRENT : UNE haie basse continue NETTE le long de chaque trottoir bordant
     la parcelle ; arbres de rue ALIGNÉS à intervalle régulier (~7,5 m) le long
     du même trottoir, jamais un tas au coin ; densité SOBRE et crédible.

Contrat : add_greenery(...) renvoie {materiau: [Quad|nested, ...]} mergé par build().
Matériaux EXISTANTS uniquement : 'vegetation' (feuillage), 'bois_clair' (troncs),
'terre_neutre' (terre/bacs), 'pierre_taille'/'enduit_blanc' (muret bas blanc),
'fer_forge' (grilles noires). NE PAS toucher d'autres fichiers. Helpers dispo via
`from build_real_scenarios import _box, Quad, ...`.

Réalité (survey_0/2/11, AMBIANCE_REELLE.md) : le long de CHAQUE trottoir, côté
parcelle, une HAIE taillée continue (~1.0 m) posée sur un MURET BLANC bas surmonté
d'une GRILLE fer noir ; arbres de rue alignés sur le trottoir.
"""
from __future__ import annotations
import math


# ── bruit déterministe (pas de random : reproductible build-à-build) ──────────
def _wob(seed: float, amp: float = 1.0) -> float:
    """Petite ondulation pseudo-aléatoire déterministe dans [-amp, +amp]."""
    s = math.sin(seed * 12.9898) * 43758.5453
    return (s - math.floor(s) - 0.5) * 2.0 * amp


def add_greenery(FP, SITE, JUNCTION, idx_rue, edge_free) -> dict:
    from build_real_scenarios import _box, Quad
    from shapely.geometry import LineString, Point, Polygon

    out = {
        "vegetation": [],     # feuillage haies + canopée arbres
        "bois_clair": [],     # troncs
        "enduit_blanc": [],   # muret bas blanc
        "pierre_taille": [],  # chapeau / pile de muret (pierre claire)
        "fer_forge": [],      # grille / clôture / portail fer noir
        "terre_neutre": [],   # bacs béton gris / terre nue
    }

    parcel = Polygon(SITE["fused_local"]).buffer(0)
    jx, jy = JUNCTION

    # paramètres haie / muret
    SW = 1.8                  # largeur trottoir (sidewalks_3d)
    HEDGE_H = 0.75            # haie BASSE (jardinet) → ne cage/cache pas le RDC
    HEDGE_T = 0.42            # demi-épaisseur haie
    WALL_H = 0.40             # muret blanc bas
    RAIL_H = 0.85             # (non utilisé : grille retirée, elle faisait "cage" devant la façade alignée)
    MAX_D_PARCEL = 18.0       # ne garnir que les rues bordant le bloc
    SEG = 1.5                 # pas de subdivision de la haie (lisse + ondulé)

    # ── HAIE ORGANIQUE : muret + grille + haie continue à dessus bombé/ondulé ──
    def hedge_run(p0, p1, off_n, nx, ny, tx, ty, base_seed):
        """Muret + grille + HAIE continue ondulée le long de p0->p1, décalé de
        off_n le long de (nx,ny). La haie a un dessus BOMBÉ (pente douce vers le
        centre) et des faces légèrement ondulées → lit organique, pas en cube."""
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if L < 1.0:
            return
        ax, ay = p0[0] + nx * off_n, p0[1] + ny * off_n
        bx, by = p1[0] + nx * off_n, p1[1] + ny * off_n

        # ── muret blanc bas (boîte fine) ──
        for t_off in (-0.10, 0.10):
            wx0, wy0 = ax + nx * t_off, ay + ny * t_off
            wx1, wy1 = bx + nx * t_off, by + ny * t_off
            out["enduit_blanc"].append(Quad((wx0, wy0, 0.0), (wx1, wy1, 0.0),
                                            (wx1, wy1, WALL_H), (wx0, wy0, WALL_H)))
        out["enduit_blanc"].append(Quad((ax - nx*0.10, ay - ny*0.10, WALL_H),
                                        (bx - nx*0.10, by - ny*0.10, WALL_H),
                                        (bx + nx*0.10, by + ny*0.10, WALL_H),
                                        (ax + nx*0.10, ay + ny*0.10, WALL_H)))  # chapeau
        # grille fer RETIRÉE : devant la façade alignée elle lisait comme une
        # cage de poteaux noirs sur un RDC vitré → on garde juste muret + haie basse.

        # ── HAIE ORGANIQUE, derrière le muret (côté parcelle) ──
        hb_off = off_n + 0.40   # décalée vers la parcelle
        # axe de la haie
        hax, hay = p0[0] + nx * hb_off, p0[1] + ny * hb_off
        hbx, hby = p1[0] + nx * hb_off, p1[1] + ny * hb_off

        # échantillonnage le long de la haie : pour chaque pas on a un profil
        # (épaisseur + hauteur ondulées) → on raccorde les sections pour faire un
        # ruban de feuillage à dessus bombé. On empile 2 couches de profondeur.
        nsamp = max(2, int(L / SEG) + 1)
        def section(t):
            # t in [0,1] le long de la haie
            cx = hax + (hbx - hax) * t
            cy = hay + (hby - hay) * t
            sd = base_seed + t * 6.0
            thick = HEDGE_T * (0.82 + 0.18 * (0.5 + 0.5 * math.cos(sd * 2.1)))
            thick += abs(_wob(sd + 3.0, 0.07))
            htop = HEDGE_H + _wob(sd, 0.10) + 0.06 * math.sin(t * math.pi)  # léger bombé
            return cx, cy, thick, htop

        prev = section(0.0)
        # faces + dessus bombé, couche par couche (2 couches verticales décalées)
        for layer, (lt_in, lt_out, ddrop) in enumerate(
                [(-1.0, 1.0, 0.0), (-0.55, 0.55, 0.18)]):  # couche externe + couche interne plus basse
            prev = section(0.0)
            for k in range(1, nsamp):
                t = k / (nsamp - 1)
                cur = section(t)
                (cx0, cy0, th0, h0), (cx1, cy1, th1, h1) = prev, cur
                h0 -= ddrop; h1 -= ddrop
                # face "outer" (vers la rue) et "inner" (vers parcelle)
                o0i = (cx0 + nx * th0 * lt_in, cy0 + ny * th0 * lt_in)
                o0o = (cx0 + nx * th0 * lt_out, cy0 + ny * th0 * lt_out)
                o1i = (cx1 + nx * th1 * lt_in, cy1 + ny * th1 * lt_in)
                o1o = (cx1 + nx * th1 * lt_out, cy1 + ny * th1 * lt_out)
                # face côté rue (lt_out)
                out["vegetation"].append(Quad((o0o[0], o0o[1], 0.0), (o1o[0], o1o[1], 0.0),
                                              (o1o[0], o1o[1], h1), (o0o[0], o0o[1], h0)))
                # face côté parcelle (lt_in)
                out["vegetation"].append(Quad((o0i[0], o0i[1], 0.0), (o1i[0], o1i[1], 0.0),
                                              (o1i[0], o1i[1], h1), (o0i[0], o0i[1], h0)))
                # dessus bombé (relie inner->outer au sommet, légèrement abaissé au centre)
                hm0 = h0 + 0.04; hm1 = h1 + 0.04
                out["vegetation"].append(Quad((o0i[0], o0i[1], h0), (o1i[0], o1i[1], h1),
                                              (o1o[0], o1o[1], h1), (o0o[0], o0o[1], h0)))
                # arête centrale légèrement surélevée (bombé) — 2 demi-quads
                cmid0 = (cx0, cy0, hm0); cmid1 = (cx1, cy1, hm1)
                out["vegetation"].append(Quad((o0i[0], o0i[1], h0), (o1i[0], o1i[1], h1),
                                              cmid1, cmid0))
                out["vegetation"].append(Quad(cmid0, cmid1,
                                              (o1o[0], o1o[1], h1), (o0o[0], o0o[1], h0)))
                prev = cur
        # bouts arrondis (faces d'extrémité) pour fermer la masse
        for (ex, ey, eth, eh, sd) in ((hax, hay, HEDGE_T, HEDGE_H, base_seed),
                                      (hbx, hby, HEDGE_T, HEDGE_H, base_seed + 9.0)):
            out["vegetation"].append(Quad((ex - nx*eth, ey - ny*eth, 0.0),
                                          (ex + nx*eth, ey + ny*eth, 0.0),
                                          (ex + nx*eth*0.6, ey + ny*eth*0.6, eh),
                                          (ex - nx*eth*0.6, ey - ny*eth*0.6, eh)))

    # ── ARBRE ORGANIQUE : tronc + canopée sphérique (disques décalés + quads obliques) ──
    def street_tree(x, y, in_bac, seed, scale=1.0):
        # Arbres d'alignement PETITS et FINS : depuis le POV plongeant, une grosse
        # canopée haute (5-6m) recouvrait les balcons du 1er = blobs gris "pod".
        # On garde la canopée SOUS la ligne de balcon (~3.6m) et un rayon réduit.
        r = 1.35 * scale
        hb = 1.7 * scale                       # base du feuillage
        ht = (hb + 1.9 * scale)                # sommet (~3.6m, sous les balcons)
        cz = (hb + ht) / 2.0                   # centre de la sphère foliaire
        cr = (ht - hb) / 2.0                   # rayon vertical
        z_trunk = 0.0
        if in_bac:
            out["terre_neutre"] += _box(x, y, 0.95, 0.95, 0.0, 0.45)  # bac béton gris
            z_trunk = 0.45
        # tronc (fin prisme)
        out["bois_clair"] += _box(x, y, 0.32, 0.32, z_trunk, hb + 0.15)

        # canopée = sphère approchée. Disques horizontaux DÉCALÉS en x/y (jitter)
        # + rayon variant en cosinus de la hauteur → profil ROND, pas un empilement
        # de carrés alignés. Chaque disque est lui-même un octogone (8 sommets via
        # 2 quads tournés) pour casser l'arête droite du carré à l'écran.
        nlay = 6
        for li in range(nlay):
            f = li / (nlay - 1)                 # 0..1 bas->haut
            zz = hb + f * (ht - hb)
            # rayon sphérique : sin sur l'angle vertical
            rr = r * math.sin(max(0.05, f) * math.pi) * (0.9 + 0.1 * _wob(seed + f, 1.0))
            rr = max(0.25, rr)
            jx_ = _wob(seed + f * 3.1, 0.45 * scale)
            jy_ = _wob(seed + 11.0 + f * 3.1, 0.45 * scale)
            ccx, ccy = x + jx_, y + jy_
            # octogone = 2 quads carrés, l'un tourné de 45°
            for rot in (0.0, math.pi / 4):
                c, s = math.cos(rot), math.sin(rot)
                pts = []
                for dx, dy in ((-rr, -rr), (rr, -rr), (rr, rr), (-rr, rr)):
                    pts.append((ccx + dx*c - dy*s, ccy + dx*s + dy*c, zz))
                out["vegetation"].append(Quad(*pts))
        # quelques plans obliques croisés à angles VARIÉS → volume vu de profil rue
        for a in (0.18, 1.05, 2.0, 2.7):
            dx, dy = math.cos(a) * r * 0.95, math.sin(a) * r * 0.95
            j = _wob(seed + a, 0.3)
            out["vegetation"].append(Quad((x - dx, y - dy, hb + 0.2),
                                          (x + dx, y + dy, hb + 0.2),
                                          (x + dx + j, y + dy, ht - 0.3),
                                          (x - dx + j, y - dy, ht - 0.3)))

    # ════════════════════════════════════════════════════════════════════════
    # 1) BANDE PLANTÉE — UNIQUEMENT contre une limite parcellaire AVEC RECUL réel
    #    du bâti (jardinet). RÈGLE DE PLACEMENT CORRIGÉE (2026-06-27) :
    #    L'ancienne version posait la haie à un OFFSET fixe depuis l'axe de la rue
    #    (half + trottoir), le long de CHAQUE segment bordant la parcelle. Pour un
    #    bâtiment ALIGNÉ sur rue (cas Nogent UA1 : FP == limite parcellaire,
    #    setback = 0 sur toute la façade), cette haie tombait DIRECTEMENT sur le
    #    trottoir et le dallage de passage, en travers du cheminement et devant
    #    l'entrée → buissons parasites sur les surfaces piétonnes.
    #
    #    Nouvelle logique GÉOMÉTRIQUEMENT JUSTE et UNIVERSELLE : une haie de rue
    #    n'a de sens que s'il existe un VRAI recul entre la limite de parcelle et
    #    le bâti (= bande de jardinet privée). On parcourt les ARÊTES de la
    #    PARCELLE qui font face à une rue ; pour chaque arête où le bâti (FP) est
    #    réellement en retrait (>= MIN_SETBACK), on plaque une bande verte NETTE
    #    et continue CONTRE la limite, côté propriété (jamais sur le trottoir).
    #    Là où le bâti est aligné (setback ~0), AUCUNE haie n'est posée : pas de
    #    place côté propriété, le cheminement reste libre. La verdure de rue est
    #    alors portée par les murets/grilles voisins + arbres de jardin voisins.
    # ════════════════════════════════════════════════════════════════════════
    MIN_SETBACK = 1.6         # recul bâti minimal pour qu'un jardinet existe (m)
    HEDGE_INSET = 0.45        # haie plaquée CONTRE la limite, côté propriété (m)
    fp_poly = Polygon(FP).buffer(0)
    roads_ls = [LineString(r["polyline"]) for r in SITE["roads"]
                if LineString(r["polyline"]).distance(parcel) < MAX_D_PARCEL]
    placed_hedge = []         # anti-doublon haie (midpoints posés)
    seed_ctr = 0

    if roads_ls:
        coords = list(parcel.exterior.coords)[:-1]
        npar = len(coords)
        for i in range(npar):
            a0 = coords[i]
            b0 = coords[(i + 1) % npar]
            ex, ey = b0[0] - a0[0], b0[1] - a0[1]
            L = math.hypot(ex, ey) or 1.0
            if L < 2.0:
                continue
            tx, ty = ex / L, ey / L
            nx, ny = ey / L, -ex / L
            mx, my = (a0[0] + b0[0]) / 2, (a0[1] + b0[1]) / 2

            # cette arête borde-t-elle une rue ?
            d_road = min(r.distance(Point(mx, my)) for r in roads_ls)
            if d_road > 8.0:
                continue   # arête de fond / mitoyenne, pas sur rue

            # y a-t-il un VRAI recul du bâti derrière cette limite ? (jardinet)
            if fp_poly.distance(Point(mx, my)) < MIN_SETBACK:
                continue   # bâti aligné sur la limite → pas de bande, on saute

            # normale orientée VERS la parcelle (côté propriété) pour la plaquer
            # CONTRE la limite, à l'intérieur, jamais vers le trottoir/la rue.
            if not parcel.contains(Point(mx + nx * 0.5, my + ny * 0.5)):
                nx, ny = -nx, -ny
            off_in = -HEDGE_INSET   # léger retrait à l'intérieur (côté propriété)

            # ── BANDE verte continue le long de cette limite (sous-tronçons) ──
            nsub = max(1, int(L // SEG))
            for ksub in range(nsub):
                t0 = ksub / nsub; t1 = (ksub + 1) / nsub
                a = (a0[0] + ex * t0, a0[1] + ey * t0)
                b = (a0[0] + ex * t1, a0[1] + ey * t1)
                hx = (a[0] + b[0]) / 2 + nx * off_in
                hy = (a[1] + b[1]) / 2 + ny * off_in
                # sécurité : ne JAMAIS poser un tronçon hors parcelle (= public)
                if not parcel.contains(Point(hx, hy)):
                    continue
                if any(math.hypot(hx - kx, hy - ky) < SEG * 0.8 for kx, ky in placed_hedge):
                    continue
                placed_hedge.append((hx, hy))
                seed_ctr += 1
                hedge_run(a, b, off_in, nx, ny, tx, ty, float(seed_ctr))

    # ════════════════════════════════════════════════════════════════════════
    # 3) MURETS BAS CRÈME + GRILLES/PORTAILS FER NOIR sur les limites des
    #    parcelles VOISINES qui bordent les 2 rues (survey_0/2/3/5 + AMBIANCE).
    #    Chaque pavillon/immeuble voisin a, côté rue, un muret enduit clair bas
    #    (~0.5 m) surmonté d'une grille/portail fer noir (~jusqu'à 1.1 m). C'est
    #    LA signature qui rend la rue close. On pose ça sur l'ARÊTE du polygone
    #    voisin la plus proche de la chaussée (= la limite sur rue).
    # ════════════════════════════════════════════════════════════════════════
    _garden_walls_and_gates(out, SITE, parcel, FP, JUNCTION, _box, Quad)

    # ════════════════════════════════════════════════════════════════════════
    # 4) GRANDS ARBRES DE JARDIN DÉBORDANTS : plantés DANS les jardins des
    #    VOISINS (entre leur bâti et la rue), canopée haute 4-7 m qui déborde
    #    par-dessus les murets → verdure haute de quartier, rue verte et close.
    #    RÈGLE ABSOLUE : aucun grand arbre devant NOTRE façade (FP) — chaque
    #    arbre est filtré à >8 m de FP ET hors du cône de vue façade↔caméra
    #    (POV plongeant carrefour_haut), sinon il se lit comme un blob gris.
    # ════════════════════════════════════════════════════════════════════════
    _overhang_garden_trees(out, SITE, parcel, FP, JUNCTION, _box, Quad)

    return {m: q for m, q in out.items() if q}


# ════════════════════════════════════════════════════════════════════════════
# MURETS + GRILLES FER NOIR (limites voisins sur rue)
# ════════════════════════════════════════════════════════════════════════════
def _garden_walls_and_gates(out, SITE, parcel, FP, JUNCTION, _box, Quad):
    """Muret enduit clair bas + grille fer noir sur l'arête de chaque voisin
    proche bordant une des 2 rues. Barreaux verticaux espacés → lit comme une
    vraie grille au canny (pas un mur plein noir). Un portail (montants +
    traverse haute) au milieu de l'arête la plus longue."""
    from shapely.geometry import LineString, Point, Polygon

    WALL_H = 0.50            # muret enduit clair bas
    CAP_H = 0.08             # chapeau pierre
    RAIL_TOP = 1.30          # sommet de la grille fer (lit mieux au canny)
    BAR_STEP = 0.26          # entraxe des barreaux verticaux
    BAR_W = 0.060            # demi-largeur barreau (plus épais → lisible 2K)
    MAX_D_ROAD = 6.0         # arête considérée "sur rue" si <6 m d'une chaussée
    MAX_D_PARCEL = 26.0      # ne traiter que les voisins du voisinage immédiat

    fp_poly = Polygon(FP).buffer(0)
    roads = [LineString(r["polyline"]) for r in SITE["roads"]
             if LineString(r["polyline"]).distance(parcel) < 14.0]
    if not roads:
        return

    def road_dist(px, py):
        p = Point(px, py)
        return min(r.distance(p) for r in roads)

    seed = 0
    for poly, h in SITE["voisins"]:
        vp = Polygon(poly).buffer(0)
        if vp.is_empty or vp.area < 30:
            continue
        # exclure le bâti démoli (sur notre parcelle) et les voisins lointains
        if vp.intersection(parcel).area / vp.area > 0.4:
            continue
        if vp.distance(parcel) > MAX_D_PARCEL:
            continue

        coords = list(vp.exterior.coords)[:-1]
        n = len(coords)
        # pour chaque arête du voisin, garder celles qui longent une rue
        for i in range(n):
            a = coords[i]
            b = coords[(i + 1) % n]
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            if road_dist(mx, my) > MAX_D_ROAD:
                continue
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 2.0:
                continue
            tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, ny = ty, -tx
            # normale orientée VERS la rue (côté qui rapproche d'une chaussée)
            if road_dist(mx + nx * 0.6, my + ny * 0.6) > road_dist(mx - nx * 0.6, my - ny * 0.6):
                nx, ny = -nx, -ny
            # décaler l'arête ~0.6 m vers la rue (limite séparative devant le bâti)
            off = 0.6
            ax, ay = a[0] + nx * off, a[1] + ny * off
            bx, by = b[0] + nx * off, b[1] + ny * off

            seed += 1
            # ── muret enduit clair (boîte fine) ──
            for t_off in (-0.09, 0.09):
                out["enduit_blanc"].append(Quad(
                    (ax + nx * t_off, ay + ny * t_off, 0.0),
                    (bx + nx * t_off, by + ny * t_off, 0.0),
                    (bx + nx * t_off, by + ny * t_off, WALL_H),
                    (ax + nx * t_off, ay + ny * t_off, WALL_H)))
            # chapeau pierre claire
            out["pierre_taille"].append(Quad(
                (ax - nx * 0.11, ay - ny * 0.11, WALL_H),
                (bx - nx * 0.11, by - ny * 0.11, WALL_H),
                (bx + nx * 0.11, by + ny * 0.11, WALL_H),
                (ax + nx * 0.11, ay + ny * 0.11, WALL_H)))
            out["pierre_taille"].append(Quad(
                (ax - nx * 0.11, ay - ny * 0.11, WALL_H + CAP_H),
                (bx - nx * 0.11, by - ny * 0.11, WALL_H + CAP_H),
                (bx + nx * 0.11, by + ny * 0.11, WALL_H + CAP_H),
                (ax + nx * 0.11, ay + ny * 0.11, WALL_H + CAP_H)))

            # ── grille fer noir : barreaux verticaux + traverses haut/bas ──
            nbar = max(2, int(L / BAR_STEP))
            for k in range(nbar + 1):
                t = k / nbar
                bxp = ax + (bx - ax) * t
                byp = ay + (by - ay) * t
                out["fer_forge"] += _box(bxp, byp, BAR_W * 2, BAR_W * 2,
                                         WALL_H + CAP_H, RAIL_TOP)
            # traverse horizontale supérieure (fin bandeau)
            for zz in (RAIL_TOP - 0.06, WALL_H + CAP_H + 0.05):
                out["fer_forge"].append(Quad(
                    (ax - nx * BAR_W, ay - ny * BAR_W, zz),
                    (bx - nx * BAR_W, by - ny * BAR_W, zz),
                    (bx + nx * BAR_W, by + ny * BAR_W, zz + 0.05),
                    (ax + nx * BAR_W, ay + ny * BAR_W, zz + 0.05)))

            # ── portail : 2 montants un peu plus hauts au milieu de l'arête ──
            if L > 5.0:
                for s in (-1.2, 1.2):
                    gx = mx + nx * off + tx * s
                    gy = my + ny * off + ty * s
                    out["fer_forge"] += _box(gx, gy, 0.12, 0.12, 0.0, RAIL_TOP + 0.25)


# ════════════════════════════════════════════════════════════════════════════
# GRANDS ARBRES DE JARDIN DÉBORDANTS (jardins des voisins, jamais devant FP)
# ════════════════════════════════════════════════════════════════════════════
def _overhang_garden_trees(out, SITE, parcel, FP, JUNCTION, _box, Quad):
    """Grands arbres (canopée 4-7 m) plantés dans les jardins des voisins, entre
    leur bâti et la rue, qui débordent sur la rue. Filtrage STRICT :
      - centre de l'arbre + emprise canopée à >8 m de FP (Polygon) ;
      - hors du cône de vue façade↔caméra du POV plongeant carrefour_haut
        (caméra ~ au-dessus du carrefour, regarde le bâtiment) → sinon blob gris.
    """
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import nearest_points

    fp_poly = Polygon(FP).buffer(0)
    jx, jy = JUNCTION
    fcx, fcy = fp_poly.centroid.x, fp_poly.centroid.y

    # direction caméra→bâtiment (le cône de vue à proscrire part du carrefour
    # vers le centre de FP). On exclut tout grand arbre dont l'angle au carrefour
    # est proche de cet axe ET qui est en avant de FP (entre caméra et façade).
    cam_ang = math.atan2(fcy - jy, fcx - jx)

    roads = [LineString(r["polyline"]) for r in SITE["roads"]
             if LineString(r["polyline"]).distance(parcel) < 14.0]

    # empreinte TROTTOIR + CHAUSSÉE : le TRONC d'un arbre de jardin voisin ne
    # doit JAMAIS y tomber (un arbre vit dans le jardin, sa canopée peut déborder
    # par-dessus le muret, mais son tronc reste côté propriété, pas sur le
    # cheminement). On reconstruit l'empreinte des surfaces de circulation.
    try:
        from build_real_scenarios import sidewalks_3d
        from shapely.ops import unary_union as _uu
        _walk_quads = sidewalks_3d(SITE["roads"])
        _walk = _uu([Polygon([(q.v0[0], q.v0[1]), (q.v1[0], q.v1[1]),
                              (q.v2[0], q.v2[1]), (q.v3[0], q.v3[1])]).buffer(0)
                     for q in _walk_quads])
        # + emprise chaussée (bande autour de chaque axe)
        _road_band = _uu([r.buffer(max(2.5, 2.0)) for r in roads])
        walk_road = _walk.union(_road_band)
    except Exception:
        walk_road = None

    MIN_D_FP = 8.0
    CONE_HALF = math.radians(26.0)   # demi-angle du cône caméra→façade interdit

    def in_camera_cone(px, py, canopy_r):
        """Vrai si (px,py) tombe dans le cône caméra→façade ET en avant de FP
        (donc se projetterait DEVANT la façade depuis le POV plongeant)."""
        d_arbre = math.hypot(px - jx, py - jy)
        d_fp = fp_poly.distance(Point(jx, jy))
        # seulement gênant si l'arbre est entre la caméra et la façade (devant)
        if d_arbre > fp_poly.centroid.distance(Point(jx, jy)) + 4.0:
            return False
        ang = math.atan2(py - jy, px - jx)
        dang = abs(math.atan2(math.sin(ang - cam_ang), math.cos(ang - cam_ang)))
        # élargir le cône proportionnellement au rayon de canopée
        eff = CONE_HALF + math.atan2(canopy_r, max(2.0, d_arbre))
        return dang < eff

    def big_tree(x, y, seed, height, radius):
        """Grand arbre organique : tronc + canopée sphérique haute (disques
        décalés + plans obliques). Même langage que street_tree mais GRAND."""
        hb = 1.8                       # base du feuillage
        ht = height                    # sommet (4-7 m)
        r = radius
        out["bois_clair"] += _box(x, y, 0.40, 0.40, 0.0, hb + 0.3)
        nlay = 7
        for li in range(nlay):
            f = li / (nlay - 1)
            zz = hb + f * (ht - hb)
            rr = r * math.sin(max(0.05, f) * math.pi) * (0.88 + 0.12 * _wob(seed + f, 1.0))
            rr = max(0.4, rr)
            jx_ = _wob(seed + f * 3.1, 0.6)
            jy_ = _wob(seed + 11.0 + f * 3.1, 0.6)
            ccx, ccy = x + jx_, y + jy_
            for rot in (0.0, math.pi / 4):
                c, s = math.cos(rot), math.sin(rot)
                pts = []
                for dx, dy in ((-rr, -rr), (rr, -rr), (rr, rr), (-rr, rr)):
                    pts.append((ccx + dx * c - dy * s, ccy + dx * s + dy * c, zz))
                out["vegetation"].append(Quad(*pts))
        for a in (0.2, 1.0, 1.9, 2.7, 3.5, 4.4):
            dx, dy = math.cos(a) * r * 0.92, math.sin(a) * r * 0.92
            j = _wob(seed + a, 0.4)
            out["vegetation"].append(Quad((x - dx, y - dy, hb + 0.4),
                                          (x + dx, y + dy, hb + 0.4),
                                          (x + dx + j, y + dy, ht - 0.4),
                                          (x - dx + j, y - dy, ht - 0.4)))

    placed = []
    seed = 100
    for poly, h in SITE["voisins"]:
        vp = Polygon(poly).buffer(0)
        if vp.is_empty or vp.area < 60:
            continue
        if vp.intersection(parcel).area / vp.area > 0.4:
            continue
        if not roads:
            continue
        d_road = min(r.distance(vp) for r in roads)
        if d_road > 12.0:
            continue   # voisin pas en bord de rue → jardin non visible de la rue
        if vp.distance(fp_poly) < 6.0:
            continue   # voisin mitoyen de NOTRE bâti → trop près de FP, on saute

        # planter 1-2 arbres dans la BANDE jardin entre le bâti voisin et la rue
        # (point sur l'arête côté rue, ramené ~2.5 m vers la rue = jardinet).
        nearest_road = min(roads, key=lambda r: r.distance(vp))
        p_v, p_r = nearest_points(vp, nearest_road)
        dx, dy = p_r.x - p_v.x, p_r.y - p_v.y
        dlen = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dlen, dy / dlen      # direction bâti→rue

        # 2 candidats le long de l'arête côté rue, légèrement avancés sur le jardin.
        # Canopées GÉNÉREUSES (4-7 m, rayon ~3 m) → débordent franchement sur la
        # rue par-dessus les murets ; ce sont elles qui font la rue verte close.
        edge_tan_x, edge_tan_y = -uy, ux
        for s, hgt, rad in ((-3.2, 5.8, 3.0), (3.2, 6.6, 3.2)):
            gx = p_v.x + ux * 1.5 + edge_tan_x * s
            gy = p_v.y + uy * 1.5 + edge_tan_y * s
            p = Point(gx, gy)
            # filtres durs
            d_fp = fp_poly.distance(p)
            if d_fp < MIN_D_FP + rad:          # canopée doit rester à >8 m de FP
                continue
            if fp_poly.buffer(MIN_D_FP).contains(p):
                continue
            if in_camera_cone(gx, gy, rad):    # pas dans le cône caméra→façade
                continue
            if parcel.contains(p):
                continue
            # le TRONC ne tombe jamais sur le trottoir/chaussée de passage
            if walk_road is not None and walk_road.contains(p):
                continue
            if any(math.hypot(gx - kx, gy - ky) < 5.0 for kx, ky in placed):
                continue
            placed.append((gx, gy))
            seed += 7
            big_tree(gx, gy, float(seed), hgt, rad)
