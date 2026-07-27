"""U-shape (îlot à cour ouverte) layout handler.

Reproduit fidèlement le design "U mono-façade" VALIDÉ PAR L'USER (prototype
scratchpad/render_u_monofacade.py + proto_traversant.single_facade_apt) :

- Forme U : un BANDEAU (le côté fermé) + 2 AILES qui flanquent l'échancrure
  (la cour). Profondeur d'aile ~9 m.
- EXACTEMENT 2 cages escalier+ascenseur, une à chaque ANGLE INTÉRIEUR
  (jonction bandeau/aile).
- Couloir périmètre en ⊓ (largeur PMR ≥1.2 m) reliant les 2 cages, côté
  rue/mitoyen (côté extérieur, opposé à la cour).
- Logements MONO-FAÇADE côté COUR : chambres + séjour ont leur fenêtre sur
  la cour intérieure du U. PAS de traversant.
- Bandeau = apts collés bord à bord remplissant l'espace ENTRE les 2 cages ;
  les coins sont absorbés dans les séjours des apts d'extrémité (0 cellier
  borgne isolé).

CHOIX MODÈLE (le pipeline n'accepte qu'UN core Polygon simple — il calcule
bounds/centroïde de ``LLayoutResult.core`` dans pipeline.py) :
  → la cage PRINCIPALE va dans ``core`` (Polygon simple).
  → la 2e cage est FUSIONNÉE (union) dans ``corridor``. Le couloir en ⊓
    touche déjà les 2 cages, donc l'union reste un couloir connexe, et la
    2e cage reste visible/représentée comme circulation verticale.

Le handler est axis-aligned et généralise aux VRAIES coordonnées du
footprint reçu (bounds réels lus dynamiquement — aucun 48×40 hardcodé).
Style volontairement calqué sur layout_l.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import box as shp_box
from shapely.ops import unary_union

from core.building_model.schemas import Typologie
from core.building_model.layout_l import LLayoutResult
from core.building_model.solver import ApartmentSlot


# ── Constantes design (calées sur le prototype user) ─────────────────────
_WING_DEPTH_DEFAULT = 9.0     # profondeur d'aile / bandeau visée
_CAGE_SIDE = 4.0              # côté d'une cage (esc + asc PMR compact)
_CAGE_LEN = 4.5              # longueur cage le long du couloir
_MIN_APT_WIDTH_M = 5.5        # frontage mini apt vendable
_MIN_WING_DEPTH = 6.0         # sous ça, pas de logement mono-façade viable
# Couloir mono-façade single-loaded = mini PMR 1,20 m (calé sur le prototype
# validé : à 1,6 m la circulation dépasse 20 %, à 1,2 m on tient 18-19 %).
_U_CORRIDOR_WIDTH = 1.2


@dataclass(frozen=True)
class UDecomposition:
    """Résultat de la décomposition d'un footprint U.

    - bar : le BANDEAU (côté fermé du U), rectangle.
    - arm_a / arm_b : les 2 AILES flanquant la cour, rectangles.
    - opens : côté vers lequel s'ouvre la cour ("nord"/"sud"/"est"/"ouest").
    - court : polygone de la cour intérieure (échancrure du U).
    """
    bar: ShapelyPolygon
    arm_a: ShapelyPolygon
    arm_b: ShapelyPolygon
    opens: str
    court: ShapelyPolygon


def _find_reflexes(footprint: ShapelyPolygon) -> list[tuple[float, float]]:
    """Retourne les sommets concaves (angles rentrants) après simplification.

    Un U propre en a exactement 2, partageant une coordonnée (ligne d'ouverture).
    """
    poly = footprint.simplify(0.8)
    if poly.geom_type != "Polygon" or poly.area < footprint.area * 0.9:
        poly = footprint
    coords = list(poly.exterior.coords)[:-1]
    if not poly.exterior.is_ccw:
        coords = coords[::-1]
    n = len(coords)
    out: list[tuple[float, float]] = []
    for i in range(n):
        p0 = coords[(i - 1) % n]
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if cross < -0.5:
            out.append((p1[0], p1[1]))
    return out


def decompose_u(
    footprint: ShapelyPolygon, min_depth: float = _MIN_WING_DEPTH,
) -> UDecomposition | None:
    """Décompose un footprint U axis-aligned en bandeau + 2 ailes.

    Généralise aux 4 orientations d'ouverture (cour au nord/sud/est/ouest)
    via les 2 sommets rentrants qui partagent une coordonnée. Renvoie None si
    ce n'est pas un U propre (le dispatcher retombera sur le layout legacy).

    Lit les BOUNDS RÉELS du footprint — aucune coordonnée hardcodée.
    """
    minx, miny, maxx, maxy = footprint.bounds
    reflexes = _find_reflexes(footprint)
    if len(reflexes) != 2:
        return None

    (ax, ay), (bx, by) = reflexes[0], reflexes[1]
    buf = footprint.buffer(0.1)
    tol = 1.0

    if abs(ay - by) < tol:
        # U vertical : ouverture vers le haut ou le bas, ligne de reflex y=ry.
        ry = (ay + by) / 2
        xl, xr = sorted((ax, bx))
        opens_up = not buf.contains(ShapelyPoint((xl + xr) / 2, ry + 0.5))
        if opens_up:
            # bandeau en bas, ailes montent de ry à maxy de part et d'autre.
            bar = shp_box(minx, miny, maxx, ry)
            arm_a = shp_box(minx, ry, xl, maxy)
            arm_b = shp_box(xr, ry, maxx, maxy)
            court = shp_box(xl, ry, xr, maxy)
            opens = "nord"
        else:
            bar = shp_box(minx, ry, maxx, maxy)
            arm_a = shp_box(minx, miny, xl, ry)
            arm_b = shp_box(xr, miny, maxx, ry)
            court = shp_box(xl, miny, xr, ry)
            opens = "sud"
    elif abs(ax - bx) < tol:
        # U horizontal : ouverture vers la gauche/droite, ligne de reflex x=rx.
        rx = (ax + bx) / 2
        yb, yt = sorted((ay, by))
        opens_right = not buf.contains(ShapelyPoint(rx + 0.5, (yb + yt) / 2))
        if opens_right:
            bar = shp_box(minx, miny, rx, maxy)
            arm_a = shp_box(rx, miny, maxx, yb)
            arm_b = shp_box(rx, yt, maxx, maxy)
            court = shp_box(rx, yb, maxx, yt)
            opens = "est"
        else:
            bar = shp_box(rx, miny, maxx, maxy)
            arm_a = shp_box(minx, miny, rx, yb)
            arm_b = shp_box(minx, yt, rx, maxy)
            court = shp_box(minx, yb, rx, yt)
            opens = "ouest"
    else:
        return None

    # Contrôle qualité : chaque membre doit avoir une profondeur exploitable.
    for w in (bar, arm_a, arm_b):
        wb = w.bounds
        if w.area <= 0 or min(wb[2] - wb[0], wb[3] - wb[1]) < min_depth:
            return None
    if court.area <= 0:
        return None

    # ANTI FAUX-POSITIF (T, +, croix…) : un VRAI U a son bandeau et ses 2 ailes
    # QUASI ENTIÈREMENT DANS le footprint, et sa cour QUASI ENTIÈREMENT HORS du
    # footprint (c'est l'échancrure ouverte). Pour un T lu à tort comme U, le
    # "bandeau" déborde hors emprise et la "cour" (base de l'excroissance) est
    # DANS l'emprise → on rejette.
    fp = footprint.buffer(0.05)
    for w in (bar, arm_a, arm_b):
        if w.intersection(fp).area < 0.92 * w.area:
            return None
    if court.intersection(fp).area > 0.15 * court.area:
        return None

    return UDecomposition(
        bar=bar, arm_a=arm_a, arm_b=arm_b, opens=opens, court=court,
    )


def _cour_side_of(rect: ShapelyPolygon, court: ShapelyPolygon) -> str:
    """Côté du rectangle (sud/nord/est/ouest) qui donne sur la cour."""
    rx0, ry0, rx1, ry1 = rect.bounds
    # On sonde 0.4 m au-delà de chaque arête ; celle qui tombe dans la cour
    # est la façade cour.
    court_buf = court.buffer(0.5)
    probes = {
        "sud": ShapelyPoint((rx0 + rx1) / 2, ry0 - 0.4),
        "nord": ShapelyPoint((rx0 + rx1) / 2, ry1 + 0.4),
        "ouest": ShapelyPoint(rx0 - 0.4, (ry0 + ry1) / 2),
        "est": ShapelyPoint(rx1 + 0.4, (ry0 + ry1) / 2),
    }
    for side, pt in probes.items():
        if court_buf.contains(pt):
            return side
    return "sud"


def build_u_corridor(
    d: UDecomposition, corridor_width: float = 1.6,
) -> ShapelyPolygon:
    """Construit le couloir périmètre en ⊓ côté EXTÉRIEUR (opposé à la cour).

    Le couloir longe la face extérieure du bandeau puis remonte le long de la
    face extérieure de chaque aile → connexe, relie les 2 futures cages.
    """
    bx0, by0, bx1, by1 = d.bar.bounds
    a = d.arm_a.bounds
    b = d.arm_b.bounds
    cw = corridor_width

    strips: list[ShapelyPolygon] = []
    if d.opens in ("nord", "sud"):
        # Ailes verticales. Le couloir bandeau longe la face extérieure du
        # bandeau (opposée à la cour) ; les couloirs d'aile longent leur face
        # extérieure (bord gauche pour arm_a, bord droit pour arm_b).
        if d.opens == "nord":
            # bandeau en bas → face extérieure = bord bas (by0).
            strips.append(shp_box(bx0, by0, bx1, by0 + cw))
        else:
            # bandeau en haut → face extérieure = bord haut (by1).
            strips.append(shp_box(bx0, by1 - cw, bx1, by1))
        # aile gauche : couloir sur son bord gauche (extérieur), sur toute sa hauteur.
        strips.append(shp_box(a[0], min(a[1], by0), a[0] + cw, max(a[3], by1)))
        # aile droite : couloir sur son bord droit (extérieur).
        strips.append(shp_box(b[2] - cw, min(b[1], by0), b[2], max(b[3], by1)))
    else:
        # Ailes horizontales (U ouvert est/ouest).
        if d.opens == "est":
            # bandeau à gauche → face extérieure = bord gauche (bx0).
            strips.append(shp_box(bx0, by0, bx0 + cw, by1))
        else:
            strips.append(shp_box(bx1 - cw, by0, bx1, by1))
        # aile basse : couloir sur son bord bas (extérieur).
        strips.append(shp_box(min(a[0], bx0), a[1], max(a[2], bx1), a[1] + cw))
        # aile haute : couloir sur son bord haut (extérieur).
        strips.append(shp_box(min(b[0], bx0), b[3] - cw, max(b[2], bx1), b[3]))

    corridor = unary_union(strips)
    if corridor.geom_type != "Polygon":
        corridor = max(corridor.geoms, key=lambda g: g.area)
    return corridor


def place_u_cages(
    d: UDecomposition, corridor: ShapelyPolygon, corridor_width: float = 1.6,
) -> tuple[ShapelyPolygon, ShapelyPolygon]:
    """Place les 2 cages aux 2 angles intérieurs (jonction bandeau/aile).

    Chaque cage est adossée au couloir, côté extérieur, à la jonction du
    bandeau et d'une aile. Renvoie (cage_a, cage_b) — cage_a côté arm_a.
    """
    bx0, by0, bx1, by1 = d.bar.bounds
    a = d.arm_a.bounds
    b = d.arm_b.bounds
    cw = corridor_width
    side = _CAGE_SIDE
    length = _CAGE_LEN

    if d.opens in ("nord", "sud"):
        if d.opens == "nord":
            # jonction en bas ; couloir bandeau à by0..by0+cw. Cage juste
            # au-dessus du couloir bandeau, à l'aplomb de chaque aile.
            cy0 = by0 + cw
            cage_a = shp_box(a[0] + cw, cy0, a[0] + cw + side, cy0 + length)
            cage_b = shp_box(b[2] - cw - side, cy0, b[2] - cw, cy0 + length)
        else:
            cy1 = by1 - cw
            cage_a = shp_box(a[0] + cw, cy1 - length, a[0] + cw + side, cy1)
            cage_b = shp_box(b[2] - cw - side, cy1 - length, b[2] - cw, cy1)
    else:
        if d.opens == "est":
            cx0 = bx0 + cw
            cage_a = shp_box(cx0, a[1] + cw, cx0 + length, a[1] + cw + side)
            cage_b = shp_box(cx0, b[3] - cw - side, cx0 + length, b[3] - cw)
        else:
            cx1 = bx1 - cw
            cage_a = shp_box(cx1 - length, a[1] + cw, cx1, a[1] + cw + side)
            cage_b = shp_box(cx1 - length, b[3] - cw - side, cx1, b[3] - cw)
    return cage_a, cage_b


@dataclass(frozen=True)
class UZone:
    """Zone rectangulaire de logements mono-façade côté cour.

    - name : "bar" / "arm_a" / "arm_b".
    - rect : rectangle des apts (profondeur = jusqu'au couloir, largeur =
      entre les cages pour le bandeau).
    - long_axis : direction de découpe des apts.
    - cour_side : côté (sud/nord/est/ouest) avec la fenêtre cour.
    """
    name: str
    rect: ShapelyPolygon
    long_axis: str
    cour_side: str


def compute_u_zones(
    d: UDecomposition,
    cage_a: ShapelyPolygon,
    cage_b: ShapelyPolygon,
    corridor_width: float = 1.6,
) -> list[UZone]:
    """Zones d'apts mono-façade : bandeau (entre les 2 cages) + 2 ailes.

    Chaque zone est le rectangle compris entre le couloir (côté extérieur) et
    la façade cour (côté intérieur), amputé de l'emprise des cages pour le
    bandeau.
    """
    bx0, by0, bx1, by1 = d.bar.bounds
    a = d.arm_a.bounds
    b = d.arm_b.bounds
    ca, cb = cage_a.bounds, cage_b.bounds
    cw = corridor_width

    zones: list[UZone] = []

    if d.opens in ("nord", "sud"):
        # BANDEAU horizontal : apts entre les 2 cages (en x), profondeur =
        # depuis le couloir bandeau jusqu'à la face cour.
        if d.opens == "nord":
            bar_y0, bar_y1 = by0 + cw, by1          # couloir en bas ; cour en haut
        else:
            bar_y0, bar_y1 = by0, by1 - cw          # couloir en haut ; cour en bas
        # Le bandeau s'étend jusqu'aux CAGES (ca[2] / cb[0]) → il absorbe les
        # coins en SHAB (séjour ouvert de l'apt d'extrémité). Le générateur de
        # pièces mono-façade aval (``_relayout_mono_facade_apts``) retype selon la
        # façade cour réelle et garde le séjour raisonnable. Pas de chevauchement
        # avec les ailes (bornées à la ligne de cour).
        bar_x0 = ca[2]                             # après la cage gauche (absorbe coin NW)
        bar_x1 = cb[0]                             # avant la cage droite (absorbe coin NE)
        if bar_x1 - bar_x0 > _MIN_APT_WIDTH_M:
            bar_rect = shp_box(bar_x0, bar_y0, bar_x1, bar_y1)
            zones.append(UZone("bar", bar_rect, "horizontal",
                               _cour_side_of(bar_rect, d.court)))
        # AILE gauche verticale : apts empilés en y, profondeur depuis le
        # couloir d'aile (bord extérieur) jusqu'à la face cour (bord intérieur).
        arm_a_x0 = a[0] + cw                        # après le couloir extérieur
        arm_a_x1 = a[2]                             # face cour
        arm_a_y0 = ca[3]                            # sous/au-dessus de la cage
        arm_a_y1 = a[3] if d.opens == "nord" else a[3]
        # L'aile garde toute sa hauteur (jusqu'au bord de la cage, dans la
        # bande du bandeau). Le NON-chevauchement est assuré côté BANDEAU : le
        # bandeau démarre après la COLONNE de l'aile (a[2] / b[0]), pas après la
        # cage. Ainsi aile et bandeau tuilent des régions complémentaires à
        # l'angle, sans recouvrement, tout en gardant la densité (15 apts).
        # L'aile est bornée à SA PROPRE hauteur (a[1]..a[3] = jusqu'à la ligne de
        # cour = reflex), PAS jusqu'à la cage : au-delà de la ligne de cour, la
        # façade cour n'existe plus (on est dans la bande du bandeau) → un apt qui
        # y monterait aurait des chambres BORGNES. Le coin cage reste hors apt
        # (circulation/résidu), comme dans le proto validé.
        aa_rect = shp_box(arm_a_x0, a[1], arm_a_x1, a[3])
        if aa_rect.area > 1.0 and (aa_rect.bounds[3] - aa_rect.bounds[1]) > _MIN_APT_WIDTH_M:
            zones.append(UZone("arm_a", aa_rect, "vertical",
                               _cour_side_of(aa_rect, d.court)))
        # AILE droite verticale (même borne = hauteur d'aile, pas la cage).
        arm_b_x0 = b[0]
        arm_b_x1 = b[2] - cw
        ab_rect = shp_box(arm_b_x0, b[1], arm_b_x1, b[3])
        if ab_rect.area > 1.0 and (ab_rect.bounds[3] - ab_rect.bounds[1]) > _MIN_APT_WIDTH_M:
            zones.append(UZone("arm_b", ab_rect, "vertical",
                               _cour_side_of(ab_rect, d.court)))
    else:
        # U horizontal : bandeau vertical, ailes horizontales.
        if d.opens == "est":
            bar_x0, bar_x1 = bx0 + cw, bx1
        else:
            bar_x0, bar_x1 = bx0, bx1 - cw
        # Le bandeau s'étend jusqu'aux CAGES (ca[3] / cb[1]) → il ABSORBE les
        # COINS (rangées y d'aile, au-delà de la ligne de cour) en SHAB (séjour
        # ouvert de l'apt d'extrémité), comme le proto validé. Pas de
        # chevauchement : les ailes sont bornées à la ligne de cour en x
        # (bx0/bx1), le bandeau est dans la bande x réservée.
        bar_y0 = ca[3]
        bar_y1 = cb[1]
        if bar_y1 - bar_y0 > _MIN_APT_WIDTH_M:
            bar_rect = shp_box(bar_x0, bar_y0, bar_x1, bar_y1)
            zones.append(UZone("bar", bar_rect, "vertical",
                               _cour_side_of(bar_rect, d.court)))
        # aile basse horizontale — bornée à la LIGNE DE JONCTION avec le bandeau
        # (bord intérieur du bandeau), PAS jusqu'au bord opposé : sinon l'aile
        # recouvre le bandeau. Pour opens=est le bandeau est à gauche (x<=bx1)
        # donc l'aile part de bx1 ; pour opens=ouest le bandeau est à droite
        # (x>=bx0) donc l'aile va jusqu'à bx0.
        if d.opens == "est":
            aa_rect = shp_box(bx1, a[1] + cw, a[2], a[3])
        else:
            aa_rect = shp_box(a[0], a[1] + cw, bx0, a[3])
        if aa_rect.area > 1.0 and (aa_rect.bounds[2] - aa_rect.bounds[0]) > _MIN_APT_WIDTH_M:
            zones.append(UZone("arm_a", aa_rect, "horizontal",
                               _cour_side_of(aa_rect, d.court)))
        # aile haute horizontale (même borne x = jonction bandeau).
        if d.opens == "est":
            ab_rect = shp_box(bx1, b[1], b[2], b[3] - cw)
        else:
            ab_rect = shp_box(b[0], b[1], bx0, b[3] - cw)
        if ab_rect.area > 1.0 and (ab_rect.bounds[2] - ab_rect.bounds[0]) > _MIN_APT_WIDTH_M:
            zones.append(UZone("arm_b", ab_rect, "horizontal",
                               _cour_side_of(ab_rect, d.court)))

    return zones


def slice_u_zone(
    zone: UZone,
    target_typo: Typologie,
    target_surface: float,
    id_prefix: str = "",
    force_n_apts: int | None = None,
) -> list[ApartmentSlot]:
    """Découpe une zone en apts mono-façade collés bord à bord le long de son
    grand axe. Chaque apt garde sa fenêtre côté cour (orientations=[cour_side]).

    ``force_n_apts`` : impose le nombre d'apts (sert pour le BANDEAU, qu'on veut
    en peu d'apts LARGES ~12,5 m → vrais T4 mono-façade, cf. proto). Sinon on
    dérive le nombre de la surface cible.
    """
    qx0, qy0, qx1, qy1 = zone.rect.bounds
    w = qx1 - qx0
    h = qy1 - qy0

    if zone.long_axis == "horizontal":
        long_len, depth = w, h
    else:
        long_len, depth = h, w

    if depth <= 0 or long_len <= 0:
        return []

    total_area = long_len * depth
    if force_n_apts is not None and force_n_apts >= 1:
        n_apts = force_n_apts
    else:
        n_apts = max(1, round(total_area / target_surface))
    actual_width = long_len / n_apts
    if actual_width < _MIN_APT_WIDTH_M and n_apts > 1:
        n_apts = max(1, int(long_len / _MIN_APT_WIDTH_M))
        actual_width = long_len / n_apts

    slots: list[ApartmentSlot] = []
    for i in range(n_apts):
        if zone.long_axis == "horizontal":
            ax0 = qx0 + i * actual_width
            ax1 = qx0 + (i + 1) * actual_width
            ay0, ay1 = qy0, qy1
        else:
            ay0 = qy0 + i * actual_width
            ay1 = qy0 + (i + 1) * actual_width
            ax0, ax1 = qx0, qx1
        poly = shp_box(ax0, ay0, ax1, ay1)
        position = "extremite" if i == 0 or i == n_apts - 1 else "milieu"
        slots.append(ApartmentSlot(
            id=f"{id_prefix}{zone.name}_{i}",
            polygon=poly,
            surface_m2=poly.area,
            target_typologie=target_typo,
            orientations=[zone.cour_side],
            position_in_floor=position,
        ))
    return slots


def _slice_bar_by_cour(zone, d, target_surface, target_typo,
                       id_prefix="", target_cour_m=10.0):
    """Découpe le BANDEAU en apts à PART ÉGALE DE FAÇADE COUR.

    La façade cour du bandeau = projection des ailes (x∈[a[2], b[0]] pour un U
    vertical). On la divise en N = round(cour / target_cour_m) segments égaux ;
    chaque apt couvre son segment de cour + (pour les extrémités) le coin
    aveugle adjacent derrière la cage. Résultat : chaque apt a ~target_cour_m de
    façade cour → 3 chambres = T4 (les extrémités absorbent le coin en séjour
    profond). Garantit un vrai mix T4/T5 au bandeau, sans trou ni chevauchement.
    """
    bx0, by0, bx1, by1 = zone.rect.bounds
    a = d.arm_a.bounds
    b = d.arm_b.bounds
    slots = []
    if zone.long_axis == "horizontal":
        # cour projetée en x = [a[2], b[0]] (bord intérieur des ailes)
        cour_lo, cour_hi = a[2], b[0]
        cour_len = cour_hi - cour_lo
        if cour_len <= 0:
            return slice_u_zone(zone, target_typo, target_surface, id_prefix)
        n = max(1, round(cour_len / target_cour_m))
        step = cour_len / n
        for i in range(n):
            # bornes x de l'apt : segment de cour, étendu au bord du bandeau
            # (bx0/bx1) pour les apts d'extrémité → absorbent le coin aveugle.
            x0 = bx0 if i == 0 else cour_lo + i * step
            x1 = bx1 if i == n - 1 else cour_lo + (i + 1) * step
            poly = shp_box(x0, by0, x1, by1)
            pos = "extremite" if i in (0, n - 1) else "milieu"
            slots.append(ApartmentSlot(
                id=f"{id_prefix}{zone.name}_{i}", polygon=poly,
                surface_m2=poly.area, target_typologie=target_typo,
                orientations=[zone.cour_side], position_in_floor=pos))
    else:
        # U horizontal : cour projetée en y = [a[3], b[1]]
        cour_lo, cour_hi = a[3], b[1]
        cour_len = cour_hi - cour_lo
        if cour_len <= 0:
            return slice_u_zone(zone, target_typo, target_surface, id_prefix)
        n = max(1, round(cour_len / target_cour_m))
        step = cour_len / n
        for i in range(n):
            y0 = by0 if i == 0 else cour_lo + i * step
            y1 = by1 if i == n - 1 else cour_lo + (i + 1) * step
            poly = shp_box(bx0, y0, bx1, y1)
            pos = "extremite" if i in (0, n - 1) else "milieu"
            slots.append(ApartmentSlot(
                id=f"{id_prefix}{zone.name}_{i}", polygon=poly,
                surface_m2=poly.area, target_typologie=target_typo,
                orientations=[zone.cour_side], position_in_floor=pos))
    return slots


def compute_u_layout(
    footprint: ShapelyPolygon,
    mix_typologique: dict[Typologie, float],
    core_surface_m2: float,
    corridor_width: float = 1.6,
    id_prefix: str = "",
) -> LLayoutResult | None:
    """Génère core + couloir ⊓ + apts mono-façade cour pour un footprint U.

    Algorithme :
    1. Décompose le U en bandeau + 2 ailes + cour (bounds réels).
    2. Couloir périmètre en ⊓ côté extérieur reliant les 2 futures cages.
    3. Place 2 cages aux angles intérieurs. La cage A part dans ``core``
       (Polygon simple, requis par le pipeline) ; la cage B est FUSIONNÉE
       dans ``corridor`` (union → circulation connexe, 2e cage représentée).
    4. Génère les apts mono-façade côté cour (bandeau + 2 ailes), hors cages
       et couloir.
    5. Clippe tout apt qui chevauche la circulation (filet de sécurité).

    Renvoie None si le footprint n'est pas un U propre (fallback legacy).
    """
    d = decompose_u(footprint)
    if d is None:
        return None

    # Couloir mono-façade : on borne au mini PMR (le pipeline passe 1,6 m par
    # défaut, trop large pour tenir la circulation ≤20 % sur un single-loaded).
    corridor_width = min(corridor_width, _U_CORRIDOR_WIDTH)

    active_mix = {t: r for t, r in mix_typologique.items() if r > 0}
    if not active_mix:
        return None

    corridor = build_u_corridor(d, corridor_width=corridor_width)
    cage_a, cage_b = place_u_cages(d, corridor, corridor_width=corridor_width)

    # CHOIX MODÈLE : cage principale → core ; 2e cage → union dans corridor.
    core = cage_a
    corridor = unary_union([corridor, cage_b])
    if corridor.geom_type != "Polygon":
        corridor = max(corridor.geoms, key=lambda g: g.area)

    zones = compute_u_zones(d, cage_a, cage_b, corridor_width=corridor_width)

    # ── Typologie PILOTÉE PAR LE MIX CIBLE (supporte T1..T5, pas juste T2/T3) ──
    # Les typos actifs sont triés par surface. Le BANDEAU (le plus profond, coins
    # absorbés → apts plus grands) reçoit les plus grandes typos (T4/T5), les
    # ailes les plus petites → on approche la cible 20/50/30 au lieu de tout en T2.
    from core.building_model.solver import _TYPO_TARGET_SURFACE_M2 as _SURF
    _sorted_typos = sorted(active_mix.keys(), key=lambda t: _SURF[t])
    _big = _sorted_typos[-1]
    _small = _sorted_typos[0]
    _mid = _sorted_typos[len(_sorted_typos) // 2]

    # Ratio cible des GRANDES typos (T4/T5) : sert à dimensionner la portion du
    # bandeau qui reçoit du grand logement. Le reste du bandeau reçoit la typo
    # MÉDIANE (T3, en général la plus demandée ~50 %), pour approcher la cible
    # 20/50/30 et éviter que le bandeau — profond — ne produise QUE 3 gros T4
    # (mix cassé, T3 minoritaire). Universel : pas de valeur en dur.
    _big_ratio = sum(r for t, r in active_mix.items() if _SURF[t] >= _SURF[_big])
    _tot_ratio = sum(active_mix.values()) or 1.0
    _big_frac = max(0.0, min(1.0, _big_ratio / _tot_ratio))

    # Nombre de petits logements (T1/T2) à réserver PAR AILE : la cible ~20 %
    # T1/T2 sur ~13 apts = ~3 petits ; réparti sur 2 ailes → ~1 (arrondi) par
    # aile, à une extrémité. Le reste de l'aile = _mid (T3). On réserve UNE
    # LARGEUR D'APT (pas un %) sinon le petit slot ressort trop large → relabellé T3.
    _small_share = sum(r for t, r in active_mix.items()
                       if _SURF[t] <= _SURF[_small]) / _tot_ratio

    def _split_zone(z: UZone, n_small: int, typo_small: Typologie, typo_main: Typologie):
        """Réserve ``n_small`` apts ``typo_small`` (largeur = surface cible /
        profondeur) à une extrémité de la zone, le reste en ``typo_main``. Si la
        zone est trop courte pour caser petit + au moins un grand, garde tout."""
        if len(_sorted_typos) <= 1 or typo_small is typo_main or n_small <= 0:
            return [(z, typo_main)]
        qx0, qy0, qx1, qy1 = z.rect.bounds
        horiz = z.long_axis == "horizontal"
        depth = (qy1 - qy0) if horiz else (qx1 - qx0)
        length = (qx1 - qx0) if horiz else (qy1 - qy0)
        small_w = n_small * (_SURF[typo_small] / max(depth, 0.1))
        if small_w + _MIN_APT_WIDTH_M > length:          # pas la place → tout _main
            return [(z, typo_main)]
        if horiz:
            r1 = shp_box(qx0, qy0, qx0 + small_w, qy1); r2 = shp_box(qx0 + small_w, qy0, qx1, qy1)
        else:
            r1 = shp_box(qx0, qy0, qx1, qy0 + small_w); r2 = shp_box(qx0, qy0 + small_w, qx1, qy1)
        return [(UZone(z.name + "_s", r1, z.long_axis, z.cour_side), typo_small),
                (UZone(z.name, r2, z.long_axis, z.cour_side), typo_main)]

    slots: list[ApartmentSlot] = []
    for z in zones:
        if z.name == "bar":
            # BANDEAU : on découpe par PART ÉGALE DE FAÇADE COUR (pas de largeur
            # brute). Chaque apt reçoit ~part_cour ≈ 10 m de cour → 3 chambres +
            # nez séjour = vrai T4, MÊME les apts d'extrémité (qui absorbent en
            # PLUS le coin aveugle derrière la cage dans la profondeur du séjour).
            # Ainsi les 3 apts du bandeau sont T4 (au lieu de 1 seul), le mix
            # atteint ~30 % T4/T5. cour = projection des ailes sur le bandeau.
            _bq = z.rect.bounds
            _a = d.arm_a.bounds
            _b = d.arm_b.bounds
            slots.extend(_slice_bar_by_cour(
                z, d, _SURF[_big], _big, id_prefix=id_prefix,
                target_cour_m=10.0,
            ))
            continue
        else:
            # Chaque AILE : ~1 petit logement (_small) à une extrémité + le reste
            # en _mid (T3) → tient ~20 % T1/T2 sans qu'une aile parte 100 % en T2.
            _n_small = 1 if _small_share > 0.05 else 0
            zone_typos = _split_zone(z, _n_small, _small, _mid)
        for zz, typo in zone_typos:
            slots.extend(slice_u_zone(
                zone=zz, target_typo=typo, target_surface=_SURF[typo], id_prefix=id_prefix,
            ))

    # Relabel HONNÊTE : chaque apt reçoit la typo dont la surface standard est la
    # plus proche de sa surface RÉELLE (le label ne ment pas sur la géométrie).
    def _nearest_typo(area: float) -> Typologie:
        return min(_sorted_typos, key=lambda t: abs(_SURF[t] - area))
    slots = [
        ApartmentSlot(
            id=s.id, polygon=s.polygon, surface_m2=s.surface_m2,
            target_typologie=_nearest_typo(s.surface_m2),
            orientations=s.orientations, position_in_floor=s.position_in_floor,
        )
        for s in slots
    ]

    # Filet de sécurité : retire la portion d'apt chevauchant la circulation.
    occupied = unary_union([corridor, core])
    clipped: list[ApartmentSlot] = []
    for s in slots:
        clean = s.polygon.difference(occupied)
        if clean.is_empty or clean.area < 20.0:
            continue
        if clean.geom_type == "MultiPolygon":
            clean = max(clean.geoms, key=lambda g: g.area)
        clipped.append(ApartmentSlot(
            id=s.id,
            polygon=clean,
            surface_m2=clean.area,
            target_typologie=s.target_typologie,
            orientations=s.orientations,
            position_in_floor=s.position_in_floor,
        ))

    # On réutilise LLayoutResult (contrat du pipeline). ``decomposition`` n'est
    # pas consommé par solver/pipeline (ils ne lisent que .core/.corridor/.slots),
    # donc on y range la UDecomposition telle quelle.
    # cage_b reste FUSIONNÉE dans ``corridor`` (couloir connexe) mais est AUSSI
    # exposée en ``secondary_cores`` pour être rendue comme 2e cage esc+asc
    # distincte (égress #2 visible au plan).
    return LLayoutResult(
        core=core, corridor=corridor, slots=clipped, decomposition=d,
        secondary_cores=(cage_b,),
    )
