# Chantier R&D — ControlNet "render exact → photo" (no-compromise 100/100)

But : un modèle qui, à partir de la STRUCTURE EXACTE de notre rendu Cycles (canny/depth),
produit une vraie PHOTO d'architecture — matière/lumière/grain photographiques TOUT EN
respectant les arêtes exactes. C'est le levier que le POC 2026-06-27 a identifié comme
LE verrou (cf. mémoire `poc_ceiling_modele_a_entrainer`). Aucun outil public ne le fait.

## Principe (recette ControlNet standard)
On NE part PAS de paires render↔photo (rares). On part de VRAIES PHOTOS d'archi : pour
chaque photo on dérive automatiquement sa carte de contrôle (canny + depth via DPT) →
paires (structure, photo). Le ControlNet apprend à reconstruire une photo à partir d'une
structure. À l'inférence on lui donne NOTRE canny (du rendu Cycles exact) → il pose la photo
sur notre géométrie. Spécialisé archi = sortie "vraie photo de rue/immeuble", pas illustration.

## Étapes
1. **DATASET (en cours)** — filtrer le corpus refs/style_dataset (~6400 imgs) pour ne garder
   que les VRAIES PHOTOS (CLIP zero-shot : "real photograph" vs "3D render/CGI/illustration").
   Cible : 2000-4000 photos archi/rue réelles, propres (pas de watermark/collage/UI). Pour
   chaque : dériver canny (cv2) + depth (DPT Intel/dpt-large) → dataset paires prêt à l'entraînement.
   Compléter si besoin par des sources photo licence-propre.
2. **ENTRAÎNEMENT** — option pragmatique d'abord : fine-tune / ControlNet-LoRA canny sur SDXL
   (plus tractable que FLUX-12B), sur le subset photo archi. Puis évaluer un ControlNet FLUX si
   le gain le justifie. Infra : modal_lora_endpoint.py / modal_controlnet_endpoint.py (A100-80GB).
3. **ÉVAL** — tester sur NOTRE canny (rendu Cycles B carrefour_haut) : la sortie est-elle (a) une
   vraie photo ET (b) géométriquement fidèle (arêtes respectées) ? Comparer au canny public actuel.
4. **BASE ~95%** (en appui, parallèle) — pousser la base Cycles (vrais assets foliage/voitures,
   cutouts photo personnes, displacement, objectif) pour minimiser ce que le modèle doit inventer.

## Coût/risque (à affiner après dataset)
- Dataset : ~$ faible (CLIP + DPT en batch sur Modal/local).
- Entraînement SDXL ControlNet : ~10-30k steps, A100, ~quelques $10aines-$100aines.
- FLUX ControlNet : nettement plus cher (12B). Décider selon le gain SDXL.
- Risque ML réel (convergence, overfit, fidélité arêtes) — itératif.

## Acquis POC réutilisés (base Cycles, modal_blender_endpoint.py)
verre miroir-ciel, AgX, DOF f/5.6, denoise OIDN, pierre bump+rough_var, assets procéduraux
(voiture car-paint, arbre tronc+amas), flag POC_NOENTOURAGE.

## Infra ENTRAÎNEMENT (2026-06-29)
- Dataset : `refs/render_engine_rd/dataset/` — 2045 paires valides 768² (manifest source de vérité ;
  les dossiers images/canny ont ~5500 résidus non filtrés, ignorés).
- Captions : `scripts/gen_controlnet_captions.py` → `dataset/metadata.jsonl` (format imagefolder
  diffusers : `file_name` / `conditioning_image` / `text`). Templates domaine, toutes en
  "a real photograph of ..." pour pousser vers PHOTO. Déterministe (seed 42), 0 dépendance modèle.
- Script train : `refs/render_engine_rd/train_scripts/train_controlnet_sdxl.py` = script OFFICIEL
  diffusers v0.32.0 + 1 patch ArchiClaude (cast colonne conditioning_image en feature Image, sinon
  `.convert("RGB")` casse car imagefolder ne décode que `file_name`).
- Endpoint Modal : `apps/render-service/src/modal_controlnet_train_endpoint.py`
  - `upload_cli` : pousse SEULEMENT les fichiers du metadata vers Volume `archfr-r2p-dataset`.
  - `smoke_cli` : 50 steps + 1 validation, récupère le PNG. Budget ~$2-4.
  - `train_cli` : run complet. Fine-tune À PARTIR de `diffusers/controlnet-canny-sdxl-1.0`
    (PAS from scratch), base SDXL + VAE fp16-fix, bf16, grad checkpointing, A100-80GB.
- Volumes : `archfr-r2p-dataset` (dataset), `archfr-r2p-ckpt` (checkpoints), `archfr-hf-cache` (modèles).
