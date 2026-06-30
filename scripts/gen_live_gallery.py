#!/usr/bin/env python3
"""Generate refs/live_gallery.html — a curated, always-current gallery of the
renders I want to SHOW the user this session. Re-run after every new render to
update the page (the user just refreshes localhost:3010/live_gallery.html).

Served root = refs/  →  all <img src> are paths RELATIVE TO refs/.

Sections are scanned from disk so new PNGs appear automatically. Newest file
first within each section. A sidecar <basename>.note.txt (one line) overrides
the caption.
"""
from __future__ import annotations
import sys
from pathlib import Path
from html import escape

REFS = Path(__file__).resolve().parent.parent / "refs"

# (section title, glob relative to refs/, short section note)
SECTIONS = [
    ("🔬 2026-06-27 VERDICT POC — pourquoi 100% exact + 100% photo est IMPOSSIBLE avec le stack actuel", "renders/POC_verdict/4_canny040_PHOTO_mais_invente.png",
     "POC mene a terme. 4 preuves (dossier POC_verdict/) : (1) base Cycles photoreal SANS FLUX = archviz haut de gamme PAS photo ; (2) finish str0.32 = preserve mais pas photo ; (3) str0.45 = toujours archviz ; (4) canny cn0.40 = VRAIE PHOTO mais reinvente le batiment. => le modele FLUX+LoRA sait faire exact-archviz OU photo-derivee, jamais exact-photo. Le 100/100 exige d'ENTRAINER un modele/ControlNet dedie render->photo sur de vraies photos d'archi (le vrai levier, aucun outil public ne le fait). Voir aussi section PREUVE DU COMPROMIS ci-dessous."),
    ("⚖️ 2026-06-27 PREUVE DU COMPROMIS — pourquoi on plafonne (canny serre vs lache)", "renders/_compromis_preuve/cn040_REALISTE_mais_invente.png",
     "PIECE A CONVICTION. Meme base v5, on desserre le verrou canny : cn0.40 = QUASI VRAIE PHOTO (lumiere/matiere/rue credibles) MAIS FLUX a REINVENTE le batiment (fenetres/coin/toit/balcons changes) -> plus notre projet. A l'inverse cn0.70 (B v5 ci-dessous) = batiment EXACT mais look CGI. Le modele FLUX.1-dev+LoRA sait faire PHOTO **ou** EXACT, pas les deux a la fois. => le 100% exactitude + 100% realisme NE viendra PAS du reglage canny, mais d'une BASE 3D elle-meme photoreal (vrais PBR + vrais assets 3D entourage + path-tracing + vrai vitrage/reflets + DOF) ou le generatif devient optionnel. Cf. cn055_intermediaire.png + cn070_EXACT_mais_CGI.png."),
    ("🧱 2026-06-27 B v5 MATERIAUX+SOL (EXACT mais encore CGI) -> canny cn0.70 2K", "renders/nogent_B_contemporain/B_v5_materiaux_2k.png",
     "Correction des problemes v4 (3 agents + auto-inspection 2K zone par zone). MATERIAUX : pierre de facade TEXTUREE + normal map (grain+relief, fini le plastique lisse), vrai materiau VERRE (reflet Fresnel + teinte homogene, fini les fenetres opaques incoherentes), dallage+asphalte textures. LISERE JAUNE sous balcons = balcon_concrete creme-chaud sature par Filmic -> passe gris neutre = ELIMINE. SOL/VEG : buissons RETIRES du trottoir/dallage (batiment aligne 0m setback = pas de jardinet rue) -> cheminement 100% degage, vert porte par murets voisins + toit + cour. COUR : pelouse a plat + allee + 7 massifs alignes + 3 arbres (fini les gradins aleatoires). Restes : fenetres un peu inegales (qq panneaux frosted), garde-corps verre bleute sature, bacs bas un peu boxy, RDC sombre."),
    ("☀️ 2026-06-27 B v4 (avant correction materiaux/sol) -> canny 2K", "renders/nogent_B_contemporain/B_v4_photo_nogent_2k.png",
     "Gros saut effet-photo (3 agents + auto-inspection 2K + tuning). LUMIERE : HDRI ciel BLEU midi (qwantani) + soleil DIRECTIONNEL cote camera (eclaire le coin vu) energy 7.5 + fill 0.78 (face ombre deboubee, pas de noir) + ombres nettes -> vrai look photo ensoleille. VOISINS NOGENTAIS : toits PENTUS tuile/ardoise + cheminees, ~40% meuliere brune + chainages brique, ~40% creme, flèche d'eglise au fond. RUE INTIME : murets creme + grilles fer noir + portails + arbres de jardin debordants COTE VOISINS (zero devant notre facade). Bugs tues apres auto-inspection : paquet de voitures noir (3 sources -> 1) + pods (arbres devant facade retires). Restes : RDC un peu sombre, terrasses jardin droite un peu regulieres, fenetres encore sombres."),
    ("🏙️ 2026-06-26 B v3 AMBIANCE (avant lumiere photo) -> canny 2K", "renders/nogent_B_contemporain/B_contemp_v3_ambiance_2k.png",
     "Enrichissement du CONTEXTE autour (cadrage garde) par 3 agents : VOISINS = les 102 batiments BDTopo rendus en vrais immeubles nogentais (fenetres+toits differencies+palette creme/meuliere) -> presents des 2 cotes, plus de boites fantomes ; RUE = vraie chaussee du carrefour T + marquages + bordures + voitures garees en file ; ATMOSPHERE = brume blanche de l'horizon tuee (degrade anti-brume HDRI) -> voisins de fond visibles, 0% pixel crame. BUG corrige apres auto-inspection 2K : les 'pods' gris des balcons = arbres d'alignement devant la facade (blob au POV plongeant) -> retires, vert porte par haies basses + toit-terrasse. Resultat : scene de rue contextualisee, batiment contemporain propre. Restes : 1er plan central encore un peu plaza ; on peut ajouter des arbres d'encadrement EN FACE (devant voisins) plus tard."),
    ("✅ 2026-06-26 B CONTEMPORAIN v2 (bugs balcons/toiture/cage corriges, AVANT enrichissement contexte)", "renders/nogent_B_contemporain/B_contemporain_v2_clean_2k.png",
     "BUGS CORRIGES apres inspection detaillee : (1) masse brune devant la facade = arbres trop pres -> repousses au bord chaussee + espaces 12m (ponctuation, pas un mur) ; (2) souches/events en toiture -> boites-arbres supprimees, bacs bas + arbustes ronds ; (3) cage de poteaux noirs devant le RDC = grille fer retiree (n'a de sens que sur retrait jardin) + haie BASSE ; (4) bande brune 1er etage = jardinieres rue retirees (contemporain = balcons verre/metal nets) ; balcons affines 1.45->1.05. Resultat : facade contemporaine propre, toiture nette, RDC lisible. Residu mineur : 2-3 balcons gauche un peu 'pod' gris."),
    ("🏢 2026-06-25 B CONTEMPORAIN v1 (AVANT correction bugs) — arbres-mur + toiture stubs + cage RDC", "renders/nogent_B_contemporain/B_contemporain_canny_1024.png",
     "PIVOT design (user: 'trop haussmannien' + 'arbres partout aucun sens'). 3 agents : ARCHI -> toit-terrasse vegetalise + attique (PLUS de mansarde/lucarnes/corniche), grandes baies, balcons fins metal noir+verre, refends affines = contemporain franc comme les vrais voisins modernes (survey_0/9). PAYSAGE -> haies/arbres ORGANIQUES (fini les cubes facettes) + placement coherent (haie continue + arbres alignes, plus d'amas). VIE -> pietons naturels + velos + voitures en file + mobilier contemporain (bancs/abribus). Conformite OK (<=18m, attique dans gabarit, balcons tous etages, emprise solveur inchangee, marge preservee). Coche : contemporain, greenery sensee, vraie photo, atmosphere Nogent."),
    ("🆕🏢 2026-06-25 B CONTEMPORAIN 2K (detail net)", "renders/nogent_B_contemporain/B_contemporain_canny_2k.png",
     "Upscale Real-ESRGAN x2. Reste (honnete) : pile de balcons gauche un peu dense/sombre, qq souches d'events en toiture, fond droit un peu brumeux. Mais lit comme une vraie photo d'immeuble neuf contemporain nogentais."),
    ("🆕🏢 2026-06-25 Base Cycles CONTEMPORAINE (avant canny)", "renders/nogent_B_contemporain/B_contemporain_base_cycles.png",
     "Base 3D combinee 3 agents + eclairage : toit terrasse, grandes baies, balcons fins, haies+arbres alignes organiques, vie+mobilier. Comparer au mansarde haussmannien d'avant (sections B ENRICHIE / B PIERRE CLAIRE ci-dessous)."),
    ("🌿 2026-06-25 B ENRICHIE (mansarde, AVANT pivot contemporain) — base 4-agents -> canny cn0.70", "renders/nogent_B_enrichie/B_enrichie_canny_1024.png",
     "GROS saut : 4 agents paralleles ont enrichi la base (flare tue + pierre claire riche ; haies taillees le long des trottoirs + arbres qui ENCADRENT le carrefour ; passage zebre + lampadaires verts + gens proches + voitures garees ; facade rythmee par pilastres verticaux + attique en retrait = fini la caserne). Tout en GEOMETRIE -> le canny photographie sans inventer (vrais voisins gardes). Coche : pierre claire (atmosphere reelle), rue verte intime, vie, pas de flare, conformite (attique <=18m pas de penthouse, balcons tous etages). RESTE : a 2k les haies proxy cubent (facettes) -> adoucir la geometrie haie. Version 1024 lit plus naturel que la 2k pour les haies."),
    ("🆕🌿 2026-06-25 B ENRICHIE 2K (detail batiment net, mais haies facettees)", "renders/nogent_B_enrichie/B_enrichie_canny_2k.png",
     "Upscale Real-ESRGAN x2 : batiment tres net (pilastres, attique retrait, lampadaire vert col-de-cygne, balcons fins). MAIS les haies proxy boxy deviennent des blocs facettes a cette resolution. Prochain fix : geometrie haie plus organique (disques/irregularite) ou canny un peu plus lache sur la vegetation."),
    ("🆕🌿 2026-06-25 Base Cycles ENRICHIE (avant canny) — ce que les 4 agents ont construit", "renders/nogent_B_enrichie/B_enrichie_base_cycles.png",
     "Base 3D combinee des 4 agents : haies+arbres encadrants, vie au sol, facade pilastres+attique, lumiere sans flare. C'est ce que le canny verrouille. Comparer au monolithe nu d'avant (section B PIERRE CLAIRE ci-dessous)."),
    ("🪨 2026-06-24 B PIERRE CLAIRE — atmosphere REELLE Nogent + voisins/rue verrouilles (canny cn0.70)", "renders/nogent_B_creme/B_creme_canny_FINAL.png",
     "Correction majeure : brique ABANDONNEE (ne colle pas a la rue de Nogent, verifie Street View). Materiau = pierre claire creme. Polish CANNY cn0.70 = verrouille les VRAIS voisins cadastraux + le damier + la rue de la base => ZERO invention (fini les faux Haussmann du str0.55). Geometrie exacte, pas de penthouse. Restent (vie/lumiere, pas geometrie) : flare soleil droit trop fort, vie peu lisible depuis ce POV plongeant, lampadaires verts+marquages a renforcer dans la base."),
    ("📷 VRAIE RUE 80 Heros (Street View) — reference atmosphere & materiaux", "renders/nogent_B_creme/REAL_street_*.png",
     "La vraie rue : voisins en pierre/enduit CLAIR creme-blanc, balcons verre/metal noir fin, haies, quartier arbore. AUCUNE brique rouge. C'est la cible d'atmosphere a matcher (pas la cible interne brique, trompeuse)."),
    ("🪨 Base Cycles B pierre claire (avant canny) — ce que le canny verrouille", "renders/nogent_B_creme/B_base_creme_cycles.png",
     "Pierre claire + vrais voisins cadastraux + damier + voitures, en GEOMETRIE. Le canny photographie ca sans rien reinventer."),
    ("✅✨🌿 BEAU + VIVANT + CONFORME — B_MID (cn0.55 sweet spot, verifie toit+pied+vie)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/scenarios_BC/mid/B_MID_2048.png",
     "LE bon equilibre : base vie-bakee (gens/voitures/arbres/jardinieres en GEOMETRIE) -> SDXL cn0.55 (assez serre = PAS de penthouse ni recul invente, assez lache = beaute gardee) -> FLUX str0.55 -> ESRGAN. VERIFIE : toit mansarde sans penthouse, facade au nu, foule+cyclistes+arbres, golden hour riche. cn0.42=invente, cn0.60=mort/plat, cn0.55=le point juste. Cbis a refaire pareil. (B_GOOD cn0.60 = conforme mais mort ; v2_FINAL cn0.42 = beau mais penthouse illegal)."),
    ("❌ NON CONFORME (a ne PAS utiliser) — penthouse + jardin en recul INVENTES par FLUX", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/scenarios_BC/v2_flux/*_FINAL_2048.png",
     "Beaux MAIS non conformes : FLUX a invente un penthouse vitre habitable sur le toit (interdit >18m) + un jardin en recul devant (alignement force interdit). Notre geometrie de base est conforme ; ce sont les etages SDXL(cn0.42 trop lache)+FLUX qui ont embelli au-dela du legal. Contre-exemple = leçon."),
    ("⚠️ FLUX-CN canny — look photo MAIS geometrie qui ondule (REJETE par user : pas la qualite voulue)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/cn_depth/PHOTO_canny080_2048.png",
     "TENSION non resolue : canny cn0.80 = belle matiere photo mais facade ONDULE + RDC/damier deformes (invention geometrie). cn0.95-1.0 = geometrie droite mais look ILLUSTRATION. cn0.80@1536 = droite mais clay+sol rouge. Aucun reglage ne donne geometrie exacte + vraie photo => plafond stack auto (cf memoire mir-tier 75-82%)."),
    ("🏆🏆 archviz PHOTO-FINISH (rendu 3D haut de gamme, PAS une photo)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/mir/photofinish/final/20260623_184521_str015_s1810_r2048.png",
     "LE rendu final qualite magazine : esthetique MIR propre + Real-ESRGAN net + passe FLUX v5 str0.15 @2048 qui ajoute la MICRO-REALITE MATIERE (appareillage brique, variation tonale, profondeur fenetres) SANS regenerer + grade propre. Pipeline 5 etapes : SDXL base -> FLUX v5 str0.62 (MIR clean) -> ESRGAN x2 -> FLUX v5 str0.15 (matiere) -> grade. NB : str0.25 introduit des artefacts FLUX-@2048, rester a 0.15."),
    ("🏆 MIR + ESRGAN 2048 (avant passe micro-matiere)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/mir/MIR_str062_2048_esrgan.png",
     "Esthetique MIR propre + Real-ESRGAN x2 net. Bon, mais materiaux encore un peu uniformes/render. La passe FLUX str0.15 ci-dessus ajoute la micro-matiere photo. Version PRINT 4096² : MIR_str062_4096_esrgan.png."),
    ("✨ MIR-tier str0.62 1024 (avant upscale ESRGAN)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/mir/20260623_183326_str062_s1810_r1024.png",
     "Base propre studio archviz avant le upscale net. Prompt 'professional architectural visualization MIR studio, clean bright daylight, crystal clear sharp, hyperdetailed, magazine cover' SANS grain/feuilles/flou."),
    ("❌ REJETE — direction 'photo amateur' (grain/feuilles/flou)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/photoreal/PHOTO2_str072_s1810.png",
     "Mauvaise direction (feedback user) : snapshot a travers feuillage = flou + moche. On veut le STUDIO PROPRE Pinterest, pas le snapshot amateur. Garde comme contre-exemple."),
    ("❌ REJETE — upscale-refine 2048 (a perdu golden hour + rue vivante)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/postprod/20260623_175333_str030_s1810_r2048.png",
     "2048² plus net en pixels MAIS la passe FLUX str0.30 a regenere toute l'image : lumiere plate, rue vide, moins realiste. Garde comme contre-exemple. La netteté ne valait pas l'atmosphere perdue."),
    ("⭐ v5 str0.60 seed1810 BRUT (avant postprod)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/20260619_224401_str060_s1810.png",
     "Base SDXL Tile detaillee -> FLUX v5 (LoRA 96 refs pierre FR) strength 0.60 qui reecrit brique->pierre en gardant le detail photo. Avant postprod."),
    ("🧪 2026-06-19 PILOTE LoRA v5 — tous les essais (040 brique-base, 045/055/062 honey-base mou, 060 = gagnant)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_v5/*.png",
     "v5 = FLUX LoRA reentrainee avec 96 refs pierre francaise. 060 sur base SDXL detaillee = pierre + realisme (gagnant). 045/055/062 sur base honey plate = pierre mais mou. 040 = brique (garbage-in : base SDXL deja brique a strength faible)."),
    ("🎬 2026-06-11 REALISME MAX — pipeline complet Cycles golden + SDXL + FLUX + postprod (3 candidats)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/_final_candidates/postprod/*.png",
     "A = SDXL seul (meuliere honey fidele, realisme moyen+). B = +FLUX str0.40 (realisme MAX : lumiere photo, fenetres droites, plantes, rue vivante — MAIS facade brique : le dataset LoRA v3 n'a AUCUNE meuliere, 29 brick vs 9 stone). C = FLUX prompt 'stone'. Choix user requis ; fix durable = dataset v4 avec refs meuliere."),
    ("🏆🏆🏆🏆 2026-06-11 v6 — balcons TOUS etages rue+cour, fenetres variees, voisins differencies (124526)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_polish/20260611_124526_tile_cn042_s1810.png",
     "Feedback user integre : balcons filants a CHAQUE etage des 2 cotes, 3 gabarits de baies (noble/courant/attique), voisin droite = brique comme en vrai, voisinage multi-couleurs par hauteur BD TOPO, rue damiers+passants. Restent : jardinieres visibles, stores RDC, skyline voisins trop parisien."),
    ("🏆🏆🏆 2026-06-11 MEULIERE HONEY — POV iconique, batiment cible A (003913)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_polish/20260611_003913_tile_cn042_s1810.png",
     "Cible A atteinte : meuliere honey (base flat PC-dossier + tint honey $0), RDC commerce anthracite + vitrines, bandeaux, corniche, garde-corps fins, mansarde zinc + lucarnes, pan coupe, damiers, voisins reels habilles, rue trottoirs propres."),
    ("Iterations batiment 2026-06-11 (rejetees : rouge/blanc, parc sans voisins)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_polish/20260611_00[13]?3?_tile_cn042_s1810.png",
     "003232 = blanc + devantures rouges (prompt red brick a fui) ; 003732 = honey OK mais voisins remplaces par un parc (prompt sans 'surrounding houses') ; 001737 = premiere version POV iconique, brique rose."),
    ("🏆 2026-06-10 AERIEN — polish cn0.30 (223040 = ORIENTATION CORRIGEE cour sud, 221210 = cour cote rue REJETE)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/polish_real/20260610_22*_s1802.png",
     "Fix orientation : bati a l'alignement des 2 rues (NW+E), cour/jardins au coeur d'ilot SUD (verifie vs photo aerienne). Emprise 726m² (57%) conservee. Gaps : meuliere honey (sort blanc/rouge), voisins blancs a cn0.30 (enrichir la base)."),
    ("Base Cycles carrefour_haut (avant polish)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/REAL_A_carrefour_haut_cycles.png",
     "Base fidele : pan coupe, damiers en geometrie (pas prompt), voisins reels, roads z-fight fixe."),
    ("🛰️ AERIEN 3/4 — bases Cycles (v3 = fenetres visibles, v1 = horrible avant fix)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/REAL_A_aerial_cycles*.png",
     "v3/v2 = nouveau builder (L solveur, toits tri_cap, demolis filtres, jardins/balcons). v1 = ancienne extrusion 100% parcelle, conserve pour comparaison."),
    ("🆕🆕 LE PLUS RECENT — VRAIE PARCELLE, batiment NEUF (cn0.30)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/real_neuf/*.png",
     "Vraie parcelle fusionnee + polish NEUF. Batiment neuf brique, RDC commerce, angle propre. Reste: brique au lieu meuliere (biais LoRA), cadrage proche."),
    ("carrefour NEUF (base box striee — abandonne)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_neuf/*.png",
     "Ancienne base box : NEUF OK mais facade bois (base striee). Remplace par la vraie parcelle ci-dessus."),
    ("Base CONFORME — vrais voisins BDTopo (geometrie, avant polish)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_*VOISINS_cycles.png",
     "Base Cycles avec voisins reels. Boxes = proxy geo (le polish les rendra photoreal)."),
    ("Base eye-level rue (z=1.6m)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_EYELEVEL_cycles.png",
     "POV rue avec passage pieton attendu au premier plan + voisins en fond."),
    ("Sweep carrefour_se — BON POV (seed 1810)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/carrefour_polish/*.png",
     "POV Héros × Plaisance. cn0.42 = favori. MAIS faux voisins + passage piéton manquant (base nue polie)."),
    ("⚠️ BATIMENT clay (forme a corriger)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/building_clay_aerial.png",
     "Batiment seul. Defauts: murs stries (look hangar). A reprendre dans L_building_v2.py."),
    ("Voisins immédiats — ZOOM implantation (heights réels)", "renders/voisins_zoom_preview.png",
     "Crop ±70m sur le T-junction. Croix verte = parcelle. Chiffres = hauteur réelle BDTopo."),
    ("Voisinage réel BDTopo — vue large (preuve data)", "renders/test_jour4_ign_context_preview.png",
     "Empreintes voisins BDTopo (jaune) sur photo aérienne. Croix verte = parcelle 80 Héros."),
    ("Sweep corner zoomé — vieux (10 juin matin)", "concept/nogent_80_heros_3_scenarios/renders_blender_v2/_probe/polish_real/2026061?_1*_s1802.png",
     "POV corner abandonné. Garde pour memoire du sweep style cn0.30→0.42."),
    ("⬇️ REFERENCE seulement — 6 options FLUX v3 (8 juin, REJETE: hallucine)", "concept/nogent_80_heros_3_scenarios/renders_6options/*/render.png",
     "Anciens renders FLUX, beaux mais hallucinent l'archi → REJETES. Gardes tout en bas comme cible de qualite uniquement."),
]


def caption(p: Path) -> str:
    note = p.with_suffix(".note.txt")
    if note.exists():
        return note.read_text(encoding="utf-8").strip()
    return p.stem


def main() -> int:
    cards_html = []
    for title, glob, note in SECTIONS:
        if "*" in glob:
            base = REFS / glob.split("*")[0].rstrip("/")
            files = sorted(REFS.glob(glob), key=lambda x: x.stat().st_mtime, reverse=True)
        else:
            f = REFS / glob
            files = [f] if f.exists() else []
        if not files:
            continue
        cards_html.append(f"<h2>{escape(title)}</h2><p>{escape(note)}</p><div class='grid'>")
        for p in files:
            rel = p.relative_to(REFS).as_posix()
            cards_html.append(
                f"<div class='card'><img src='{escape(rel)}' onclick=\"zoom(this.src)\">"
                f"<div class='meta'><div class='label'>{escape(caption(p))}</div>"
                f"<div class='timestamp'>{escape(rel)}</div></div></div>"
            )
        cards_html.append("</div>")

    html = f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>ArchiClaude — Live renders Nogent</title>
<style>
* {{ box-sizing: border-box; margin:0; padding:0; }}
body {{ background:#1a1a1a; color:#eee; font-family:-apple-system,BlinkMacSystemFont,sans-serif; padding:24px; }}
h1 {{ font-size:22px; font-weight:500; margin-bottom:4px; }}
.sub {{ color:#888; font-size:12px; margin-bottom:20px; }}
h2 {{ font-size:14px; font-weight:600; margin:28px 0 6px; color:#ddd; }}
p {{ color:#999; margin-bottom:12px; font-size:12px; }}
.grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }}
.card {{ background:#2a2a2a; border-radius:8px; overflow:hidden; }}
.card img {{ width:100%; display:block; cursor:zoom-in; }}
.meta {{ padding:10px 12px; }}
.label {{ font-weight:600; font-size:13px; margin-bottom:4px; }}
.timestamp {{ color:#666; font-size:10px; font-family:monospace; word-break:break-all; }}
.modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.95); z-index:100; justify-content:center; align-items:center; cursor:zoom-out; }}
.modal.open {{ display:flex; }}
.modal img {{ max-width:96%; max-height:96%; }}
</style></head><body>
<h1>ArchiClaude — Live renders Nogent 80 Héros</h1>
<div class='sub'>Régénéré à chaque rendu. Rafraîchis la page (⌘R) pour voir le dernier. Clique une image pour zoomer.</div>
{''.join(cards_html)}
<div class='modal' id='m' onclick='this.classList.remove("open")'><img id='mi'></div>
<script>
function zoom(s){{document.getElementById('mi').src=s;document.getElementById('m').classList.add('open');}}
</script></body></html>"""

    out = REFS / "live_gallery.html"
    out.write_text(html, encoding="utf-8")
    n = html.count("class='card'")
    print(f"✓ {out} written ({n} images)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
