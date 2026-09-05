# Moteur de plans v2 — Architecture (refonte correct-by-construction)

Créé 2026-07-27. Branche `feat/plan-engine-cpsat`. Golden de repli : tag `plan-engine-golden-v46`.

## Le problème qu'on résout (audit 3-agents 2026-07-27)
Le moteur v1 est **sur-appris sur Nogent** : 6% de réussite premier-coup sur formes variées,
2 formes le font crasher (géométrie auto-sécante). Paradigme = **generate-then-repair** :
~30 passes correctrices empilées, horodatées par défaut vu à l'œil. Le gate `verify_plan.py`
(49 checks) contient DÉJÀ la spec du bon plan, mais il n'est PAS le moteur — le générateur
porte ses propres seuils, différents, synchronisés à la main → drift. Résultat : une semaine
de tâtonnement pour UN projet, et rien ne garantit le suivant.

## Le principe directeur : LES RÈGLES SONT LE MOTEUR
On inverse. Au lieu de « poser des pièces puis vérifier/réparer jusqu'à passer le gate », on
**place sous contraintes** : les règles deviennent les contraintes d'un solveur, la qualité
(surface utile, confort, beauté, rentabilité) devient la fonction objectif. **Un plan qui sort
du solveur est valide par construction.** Plus de rustines, plus de double source de vérité.

Vision user (2026-07-27) : le moteur doit produire un PROJET ENTIER *inrefusable* — juste
architecturalement ET urbanistiquement — conforme à la fois à nos règles, aux règles publiques
(PLU-i, servitudes, RE2020…), rentable (marge ≥12%), beau, dans les min/max constructibles.
La justesse n'est pas un contrôle a posteriori : elle est garantie par construction. C'est ce
qui rend le projet inrefusable pour le promoteur ET les services publics.

## Les 4 couches de contraintes (source unique = `constraints.py`)
Le point de bascule : UN module déclaratif, importé par le solveur ET le gate (qui devient un
simple ré-vérificateur de non-régression, plus un correcteur).

1. **Réglementaire dur (public)** — chambre ≥ 9 m² habitable (on vise 10,5), séjour ouvert,
   WC jamais sur cuisine, PMR/couloir ≥ 0,90/1,40, R.111-18 (6 m vue voisins), emprise PLU,
   hauteur, retraits, gabarit, RE2020… Non négociables : contraintes HARD.
2. **Produit / promoteur** — mix 20/50/30 (quota T3+ par commune, LLS), chambres cible ~12,
   séjour « de promoteur », balcons tous étages rue+cour, suite parentale, pas de cellier/vide.
   Certaines HARD (mix, LLS), d'autres SOFT (préférences dimensionnelles).
3. **Économique** — marge bilan ≥ 12% TTC (contrainte HARD bancaire), SHAB/SDP, nb logts.
4. **Objectif (à maximiser)** — surface utile vendable + confort habitant (lumière, largeur
   salon, vues, compacité service) + beauté (proportions, alignements) + rentabilité.

Tout seuil aujourd'hui codé en dur et DUPLIQUÉ (générateur `_SEJ_CAP=34` vs gate `CAP_SEJ=44`,
etc.) est extrait ici UNE fois, nommé, sourcé (loi vs préférence), et dérivable des entrées PLU.

## L'architecture cible (hybride)
```
footprint + PLU + parcelle + mix cible + marge cible
        │
        ▼
[1] OSSATURE (procédural généralisé, PAS un dispatcher L/U/other figé)
    footprint → décomposition en BANDES le long des façades-jour (squelette médial),
    placement noyau (cage+asc), couloir, découpe en SLOTS d'appartements.
    → marche pour L / U / T / rect / barre / oblique par UN algorithme, pas un handler par lettre.
        │  (slots + orientation-jour de chaque slot + contraintes héritées PLU/éco)
        ▼
[2] SOLVEUR APPARTEMENT (CP-SAT / OR-Tools, correct-by-construction)  ← LE CŒUR
    par slot : variables = position+taille de chaque pièce sur grille 25 cm.
    contraintes = traduction 1:1 de constraints.py (surfaces, jour, portes=adjacences,
    WC/SdB plaqués non-façade, tuilage=partition exacte, PMR).
    objectif = surface utile + confort (salon large, lumière) + compacité service.
    → remplace _layout_for_typology + _relayout_mono_facade_apts + _fill_intra_apt_pockets
      + les ~30 rustines. Résout un apt en dizaines de ms à qq s.
        │
        ▼
[3] LOGGIAS/BALCONS intégrés DANS le solveur (pas une passe _attach_balconies après coup
    qui écrase tout). Règle générale : apt d'angle (≥2 façades rue) → loggia par façade.
        │
        ▼
[4] GATE = ré-vérificateur de non-régression (49 checks), plus un correcteur.
    Sortie solveur DOIT passer le gate à 0 défaut sans une ligne de correction.
```

## Stratégie anti-tâtonnement : PoC AVANT la réécriture
On ne réécrit pas 6000 lignes en aveugle. On prouve le cœur d'abord, petit et jetable.
- **Phase 0** (fait) : backup golden (tag + archive), branche, cette archi.
- **Phase 1 — PoC solveur 1 apt** : CP-SAT sur UN slot rectangulaire → un T3 valide (chambres
  ≥10,5+jour, séjour, WC/SdB plaqués, portes, tuilage 100%) en < 1 s. Valide/invalide le
  paradigme pour un coût minime. **Go/No-Go ici.**
- **Phase 2** : `constraints.py` unique + solveur toutes typologies (T1→T5), objectif confort.
- **Phase 3** : ossature généralisée (décomposition bandes-jour) remplaçant le dispatcher.
- **Phase 4** : validation. (a) Nogent doit ressortir en passant le gate à 0 SANS rustine
  (le golden v46 est l'oracle). (b) 3-4 parcelles IDF jamais vues → 0 défaut premier coup.

## Métrique de succès NON NÉGOCIABLE
Générer un plan sur une parcelle **jamais bricolée** et passer `verify_plan` à **0 défaut sans
écrire une seule ligne de correction après coup**. Tant que ce test n'est pas vert, le moteur
reste « mémoïsé », pas « intelligent ». Aujourd'hui : 6% → cible : ~100% sur formes réglementaires.

## Ce qu'on garde de v1
- `verify_plan.py` : c'est la spec exécutable, réutilisée comme oracle + source des contraintes.
- L'ossature L/U (`layout_l.py`) : bonne base à généraliser, pas à jeter.
- Le plan Nogent v46 : golden test.
- `validator/conformite.py` : couche PLU/réglementaire à brancher dans constraints.py.

## Journal
- **2026-07-27** : backup golden (tag `plan-engine-golden-v46` + archive disque) OK.
  Branche `feat/plan-engine-cpsat` + cette archi OK.
  **BLOCKER PoC** : `from ortools.sat.python import cp_model` DEADLOCKE à l'import dans le
  venv backend (CPU ~0 = verrou, pas calcul ; confirmé hors sandbox). Cause quasi-certaine :
  conflit `ortools 9.15.6755` ↔ `protobuf 6.33.6` (le backend pousse protobuf haut pour une
  autre dép ; l'extension C++ d'OR-Tools attend un runtime protobuf différent).
  **FIX (prochaine étape)** : venv ISOLÉ pour le solveur (`python -m venv .venv_solver` +
  `pip install ortools shapely` seuls, protobuf tiré par ortools) → le solveur devient de toute
  façon un module découplé avec ses propres deps (bonne archi). Re-run `poc_solver_apt.py` dedans.
  Alternative si ortools reste capricieux sur macOS : valider le paradigme avec un solveur
  strip/guillotine maison (place par bandes façade) — moins général mais sans dépendance native.
  NB : la formulation "rectangles libres + exact-cover + multiplication" est trop lente même sur
  grille grossière → en prod, formuler en BANDES/guillotine (variables = cuts), naturellement
  exact-cover et rapide.

- **2026-07-27 (correctif diagnostic)** : le "deadlock ortools / conflit protobuf" noté plus
  haut était une MAUVAISE interprétation. Après reboot, `mds_stores` (Spotlight) réindexait le
  disque (load pic 63 ; `import numpy`=16 s, `import shapely`=23 s). Les imports de grosses libs
  natives (numpy/shapely/ortools) STALLENT sur l'I/O saturé, pas sur un conflit de deps.
  → RE-TESTER l'import ortools quand la machine est calme (load < 4) AVANT de conclure à un
  besoin de venv isolé. Le venv isolé reste une BONNE archi (module découplé) mais n'est
  peut-être pas nécessaire pour débloquer ortools.

- **2026-07-27 (PoC = GO ✅)** : diag ortools corrigé — l'import DEADLOCKE vraiment dans le
  venv BACKEND (60s+, CPU~0, même à froid load 3) à cause d'un CONFLIT DE PAQUET (symboles
  protobuf/grpc C++), PAS de la version protobuf ni du Spotlight. FIX = venv isolé
  `refs/plan_engine_v2/.venv_solver` (ortools+shapely+numpy seuls) → import OK (22s à froid),
  solve OK. Le solveur SERA un module découplé qui tourne dans ce venv (ou en sous-process).
  **PoC validé** : T3 dans slot 8×9 m, CP-SAT free-rectangles + no-overlap-2D + pièce
  "circ" qui absorbe le résidu → **tuilage 100%, 0,02 s**, séjour nez 3 m pleine profondeur,
  2 chambres éclairées (façade y=0), SdB/WC aveugles derrière. Correct-by-construction, 0 rustine.
  Leçons pour Phase 2 : (a) grille 50 cm trop grossière (chambre sortie à 2,5 m < seuil tunnel
  2,6 → passer à 25 cm) ; (b) exact-cover marche SI une pièce circulation absorbe le vide ;
  (c) la formulation free-rectangles est ASSEZ RAPIDE pour 1 apt (le "trop lent" d'avant était
  le Spotlight, pas la formulation) → pas besoin de guillotine ; (d) reste à ajouter :
  portes=adjacences, min-largeur en cellules = 2,6 m, H10 parents>enfant, objectif confort+valeur.
