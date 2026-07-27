"""Plan du bâtiment en L d'ANGLE (branche double) — 80 rue des Héros, Nogent.

Forme VERROUILLÉE USER (2026-07-03, remplace le U) : L d'angle 2 branches.
  - 2 branches ÉPAISSES le long des 2 rues : NORD (rue de Plaisance) + EST (rue des Héros).
  - Jardin au FOND dans l'angle rentrant, contre les 2 mitoyens : OUEST + SUD (murs aveugles).
  - Emprise ~79% (void 18x16), R+5, cible mix 20/50/30.

Un footprint L d'angle (1 seul sommet rentrant) est routé NATIVEMENT par
`generate_building_model` -> `layout_dispatcher.classify_footprint_topology` == "L"
-> `layout_l.compute_l_layout` (openings/portes/fenêtres via build_walls_and_openings,
jardins, loggias déjà OK sur le chemin L). On ne réinvente rien.

Repère local axis-aligné : x=Est, y=Nord.
  - rue NORD  = arête du haut  (y = H)      -> voirie "nord"
  - rue EST   = arête de droite (x = W)      -> voirie "est"
  - mitoyen OUEST = arête de gauche (x = 0)  -> mur aveugle
  - mitoyen SUD   = arête du bas   (y = 0)   -> mur aveugle
  - jardin = angle rentrant au SUD-OUEST (x in [0,wv], y in [0,hv])

Usage : PYTHONPATH=. .venv/bin/python scripts/render_l_pipeline.py
"""
from uuid import uuid4

from shapely.geometry import Polygon, mapping

from core.feasibility.schemas import Brief
from core.building_model.pipeline import GenerationInputs
from core.plu.schemas import NumericRules

# ── Footprint L d'angle (branche double) ────────────────────────────────────
# bbox W(E-W) x H(N-S) ; branches épaisses dN (nord) / dE (est) ; jardin SW wv x hv.
# W37 H35 dN=dE=19 -> emprise 79.5% (1007 m²), void 18x16=288 m² (jardin au fond).
W, H = 37.0, 35.0
dN, dE = 19.0, 19.0
WV, HV = W - dE, H - dN            # 18 x 16 : jardin dans l'angle rentrant SO
PARCEL_SURFACE = 1266.0           # tènement réel (cadastre 3 lots)

# Contour CCW : void au SUD-OUEST, branches au NORD (haut) + EST (droite).
FP = [
    (0.0, HV),      # coin rentrant O (le long mitoyen ouest, sous la branche nord)
    (WV, HV),       # sommet RENTRANT (angle intérieur du L)
    (WV, 0.0),      # coin rentrant S (le long mitoyen sud, à gauche de la branche est)
    (W, 0.0),       # coin SE
    (W, H),         # coin NE (carrefour Plaisance x Héros)
    (0.0, H),       # coin NO
]
PARCEL = [(-4.0, -4.0), (W + 4.0, -4.0), (W + 4.0, H + 4.0), (-4.0, H + 4.0)]

fp = Polygon(FP)
parcelle = Polygon(PARCEL)


def build_inputs(project_id=None) -> GenerationInputs:
    return GenerationInputs(
        project_id=project_id or uuid4(),
        parcelle_geojson=mapping(parcelle),
        parcelle_surface_m2=PARCEL_SURFACE,
        # rues = NORD (Plaisance) + EST (Héros) ; O+S = mitoyens (murs aveugles)
        voirie_orientations=["nord", "est"],
        north_angle_deg=0.0,
        plu_rules=NumericRules(
            emprise_max_pct=80.0, hauteur_max_m=18.0, pleine_terre_min_pct=15.0,
            retrait_voirie_m=None, retrait_limite_m=0.0, stationnement_pct=100.0,
            hauteur_max_niveaux=6,
        ),
        zone_plu="UA1",
        # Brief calibré (2026-07-03) : le room-fitting downstream reclasse une
        # partie des slots larges vers T3 (attracteur). Sur-demander des grands
        # (T4/T5) + un peu de T1 compense → sortie réelle ≈ 18/56/26 (cible
        # 20/50/30, dans ±8). Cf. registre : la calibration mix passe par la
        # demande, pas par un mix "vrai" injecté tel quel.
        brief=Brief(destination="logement_collectif", cible_nb_logements=80,
                    mix_typologique={"T1": 0.02, "T2": 0.14, "T3": 0.54,
                                     "T4": 0.18, "T5": 0.12}),
        footprint_recommande_geojson=mapping(fp),
        niveaux_recommandes=6,
        hauteur_recommandee_m=18.0,
        emprise_pct_recommandee=79.0,
    )


if __name__ == "__main__":
    import asyncio
    from collections import Counter
    from core.building_model.pipeline import generate_building_model
    from core.building_model.layout_dispatcher import classify_footprint_topology
    from core.building_model.schemas import CelluleType
    from db.session import AsyncSessionLocal

    print(f"footprint L : emprise {fp.area:.0f} m² "
          f"({100*fp.area/PARCEL_SURFACE:.1f}%) | jardin {WV:.0f}x{HV:.0f}={WV*HV:.0f} m² "
          f"| topo={classify_footprint_topology(fp)}")

    async def _run():
        async with AsyncSessionLocal() as s:
            return await generate_building_model(build_inputs(), session=s)

    bm = asyncio.run(_run())
    logts = [c for niv in bm.niveaux for c in niv.cellules
             if c.type == CelluleType.LOGEMENT]
    per = [(n.index, sum(1 for c in n.cellules if c.type == CelluleType.LOGEMENT))
           for n in bm.niveaux]
    mix = Counter(str(getattr(c, "typologie", "?")).split(".")[-1] for c in logts)
    print("niveaux", len(bm.niveaux), "| logts/niveau", per, "| TOTAL", len(logts))
    print("mix", dict(mix))
