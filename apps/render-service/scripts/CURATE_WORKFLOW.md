# Workflow curation refs LoRA — `manual_refs/`

Système web local pour curer rapidement des centaines d'images sans naviguer un par un sur Architizer / Brick / MIR.

## Principe

```
LAION-Aesthetics  →  [Filter permissif: caption + score]  →  Pool 1000 imgs
                                                                      ↓
                                          curate.html (open in Chrome)
                                                                      ↓
                                          Click ❤️ on what you like
                                                                      ↓
                                          "Export selection" → selection.json
                                                                      ↓
                                          apply_curate_selection.py
                                                                      ↓
                                          refs/style_dataset/manual_refs/
                                                                      ↓
                                          LoRA training
```

## Étapes

### 1. Build le pool (5-15 min, gratuit)

```bash
cd ~/Desktop/ArchiClaude
apps/render-service/.venv/bin/python \
    apps/render-service/scripts/build_curate_pool.py --n=1000
```

Fetch 1000 images LAION-Aesthetics avec filters permissifs :
- Caption contient au moins un mot architectural (build, facad, exter, render, ...)
- Aesthetic score ≥ 5.8
- Pas de host stock photo blacklist (Shutterstock, iStock, ...)

Outputs :
- `refs/style_dataset/curate_pool/full/` — images 1024px max
- `refs/style_dataset/curate_pool/thumbs/` — vignettes 320×320
- `refs/style_dataset/curate_pool/manifest.json` — métadonnées

### 2. Generate l'UI

```bash
apps/render-service/.venv/bin/python \
    apps/render-service/scripts/generate_curate_ui.py
```

Crée `refs/style_dataset/curate_pool/curate.html`.

### 3. Open dans Chrome/Safari

```bash
open refs/style_dataset/curate_pool/curate.html
```

L'UI montre :
- Grille de 1000 vignettes
- **Click une vignette** → toggle ❤️ (selected)
- **Hover** → preview full-size dans la sidebar droite
- **Search caption** : ex "balcon", "brick", "modern"
- **Min score** : filter aesthetic score
- **Only ❤️** : voir seulement tes selections
- **Counter** en haut : N sélectionnées / 1000

Ta sélection est sauvegardée en localStorage — tu peux fermer/rouvrir, tout est conservé.

### 4. Export selection

Click le bouton jaune **"Export selection"** → télécharge `selection.json` dans `~/Downloads/`.

### 5. Apply la sélection

```bash
apps/render-service/.venv/bin/python \
    apps/render-service/scripts/apply_curate_selection.py \
    ~/Downloads/selection.json
```

Ça copie les ❤️ dans `refs/style_dataset/manual_refs/` avec :
- `<id>.jpg` — image full
- `<id>.txt` — caption sidecar (pour le LoRA training pickup)
- `<id>.meta.json` — source URL + license attribution

### 6. (Plus tard) Lance le LoRA training

Une fois 100-300 refs curées dans `manual_refs/` :
```bash
cd apps/render-service
.venv/bin/modal run src/modal_lora_endpoint.py train \
    --dataset-path refs/style_dataset/manual_refs \
    --output-name brick_tier_archviz_v1 \
    --epochs 10
```

Coût Modal A100 ~6h × $5.59/h = **~$33-50** (sur 5000 imgs) ou **~$10-15** si plus petit dataset (~250 imgs concentrés).

## Conseils curation

**Objectif** : 100-300 images **pertinentes** > 5000 mediocres. La qualité battent le volume pour le style LoRA.

**Cherche** :
- 🏠 Vue extérieure bâtiments collectifs / résidentiels
- 🌆 Skylines / quartiers urbains photoréalistes
- 🎨 Style Brick / MIR / Forbes Massie (lighting magique, color grading raffiné, atmosphère)
- 🪟 Détails façades (briques, verre, zinc, bois)

**Évite** :
- ❌ Intérieurs (kitchen, living room, bedroom)
- ❌ Portraits / personnes en gros plan
- ❌ Concept art fantasy / sci-fi stylisé
- ❌ Paysages purs sans bâtiment
- ❌ Watermarks visibles (Shutterstock devrait être déjà filtré)

## Refresh le pool (si tu veux plus de variété)

```bash
# Continue depuis le row 80,000 pour fresh content
apps/render-service/.venv/bin/python \
    apps/render-service/scripts/build_curate_pool.py \
    --n=500 --skip-rows=80000
```

Puis re-generate l'UI.

## Légalité

- **LAION-Aesthetics metadata** : CC-BY-4.0
- **Images individuelles** : droits original aux URL sources (varient)
- **Usage interne R&D** = fair use défendable EU
- **Output LoRA** = transformative ; renders finaux ≠ copies des sources
- Attribution conservée dans `<id>.meta.json` pour audit légal futur

## Troubleshooting

**Pool fetch lent** : LAION-Aesthetics est streamé depuis HuggingFace. Yield typique 1-3% (i.e. 1000 keepers nécessite ~50-100k rows scannés). Compter 5-15 min.

**Trop de bruit dans le pool** : ajuste les keywords dans `PERMISSIVE_KEYWORDS` ou `HARD_REJECT_CAPTION_TERMS` dans `build_curate_pool.py`.

**Pas assez d'images Brick-tier** : la curation manuelle finale est ta valeur ajoutée — LAION ne te donnera pas du MIR pur, tu sélectionneras les meilleurs candidates parmi 1000.

**Vraie quête Brick-tier** : exporte des screenshots manuels depuis Architizer/Dezeen/Brick.com (consultation perso fair use) → drop directement dans `manual_refs/<custom_name>.jpg` + sidecar `.txt` avec une caption descriptive. Pas besoin du flow curate_pool dans ce cas.
