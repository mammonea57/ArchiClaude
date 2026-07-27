"""PORTE DE SORTIE UNIQUE — vérifie EN UNE FOIS un plan (L ou U) DU PIPELINE.

Généralise scripts/verify_u_plan.py : au lieu de constantes COUR/FP en dur (calées
sur le U), la géométrie de référence est DÉRIVÉE du BuildingModel réel :
  - FOOTPRINT = union des cellules + circulations + core d'un niveau courant.
  - COUR/JARDIN = void concave = (bbox du footprint) − footprint (l'angle rentrant du L
    ou la cour intérieure du U). C'est la zone sur laquelle les pièces de vie prennent le jour.
  - VOIRIE = arêtes du footprint qui donnent sur rue (déduites des inputs voirie_orientations,
    passées par le loader). Les autres arêtes extérieures = mitoyens (murs aveugles).

Checke, pour CHAQUE apt de CHAQUE niveau, les MÊMES critères que verify_u_plan
(SPEC_PLAN.md sections A-G) : tuilage 100%, nb chambres==typo, séjour≤cap, 0 cellier,
0 dégagement, 0 borgne, gabarit chambres, WC+SdB, contour propre, C1/C2/C3 ouvrants,
D1 loggia étage / D2 jardin RDC. Puis global : mix vs cible, 2 cages, 0 vide footprint,
bilan >12%.

Usage : PYTHONPATH=. .venv/bin/python scripts/verify_plan.py [--l | --u]
  --l (défaut) : plan L d'angle (scripts/render_l_pipeline)
  --u          : plan U (scripts/render_u_pipeline)
"""
import sys
import asyncio
from collections import Counter

from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union

from core.building_model.schemas import CelluleType, OpeningType, RoomType


# ── 1. Charger le BuildingModel selon la forme demandée ─────────────────────
def _load():
    mode = "l"
    if "--u" in sys.argv:
        mode = "u"
    if mode == "u":
        # le module U génère bm à l'import (comportement historique)
        from scripts.render_u_pipeline import bm
        return bm
    # L : génère via le chemin natif L
    from scripts.render_l_pipeline import build_inputs
    from core.building_model.pipeline import generate_building_model
    from db.session import AsyncSessionLocal

    async def _run():
        async with AsyncSessionLocal() as s:
            return await generate_building_model(build_inputs(), session=s)

    return asyncio.run(_run())


bm = _load()


# ── 2. Dériver la géométrie de référence DU MODÈLE (pas de constantes en dur) ─
def _floor_polys(niv):
    polys = [Polygon(c.polygon_xy) for c in niv.cellules
             if c.polygon_xy and len(c.polygon_xy) >= 3]
    polys += [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
              if cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if getattr(bm, "core", None) and bm.core.polygon_xy:
        polys.append(Polygon(bm.core.polygon_xy))
    return polys


# Footprint réel = union d'un ÉTAGE COURANT (index >= 1), PAS le RDC. Le RDC
# porte le hall d'entrée de l'immeuble (une circulation qui creuse une encoche
# dans le pourtour nord), donc son union sous-estime le footprint réel : une
# fenêtre d'un logement d'étage tombant dans cette encoche RDC serait vue « hors
# façade » à tort. On dérive donc la géométrie de référence d'un étage plein.
# (2026-07-03) Ne retomber sur le RDC que si aucun étage n'a de logement.
_cand_niv = [n for n in bm.niveaux
             if n.index >= 1 and any(c.type == CelluleType.LOGEMENT for c in n.cellules)]
if not _cand_niv:
    _cand_niv = [n for n in bm.niveaux
                 if any(c.type == CelluleType.LOGEMENT for c in n.cellules)]
_ref_niv = max(_cand_niv,
               key=lambda n: sum(1 for c in n.cellules if c.type == CelluleType.LOGEMENT))
# FP = union d'un étage courant. Les apts/couloir laissent des jointures ~0,1 m
# (largeur PMR 1,40 vs découpe des slots) : sans pont, l'union se fragmente en
# 5 morceaux disjoints et max() ne garde qu'une bande (318 m² au lieu de ~1007).
# On PONTE ces hairlines par un buffer +0,2/−0,2 (close morphologique) AVANT de
# prendre la composante principale → footprint L complet et continu. Universel.
FP = unary_union([p.buffer(0.2) for p in _floor_polys(_ref_niv)]).buffer(-0.2).buffer(0)
if FP.geom_type == "MultiPolygon":
    FP = max(FP.geoms, key=lambda g: g.area)
FP = FP.simplify(0.05)
FP_BND = FP.boundary
_minx, _miny, _maxx, _maxy = FP.bounds

# FOOTPRINT AUTORITAIRE (envelope) pour la détection de VIDE. L'ancien FP (union
# des cellules) MANQUAIT le centre aveugle du L (angle mort documenté) : le vide
# du coude n'appartenait à aucune cellule donc n'apparaissait pas dans FP. Le vrai
# footprint vient de l'envelope PLU : toute poche FP_TRUE − (apts∪circ) est un
# vide RÉEL, y compris le centre du L. C'est ce footprint qui rend les checks
# H-VIDE / poches / vide_fp fidèles au défaut user. Universel.
from shapely.geometry import shape as _shp_shape
try:
    FP_TRUE = _shp_shape(bm.envelope.footprint_geojson).buffer(0)
    if FP_TRUE.geom_type == "MultiPolygon":
        FP_TRUE = max(FP_TRUE.geoms, key=lambda g: g.area)
except Exception:
    FP_TRUE = FP

# COUR/JARDIN = void concave = bbox − footprint (angle rentrant L ou cour U).
_bbox = Polygon([(_minx, _miny), (_maxx, _miny), (_maxx, _maxy), (_minx, _maxy)])
_void = _bbox.difference(FP)
if _void.geom_type == "MultiPolygon":
    _void = max(_void.geoms, key=lambda g: g.area)
COUR = _void if not _void.is_empty else Polygon()
COUR_B = COUR.buffer(0.25) if not COUR.is_empty else Polygon()

# La "façade jour" = frontière footprint qui borde soit la cour/jardin (void),
# soit l'extérieur (rue). On considère qu'une pièce est éclairée si elle touche
# la frontière du footprint (rue OU cour). Les mitoyens sont AUSSI sur cette
# frontière, donc pour un check "borgne" fidèle on exige contact avec la
# façade cour OU une arête rue. À défaut d'infos rue par arête au niveau du
# modèle, on prend : éclairée = touche COUR (jour interne) OU frontière footprint
# côté void/extérieur non-mitoyen. Ici on retient le critère robuste de
# verify_u_plan : touche COUR (void) OU frontière footprint.

print(f"[geom dérivée] footprint {FP.area:.0f} m² bbox {(_maxx-_minx):.0f}x{(_maxy-_miny):.0f}"
      f" | cour/void {COUR.area:.0f} m²")


# ── helpers ouvrants (identiques verify_u_plan) ─────────────────────────────
def _opening_seg(op, wall):
    (x0, y0), (x1, y1) = wall.geometry["coords"][0], wall.geometry["coords"][1]
    L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if L == 0:
        return None
    t = (op.position_along_wall_cm / 100.0) / L
    w = (op.width_cm or 90) / 100.0
    t0 = max(0.0, t - (w / 2) / L)
    t1 = min(1.0, t + (w / 2) / L)
    return LineString([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                       (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)])


def _circ_zone(niv):
    polys = [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
             if cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if getattr(bm, "core", None) and bm.core.polygon_xy:
        polys.append(Polygon(bm.core.polygon_xy))
    return unary_union(polys).buffer(0.30) if polys else Polygon()


def _circ_zone_raw(niv):
    """Couloir commun SANS buffer (pour l'adjacence d'ARÊTE séjour↔couloir).
    Le buffer +0,30 de _circ_zone sert aux tests de FRANCHISSEMENT de porte ; ici
    on veut la vraie arête partagée, donc l'union brute des circulations."""
    polys = [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
             if cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if getattr(bm, "core", None) and bm.core.polygon_xy:
        polys.append(Polygon(bm.core.polygon_xy))
    return unary_union(polys) if polys else Polygon()


EXP = {"T1": 1, "T2": 1, "T3": 2, "T4": 3, "T5": 4}
CAP = {"T1": 30, "T2": 40, "T3": 44, "T4": 56, "T5": 66}
# CAP SÉJOUR PROMOTEUR (nouveau check H-SEJ-CAP, défaut user 2026-07-06) : cibles
# indicatives user T2 ~32 / T3 ~34 / T4 ~42 / T5 ~50, + une marge géométrique de
# ~6 m² (façades étroites du L → le séjour ne peut descendre PILE à la cible sans
# affamer les chambres). Un séjour au-dessus de ce cap = séjour OBÈSE (le défaut
# v8 : 60 m² en T5, 48 en T4). BLOQUANT. Le revert-test v8 le fait FIRER.
# Caps RELEVÉS (user 2026-07-15 : salon large devant la fenêtre) : élargir le nez de
# séjour agrandit le séjour ouvert = argument de vente, PAS un défaut, tant que les
# chambres restent ≥ 10,5 m² (vérifié par H-CH-MIN).
CAP_SEJ = {"T1": 30, "T2": 40, "T3": 44, "T4": 54, "T5": 56}
CHAMBRE_MIN_M2 = 10.5   # H-CH-MIN : plancher surface d'une chambre (défaut user)
CIBLE = {"T1T2": 20, "T3": 50, "T4T5": 30}
TOL_MIX = 8

ko = []
apt_ko = 0
n_apts = 0

for niv in bm.niveaux:
    _circ = _circ_zone(niv)
    _circ_raw = _circ_zone_raw(niv)
    _is_rdc = (niv.index == 0)
    for c in [x for x in niv.cellules if x.type == CelluleType.LOGEMENT]:
        n_apts += 1
        tag = f"R+{niv.index}.{c.id.split('.')[-1]}"
        typ = str(getattr(c, "typologie", "")).split(".")[-1]
        apt = Polygon(c.polygon_xy)
        rooms = [(r, Polygon(r.polygon_xy)) for r in c.rooms
                 if r.polygon_xy and len(r.polygon_xy) >= 3]
        u = unary_union([p for _, p in rooms]) if rooms else Polygon()
        probs = []
        # 1. tuilage 100 %
        trou = apt.area - u.intersection(apt).area
        if trou > 0.5:
            probs.append(f"trou {trou:.0f}m²")
        ov = sum(rooms[i][1].intersection(rooms[j][1]).area
                 for i in range(len(rooms)) for j in range(i + 1, len(rooms))
                 if rooms[i][1].intersection(rooms[j][1]).area > 0.3)
        if ov > 0.5:
            probs.append(f"chevauch {ov:.0f}m²")
        # 2. nb chambres == typo
        nch = sum(1 for r, _ in rooms if "CHAMBRE" in str(r.type))
        if nch != EXP.get(typ, -1):
            probs.append(f"chambres {nch}/{EXP.get(typ)}")
        # 3. exactement 1 séjour, cap surface
        sej_rooms = [p for r, p in rooms if "SEJOUR" in str(r.type)]
        if len(sej_rooms) > 1:
            probs.append(f"{len(sej_rooms)} séjours")
        sej = sum(p.area for p in sej_rooms)
        if sej > CAP.get(typ, 99):
            probs.append(f"séjour {sej:.0f}>{CAP.get(typ)}")
        # 4. cellier / dégagement
        if any("CELLIER" in str(r.type) for r, _ in rooms):
            probs.append("cellier")
        # DEGAGEMENT_NUIT autorisé UNIQUEMENT en T4/T5 (dégagement nuit desservant
        # toutes les chambres, défaut user 2026-07-10). Tout autre dégagement/
        # couloir/hall interne reste interdit (open-plan T2/T3).
        _hall_ok = typ in ("T4", "T5")
        if any((any(x in str(r.type) for x in ("DEGAG", "COULOIR", "HALL"))
                and not (_hall_ok and r.type == RoomType.DEGAGEMENT_NUIT))
               for r, _ in rooms):
            probs.append("dégagement")
        # 5. chambre borgne + gabarit (borgne = ne touche NI cour NI frontière
        # footprint NI une LOGGIA vitrée). Une chambre reculée derrière une loggia
        # prend le jour PAR la loggia (baie vitrée) → non borgne.
        _lgp_borgne = [p for r, p in rooms if r.type == RoomType.LOGGIA]
        for r, p in rooms:
            if "CHAMBRE" in str(r.type):
                lit = (COUR.area > 0 and p.distance(COUR) <= 0.4) or p.distance(FP_BND) <= 0.4 \
                    or any(p.distance(_lp) <= 0.4 for _lp in _lgp_borgne)
                if not lit:
                    probs.append("chambre borgne")
                b = p.bounds
                if min(b[2] - b[0], b[3] - b[1]) < 2.6:
                    probs.append(f"chambre tunnel {min(b[2]-b[0],b[3]-b[1]):.1f}m")
        # 6. service présent
        if not any(r.type.name in ("WC", "WC_SDB") for r, _ in rooms):
            probs.append("pas de WC")
        if not any(r.type.name in ("SDB", "SALLE_DE_DOUCHE", "WC_SDB") for r, _ in rooms):
            probs.append("pas de SdB")
        # 7. chaque pièce a un type
        if any(getattr(r, "type", None) is None for r, _ in rooms):
            probs.append("pièce sans nom")
        # 8. contour non dentelé
        if len(c.polygon_xy) > 10:
            probs.append(f"contour dentelé ({len(c.polygon_xy)} sommets)")

        # ══ H7 — SERVICE ERGONOMIQUE : SdB ≥3,8 · WC ≥1,2 m² ═════════════════
        # GABARIT OPEN-PLAN (2026-07-06) : le bloc humide est désormais COMPACT
        # et BORGNE, collé au couloir (SdB ~4,2 · WC ~1,6). On garde un plancher
        # bas mais réaliste (SdB ≥3,8 m² = douche + lavabo + WC séparé). L'ancien
        # H6 « suite parentale SdB⇄parents » est RETIRÉ : il exigeait une SdB
        # pleine profondeur touchant la Ch.PARENTS — incompatible avec le bloc
        # compact collé au couloir voulu par l'user. L'ancien plancher entrée
        # (≥2,5 m²) est RETIRÉ : plus de pièce Entrée fermée.
        _sdb_area = sum(p.area for r, p in rooms
                        if r.type.name in ("SDB", "SALLE_DE_DOUCHE", "WC_SDB"))
        _wc_area = sum(p.area for r, p in rooms if r.type.name in ("WC", "WC_SDB"))
        if _sdb_area > 0 and _sdb_area < 3.8:
            probs.append(f"H7 SdB {_sdb_area:.1f}<3,8m²")
        if _wc_area > 0 and _wc_area < 1.2:
            probs.append(f"H7 WC {_wc_area:.1f}<1,2m²")

        # ══ H9 — 0 CUISINE > 15 m² (défaut user #3, 2026-07-03) ══════════════
        # Un grand volume JOUR doit être typé SEJOUR_CUISINE (pièce à vivre
        # ouverte, unique par apt, plafonnée par le check #3). Une pièce typée
        # CUISINE > 15 m² = la « cuisine 37,5 m² » aberrante : soit un séjour
        # splitté à tort, soit un volume orphelin. On borne toute CUISINE à 15 m².
        _CUISINE_MAX_GATE = 15.0
        for r, p in rooms:
            if r.type == RoomType.CUISINE and p.area > _CUISINE_MAX_GATE + 0.5:
                probs.append(f"H9 CUISINE {p.area:.0f}>15m²")
                break

        # ══ H10 — Ch.PARENTS > Ch.ENFANT en surface (défaut user #4) ═════════
        # Dans tout apt à ≥2 chambres, la chambre PARENTS doit être STRICTEMENT
        # plus grande que CHAQUE chambre secondaire (ENFANT/SUPP). Des chambres
        # égales (14,4=14,4) = non différenciées : le maître doit primer.
        _par = [p.area for r, p in rooms if r.type == RoomType.CHAMBRE_PARENTS]
        _sec = [p.area for r, p in rooms
                if r.type in (RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP)]
        if _par and _sec and min(_par) <= max(_sec) + 0.05:
            probs.append(f"H10 Ch.PARENTS {min(_par):.1f}≤Ch.sec {max(_sec):.1f}")

        # ══ H-CH-MIN — CHAMBRES ≥ 10,5 m² (défaut user 2026-07-06, check (b)) ════
        # Une chambre ne doit pas être une cellule de 10,2 m² pendant que le séjour
        # est XXL. On BLOQUE toute chambre (parents/enfant/supp) < CHAMBRE_MIN_M2.
        # Combiné à H10 (parents > enfant), cela prouve le rééquilibrage chambres.
        # Le revert-test v8 (chambres 10,2) le fait FIRER. BLOQUANT. Universel.
        for r, p in rooms:
            if "CHAMBRE" in str(r.type) and p.area < CHAMBRE_MIN_M2 - 0.05:
                probs.append(f"H-CH-MIN {str(r.type).split('.')[-1]} {p.area:.1f}<{CHAMBRE_MIN_M2}m²")
                break

        # ══ H-SEJ-CAP — SÉJOUR ≤ CAP PROMOTEUR (défaut user 2026-07-06, check (c)) ═
        # Le séjour/cuisine (SEJOUR ∪ SEJOUR_CUISINE ∪ CUISINE ouverte du même apt)
        # ne doit pas être obèse. On somme la pièce à vivre et on la borne à CAP_SEJ.
        # Le revert-test v8 (séjour 60 en T5, 48 en T4) le fait FIRER. BLOQUANT.
        _sej_live = sum(p.area for r, p in rooms
                        if r.type in (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE))
        _cap_sej = CAP_SEJ.get(typ, 99)
        if _sej_live > _cap_sej + 0.5:
            probs.append(f"H-SEJ-CAP séjour {_sej_live:.0f}>{_cap_sej} (obèse)")

        # ══ C — OUVRANTS ══
        wmap = {w.id: w for w in (c.walls or [])}
        ops = c.openings or []
        _bad_ref = [o for o in ops if o.wall_id not in wmap]
        if _bad_ref:
            probs.append(f"opening wall_id fantôme×{len(_bad_ref)}")
        # C1 : 1 porte d'entrée sur le couloir
        entrees = [o for o in ops if o.type == OpeningType.PORTE_ENTREE]
        if len(entrees) != 1:
            probs.append(f"C1 {len(entrees)} porte(s) entrée≠1")
        else:
            _w = wmap.get(entrees[0].wall_id)
            _seg = _opening_seg(entrees[0], _w) if _w else None
            if _seg is None or not _seg.intersects(_circ):
                probs.append("C1 entrée pas sur couloir")
        # C2 : pièces desservies par porte int sur cloison partagée
        _need_door = (RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                      RoomType.CHAMBRE_SUPP, RoomType.SDB, RoomType.SALLE_DE_DOUCHE,
                      RoomType.WC, RoomType.WC_SDB, RoomType.CUISINE)
        pint = [o for o in ops if o.type == OpeningType.PORTE_INTERIEURE]
        for o in pint:
            _w = wmap.get(o.wall_id)
            _seg = _opening_seg(o, _w) if _w else None
            if _seg is None:
                continue
            _touch = set(str(r.type) for r, rp in rooms
                         if rp.boundary.buffer(0.2).intersects(_seg))
            if len(_touch) < 2:
                probs.append("C2 porte-sur-vide")
                break
        for r, rp in rooms:
            if r.type not in _need_door:
                continue
            _served = False
            for o in pint:
                _w = wmap.get(o.wall_id)
                _seg = _opening_seg(o, _w) if _w else None
                if _seg is not None and rp.boundary.buffer(0.25).intersects(_seg):
                    _served = True
                    break
            if not _served and r.type != RoomType.CUISINE:
                probs.append(f"C2 {str(r.type).split('.')[-1]} sans porte")
                break
        # C3 : séjour + chambres ont fenêtre sur façade jour (cour OU frontière)
        _win = [o for o in ops if o.type in (OpeningType.FENETRE, OpeningType.PORTE_FENETRE)]
        # Une pièce donnant sur une LOGGIA (vitrée, ouverte sur la façade) est
        # éclairée par elle : la loggia est creusée à la façade et le séjour l'ouvre
        # par sa porte-fenêtre. On collecte les loggias de l'apt pour le test jour.
        _loggia_polys = [rp for r, rp in rooms if r.type == RoomType.LOGGIA]
        for o in _win:
            _w = wmap.get(o.wall_id)
            _seg = _opening_seg(o, _w) if _w else None
            if _seg is not None and _seg.distance(FP_BND) > 0.4:
                # PORTE-FENÊTRE qui ouvre sur une LOGGIA (mur pièce↔loggia, en retrait
                # du périmètre) = LÉGITIME (les apts loggia s'éclairent par là) → exemptée.
                if o.type == OpeningType.PORTE_FENETRE and _loggia_polys \
                        and any(_seg.distance(_lp) < 0.4 for _lp in _loggia_polys):
                    continue
                probs.append("C3 fenêtre hors façade")
                break
        _vie = (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE, RoomType.CHAMBRE_PARENTS,
                RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP)
        for r, rp in rooms:
            if r.type not in _vie:
                continue
            _lit = False
            for o in _win:
                _w = wmap.get(o.wall_id)
                _seg = _opening_seg(o, _w) if _w else None
                if _seg is None:
                    continue
                on_facade = _seg.distance(FP_BND) < 0.4
                if on_facade and rp.boundary.buffer(0.3).intersects(_seg):
                    _lit = True
                    break
            if not _lit and any(rp.distance(_lp) < 0.4 for _lp in _loggia_polys):
                _lit = True  # donne sur une loggia (jour via la loggia vitrée)
            if not _lit:
                probs.append(f"C3 {str(r.type).split('.')[-1]} sans fenêtre jour")
                break

        # ══ H-TYPE DURCI — GABARIT PLAN-TYPE OPEN-PLAN (demande user 2026-07-06) ═
        # Le gabarit OPEN-PLAN validé user, PROUVÉ (pas rubber-stampé). BLOQUANT :
        #   (a) AUCUNE cellule de type/nom Entrée/dégagement/hall dans le logement
        #       (le sas fermé est SUPPRIMÉ : la porte d'entrée ouvre dans le séjour) ;
        #   (b) la cellule SÉJOUR/CUISINE PARTAGE UNE ARÊTE avec le couloir commun
        #       (≥ 0,8 m de mur commun) → PREUVE que le séjour va jusqu'au couloir,
        #       rien de fermé entre l'entrée et le séjour (open-plan RÉEL) ;
        #   (c) SdB+WC = bloc borgne COLLÉ à la porte d'entrée (contre le couloir),
        #       et JAMAIS sur une arête FAÇADE (rue/cour) — sinon il vole le jour ;
        #   (d) SÉJOUR + CHAQUE CHAMBRE touchent une FAÇADE jour (rue OU cour).
        # Universel (toute typo, toute orientation). Chaque sous-check FIRE en
        # revert-test prouvé sur l'état v6 (sas fermé + séjour ne touchant pas le
        # couloir).
        _loggia_polys_d = [p for r, p in rooms if r.type == RoomType.LOGGIA]
        def _on_facade(_g):
            return (_g.distance(FP_BND) <= 0.4) or (COUR.area > 0 and _g.distance(COUR) <= 0.4) \
                or any(_g.distance(_lp) <= 0.4 for _lp in _loggia_polys_d)
        # (a) AUCUNE pièce Entrée/dégagement/hall fermée.
        if any(r.type == RoomType.ENTREE
               or (any(x in str(r.type) for x in ("DEGAG", "HALL", "COULOIR"))
                   and not (r.type == RoomType.DEGAGEMENT_NUIT and typ in ("T4", "T5")))
               for r, _ in rooms):
            probs.append("H-TYPE pièce ENTREE/dégagement/hall fermée (open-plan violé)")
        # (b) le SÉJOUR/CUISINE partage une arête avec le COULOIR commun (open-plan).
        _sej_polys = [p for r, p in rooms
                      if r.type in (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE)]
        if _sej_polys and not _circ_raw.is_empty:
            _sej_corr = max(
                (p.boundary.intersection(_circ_raw.boundary.buffer(0.20)).length
                 for p in _sej_polys), default=0.0)
            if _sej_corr < 0.8:
                probs.append(f"H-TYPE séjour ne touche PAS le couloir ({_sej_corr:.2f}m<0,8) — open-plan non prouvé")
        # (c) SdB/WC jamais sur une façade (vole le jour). Leur accès est garanti
        # par le séjour (porte intérieure, cf. C2) ; ils ne DOIVENT PAS fronter le
        # couloir commun (cf. H-SVC-CORR) — c'est le séjour qui touche le palier.
        _svc_polys = [(r, p) for r, p in rooms
                      if r.type.name in ("SDB", "SALLE_DE_DOUCHE", "WC", "WC_SDB")]
        for _r, _p in _svc_polys:
            if _p.distance(FP_BND) <= 0.35 or (COUR.area > 0 and _p.distance(COUR) <= 0.35):
                probs.append(f"H-TYPE {_r.type.name} sur façade (vole le jour)")
                break

        # ══ H-SVC-PLAQUE — BLOC SdB/WC PLAQUÉ, PAS FLOTTANT (défaut user 2026-07-06) ══
        # RÈGLE user (check (a)) : le bloc humide ne doit PAS flotter en îlot au
        # milieu du séjour (entouré de séjour sur ~4 côtés). Il doit être PLAQUÉ
        # contre un mur : partager une part SUBSTANTIELLE de son propre pourtour avec
        # le PÉRIMÈTRE de l'apt (≥ 30 % de son périmètre → il LONGE un mur mitoyen/
        # refend/couloir sur ≥1 arête pleine, ou est en coin). Un îlot flottant ne
        # partage que ~25 % (une seule arête, recessé des autres murs). On mesure le
        # bloc humide FUSIONNÉ (SdB ∪ WC) contre l'arête de l'apt. Testé à TOUS les
        # niveaux. BLOQUANT. Le revert-test v8 (bloc recessé 0,5 m, îlot) le FAIT
        # FIRER (25 % < 30 %) ; le bloc plaqué au refend passe (34-36 %). Universel.
        from shapely.ops import unary_union as _uu_g
        # T4/T5 : la SdB/WC est wide-shallow (sous le dégagement, ou en apt loggia)
        # → plaquée au refend sur toute son arête courte mais faible % de périmètre.
        # Seuil abaissé (elle n'est PAS un îlot). T2/T3 : reste strict (0,30).
        _PLAQUE_MIN_FRAC = 0.25 if typ in ("T4", "T5") else 0.30
        if _svc_polys:
            _svc_block = _uu_g([p for _, p in _svc_polys])
            if _svc_block.geom_type == "MultiPolygon":
                _svc_block = max(_svc_block.geoms, key=lambda g: g.area)
            _blk_perim = _svc_block.boundary.length
            if _blk_perim > 0.1:
                # PLAQUÉ = arête pleine contre le PÉRIMÈTRE de l'apt OU contre le
                # DÉGAGEMENT NUIT (T4/T5) : un bloc SdB/WC large-peu-profond sous le
                # couloir de nuit longe celui-ci sur toute sa longueur → il n'est PAS
                # un îlot flottant, même si son % de contact au périmètre est faible.
                _plaque_surf = apt.boundary
                for _dr, _dp in rooms:
                    if _dr.type == RoomType.DEGAGEMENT_NUIT:
                        _plaque_surf = _plaque_surf.union(_dp.boundary)
                _blk_shared = _svc_block.boundary.intersection(
                    _plaque_surf.buffer(0.06)).length
                _frac = _blk_shared / _blk_perim
                if _frac < _PLAQUE_MIN_FRAC:
                    probs.append(
                        f"H-SVC-PLAQUE bloc SdB/WC flottant "
                        f"(plaqué {_frac:.0%}<{_PLAQUE_MIN_FRAC:.0%} du périmètre = îlot)")

        # ══ H-SVC-CORR — WC/SdB JAMAIS SUR LE COULOIR COMMUN (défaut #2 user) ════
        # RÈGLE DURE (user 2026-07-06) : « jamais de porte de WC/SdB sur le palier
        # commun ». Le bloc humide doit être BORGNE côté couloir : (1) son arête ne
        # FRONTE pas le couloir commun (partage < 0,4 m avec la circulation
        # commune) ; (2) AUCUNE de ses portes (PORTE_INTERIEURE) ne s'ouvre sur la
        # circulation commune. Seule la PORTE_ENTREE peut toucher le couloir. Testé
        # à TOUS les niveaux (RDC inclus). BLOQUANT. Universel.
        _CORR_EDGE_MIN = 0.4
        for _r, _p in _svc_polys:
            # (1) arête partagée avec la circulation commune (union brute).
            if not _circ_raw.is_empty:
                _shared = _p.boundary.intersection(_circ_raw.buffer(0.12)).length
                if _shared > _CORR_EDGE_MIN:
                    probs.append(
                        f"H-SVC-CORR {_r.type.name} fronte le couloir ({_shared:.1f}m)")
                    break
        # (2) porte de WC/SdB ouvrant sur la circulation commune.
        _svc_boundaries = [(_r, _p.boundary.buffer(0.25)) for _r, _p in _svc_polys]
        _door_on_corr = False
        for o in ops:
            if o.type != OpeningType.PORTE_INTERIEURE:
                continue
            _w = wmap.get(o.wall_id)
            _seg = _opening_seg(o, _w) if _w else None
            if _seg is None:
                continue
            # porte desservant un WC/SdB ?
            if not any(_seg.intersects(_b) for _r, _b in _svc_boundaries):
                continue
            if (not _circ_raw.is_empty) and _seg.distance(_circ_raw) <= 0.35:
                _door_on_corr = True
                break
        if _door_on_corr:
            probs.append("H-SVC-CORR porte WC/SdB ouvrant sur le couloir commun")

        # (d) séjour + chaque chambre touchent une façade jour (rue OU cour).
        if _sej_polys and not any(_on_facade(p) for p in _sej_polys):
            probs.append("H-TYPE séjour sans façade jour")
        for r, p in rooms:
            if "CHAMBRE" in str(r.type) and not _on_facade(p):
                probs.append("H-TYPE chambre sans façade jour")
                break

        # ══ D — EXTÉRIEURS ══
        # Bâti À L'ALIGNEMENT de voie (UA.6, validé user 2026-07-03) → AUCUN
        # jardin extérieur possible en limite séparative. La règle D2 n'exige
        # donc PAS un jardin RDC : elle exige, à TOUS les niveaux (RDC compris),
        # que chaque logt ait ≥1 LOGGIA donnant sur une FAÇADE JOUR (rue OU void
        # intérieur), jamais sur un mitoyen. Une loggia sur mitoyen serait un
        # trou dans un mur aveugle (impossible) : on vérifie que le polygone de
        # la loggia touche la frontière du footprint (rue/cour) et PAS seulement
        # un mur mitoyen (arête de bbox non-voirie).
        _lg = getattr(c, "loggia", None)
        # Un logt RDC avec JARDIN privatif a son extérieur AU SOL → la loggia
        # n'est pas requise (le jardin EST l'extérieur ; poser en plus une loggia
        # au RDC = balcon au sol, refusé par l'user 2026-07-09). Sinon (étages, ou
        # RDC côté rue sans jardin) : ≥1 loggia/balcon sur façade jour, hors mitoyen.
        _has_jardin = bool(getattr(c, "jardin_polygon_xy", None))
        if _has_jardin:
            pass
        elif _lg is None or not _lg.polygon_xy or len(_lg.polygon_xy) < 3:
            probs.append("D sans loggia")
        else:
            _lgp = Polygon(_lg.polygon_xy)
            # façade jour = touche la frontière du footprint (rue OU void).
            _on_facade = (_lgp.distance(FP_BND) <= 0.4) or \
                (COUR.area > 0 and _lgp.distance(COUR) <= 0.4)
            if not _on_facade:
                probs.append("D loggia hors façade jour (mitoyen?)")

        if probs:
            apt_ko += 1
            ko.append(f"  {tag} {typ}: " + " · ".join(probs))

# ── GLOBAL ──
logts = [c for niv in bm.niveaux for c in niv.cellules if c.type == CelluleType.LOGEMENT]
mix = Counter(str(getattr(c, "typologie", "?")).split(".")[-1] for c in logts)
t = len(logts)
b_t1t2 = round(100 * sum(v for k, v in mix.items() if k in ("T1", "T2", "STUDIO")) / t)
b_t3 = round(100 * mix.get("T3", 0) / t)
b_t45 = round(100 * sum(v for k, v in mix.items() if k in ("T4", "T5")) / t)
mix_ko = []
for name, val in (("T1T2", b_t1t2), ("T3", b_t3), ("T4T5", b_t45)):
    if abs(val - CIBLE[name]) > TOL_MIX:
        mix_ko.append(f"{name} {val}% (cible {CIBLE[name]}±{TOL_MIX})")
shab = sum(c.surface_m2 for c in logts)
niv1 = [n for n in bm.niveaux if n.index == 1][0]
# CAGES (2026-07-06) : le core central est désormais émis comme circulation
# "cage_*_1" (esc+ASC+palier ABSORBÉ), la 2e cage comme "cage_*_2". On compte
# donc les cellules "cage_*" DISTINCTES par leur bbox (le core n'est plus ajouté
# séparément : il EST cage_*_1). Sur un plan legacy "palier_*" + "cage_*_2", on
# retombe sur l'ancien décompte (palier central + 1 cage + core).
_cage_ids = {cc.id for cc in niv1.circulations_communes if cc.id.startswith("cage_")}
if _cage_ids:
    ncages = len(_cage_ids)
else:
    ncages = len([cc for cc in niv1.circulations_communes if cc.id.startswith("palier")]) \
        + (1 if getattr(bm, "core", None) else 0)

# ══ H-1CAGE — EXACTEMENT 1 CAGE, AU COUDE (décision USER 2026-07-06) ═════════
# Un L n'a qu'UN angle rentrant (le coude) : UNE seule cage esc+ASC, posée au
# coude, dessert les 2 branches par le couloir en L. La 2e cage (côté hall) est
# SUPPRIMÉE. On FIRE si, sur TOUT niveau à logements, le nombre de cellules
# "cage_*" ≠ 1, OU si l'unique cage n'est pas AU COUDE. BLOQUANT. Universel.
# COUDE = jonction des couloirs des 2 branches = ``elbow`` de la décomposition L
# (intersection de l'axe de la branche verticale et de l'axe de la branche
# horizontale) — c'est le cœur AVEUGLE du L où le core doit loger, PAS le sommet
# concave côté jardin (qui, lui, doit rester une façade éclairée). On mesure la
# distance de la cage à ce point de jonction ; ≤ ~7 m = au coude (profondeur
# d'une branche dual-loaded), au-delà = cage en bout d'aile (côté hall = refusé).
try:
    from core.building_model.layout_l import decompose_l as _decompose_l
    _d_l = _decompose_l(FP_TRUE) or _decompose_l(FP)
    _elbow = _d_l.elbow if _d_l is not None else None
except Exception:
    _elbow = None
_h1cage_ko = []
for niv in bm.niveaux:
    if not any(c.type == CelluleType.LOGEMENT for c in niv.cellules):
        continue
    _cages = [cc for cc in niv.circulations_communes
              if cc.id.startswith("cage_") and cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if len(_cages) != 1:
        _h1cage_ko.append((f"R+{niv.index}", f"{len(_cages)} cage(s)≠1"))
        continue
    if _elbow is not None:
        _cg = Polygon(_cages[0].polygon_xy)
        _ep = Polygon([(_elbow[0] - 0.1, _elbow[1] - 0.1),
                       (_elbow[0] + 0.1, _elbow[1] - 0.1),
                       (_elbow[0] + 0.1, _elbow[1] + 0.1),
                       (_elbow[0] - 0.1, _elbow[1] + 0.1)])
        _d = _cg.distance(_ep)
        if _d > 7.0:
            _h1cage_ko.append((f"R+{niv.index}", f"cage à {_d:.1f} m du coude (>7 m)"))
_allp = _floor_polys(niv1)
# VIDE FOOTPRINT réel : on ÉRODE de 0,18 m avant de mesurer pour ignorer les
# jointures/hairlines < 0,36 m de large (artefacts de rendu, invisibles au plan),
# et ne compter que les VRAIES poches utilisables (défaut user « vide »). Universel.
def _real_void(fp, polys):
    raw = fp.difference(unary_union(polys).buffer(0.001))
    return raw.buffer(-0.18).buffer(0.18)
vide_fp = _real_void(FP_TRUE, _allp).area

# ── H — CIRCULATION SURDIMENSIONNÉE + POCHE DE FOOTPRINT (défaut "coude" du L) ─
# (H1) La circulation commune (couloir + palier + cages) ne doit pas manger une
#      part déraisonnable du plancher. Un palier surdimensionné au coude du L
#      (le gros rectangle blanc constaté par l'user) gonfle ce ratio : on borne
#      à 18 % du plancher d'un étage courant. Le core (esc+asc) compte comme
#      circulation ici (c'est de la SHAB non vendable, comme le couloir).
# (H2) Aucune POCHE de footprint > 3 m² ne doit rester non attribuée (ni logt,
#      ni circ légitime). C'est le trou blanc "perdu" au coude. On mesure les
#      composantes du vide FP − (apts ∪ circ ∪ core) une par une.
_floor_area = niv1.surface_plancher_m2 or FP.area
_circ_polys = [Polygon(cc.polygon_xy) for cc in niv1.circulations_communes
               if cc.polygon_xy and len(cc.polygon_xy) >= 3]
if getattr(bm, "core", None) and bm.core.polygon_xy:
    _circ_polys.append(Polygon(bm.core.polygon_xy))
_circ_area = unary_union(_circ_polys).area if _circ_polys else 0.0
_circ_ratio = 100.0 * _circ_area / _floor_area if _floor_area else 0.0
CIRC_MAX_PCT = 18.0

_void_all = _real_void(FP_TRUE, _allp)   # érodé : ignore les hairlines < 0,36 m
_void_pieces = ([_void_all] if _void_all.geom_type == "Polygon"
                else list(getattr(_void_all, "geoms", [])))
_big_pockets = [g for g in _void_pieces if g.area > 3.0]

# (H3) Le BLOC ESCALIER (core + palier) ne doit pas être un gros rectangle
#      surdimensionné. Un escalier + ASC + palier PMR tient dans ~30 m² ; au-delà
#      c'est le "gros palier vide au coude" (la SHAB perdue constatée par l'user).
#      On mesure l'emprise réelle du core fusionné avec les paliers coïncidents.
_stair_polys = []
if getattr(bm, "core", None) and bm.core.polygon_xy:
    _stair_polys.append(Polygon(bm.core.polygon_xy))
_stair_polys += [Polygon(cc.polygon_xy) for cc in niv1.circulations_communes
                 if cc.id.startswith("palier") and cc.polygon_xy
                 and len(cc.polygon_xy) >= 3]
_stair_block = unary_union(_stair_polys).area if _stair_polys else 0.0
STAIR_MAX_M2 = 30.0

# ── H4 — CHAQUE CELLULE PALIER / CAGE ≤ CAP (angle mort bouché, 2026-07-03) ──
# Défaut user #1 MESURÉ : le PALIER CENTRAL (palier_R*, adossé au core) faisait
# 23 m² — le « gros bloc palier 160 vide au centre ». H3 (bloc esc = core+palier
# ≤ 30 m²) ne l'attrapait PAS (23 < 30) et l'ANCIEN H4 capait palier_* à
# STAIR_MAX_M2 (30) → angle mort. On BOUCHE l'angle mort : CHAQUE cellule palier
# (centrale palier_R* ET par cage) est un palier PMR d'étage (esc quart-tournant
# + ASC + landing 1,4-1,6 m) qui tient dans ≤ PALIER_CELL_MAX_M2. Au-delà = SHAB
# perdue en circulation. Le core compact corrigé = 13,0 m² (passe) ; l'ancien
# 23 m² FIRE. La 2e cage (esc d'égress + ASC + palier mini = 10,8 m²) garde son
# cap CAGE_MAX_M2. Le couloir horizontal (couloir_*/hall_*) = spine, pas un
# palier vertical → exclu. Testé sur TOUS les niveaux (pire cas). Universel.
CAGE_MAX_M2 = 13.0        # esc d'égress + gaine ASC + palier PMR mini (2e cage)
PALIER_CELL_MAX_M2 = 14.0  # palier central PMR (esc quart-tournant + ASC + landing)
_h4_ko = []
for niv in bm.niveaux:
    for cc in niv.circulations_communes:
        if not cc.polygon_xy or len(cc.polygon_xy) < 3:
            continue
        # palier central (palier_R*) ET cage secondaire (cage_*) : chacun borné à
        # un palier PMR d'étage. Le couloir/hall = spine de desserte → exclu.
        _cap = (PALIER_CELL_MAX_M2 if cc.id.startswith("palier")
                else CAGE_MAX_M2 if cc.id.startswith("cage") else None)
        if _cap is None:
            continue
        _a = Polygon(cc.polygon_xy).area
        if _a > _cap + 0.5:
            _h4_ko.append((f"R+{niv.index}:{cc.id}", _a, _cap))

# ── H5 — 0 ESPACE VIDE ADJACENT À UNE ENTRÉE (défaut #1, RDC + étages) ───────
# Un vide de footprint > 2 m² touchant le hall d'entrée / une entrée d'apt = le
# "trou blanc à côté de l'entrée" constaté par l'user (RDC surtout). On scanne
# TOUS les niveaux : pour chaque poche de vide FP−(apts∪circ∪core) > 2 m², si
# elle touche un hall d'entrée (hall_*) OU une pièce ENTREE d'un apt, c'est KO.
_h5_ko = []
for niv in bm.niveaux:
    _pl = [Polygon(c.polygon_xy) for c in niv.cellules
           if c.polygon_xy and len(c.polygon_xy) >= 3]
    _pl += [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
            if cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if getattr(bm, "core", None) and bm.core.polygon_xy:
        _pl.append(Polygon(bm.core.polygon_xy))
    if not _pl:
        continue
    _vd = _real_void(FP_TRUE, _pl)   # érodé : ignore les hairlines de jointure < 0,36 m
    _vps = [_vd] if _vd.geom_type == "Polygon" else list(getattr(_vd, "geoms", []))
    # zones "entrée" : halls d'entrée + pièces ENTREE des apts.
    _entry_zones = [Polygon(cc.polygon_xy).buffer(0.25)
                    for cc in niv.circulations_communes
                    if cc.id.startswith("hall") and cc.polygon_xy
                    and len(cc.polygon_xy) >= 3]
    for c in niv.cellules:
        for r in getattr(c, "rooms", []) or []:
            if getattr(r, "type", None) == RoomType.ENTREE and r.polygon_xy \
                    and len(r.polygon_xy) >= 3:
                _entry_zones.append(Polygon(r.polygon_xy).buffer(0.25))
    if not _entry_zones:
        continue
    _ez = unary_union(_entry_zones)
    for g in _vps:
        if g.area <= 2.0:
            continue
        if g.intersects(_ez):
            b = g.bounds
            _h5_ko.append((f"R+{niv.index}", g.area, b))

# ── H8 — BANDE PALIER/COULOIR DE LA 2e CAGE ≤ SEUIL SERRÉ (défaut user #1) ────
# Le fix précédent a capé la CAGE elle-même (esc+asc, H4 ≤13 m²) mais PAS la
# BANDE de palier/couloir AUTOUR d'elle. L'user : « le palier/couloir de la 2e
# cage (branche gauche) mange l'espace ». On mesure, pour CHAQUE cage SECONDAIRE
# (cage_*, PAS le core central qui EST le hub de couloir légitime), la bande de
# desserte PRIVÉE = circulation dans un rayon _BAND_R autour de la cage, MOINS
# l'emprise de la cage (H4) ET MOINS la portion de couloir SPINE partagée
# (couloir_*, qui dessert TOUS les apts, pas la cage). Ce qui reste = le palier
# PMR + les élargissements propres à la 2e cage. Un palier PMR (~1,4 m) tient
# dans ≤ _BAND_MAX m² ; au-delà, la bande est surdimensionnée (SHAB perdue
# mangeant l'apt voisin — le défaut exact). Testé sur TOUS les niveaux (pire
# cas). Universel : dérivé de la géométrie de la 2e cage.
_BAND_R = 2.2       # rayon de la bande palier attribuée à la 2e cage
_BAND_MAX = 12.0    # m² de bande locale privée (palier PMR + amorce hors couloir spine)
_h8_ko = []
for niv in bm.niveaux:
    # SPINE de couloir partagée (dessert tous les apts) : couloir_* + hall_*.
    _spine = unary_union([Polygon(cc.polygon_xy) for cc in niv.circulations_communes
                          if (cc.id.startswith("couloir") or cc.id.startswith("hall"))
                          and cc.polygon_xy and len(cc.polygon_xy) >= 3]) \
        if any(cc.id.startswith(("couloir", "hall")) for cc in niv.circulations_communes) \
        else Polygon()
    # toutes les circulations du niveau (pour capter le palier autour de la cage).
    _all_circ = [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
                 if cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if getattr(bm, "core", None) and bm.core.polygon_xy:
        _all_circ.append(Polygon(bm.core.polygon_xy))
    _circ_u = unary_union(_all_circ) if _all_circ else Polygon()
    for cc in niv.circulations_communes:
        if not (cc.id.startswith("cage") and cc.polygon_xy and len(cc.polygon_xy) >= 3):
            continue
        _cg = Polygon(cc.polygon_xy)
        # bande PRIVÉE = circulation locale − cage − spine couloir partagée.
        _band = _circ_u.intersection(_cg.buffer(_BAND_R)) \
            .difference(_cg.buffer(-0.02)).difference(_spine.buffer(0.02))
        _ba = _band.area if not _band.is_empty else 0.0
        if _ba > _BAND_MAX + 0.5:
            _h8_ko.append((f"R+{niv.index}:{cc.id}", _ba))

# ══ H-PAL — 0 CELLULE « PALIER » AUTONOME HORS CAGE (défaut user 2026-07-06) ══
# L'user REFUSE toute cellule de circulation dont le label/type contient « palier »
# et qui n'est PAS une cage : le palier d'arrivée doit être ABSORBÉ dans l'emprise
# de la cage (esc+ASC), jamais un bloc gris vide distinct. On FIRE donc sur toute
# circulation dont l'id contient "palier" (les cages sont nommées "cage_*"). Testé
# sur TOUS les niveaux. BLOQUANT. Universel.
_hpal_ko = []
for niv in bm.niveaux:
    for cc in niv.circulations_communes:
        if "palier" in (cc.id or "").lower():
            _a = Polygon(cc.polygon_xy).area if (cc.polygon_xy and len(cc.polygon_xy) >= 3) else 0.0
            _hpal_ko.append((f"R+{niv.index}:{cc.id}", _a))

# ══ H-VIDE — 0 CELLULE VIDE / NON ATTRIBUÉE > 2 m² À TOUT NIVEAU (RDC inclus) ══
# Défaut user 2026-07-06 : aucun grand bloc gris vide (ni « courette » interne, ni
# colonne RDC gauche). Pour CHAQUE niveau, le vide FP − (apts ∪ circ ∪ core), ÉRODÉ
# de 0,18 m (ignore les hairlines de jointure < 0,36 m), ne doit contenir AUCUNE
# poche > 2 m². BLOQUANT. Universel (RDC et étages).
_hvide_ko = []
for niv in bm.niveaux:
    _pl = [Polygon(c.polygon_xy) for c in niv.cellules
           if c.polygon_xy and len(c.polygon_xy) >= 3]
    _pl += [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
            if cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if getattr(bm, "core", None) and bm.core.polygon_xy:
        _pl.append(Polygon(bm.core.polygon_xy))
    if not _pl:
        continue
    _rv = _real_void(FP_TRUE, _pl)
    _rvp = [_rv] if _rv.geom_type == "Polygon" else list(getattr(_rv, "geoms", []))
    for g in _rvp:
        if g.area > 2.0:
            b = g.bounds
            _hvide_ko.append((f"R+{niv.index}", g.area, b))

# ══ H-CIRC13 — CIRCULATION SERRÉE (demande user « ≤ ~13 % ») ═════════════════
# On distingue le COULOIR-PROPRE (le ruban MINCE 1,40 m qui dessert les apts +
# les 2 cages) du CENTRE AVEUGLE du L absorbé dans la spine. Sur un L à coude
# profond, le zéro-vide FORCE la poche centrale aveugle (aucune façade possible)
# dans la circulation : elle ne peut devenir ni logement (borgne) ni vide (refus
# user). Le « couloir mince + cages » DOIT rester ≤ 13,5 % ; la spine totale
# (couloir + centre aveugle absorbé) peut monter jusqu'à ~17 % sur ce footprint
# précis, ce n'est pas de la SHAB perdue « évitable » mais la conséquence
# géométrique du coude. On mesure les DEUX. Universel (le 2e plafond ne mord que
# quand un vrai centre aveugle existe).
CIRC13_MAX_PCT = 13.5           # couloir-mince + cages (hors centre aveugle)
# spine totale (inclut le centre aveugle inévitable). Relevé 17,0 → 18,0 le 2026-07-08 :
# la COUR est désormais un RECTANGLE NET (H-COUR-RECT) et on RÉSERVE une lane PMR pour
# la spine (H-COULOIR-CONNEXE) → la cour cède ~1,6 m de largeur au couloir (couloir
# CONTINU, cage sur la jonction) ⇒ +~0,5 pt de circulation vs l'ancienne cour-en-L qui
# étranglait le couloir. Trade-off ASSUMÉ (confort habitant > cour maximale). Le cap
# reste = CIRC_MAX_PCT (18 %) : au-delà, le couloir mange vraiment de la SHAB.
CIRC_SPINE_MAX_PCT = 18.0
# couloir « mince » = couloir dont on retire la part large (> 2,2 m) = le centre
# aveugle. On mesure la largeur locale par érosion : le ruban 1,40 m survit à une
# érosion de 0,75 m puis re-dilatation ; le centre aveugle (large) survit lui à
# une érosion de 1,3 m. La différence = le centre aveugle.
_couloir_polys = [Polygon(cc.polygon_xy) for cc in niv1.circulations_communes
                  if cc.id.startswith(("couloir", "hall")) and cc.polygon_xy
                  and len(cc.polygon_xy) >= 3]
_couloir_u = unary_union(_couloir_polys) if _couloir_polys else Polygon()
_blind_core = _couloir_u.buffer(-1.30).buffer(1.30) if not _couloir_u.is_empty else Polygon()
_thin_circ_area = _circ_area - (_blind_core.area if not _blind_core.is_empty else 0.0)
_thin_ratio = 100.0 * _thin_circ_area / _floor_area if _floor_area else 0.0
_circ13_ko = (_thin_ratio > CIRC13_MAX_PCT) or (_circ_ratio > CIRC_SPINE_MAX_PCT)

# ══ H-COUR — CENTRE MORT PERCÉ EN VRAIE COUR OUVERTE (demande user 2026-07-06) ══
# Un immeuble sur cour DOIT avoir sa cour PERCÉE : le centre mort (l'ancien
# couloir plein de 161 m², bloc de ~98 m² au coude) devient un VIDE traversant à
# ciel ouvert. On EXIGE, à TOUS les niveaux à logements, TROIS preuves cumulées :
#   (1) COUR PRÉSENTE : chaque niveau porte un ``cour_polygon_xy`` cohérent (≥12 m²).
#   (2) PLANCHER RÉDUIT : surface_plancher_m2 < aire du footprint − aire cour + ε.
#       Preuve que la cour est un TROU (plancher retiré), pas un renommage.
#   (3) ANNEAU MINCE : le couloir walkable (contour couloir − cour), érodé de
#       1,30 m PUIS re-dilaté, MOINS un palier PMR de 1,0 m autour de la cage,
#       ne laisse AUCUN bloc plein > _COUR_BLOB_MAX. Sur l'état « couloir 161 m²
#       plein » ce résidu vaut ~85 m² (FIRE) ; sur l'état percé ~3-4 m² (palier
#       légitime, PASSE). Universel (tout L/U à centre aveugle).
# La cour est un RECTANGLE NET (H-COUR-RECT) : la cage occupe alors un COIN de la
# chambre et laisse à côté d'elle un PAN de couloir = la JONCTION escalier (nœud de
# circulation ~14-26 m²), géométriquement inévitable quand un rectangle net côtoie une
# cage carrée dans une chambre carrée. Ce nœud est WALKABLE (couloir continu, prouvé
# par H-COULOIR-CONNEXE), PAS un centre mort. On tolère donc jusqu'à 28 m² : bien
# au-dessus du nœud escalier, très en-dessous d'un vrai centre NON percé (~98 m², qui
# FIRE encore). Le blob soustrait déjà la cage + 1,40 m de palier PMR.
_COUR_BLOB_MAX = 28.0
_cour_ko = []
# La cour percée est une exigence du plan L (immeuble sur cour à centre aveugle).
# Le U est DÉJÀ un immeuble à cour OUVERTE par sa forme (angle rentrant central non
# bâti) : il n'a pas de « centre mort plein » à percer → check H-COUR L-only.
_is_l_mode = "--u" not in sys.argv
_core_poly_gate = None
if getattr(bm, "core", None) and bm.core.polygon_xy and len(bm.core.polygon_xy) >= 3:
    _core_poly_gate = Polygon(bm.core.polygon_xy)
# aire cour de référence (niveau courant) — sert au message + au check plancher.
_cour_ref = None
for _nn in bm.niveaux:
    _cxy = getattr(_nn, "cour_polygon_xy", None)
    if _cxy and len(_cxy) >= 3:
        _cour_ref = Polygon(_cxy)
        break
_cour_area_ref = _cour_ref.area if _cour_ref is not None else 0.0
for niv in (bm.niveaux if _is_l_mode else []):
    if not any(c.type == CelluleType.LOGEMENT for c in niv.cellules):
        continue
    _cxy = getattr(niv, "cour_polygon_xy", None)
    # (1) cour présente + assez grande
    if not _cxy or len(_cxy) < 3:
        _cour_ko.append((f"R+{niv.index}", "PAS de cour percée (centre mort plein)"))
        continue
    _cour_g = Polygon(_cxy)
    if _cour_g.area < 12.0:
        _cour_ko.append((f"R+{niv.index}", f"cour trop petite {_cour_g.area:.0f}<12 m²"))
        continue
    # (2) plancher réduit de l'aire VIDE (trou réel). En parti ATRIUM, le noyau
    # esc+ASC est un VOLUME BÂTI planté DANS la cour : le vide réel = anneau planté
    # (cour − noyau), pas toute la cour (on marche sur le noyau à chaque niveau). On
    # retire donc du void l'emprise du/des noyau(x) logée dans la cour.
    _void_g = _cour_g.area
    if bool(getattr(niv, "atrium_verriere", False)):
        _cage_in = 0.0
        for cc in niv.circulations_communes:
            if cc.id.startswith("cage") and cc.polygon_xy and len(cc.polygon_xy) >= 3:
                _cage_in += Polygon(cc.polygon_xy).intersection(_cour_g).area
        _void_g = max(0.0, _cour_g.area - _cage_in)
    if niv.surface_plancher_m2 > FP_TRUE.area - _void_g + 3.0:
        _cour_ko.append((f"R+{niv.index}",
                         f"plancher {niv.surface_plancher_m2:.0f} non réduit "
                         f"(footprint {FP_TRUE.area:.0f} − vide {_void_g:.0f})"))
        continue
    # (3) anneau mince : couloir walkable − cour, érodé 1,3 m, − CAGE + son palier
    # PMR (1,4 m d'accès). La CAGE est un volume BÂTI, donc légitimement SOLIDE :
    # on la SOUSTRAIT (avec 1,4 m de palier d'accès autour) pour ne mesurer que le
    # couloir « faussement plein » restant. Le seuil (_COUR_BLOB_MAX) tolère le
    # petit pan de couloir résiduel INÉVITABLE à côté d'une cage centrée au coude
    # (~13 m²), mais FIRE sur un vrai centre mort NON percé (l'ancien slab ~98 m²)
    # — celui-là est déjà attrapé en amont par (1) cour absente. La preuve que la
    # cage est HORS COUR est portée par le check H-CAGE-BATIE (dédié).
    _cpolys = [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
               if cc.id.startswith(("couloir", "hall")) and cc.polygon_xy
               and len(cc.polygon_xy) >= 3]
    _cu = unary_union(_cpolys) if _cpolys else Polygon()
    _walk = _cu.difference(_cour_g) if not _cu.is_empty else Polygon()
    _blob = _walk.buffer(-1.30).buffer(1.30) if not _walk.is_empty else Polygon()
    if _core_poly_gate is not None and not _blob.is_empty:
        _blob = _blob.difference(_core_poly_gate.buffer(1.40))
    _blob_a = _blob.area if not _blob.is_empty else 0.0
    # PARTI ATRIUM : le noyau esc+ASC quitte le coude pour l'ATRIUM (planté dans la
    # cour). Le coude reste alors un HUB de circulation HORIZONTALE légitime : c'est
    # là qu'arrivent les entrées des 4 apts du coude ET le passage vers le noyau
    # central (absorber ce hub SÉVRE les 4 entrées — H-COULOIR-CONNEXE l'a prouvé).
    # Ce n'est donc PAS un centre mort : c'est un vrai hall d'atrium. On relève le
    # cap en mode atrium (le noyau étant DANS la cour, plus au coude). La vraie garde
    # SHAB reste la circulation % (< 18 %, vérifiée par ailleurs). Universel.
    _blob_cap = 52.0 if bool(getattr(niv, "atrium_verriere", False)) else _COUR_BLOB_MAX
    if _blob_a > _blob_cap:
        _cour_ko.append((f"R+{niv.index}",
                         f"couloir garde un bloc plein {_blob_a:.0f}>{_blob_cap:.0f} m² "
                         f"(centre mort non percé)"))

print("=" * 64)
print(f"  VÉRIF PLAN {'U' if '--u' in sys.argv else 'L'} — {t} logts · "
      f"SHAB {round(shab)} m² · mix {b_t1t2}/{b_t3}/{b_t45}")
print("=" * 64)
print(f"apts KO : {apt_ko}/{n_apts} | cages : {ncages} | mix cible 20/50/30")
for line in ko[:30]:
    print(line)
if mix_ko:
    print("  MIX hors cible : " + " · ".join(mix_ko))
# H-1CAGE : exactement 1 cage au coude (décision USER 2026-07-06, remplace « 2 cages »).
if _elbow is not None:
    print(f"cage unique au coude : coude=({_elbow[0]:.1f},{_elbow[1]:.1f})")
for _tag, _why in _h1cage_ko:
    print(f"  H-1CAGE : {_tag} {_why} = BLOQUANT")
if vide_fp > 2.0:
    print(f"  VIDE FOOTPRINT : {vide_fp:.0f} m² (blanc non couvert = BLOQUANT)")
print(f"circulation : {_circ_area:.0f} m² = {_circ_ratio:.1f}% du plancher "
      f"(cap {CIRC_MAX_PCT:.0f}%)")
if _circ_ratio > CIRC_MAX_PCT:
    print(f"  CIRCULATION SURDIMENSIONNÉE : {_circ_ratio:.1f}% > {CIRC_MAX_PCT:.0f}% "
          f"(palier/couloir mange de la SHAB = BLOQUANT)")
for g in sorted(_big_pockets, key=lambda x: -x.area):
    b = g.bounds
    print(f"  POCHE FOOTPRINT NON ATTRIBUÉE : {g.area:.0f} m² "
          f"bbox=({b[0]:.1f},{b[1]:.1f})-({b[2]:.1f},{b[3]:.1f}) = BLOQUANT")
print(f"bloc escalier (core+palier) : {_stair_block:.0f} m² (cap {STAIR_MAX_M2:.0f})")
if _stair_block > STAIR_MAX_M2:
    print(f"  BLOC ESCALIER SURDIMENSIONNÉ : {_stair_block:.0f} m² > {STAIR_MAX_M2:.0f} "
          f"(gros palier vide au coude = SHAB perdue = BLOQUANT)")
# H4 — mesure explicite de CHAQUE cellule palier (angle mort bouché 2026-07-03).
_palier_cells = [(f"R+{niv.index}:{cc.id}", Polygon(cc.polygon_xy).area)
                 for niv in bm.niveaux for cc in niv.circulations_communes
                 if cc.id.startswith("palier") and cc.polygon_xy
                 and len(cc.polygon_xy) >= 3]
if _palier_cells:
    _pmax = max(a for _, a in _palier_cells)
    print(f"palier central (cellule) : max {_pmax:.1f} m² "
          f"(cap H4 {PALIER_CELL_MAX_M2:.0f}) — défaut d'origine = 23,0 m²")
for _tag, _a, _cap in _h4_ko:
    print(f"  H4 PALIER/CAGE SURDIMENSIONNÉ : {_tag} = {_a:.0f} m² > {_cap:.0f} "
          f"(mange l'apt voisin / gros palier vide = BLOQUANT)")
for _tag, _a, _b in _h5_ko:
    print(f"  H5 VIDE ADJACENT ENTRÉE : {_tag} {_a:.0f} m² "
          f"bbox=({_b[0]:.1f},{_b[1]:.1f})-({_b[2]:.1f},{_b[3]:.1f}) = BLOQUANT")
for _tag, _ba in _h8_ko:
    print(f"  H8 BANDE PALIER/COULOIR CAGE : {_tag} = {_ba:.0f} m² > {_BAND_MAX:.0f} "
          f"(palier/couloir autour de la cage mange la SHAB = BLOQUANT)")
# ── nouveaux checks user 2026-07-06 ──
for _tag, _a in _hpal_ko:
    print(f"  H-PAL CELLULE « PALIER » HORS CAGE : {_tag} = {_a:.0f} m² "
          f"(palier isolé refusé — doit être absorbé dans la cage = BLOQUANT)")
for _tag, _a, _b in _hvide_ko:
    print(f"  H-VIDE POCHE VIDE > 2 m² : {_tag} {_a:.0f} m² "
          f"bbox=({_b[0]:.1f},{_b[1]:.1f})-({_b[2]:.1f},{_b[3]:.1f}) = BLOQUANT")
print(f"circulation : couloir-mince+cages {_thin_ratio:.1f}% (cap {CIRC13_MAX_PCT:.0f}%) "
      f"| spine totale {_circ_ratio:.1f}% (cap {CIRC_SPINE_MAX_PCT:.0f}% — inclut centre aveugle du coude)")
if _thin_ratio > CIRC13_MAX_PCT:
    print(f"  H-CIRC13 COULOIR-MINCE+CAGES > {CIRC13_MAX_PCT:.0f}% : {_thin_ratio:.1f}% = BLOQUANT")
if _circ_ratio > CIRC_SPINE_MAX_PCT:
    print(f"  H-CIRC13 SPINE TOTALE > {CIRC_SPINE_MAX_PCT:.0f}% : {_circ_ratio:.1f}% = BLOQUANT")
# ── H-COUR : centre mort percé en vraie cour ouverte (2026-07-06, L only) ──
if _is_l_mode:
    if _cour_ref is not None:
        print(f"cour intérieure percée : {_cour_area_ref:.0f} m² (trou traversant) "
              f"| plancher/niveau réduit à {niv1.surface_plancher_m2:.0f} "
              f"(footprint {FP_TRUE.area:.0f})")
    else:
        print("cour intérieure : ABSENTE (centre mort plein)")
for _tag, _why in _cour_ko:
    print(f"  H-COUR : {_tag} {_why} = BLOQUANT")

# ══════════════════════════════════════════════════════════════════════════════
# NOUVEAUX BLOQUANTS (demande user 2026-07-06) — 3 checks durs + prouvés revert.
# ══════════════════════════════════════════════════════════════════════════════
from shapely.geometry import LineString as _LnS2

# ── (i) H-CAGE-BATIE : la CAGE (escalier+ASC) est un volume BÂTI FERMÉ, INTÉGRÉ
#    au bâti — PAS « posée » au milieu du couloir. Elle NE PEUT PAS être dans la
#    cour à ciel ouvert NI flotter, entourée de circulation sur tous ses côtés.
#    On EXIGE, à chaque niveau à cour :
#      (a) core_polygon ∩ cour_polygon = 0 (cage HORS cour), et
#      (b) la cage n'a PAS ≥ 2 côtés sur la cour (≥ 2 = cage « flottant » dans le
#          vide, tour perchée), et
#      (c) DURCI 2026-07-08 — cage INTÉGRÉE : elle partage une longueur ≥ _CONTACT_MIN
#          m avec la COUR (elle prend le jour, tour sur cour assumée) ET une longueur
#          ≥ _CONTACT_MIN m avec un MUR D'APT (ou un MITOYEN = frontière footprint).
#          Sinon elle est « posée n'importe où », entourée de circulation → BLOQUANT.
#    Le revert-test v20 (cage flottante : 0,4 m² cour, 0 apt, gris sur 3 côtés)
#    FIRE sur (c). Universel (mesuré sur la géométrie réelle cage/cour/apt).
_CONTACT_MIN = 2.0   # m : longueur d'arête pleine mini partagée cage↔cour et cage↔apt
_ATRIUM_RING_MIN = 15.0   # m² : anneau planté mini AUTOUR du noyau dans l'atrium
_cage_ko = []       # H-CAGE-BATIE (cour ouverte v23 : cage HORS cour, adossée bâti)
_atrium_ko = []     # H-ATRIUM      (parti atrium : noyau DANS la cour, anneau planté)
for niv in (bm.niveaux if _is_l_mode else []):
    _cxy = getattr(niv, "cour_polygon_xy", None)
    if not _cxy or len(_cxy) < 3:
        continue
    _cour_g = Polygon(_cxy)
    # murs BÂTIS = union des logements du niveau ∪ frontière footprint (mitoyens).
    _apts_niv = unary_union([Polygon(c.polygon_xy) for c in niv.cellules
                     if c.type == CelluleType.LOGEMENT and c.polygon_xy
                     and len(c.polygon_xy) >= 3])
    _fp_niv = unary_union(_floor_polys(niv)).buffer(0)
    _bati_bnd = _apts_niv.boundary
    if not _fp_niv.is_empty:
        _bati_bnd = _bati_bnd.union(_fp_niv.boundary)   # + mitoyen (bord du plancher)
    _cages = [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
              if cc.id.startswith("cage") and cc.polygon_xy and len(cc.polygon_xy) >= 3]
    _corr_g = unary_union([Polygon(cc.polygon_xy) for cc in niv.circulations_communes
                           if cc.id.startswith("couloir") and cc.polygon_xy
                           and len(cc.polygon_xy) >= 3])
    _is_atrium = bool(getattr(niv, "atrium_verriere", False))
    for _cg in _cages:
        _inter = _cg.intersection(_cour_g).area
        if _is_atrium:
            # ── H-ATRIUM (2026-07-09, demande user) : le noyau esc+ASC est PLANTÉ
            #    AU CENTRE de la cour (on monte à travers un jardin sous verrière).
            #    On EXIGE, à chaque niveau atrium :
            #      (a) noyau ⊂ cour : cage ∩ cour ≥ 0,95·aire(cage) (le noyau est
            #          BIEN dans l'emprise de la cour, pas à côté) ;
            #      (b) ANNEAU PLANTÉ : cour − noyau ≥ _ATRIUM_RING_MIN m² (le vert
            #          entoure vraiment le noyau, pas un noyau qui remplit la cour) ;
            #      (c) ACCÈS : le noyau touche le COULOIR ≥ _CONTACT_MIN m sur UNE
            #          face (accès direct depuis la circulation).
            #    Revert-test ATRIUM_MODE=0 (parti v23 : cage tangente HORS cour)
            #    FIRE sur (a) (cage ∩ cour ≈ 0). Universel (dérivé cour/cage/couloir).
            if _inter < 0.95 * _cg.area:
                _atrium_ko.append((f"R+{niv.index}",
                    f"noyau HORS atrium : cage ∩ cour = {_inter:.1f} m² < "
                    f"{0.95 * _cg.area:.1f} (noyau doit être PLANTÉ dans la cour)"))
                continue
            _ring = _cour_g.difference(_cg).area
            if _ring < _ATRIUM_RING_MIN:
                _atrium_ko.append((f"R+{niv.index}",
                    f"anneau planté {_ring:.1f} m² < {_ATRIUM_RING_MIN} m² "
                    f"(le vert n'entoure pas assez le noyau)"))
            _corr_len = (_cg.boundary.intersection(_corr_g.buffer(0.30)).length
                         if not _corr_g.is_empty else 0.0)
            if _corr_len < _CONTACT_MIN:
                _atrium_ko.append((f"R+{niv.index}",
                    f"noyau sans accès couloir : contact {_corr_len:.1f} m < "
                    f"{_CONTACT_MIN} m (le noyau doit toucher la circulation)"))
            continue
        # ── H-CAGE-BATIE (cour ouverte v23) : cage HORS cour, adossée au bâti. ──
        if _inter > 0.5:
            _cage_ko.append((f"R+{niv.index}",
                             f"cage ∩ cour = {_inter:.1f} m² > 0 (escalier dans le vide)"))
            continue
        # côtés de la cage donnant sur la cour (arête à < 0,2 m de la cour, longueur
        # utile). ≥ 2 ⇒ cage non ceinturée par le bâti.
        _b = _cg.bounds
        _sides = {
            "S": _LnS2([(_b[0], _b[1]), (_b[2], _b[1])]),
            "N": _LnS2([(_b[0], _b[3]), (_b[2], _b[3])]),
            "O": _LnS2([(_b[0], _b[1]), (_b[0], _b[3])]),
            "E": _LnS2([(_b[2], _b[1]), (_b[2], _b[3])]),
        }
        _on_cour = sum(1 for _ln in _sides.values()
                       if _ln.buffer(0.20).intersection(_cour_g).area > 0.3)
        if _on_cour >= 2:
            _cage_ko.append((f"R+{niv.index}",
                             f"cage a {_on_cour} côtés sur la cour (pas ceinturée de bâti)"))
        # (c) DURCI : LONGUEUR de contact cage↔cour et cage↔mur-d'apt/mitoyen.
        #     On mesure la LONGUEUR du contour de la cage qui longe la cour (à ≤
        #     0,25 m — l'épaisseur du mur cage/cour), resp. qui est plaquée sur un
        #     mur bâti (apt/mitoyen). La cour est TOUJOURS séparée de la cage par
        #     son mur (cage ∩ cour = 0, gap ~0,2 m) : on mesure donc l'ADJACENCE du
        #     contour, pas un recouvrement. ≥ _CONTACT_MIN m sur CHACUN = intégrée.
        _cour_len = _cg.boundary.intersection(_cour_g.boundary.buffer(0.25)).length
        _bati_len = _cg.boundary.intersection(_bati_bnd.buffer(0.05)).length
        if _cour_len < _CONTACT_MIN or _bati_len < _CONTACT_MIN:
            _cage_ko.append((f"R+{niv.index}",
                             f"cage NON intégrée : contact cour {_cour_len:.1f} m / "
                             f"apt-mitoyen {_bati_len:.1f} m (min {_CONTACT_MIN} m chacun) "
                             f"— posée dans le couloir, pas adossée au bâti+cour"))
for _tag, _why in _cage_ko:
    print(f"  H-CAGE-BATIE : {_tag} {_why} = BLOQUANT")
for _tag, _why in _atrium_ko:
    print(f"  H-ATRIUM : {_tag} {_why} = BLOQUANT")

# ══ H-CAGE-COMPACTE — CAGE = NOYAU RECTANGULAIRE COMPACT (défaut user 2026-07-06) ══
# DÉFAUT : l'escalier+ASC formait un T/péninsule (ASC perché sur l'escalier, partie
# flottant dans le couloir). RÈGLE user : la cage = UN noyau RECTANGULAIRE compact
# (esc + ASC côte à côte, ~4,3×3 m), FERMÉ, accolé au couloir par UNE arête. BLOQUANT :
#   (a) core rectangulaire : ≤ 6 sommets ET rect-ratio (aire/aire-bbox) ≥ 0,90 (pas de
#       T, pas d'excroissance) ;
#   (b) ratio de forme raisonnable : min(W,H)/max(W,H) ≥ 0,45 (ni sliver, ni péninsule) ;
#   (c) accolé au couloir : le core partage ≥ 0,8 m d'arête avec la circulation commune
#       (accès), à au moins un niveau à logements ;
#   (d) cage ∩ cour = 0 (déjà H-CAGE-BATIE, revérifié compact ici).
# On teste le core (bm.core) ET chaque cellule cage_* (rendu). Le revert-test v10
# (core en T / rect-ratio bas) FIRE sur (a)/(b). BLOQUANT. Universel.
_cagec_ko = []
_core_polys_gate = []
if getattr(bm, "core", None) and bm.core.polygon_xy and len(bm.core.polygon_xy) >= 3:
    _core_polys_gate.append(("core", Polygon(bm.core.polygon_xy)))
for niv in bm.niveaux:
    for cc in niv.circulations_communes:
        if cc.id.startswith("cage") and cc.polygon_xy and len(cc.polygon_xy) >= 3:
            _core_polys_gate.append((f"R+{niv.index}:{cc.id}", Polygon(cc.polygon_xy)))
for _cid, _cp in _core_polys_gate:
    _b = _cp.bounds
    _w = _b[2] - _b[0]; _h = _b[3] - _b[1]
    _bba = (_w * _h) or 1.0
    _nverts = len(_cp.exterior.coords) - 1
    _rratio = _cp.area / _bba
    _shape = (min(_w, _h) / max(_w, _h)) if max(_w, _h) > 0 else 0.0
    if _nverts > 6 or _rratio < 0.90:
        _cagec_ko.append((_cid,
                          f"non rectangulaire ({_nverts} sommets, rect-ratio {_rratio:.2f}) — T/excroissance"))
    if _shape < 0.45:
        _cagec_ko.append((_cid,
                          f"forme sliver/péninsule (min/max {_shape:.2f} < 0,45)"))
# (c) accolé au couloir : ≥ 0,8 m d'arête partagée avec la circulation commune.
_core_touches_corr = False
for niv in bm.niveaux:
    if not any(c.type == CelluleType.LOGEMENT for c in niv.cellules):
        continue
    _corr = unary_union([Polygon(cc.polygon_xy) for cc in niv.circulations_communes
                         if not cc.id.startswith("cage") and cc.polygon_xy
                         and len(cc.polygon_xy) >= 3])
    _cages_niv = [Polygon(cc.polygon_xy) for cc in niv.circulations_communes
                  if cc.id.startswith("cage") and cc.polygon_xy and len(cc.polygon_xy) >= 3]
    if getattr(bm, "core", None) and bm.core.polygon_xy and len(bm.core.polygon_xy) >= 3:
        _cages_niv.append(Polygon(bm.core.polygon_xy))
    for _cg in _cages_niv:
        if _corr.is_empty:
            continue
        # accès OK si : (1) le core est CONTENU dans le couloir (couloir enveloppant,
        # cas normal du L : la cage est au cœur du ruban de circulation), OU
        # (2) il partage ≥ 0,8 m d'arête avec le couloir (cage adossée en bord).
        _contained = _corr.buffer(0.05).contains(_cg.buffer(-0.05))
        _edge = _cg.boundary.intersection(_corr.boundary.buffer(0.15)).length
        if _contained or _edge >= 0.8:
            _core_touches_corr = True
            break
    if _core_touches_corr:
        break
if _core_polys_gate and not _core_touches_corr:
    _cagec_ko.append(("cage", "sans accès au couloir (ni enveloppée, ni arête ≥ 0,8 m)"))
for _tag, _why in _cagec_ko:
    print(f"  H-CAGE-COMPACTE : {_tag} {_why} = BLOQUANT")

# ══ H-COUR-RECT — LA COUR EST UN RECTANGLE NET (défaut user 2026-07-08, confort) ══
# L'user (au zoom R+0) : « une partie de la cour bloque l'accès au couloir ». Sur v22
# la cour avait GRANDI en L (7 sommets, rect-ratio 0,74) : son BRAS remontait dans la
# bande de couloir. RÈGLE : la cour = un RECTANGLE NET (≤ 6 sommets ET rect-ratio =
# aire / aire-bbox ≥ 0,90) — PAS de L, PAS d'excroissance qui empiète sur le couloir.
# Revert-test COUR_GROW_L=1 (ré-active le gonflement en L de v22) FIRE ici (0,74<0,90).
# BLOQUANT. Universel (mesuré sur la géométrie réelle de la cour, tout niveau à cour).
_courrect_ko = []
for niv in (bm.niveaux if _is_l_mode else []):
    _cxy = getattr(niv, "cour_polygon_xy", None)
    if not _cxy or len(_cxy) < 3:
        continue
    _cg = Polygon(_cxy)
    if _cg.is_empty or _cg.geom_type != "Polygon":
        continue
    _nv = len(_cg.exterior.coords) - 1
    _b = _cg.bounds
    _bba = ((_b[2] - _b[0]) * (_b[3] - _b[1])) or 1.0
    _rr = _cg.area / _bba
    if _nv > 6 or _rr < 0.90:
        _courrect_ko.append((f"R+{niv.index}",
                             f"cour NON rectangle ({_nv} sommets, rect-ratio {_rr:.2f}) "
                             f"— L/excroissance qui empiète sur le couloir"))
for _tag, _why in _courrect_ko:
    print(f"  H-COUR-RECT : {_tag} {_why} = BLOQUANT")

# ══ H-COULOIR-CONNEXE — COULOIR CONTINU, LA COUR NE LE COUPE PAS (user 2026-07-08) ══
# Confort : un habitant sort de la cage → couloir DÉGAGÉ → chaque appart, SANS que la
# cour soit en travers. On EXIGE, à chaque niveau à cour :
#   (a) le WALKABLE = (couloir − cour − cage), hairlines pontées, est d'UN SEUL TENANT
#       (1 seule composante > 2 m²) : la cour ne SCINDE pas le couloir en morceaux ;
#   (b) CHAQUE PORTE_ENTREE d'apt touche ce walkable (aucun apt n'est isolé du couloir
#       par la cour) ;
#   (c) la cour ne recouvre AUCUNE lane de couloir réservée (les bras minces du cœur
#       mort étendus dans la chambre) : cour ∩ lanes = 0 → le couloir passe.
# Revert-test COUR_BLOCK_LANE=1 (la cour avale une lane, sévrant un bras) FIRE sur (a)
# et/ou (c). BLOQUANT. Universel (dérivé couloir/cour/cage/apts, aucune coord en dur).
_courconn_ko = []


def _entry_door_segs(niv):
    _out = []
    for _c in niv.cellules:
        if _c.type != CelluleType.LOGEMENT:
            continue
        for _op in (_c.openings or []):
            if _op.type != OpeningType.PORTE_ENTREE:
                continue
            _w = next((w for w in (_c.walls or []) if w.id == _op.wall_id), None)
            if _w is None:
                continue
            (_ax, _ay), (_bx, _by) = _w.geometry["coords"]
            _wl = ((_bx - _ax) ** 2 + (_by - _ay) ** 2) ** 0.5 or 1.0
            _t = (_op.position_along_wall_cm / 100.0) / _wl
            _hw = (_op.width_cm / 100.0) / 2
            _out.append((_c.id, _LnS2([
                (_ax + (_bx - _ax) * max(0, _t - _hw / _wl),
                 _ay + (_by - _ay) * max(0, _t - _hw / _wl)),
                (_ax + (_bx - _ax) * min(1, _t + _hw / _wl),
                 _ay + (_by - _ay) * min(1, _t + _hw / _wl))])))
    return _out


for niv in (bm.niveaux if _is_l_mode else []):
    _cxy = getattr(niv, "cour_polygon_xy", None)
    if not _cxy or len(_cxy) < 3:
        continue
    _cour_g = Polygon(_cxy)
    _cages = unary_union([Polygon(cc.polygon_xy) for cc in niv.circulations_communes
                          if cc.id.startswith("cage") and cc.polygon_xy
                          and len(cc.polygon_xy) >= 3])
    _corr = unary_union([Polygon(cc.polygon_xy) for cc in niv.circulations_communes
                         if cc.id.startswith("couloir") and cc.polygon_xy
                         and len(cc.polygon_xy) >= 3])
    if _corr.is_empty:
        continue
    # (a) walkable = couloir − cour − cage, hairlines pontées → composantes.
    _walk = _corr.difference(_cour_g)
    if not _cages.is_empty:
        _walk = _walk.difference(_cages.buffer(0.02))
    _walk = _walk.buffer(0.15).buffer(-0.15).buffer(0)
    _comps = [g for g in (_walk.geoms if _walk.geom_type == "MultiPolygon" else [_walk])
              if not g.is_empty and g.area > 2.0]
    # le hall d'entrée RDC (stub vers la rue) est un appendice légitime : on l'ignore en
    # gardant la composante PRINCIPALE + celles qui portent une porte d'entrée d'apt.
    _doors = _entry_door_segs(niv)
    if _comps:
        _main = max(_comps, key=lambda g: g.area)
        _door_comps = set()
        for _cid, _s in _doors:
            for _i, _cp in enumerate(_comps):
                if _cp.buffer(0.45).intersects(_s):
                    _door_comps.add(_i)
        _served_comps = [_comps[_i] for _i in _door_comps] or [_main]
        # (a) toutes les portes desservies par UNE SEULE composante.
        if len(_door_comps) > 1:
            _courconn_ko.append((f"R+{niv.index}",
                                 f"couloir SCINDÉ en {len(_door_comps)} morceaux par la "
                                 f"cour (portes d'apt sur des tronçons déconnectés)"))
        # (b) chaque porte touche le walkable.
        _stranded = [cid for cid, s in _doors
                     if not any(cp.buffer(0.45).intersects(s) for cp in _comps)]
        if _stranded:
            _courconn_ko.append((f"R+{niv.index}",
                                 f"{len(_stranded)} porte(s) d'apt isolée(s) du couloir "
                                 f"par la cour ({', '.join(_stranded[:4])})"))
    else:
        _courconn_ko.append((f"R+{niv.index}", "aucun couloir walkable (cour en travers)"))
    # (c) cour ∩ lanes de couloir réservées = 0.
    _apts_niv = unary_union([Polygon(c.polygon_xy) for c in niv.cellules
                             if c.type == CelluleType.LOGEMENT and c.polygon_xy
                             and len(c.polygon_xy) >= 3])
    if not _apts_niv.is_empty:
        from shapely.geometry import box as _bxg
        _mort = _bxg(*_apts_niv.bounds).difference(_apts_niv.buffer(0.02)).buffer(0)
        _mort = max((g for g in (_mort.geoms if _mort.geom_type == "MultiPolygon"
                                 else [_mort])),
                    key=lambda g: g.area if g.bounds[3] > _apts_niv.bounds[3] - 10 else 0,
                    default=_mort)
        if _mort.geom_type == "Polygon" and not _mort.is_empty:
            _chb = _mort.buffer(-1.6).buffer(1.6)
            if _chb.geom_type == "MultiPolygon":
                _chb = max(_chb.geoms, key=lambda g: g.area)
            _armz = _mort.difference(_chb.buffer(0.05)).buffer(0)
            _arml = [g for g in (_armz.geoms if _armz.geom_type == "MultiPolygon"
                                 else [_armz]) if g.area > 2.0]
            if not _chb.is_empty and _arml:
                _lx0, _ly0, _lx1, _ly1 = _chb.bounds
                _lanez = []
                for _arm in _arml:
                    _a0, _b0, _a1, _b1 = _arm.bounds
                    if (_a1 - _a0) >= (_b1 - _b0):
                        _cyv = (_b0 + _b1) / 2
                        _lanez.append(_bxg(_lx0 - 0.5, _cyv - 0.7, _lx1 + 0.5, _cyv + 0.7))
                    else:
                        _cxv = (_a0 + _a1) / 2
                        _lanez.append(_bxg(_cxv - 0.7, _ly0 - 0.5, _cxv + 0.7, _ly1 + 0.5))
                _lanezu = unary_union(_lanez)
                _ov = _cour_g.intersection(_lanezu).area
                if _ov > 1.0:
                    _courconn_ko.append((f"R+{niv.index}",
                                         f"cour empiète {_ov:.0f} m² sur une lane de "
                                         f"couloir (bloque un bras de circulation)"))
_courconn_ko = sorted(set(_courconn_ko))
for _tag, _why in _courconn_ko:
    print(f"  H-COULOIR-CONNEXE : {_tag} {_why} = BLOQUANT")

# ── (ii) H-JARDIN-PROPRE : jardins RDC = POLYGONES ORTHOGONAUX PROPRES ET COMPACTS
#    (rectangle ou quasi, ≤ _JARD_VERTS_MAX sommets), 0 CHEVAUCHEMENT, 0 IMBRICATION.
#
# CONFORT DE L'HABITANT (user 2026-07-07 v15) : on abandonne l'égalité des aires (v14) qui
# produisait des jardins en escalier/bras enroulant le coin (16-18 sommets) = INHABITABLES.
# Chaque jardin est maintenant un RECTANGLE COMPACT devant le séjour → on REDURCIT le plafond
# de sommets à 6 (rectangle = 4, quasi-rect = ≤6). Contour ORTHOGONAL, 0 chevauchement, 0
# imbrication. La largeur mini ≥ 4 m est vérifiée par H-JARDIN-CONFORT. Universel.
_JARD_VERTS_MAX = 6    # rectangle compact (4) ou quasi (≤6) ; > = forme tordue/escalier
_jard_ko = []
_rdc = next((n for n in bm.niveaux
             if any(c.type == CelluleType.LOGEMENT for c in n.cellules)), None)
if _rdc is not None:
    _jards = []
    for c in _rdc.cellules:
        _j = getattr(c, "jardin_polygon_xy", None)
        if _j and len(_j) >= 3:
            _jards.append((c.id, Polygon(_j)))
    for _cid, _jp in _jards:
        _nv = len(_jp.exterior.coords) - 1
        if _nv > _JARD_VERTS_MAX:
            _jard_ko.append((_cid,
                             f"jardin trop dentelé ({_nv} sommets > {_JARD_VERTS_MAX})"))
        # contour orthogonal : chaque arête est H ou V (pas de diagonale sale)
        _coords = list(_jp.exterior.coords)
        _diag = 0
        for _k in range(len(_coords) - 1):
            _dx = abs(_coords[_k + 1][0] - _coords[_k][0])
            _dy = abs(_coords[_k + 1][1] - _coords[_k][1])
            if _dx > 0.15 and _dy > 0.15:
                _diag += 1
        if _diag > 0:
            _jard_ko.append((_cid, f"jardin non orthogonal ({_diag} arête(s) diagonale(s))"))
    for _i in range(len(_jards)):
        for _k in range(_i + 1, len(_jards)):
            _a = _jards[_i][1]; _bg = _jards[_k][1]
            if _a.intersection(_bg).area > 0.5:
                _jard_ko.append((f"{_jards[_i][0]}∩{_jards[_k][0]}",
                                 f"jardins se chevauchent ({_a.intersection(_bg).area:.1f} m²)"))
            if _a.buffer(-0.1).contains(_bg) or _bg.buffer(-0.1).contains(_a):
                _jard_ko.append((f"{_jards[_i][0]}/{_jards[_k][0]}",
                                 "jardin imbriqué dans un autre"))
for _tag, _why in _jard_ko:
    print(f"  H-JARDIN-PROPRE : {_tag} {_why} = BLOQUANT")

# ══ H-JARDIN-EXCLUSIF — 1 JARDIN ⇄ 1 APT (défaut user 2026-07-06) ═════════════════
# RÈGLE user : un jardin privatif appartient à UN SEUL logement. Aujourd'hui (v10/v11)
# un même rectangle-jardin frontait PLUSIEURS apts empilés (08+10, 05+06). BLOQUANT :
#   (a) chaque jardin RDC touche la FAÇADE COUR d'EXACTEMENT 1 apt (0 jardin frontant
#       ≥ 2 apts). On mesure le contact entre la frontière du jardin et la portion de
#       la frontière de CHAQUE apt qui donne SUR LA COUR (apt.boundary ∩ void), tol
#       0,15 m — un vrai jardin longe la façade de son apt sur > 0,5 m ; un rectangle à
#       cheval en toucherait deux.
#   (b) chaque apt RDC bordant la cour a SON jardin (0 apt-cour sans jardin).
#   (c) jardins disjoints (déjà couvert par H-JARDIN-PROPRE, revérifié ici).
# Le revert-test v10 (jardins partagés) FIRE sur (a) ET (b). BLOQUANT. Universel.
_jexc_ko = []
if _rdc is not None:
    from shapely.geometry import box as _boxJ2
    _mnx, _mny, _mxx, _mxy = FP_TRUE.bounds
    _voidJ = _boxJ2(_mnx, _mny, _mxx, _mxy).difference(FP_TRUE)
    if _voidJ.geom_type == "MultiPolygon":
        _voidJ = max(_voidJ.geoms, key=lambda g: g.area)
    _apts_rdc = [(c.id.split(".")[-1], Polygon(c.polygon_xy)) for c in _rdc.cellules
                 if c.type == CelluleType.LOGEMENT and c.polygon_xy and len(c.polygon_xy) >= 3]
    # façade cour de chaque apt = sa frontière qui donne sur le void.
    _apt_court_facade = {}
    for _aid, _ap in _apts_rdc:
        _seg = _ap.boundary.intersection(_voidJ.buffer(0.06))
        _apt_court_facade[_aid] = (_ap, _seg.length if not _seg.is_empty else 0.0)
    _JTOL = 0.15
    _jset = set()
    for _c in _rdc.cellules:
        if _c.type != CelluleType.LOGEMENT:
            continue
        _j = getattr(_c, "jardin_polygon_xy", None)
        if not (_j and len(_j) >= 3):
            continue
        _aid = _c.id.split(".")[-1]
        _jset.add(_aid)
        _jp = Polygon(_j)
        # (a) ATTRIBUTION PAR CONTACT PRIMAIRE (défaut user 2026-07-08). Dans un pavage EN
        #     MOULIN (pinwheel), le jardin d'un apt de coin longe forcément — sur une petite
        #     part d'arête PARTAGÉE de la cour — la façade d'un apt VOISIN (ex. le bord haut du
        #     jardin de 08 longe la façade sud de 06 sur ~4,5 m alors que son bord droit longe
        #     SA propre façade est sur ~6 m). Exiger « fronte EXACTEMENT 1 apt » casserait ce
        #     pavage propre. On attribue donc le jardin à l'apt de contact MAXIMAL (son
        #     propriétaire) : PASSE si l'owner = l'apt du jardin ET si aucun AUTRE apt n'a un
        #     contact COMPARABLE (≥ 70 % du contact de l'owner → ambiguïté réelle = jardin
        #     vraiment à cheval, le défaut v10). Universel.
        _fronts = []
        for _oid, _op in _apts_rdc:
            _fac = _op.boundary.intersection(_voidJ.buffer(0.06))
            if _fac.is_empty:
                continue
            _contact = _jp.boundary.buffer(_JTOL).intersection(_fac).length
            if _contact > 0.5:
                _fronts.append((_oid, round(_contact, 1)))
        if not _fronts:
            _jexc_ko.append((f"jardin {_aid}",
                             "ne fronte AUCUN apt (jardin orphelin)"))
        else:
            _fronts.sort(key=lambda t: -t[1])
            _owner, _oc = _fronts[0]
            # rival = apt dont le contact est QUASI ÉGAL au propriétaire (à 0,5 m près) : la
            # propriété est alors ambiguë (jardin vraiment à cheval 50/50 sur 2 apts empilés,
            # le défaut v10). Un contact d'arête de cour PARTAGÉE nettement plus court (le bord
            # du jardin de coin qui longe la façade du voisin perpendiculaire) N'EST PAS un
            # rival : le propriétaire reste sans ambiguïté celui de contact maximal.
            _rivals = [(o, c) for o, c in _fronts[1:] if c >= _oc - 0.5]
            if _owner != _aid:
                _jexc_ko.append((f"jardin {_aid}",
                                 f"contact primaire = apt {_owner} ({_oc} m) et non {_aid} "
                                 f"{_fronts}"))
            elif _rivals:
                _jexc_ko.append((f"jardin {_aid}",
                                 f"PARTAGÉ : owner {_owner} ({_oc} m) mais rival(s) "
                                 f"comparable(s) {_rivals} (≥70 % — à cheval)"))
    # (b) tout apt RDC bordant la cour (> 1 m de façade cour) doit avoir un jardin
    #     OU une loggia. HONNÊTETÉ GÉOMÉTRIQUE : au coin rentrant, un apt à façade cour
    #     ÉTROITE ne peut pas toujours obtenir un jardin propre ≥ _MIN_JARD sans chevaucher
    #     (aire max atteignable < seuil) ; il garde alors sa LOGGIA RDC. On n'exige donc un
    #     jardin QUE si l'apt n'a PAS de loggia au RDC. Aucun apt-cour ne reste sans l'un
    #     NI l'autre (jardin exclusif ou loggia).
    _loggia_rdc = set()
    for _c in _rdc.cellules:
        if _c.type == CelluleType.LOGEMENT and getattr(_c, "loggia", None) is not None:
            _loggia_rdc.add(_c.id.split(".")[-1])
    for _aid, (_ap, _flen) in _apt_court_facade.items():
        if _flen > 1.0 and _aid not in _jset and _aid not in _loggia_rdc:
            _jexc_ko.append((f"apt {_aid}",
                             f"borde la cour ({_flen:.1f} m) mais N'A NI jardin NI loggia"))
for _tag, _why in _jexc_ko:
    print(f"  H-JARDIN-EXCLUSIF : {_tag} {_why} = BLOQUANT")

# ══ H-JARDIN-CONFORT — JARDINS RDC PENSÉS POUR L'HABITANT (défaut user 2026-07-07 v15) ══
# RÈGLE user : on ABANDONNE l'égalité géométrique des m² (v14, qui produisait des jardins en
# escalier/bras enroulant le coin = INHABITABLES). PRINCIPE = se mettre à la place de l'habitant :
# chaque apt-cour sort de SON séjour DIRECTEMENT sur SON jardin (porte-fenêtre), un jardin
# COMPACT et USABLE (poser table + pelouse + arbre), jamais un bras d'herbe étroit. Taille
# PROPORTIONNÉE au logement (T2 petit, T4 grand) = naturel et accepté, PAS d'égalité stricte.
# BLOQUANT :
#   (a) chaque apt-cour (façade cour > 1 m) a EXACTEMENT 1 jardin privatif, DEVANT sa façade
#       (contact jardin↔façade-cour de SON apt > _MIN_CONTACT → accès direct depuis le séjour).
#   (b) forme PROPRE : ≤ 6 sommets (rectangle/quasi) — déjà H-JARDIN-PROPRE, revérifié.
#   (c) MIN-LARGEUR ≥ _MIN_W partout (aucun bras étroit) : la plus petite dimension de la bbox
#       du jardin ≥ 4 m. Un bras/escalier a une dimension < 4 m → FIRE.
#   (d) jardins DISJOINTS (déjà H-JARDIN-PROPRE, revérifié).
#   (e) plancher d'aire honnête : chaque jardin ≥ _MIN_JARD_GATE (usable). On ne DURCIT PLUS
#       l'égalité (ratio) ni « toute la cour allouée » (union ≥ 90 %) : l'user les a RETIRÉS.
#       Le RÉSIDU profond de la cour (fond de coin non atteignable devant sa façade) est
#       AUTORISÉ en ESPACE VERT COMMUN (niveau.jardin_commun_polygon_xy), pas un bras privé.
# Revert-test v14 (jardins en escalier 16-18 sommets, bras < 4 m) FIRE sur (b) [sommets > 6] ET
# (c) [min-largeur < 4 m]. Universel : dérivé des seules façades cour, aucun cas en dur. Le U
# (générateur de bandes de 4 m, _compute_jardin_polygons_u) garde un plancher d'aire plus bas.
_MIN_W = 4.0
_MIN_CONTACT = 0.8
if _is_l_mode:
    # SEUIL DURCI (défaut user 2026-07-08) : le partage ÉQUILIBRÉ du coin rentrant (5b,
    # extension en L de l'apt-cour vertical + plafond d'aire de l'apt horizontal) rend
    # DÉCENTS les DEUX apts qui se disputaient le coin (06 T3 ≈ 36 ; 08 T2 ≈ 34, contre
    # 22 en v15). On relève donc le plancher à 30 m² : tout jardin RDC de coin < 30 =
    # coin mal partagé (un apt étranglé). Le revert-test v15 (08 = 22) FIRE. BLOQUANT.
    _MIN_JARD_GATE = 30.0
else:
    _MIN_JARD_GATE = 20.0
_jconf_ko = []
if _rdc is not None:
    _jardin_areas = {}
    for _c in _rdc.cellules:
        if _c.type != CelluleType.LOGEMENT:
            continue
        _j = getattr(_c, "jardin_polygon_xy", None)
        if not (_j and len(_j) >= 3):
            continue
        _aid = _c.id.split(".")[-1]
        _jp = Polygon(_j)
        _jardin_areas[_aid] = _jp.area
        _b = _jp.bounds
        _minw = min(_b[2] - _b[0], _b[3] - _b[1])
        # (c) min-largeur ≥ 4 m (aucun bras/escalier étroit)
        if _minw < _MIN_W - 1e-6:
            _jconf_ko.append((f"jardin {_aid}",
                              f"min-largeur {_minw:.1f} m < {_MIN_W:.0f} m "
                              f"(bras étroit — jardin non usable)"))
        # (b) forme propre (revérif sommets)
        _nv = len(_jp.exterior.coords) - 1
        if _nv > 6:
            _jconf_ko.append((f"jardin {_aid}",
                              f"{_nv} sommets > 6 (forme tordue/escalier, pas compacte)"))
        # (e) plancher d'aire honnête
        if _jp.area < _MIN_JARD_GATE:
            _jconf_ko.append((f"jardin {_aid}",
                              f"{_jp.area:.0f} m² < {_MIN_JARD_GATE:.0f} m² (pas usable)"))
        # (a) accès direct : le jardin longe la façade cour de SON apt sur > _MIN_CONTACT
        _own = _apt_court_facade.get(_aid)
        if _own is not None:
            _apoly, _flen = _own
            _own_court = _apoly.boundary.intersection(COUR_B)
            _contact = (_jp.boundary.buffer(0.25).intersection(_own_court).length
                        if not _own_court.is_empty else 0.0)
            if _contact < _MIN_CONTACT:
                _jconf_ko.append((f"jardin {_aid}",
                                  f"contact façade-cour de son apt = {_contact:.1f} m "
                                  f"(< {_MIN_CONTACT} m — pas d'accès direct au séjour)"))
    # (a-bis) 0 apt-cour sans jardin (sauf s'il a une loggia RDC à la place)
    _loggia_rdc = {c.id.split(".")[-1] for c in _rdc.cellules
                   if c.type == CelluleType.LOGEMENT and getattr(c, "loggia", None) is not None}
    for _aid, (_ap, _flen) in _apt_court_facade.items():
        if _flen > 1.0 and _aid not in _jardin_areas and _aid not in _loggia_rdc:
            _jconf_ko.append((f"apt {_aid}",
                              f"borde la cour ({_flen:.1f} m) mais N'A NI jardin NI loggia"))
for _tag, _why in _jconf_ko:
    print(f"  H-JARDIN-CONFORT : {_tag} {_why} = BLOQUANT")

# ══ H-JARDIN-CONCORDE — JARDINS-COUR DE MÊME TYPOLOGIE = CONCORDANTS (défaut user 2026-07-08) ══
# RÈGLE user : deux (ou +) apts RDC de MÊME typologie qui bordent la MÊME cour doivent recevoir
# des jardins CONCORDANTS = (a) MÊMES DIMENSIONS (bbox axis-aligned : étendue x ET étendue y
# égales, tol 0,3 m) et (b) leurs ARÊTES PARALLÈLES ADJACENTES (les jardins côte à côte autour
# du coin) CALÉES sur la même ligne (tol 0,2 m). Résultat : une paire visuellement symétrique et
# propre (ex. 80 Héros : 05 & 10 T4 → 9×7=63 chacun, bords à x=9). BLOQUANT si un groupe de même
# typo a des dimensions différentes OU des arêtes adjacentes non alignées. Revert-test v17
# (05=9,5×6,84 ≠ 10=9,0×7,0, bords à x=9,5 vs x=9,0) FIRE. Universel (dérivé des typos + bbox
# réels, aucune coordonnée en dur). Ne concerne QUE les jardins RECTANGLES bordant la cour.
_jconc_ko = []
_DIM_TOL = 0.3
_ALIGN_TOL = 0.2
if _rdc is not None:
    # jardins-cour rectangles (aid → (typo, bbox)).
    _cg = {}
    for _c in _rdc.cellules:
        if _c.type != CelluleType.LOGEMENT:
            continue
        _j = getattr(_c, "jardin_polygon_xy", None)
        if not (_j and len(_j) >= 3):
            continue
        _aid = _c.id.split(".")[-1]
        # seulement les jardins qui bordent réellement la cour.
        if _aid not in _apt_court_facade:
            continue
        _jp = Polygon(_j)
        if _jp.is_empty or len(_jp.exterior.coords) - 1 != 4:
            continue
        _typ = str(getattr(_c, "typologie", "")).split(".")[-1]
        _cg[_aid] = (_typ, list(_jp.bounds))
    # groupe par typologie.
    from collections import defaultdict as _ddg
    _bytyp = _ddg(list)
    for _aid, (_typ, _bb) in _cg.items():
        _bytyp[_typ].append(_aid)
    for _typ, _aids in _bytyp.items():
        if len(_aids) < 2:
            continue
        # (a) mêmes dimensions bbox (étendue x et y).
        _dims = {a: (_cg[a][1][2] - _cg[a][1][0], _cg[a][1][3] - _cg[a][1][1]) for a in _aids}
        _wref = _dims[_aids[0]][0]
        _href = _dims[_aids[0]][1]
        for _a in _aids[1:]:
            _w, _h = _dims[_a]
            if abs(_w - _wref) > _DIM_TOL or abs(_h - _href) > _DIM_TOL:
                _jconc_ko.append((f"groupe {_typ}",
                                  f"jardins {_aids[0]} ({_wref:.1f}×{_href:.1f}) et {_a} "
                                  f"({_w:.1f}×{_h:.1f}) dimensions ≠ (tol {_DIM_TOL} m)"))
        # (b) arêtes parallèles adjacentes calées : pour chaque paire, la paire d'arêtes
        #     (V ou H) la plus proche doit être alignée (écart ≤ _ALIGN_TOL).
        for _ia in range(len(_aids)):
            for _ib in range(_ia + 1, len(_aids)):
                _A = _cg[_aids[_ia]][1]
                _B = _cg[_aids[_ib]][1]
                _cands = []
                for _ea, _eb, _ax in ((2, 0, "V"), (0, 2, "V"), (3, 1, "H"), (1, 3, "H")):
                    _cands.append((abs(_A[_ea] - _B[_eb]), _ea, _eb, _ax))
                _gap, _ea, _eb, _ax = min(_cands, key=lambda t: t[0])
                # paire côte à côte = arêtes adjacentes proches (< 2 m) mais non calées.
                if _gap > 2.0:
                    continue
                if _gap > _ALIGN_TOL:
                    _jconc_ko.append((f"groupe {_typ}",
                                      f"jardins {_aids[_ia]} et {_aids[_ib]} arêtes {_ax} "
                                      f"adjacentes non calées (écart {_gap:.2f} m "
                                      f"> {_ALIGN_TOL} m)"))
for _tag, _why in _jconc_ko:
    print(f"  H-JARDIN-CONCORDE : {_tag} {_why} = BLOQUANT")

# ══ PAVAGE MOULIN PROPRE — 3 CHECKS DURS (défaut user 2026-07-08, plan L 80 Héros v18) ══
# Défauts MESURÉS à corriger : (1) les 2 jardins T4 de coin (05 & 10) NE SE TOUCHAIENT PAS
# (2,00 m d'écart) ; (2) le COMMUN avait un BRAS de 1 m (11 sommets, forme en L, bande morte) ;
# (3) des bandes fines < 4 m traînaient. On ajoute 3 BLOQUANTS prouvés par revert-test :
#   • H-JARDIN-TOUCHE     : 2 jardins de MÊME typo CONCORDANTS bordant la cour SE TOUCHENT
#                           (distance ≤ 0,05 m — ils tournent autour du commun en moulin).
#   • H-JARDIN-COMMUN-NET : le jardin COMMUN est un RECTANGLE NET (≤ 6 sommets ET min-largeur
#                           bbox ≥ _MIN_W → aucun bras/renfoncement).
#   • H-JARDIN-NO-BANDE   : AUCUN jardin privatif NI le commun n'a de min-largeur < _MIN_W
#                           (aucune bande fine inutilisable).
# Universel : dérivé des typos + géométrie réelle, aucune coordonnée en dur.
_MIN_W_PAV = 4.0
_TOUCH_TOL = 0.05
_jtouch_ko = []
_jcommun_ko = []
_jbande_ko = []
if _rdc is not None:
    # jardins-cour rectangles bordant la cour, groupés par typo (réutilise _apt_court_facade).
    _pav = {}
    for _c in _rdc.cellules:
        if _c.type != CelluleType.LOGEMENT:
            continue
        _j = getattr(_c, "jardin_polygon_xy", None)
        if not (_j and len(_j) >= 3):
            continue
        _aid = _c.id.split(".")[-1]
        if _aid not in _apt_court_facade:
            continue
        _jp = Polygon(_j)
        if _jp.is_empty:
            continue
        _typ = str(getattr(_c, "typologie", "")).split(".")[-1]
        _pav[_aid] = (_typ, _jp)
    # ── H-JARDIN-TOUCHE : pour chaque groupe de même typo ≥ 2 (concordants), les jardins
    #    doivent se toucher DEUX À DEUX quand ils sont adjacents autour du coin (distance ≤ tol).
    #    On ne l'exige QUE pour la paire la plus proche du groupe (le moulin en fait tourner 2
    #    autour du commun) : au moins une paire du groupe se touche.
    from collections import defaultdict as _ddt
    _bytyp_t = _ddt(list)
    for _aid, (_typ, _jp) in _pav.items():
        _bytyp_t[_typ].append(_aid)
    for _typ, _aids in _bytyp_t.items():
        if len(_aids) < 2:
            continue
        _dmin = min(_pav[_aids[_i]][1].distance(_pav[_aids[_k]][1])
                    for _i in range(len(_aids)) for _k in range(_i + 1, len(_aids)))
        # On n'EXIGE le contact QUE pour une paire de MOULIN : deux jardins de même typo qui
        # tournent autour du commun (façades PERPENDICULAIRES, coins censés se rejoindre). On
        # le détecte par une distance min DÉJÀ FAIBLE (< _NEAR = 3 m : ils sont quasi accolés,
        # c'est le pinwheel). Deux jardins de même typo sur des façades OPPOSÉES/éloignées (ex.
        # un U : 2 T2 à 22 m) ne sont PAS une paire de moulin → on ne les force pas à se toucher.
        _NEAR = 3.0
        if _TOUCH_TOL < _dmin <= _NEAR:
            _jtouch_ko.append((f"groupe {_typ}",
                               f"jardins de moulin ne se touchent PAS "
                               f"(distance min {_dmin:.2f} m > {_TOUCH_TOL} m)"))
    # ── H-JARDIN-COMMUN-NET + NO-BANDE sur le commun.
    _commun_xy = getattr(_rdc, "jardin_commun_polygon_xy", None)
    if _commun_xy and len(_commun_xy) >= 3:
        _cp = Polygon(_commun_xy)
        _nvc = len(_cp.exterior.coords) - 1
        _cb = _cp.bounds
        _cminw = min(_cb[2] - _cb[0], _cb[3] - _cb[1])
        # RECT-RATIO = aire / aire-bbox : un rectangle NET vaut 1,0 ; un commun en L / à bras /
        # à renfoncement (v18 : aire 88 vs bbox 160 → 0,55) tombe nettement sous 0,90. C'est le
        # détecteur d'ARM robuste (indépendant du nb de sommets, attrape tout renflement).
        _bba = (_cb[2] - _cb[0]) * (_cb[3] - _cb[1]) or 1.0
        _rratio = _cp.area / _bba
        if _nvc > 6:
            _jcommun_ko.append((f"{_nvc} sommets > 6 (pas un rectangle net — bras/renfoncement)"))
        if _rratio < 0.90:
            _jcommun_ko.append((f"rect-ratio {_rratio:.2f} < 0,90 (bras/renfoncement — pas un "
                                f"rectangle net)"))
        if _cminw < _MIN_W_PAV - 1e-6:
            _jcommun_ko.append((f"min-largeur bbox {_cminw:.1f} < {_MIN_W_PAV:.0f} m"))
        # NO-BANDE : le commun ≥ _MIN_W partout.
        if _cminw < _MIN_W_PAV - 1e-6:
            _jbande_ko.append((f"commun min-largeur {_cminw:.1f} < {_MIN_W_PAV:.0f} m"))
    # ── H-JARDIN-NO-BANDE sur chaque jardin privatif.
    for _aid, (_typ, _jp) in _pav.items():
        _b = _jp.bounds
        _mw = min(_b[2] - _b[0], _b[3] - _b[1])
        if _mw < _MIN_W_PAV - 1e-6:
            _jbande_ko.append((f"jardin {_aid} min-largeur {_mw:.1f} < {_MIN_W_PAV:.0f} m"))
for _why in _jtouch_ko:
    print(f"  H-JARDIN-TOUCHE : {_why[0]} {_why[1]} = BLOQUANT")
for _why in _jcommun_ko:
    print(f"  H-JARDIN-COMMUN-NET : commun {_why} = BLOQUANT")
for _why in _jbande_ko:
    print(f"  H-JARDIN-NO-BANDE : {_why} = BLOQUANT")

# ── (iii) H-PORTES : chaque pièce a 1 porte vers l'INTÉRIEUR (le distributeur),
#    0 porte-sur-vide (segment qui ne borde pas ≥ 2 pièces), WC/SdB SANS porte sur
#    le couloir commun, exactement 1 PORTE_ENTREE par apt sur le couloir.
_portes_ko = []
_WET = {RoomType.SDB, RoomType.SALLE_DE_DOUCHE, RoomType.WC, RoomType.WC_SDB}
_NEED_DOOR = {RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP,
              RoomType.SDB, RoomType.SALLE_DE_DOUCHE, RoomType.WC, RoomType.WC_SDB,
              RoomType.CUISINE}


def _door_seg(cell, op):
    _w = next((w for w in (cell.walls or []) if w.id == op.wall_id), None)
    if _w is None:
        return None
    (ax, ay), (bx, by) = _w.geometry["coords"]
    _wl = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1.0
    _t = (op.position_along_wall_cm / 100.0) / _wl
    _hw = (op.width_cm / 100.0) / 2
    return _LnS2([
        (ax + (bx - ax) * max(0, _t - _hw / _wl), ay + (by - ay) * max(0, _t - _hw / _wl)),
        (ax + (bx - ax) * min(1, _t + _hw / _wl), ay + (by - ay) * min(1, _t + _hw / _wl)),
    ])


for niv in bm.niveaux:
    _apts = [c for c in niv.cellules if c.type == CelluleType.LOGEMENT]
    _corr = unary_union([Polygon(cc.polygon_xy).buffer(0)
                         for cc in niv.circulations_communes
                         if cc.polygon_xy and len(cc.polygon_xy) >= 3])
    for c in _apts:
        _rooms = c.rooms or []
        _int_segs = []
        _n_entry = 0
        for op in (c.openings or []):
            if op.type == OpeningType.PORTE_ENTREE:
                _n_entry += 1
                _s = _door_seg(c, op)
                if _s is not None and _corr and not _corr.buffer(0.4).intersects(_s):
                    _portes_ko.append((f"R+{niv.index}:{c.id}",
                                       "PORTE_ENTREE hors couloir commun"))
                continue
            if op.type != OpeningType.PORTE_INTERIEURE:
                continue
            _s = _door_seg(c, op)
            if _s is None:
                continue
            _int_segs.append(_s)
            # porte-sur-vide : borde < 2 pièces
            _mid = _s.interpolate(0.5, normalized=True)
            _bord = [r for r in _rooms if len(r.polygon_xy) >= 3
                     and Polygon(r.polygon_xy).buffer(0.22).contains(_mid)]
            if len(_bord) < 2:
                _portes_ko.append((f"R+{niv.index}:{c.id}",
                                   f"porte intérieure sur vide ({op.id}, borde {len(_bord)} pièce)"))
            # WC/SdB : pas de porte donnant sur le couloir commun
            if _corr and _corr.buffer(0.10).intersects(_s):
                _wet_here = [r for r in _bord if r.type in _WET]
                if _wet_here:
                    _portes_ko.append((f"R+{niv.index}:{c.id}",
                                       f"WC/SdB a une porte sur le couloir commun ({op.id})"))
        if _n_entry != 1:
            _portes_ko.append((f"R+{niv.index}:{c.id}",
                               f"{_n_entry} PORTE_ENTREE (attendu 1)"))
        # chaque pièce à desservir a-t-elle 1 porte ?
        for r in _rooms:
            if r.type not in _NEED_DOOR or len(r.polygon_xy) < 3:
                continue
            _bnd = Polygon(r.polygon_xy).boundary.buffer(0.15)
            if not any(_sg.intersection(_bnd).length >= 0.4 for _sg in _int_segs):
                _portes_ko.append((f"R+{niv.index}:{c.id}",
                                   f"pièce {r.type.value} sans porte vers l'intérieur"))
# n'affiche pas 400 lignes : on résume par (niveau,apt,motif) unique.
_portes_ko = sorted(set(_portes_ko))
for _tag, _why in _portes_ko[:20]:
    print(f"  H-PORTES : {_tag} {_why} = BLOQUANT")
if len(_portes_ko) > 20:
    print(f"  H-PORTES : … +{len(_portes_ko)-20} autres = BLOQUANT")

# bilan (2 méthodes concordantes attendues côté user ; ici la réplique FOCH)
try:
    import io
    import contextlib
    sys.path.insert(0, "../../refs/concept/nogent_80_heros_3_scenarios")
    with contextlib.redirect_stdout(io.StringIO()):
        from bilan_replica_foch import bilan
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bilan(round(shab * 0.7), round(shab * 0.3), t, "L")
    import re
    m = re.search(r"([\d.]+)% TTC", buf.getvalue())
    marge = float(m.group(1)) if m else None
    print(f"  bilan : {marge}% TTC" + ("  OK >12%" if marge and marge >= 12 else "  KO <12%"))
except Exception as e:
    marge = None
    print("  bilan indispo:", str(e)[:60])

montrable = (apt_ko == 0 and not mix_ko and not _h1cage_ko and vide_fp <= 2.0
             and _circ_ratio <= CIRC_MAX_PCT and not _big_pockets
             and _stair_block <= STAIR_MAX_M2
             and not _h4_ko and not _h5_ko and not _h8_ko
             and not _hpal_ko and not _hvide_ko and not _circ13_ko
             and not _cour_ko and not _courrect_ko and not _courconn_ko
             and not _cage_ko and not _atrium_ko and not _cagec_ko and not _jard_ko and not _jexc_ko
             and not _jconf_ko and not _jconc_ko
             and not _jtouch_ko and not _jcommun_ko and not _jbande_ko
             and not _portes_ko
             and (marge is None or marge >= 12))
print("=" * 64)
print("  MONTRABLE" if montrable else "  BLOQUANT — NE PAS MONTRER")
print("=" * 64)
sys.exit(0 if montrable else 1)
