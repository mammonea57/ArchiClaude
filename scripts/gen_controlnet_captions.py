#!/usr/bin/env python3
"""Génère metadata.jsonl (format diffusers ControlNet) à partir du manifest R2P.

Chantier : ControlNet "render exact -> photo" (refs/render_engine_rd/CHANTIER_*).

Le ControlNet SDXL training script attend des paires :
    {"image": "<photo couleur>", "conditioning_image": "<canny>", "text": "<caption>"}

On part du manifest (source de vérité, ~1796 paires valides 768²) — PAS du
contenu brut des dossiers images/canny qui contient ~5500 résidus non filtrés.

Captions : approche templates variés orientés domaine (Paris/IDF, archi/rue).
Fiable, déterministe, zéro dépendance modèle. On dérive la "famille" matière
(meulière / brique / pierre de taille / contemporain) depuis le nom de fichier
source quand c'est possible, sinon on tire aléatoirement (seedé) dans le pool
parisien générique. Toutes les captions commencent par "a real photograph of"
pour pousser le ControlNet du côté PHOTO (vs render/illustration) — c'est tout
l'objet du chantier.

Sortie : refs/render_engine_rd/dataset/metadata.jsonl avec des chemins RELATIFS
au dataset (images/xxx.jpg, canny/xxx.png) prêts à uploader sur le Volume Modal.

Usage :
    python3 scripts/gen_controlnet_captions.py
    python3 scripts/gen_controlnet_captions.py --limit 50   # sous-échantillon test
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "refs" / "render_engine_rd" / "dataset"
MANIFEST = DATASET / "manifest.jsonl"
OUT = DATASET / "metadata.jsonl"

# --- Vocabulaire domaine -----------------------------------------------------

# Matières détectées par mots-clés dans le nom de fichier source.
MATERIAL_HINTS = {
    "meuliere": ["meuliere", "meulière", "millstone"],
    "brick": ["brique", "brick", "rouge"],
    "haussmann": ["haussmann", "pierre de taille", "ashlar", "limestone"],
    "contemporary": ["contemporain", "modern", "verre", "glass", "neuf"],
}

# Phrases matière (le coeur sémantique).
MATERIAL_PHRASES = {
    "meuliere": [
        "honey-coloured millstone (meulière) facade",
        "warm millstone stone facade typical of the Paris suburbs",
        "meulière rubble-stone facade with brick window surrounds",
    ],
    "brick": [
        "red brick facade",
        "warm red brick apartment building facade",
        "brick facade with stone string courses",
    ],
    "haussmann": [
        "cut limestone Haussmann-style facade",
        "cream ashlar stone facade with wrought-iron balconies",
        "Parisian limestone facade with carved cornices",
    ],
    "contemporary": [
        "contemporary apartment building facade with large glazing",
        "modern residential facade with rendered panels and glass balconies",
        "clean contemporary facade with metal and glass",
    ],
    "generic": [
        "Parisian apartment building facade",
        "residential building facade in the Île-de-France region",
        "stone-and-brick apartment building facade",
        "typical Paris street building facade",
    ],
}

# Éléments architecturaux (mix).
ELEMENTS = [
    "balconies",
    "tall windows",
    "ground-floor shopfronts",
    "a zinc mansard roof",
    "wrought-iron railings",
    "stone cornices",
    "French casement windows",
    "a slate roof",
]

# Cadrage / contexte rue.
CONTEXT = [
    "seen from the street",
    "on a quiet residential street",
    "at a street corner",
    "along a tree-lined avenue",
    "in a dense urban block",
    "facing the sidewalk",
]

# Lumière / ambiance photographique.
LIGHT = [
    "soft daylight",
    "overcast daylight",
    "warm late-afternoon light",
    "clear blue-sky daylight",
    "diffuse morning light",
]

# Suffixe "vraie photo" — pousse vers le côté photographique.
PHOTO_TAIL = [
    "realistic architectural photography, sharp detail, natural colours",
    "documentary street photography, high detail, photorealistic",
    "professional real-estate photography, crisp textures",
    "candid urban photograph, fine grain, true-to-life lighting",
]


def detect_material(source: str) -> str:
    s = source.lower()
    for mat, hints in MATERIAL_HINTS.items():
        if any(h in s for h in hints):
            return mat
    return "generic"


def make_caption(rng: random.Random, source: str) -> str:
    mat = detect_material(source)
    mat_phrase = rng.choice(MATERIAL_PHRASES[mat])
    n_elem = rng.randint(1, 2)
    elems = ", ".join(rng.sample(ELEMENTS, n_elem))
    ctx = rng.choice(CONTEXT)
    light = rng.choice(LIGHT)
    tail = rng.choice(PHOTO_TAIL)
    return (
        f"a real photograph of a {mat_phrase} with {elems}, "
        f"{ctx}, {light}, {tail}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="ne garder que les N premières paires (0 = toutes)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not MANIFEST.exists():
        raise SystemExit(f"manifest introuvable : {MANIFEST}")

    rng = random.Random(args.seed)
    rows = []
    n_skipped = 0
    mat_counts: dict[str, int] = {}

    with MANIFEST.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = json.loads(line)
            # chemins manifest = "render_engine_rd/dataset/images/xxx" ;
            # on les rend relatifs au dataset -> "images/xxx".
            img_rel = re.sub(r"^.*?dataset/", "", m["image"])
            canny_rel = re.sub(r"^.*?dataset/", "", m["canny"])
            img_abs = DATASET / img_rel
            canny_abs = DATASET / canny_rel
            if not img_abs.exists() or not canny_abs.exists():
                n_skipped += 1
                continue
            mat = detect_material(m.get("source", "") + " " + img_rel)
            mat_counts[mat] = mat_counts.get(mat, 0) + 1
            caption = make_caption(rng, m.get("source", "") + " " + img_rel)
            # NB : la clé DOIT être "file_name" pour que le builder HF
            # `imagefolder` lie la ligne metadata à son image et la décode
            # dans une colonne `image` (que le script lit via --image_column
            # image). "conditioning_image" reste un chemin relatif que notre
            # patch du script caste ensuite en feature Image.
            rows.append({
                "file_name": img_rel,
                "conditioning_image": canny_rel,
                "text": caption,
            })

    if args.limit:
        rows = rows[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"écrit {len(rows)} paires -> {args.out}")
    print(f"paires ignorées (fichier manquant) : {n_skipped}")
    print(f"répartition matière : {mat_counts}")
    print("\nexemples de captions :")
    for r in rows[:3]:
        print(f"  - {r['text']}")


if __name__ == "__main__":
    main()
