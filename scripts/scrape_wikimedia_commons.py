#!/usr/bin/env python3
"""Scraper Wikimedia Commons — acquisition de VRAIES PHOTOS d'architecture/rue
(Paris / Île-de-France) sous LICENCE PROPRE uniquement, pour le chantier
`refs/render_engine_rd/CHANTIER_controlnet_render2photo.md`.

Objectif : télécharger 3000-6000 images candidates (le filtre CLIP en aval, dans
`scripts/build_render2photo_dataset.py`, en gardera un sous-ensemble). On parcourt
des catégories Commons (+ sous-catégories profondeur 1-2), on filtre STRICTEMENT
la licence (CC0/CC-BY/CC-BY-SA/domaine public uniquement), on déduplique par sha1,
et on capture l'attribution obligatoire dans `_attribution.jsonl`.

Sortie :
  refs/style_dataset/commons_idf/<fichier>.jpg|png
  refs/style_dataset/commons_idf/_attribution.jsonl   (titre, auteur, licence, URL)
  refs/style_dataset/commons_idf/_state.json          (reprise : sha1 vus, catégories faites)

API MediaWiki polie : User-Agent contact, maxlag=5, pause, continuation,
reprise propre si coupé. Pas de parallélisme agressif.

Lance avec n'importe quel python ayant `requests` (ex. le venv render-service) :
  apps/render-service/.venv/bin/python scripts/scrape_wikimedia_commons.py [--target 4000] [--max-per-cat 1500]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "refs" / "style_dataset" / "commons_idf"
ATTR_PATH = OUT / "_attribution.jsonl"
STATE_PATH = OUT / "_state.json"

API = "https://commons.wikimedia.org/w/api.php"
UA = ("ArchiClaude-dataset-bot/1.0 (render2photo research; "
      "contact: mammonea57@gmail.com) requests/python")

# Catégories racines pertinentes (Paris / IDF / meulière / townhouses FR).
# On descend en sous-catégories jusqu'à DEPTH.
SEED_CATEGORIES = [
    "Buildings in Paris",
    "Streets in Paris",
    "Apartment buildings in Paris",
    "Facades in France",
    "Architecture of Île-de-France",
    "Buildings in Val-de-Marne",
    "Nogent-sur-Marne",
    "Maisons en meulière",
    "Streets in Île-de-France",
    "Townhouses in France",
    # élargissement raisonnable, même registre (rue/façade IDF + petite couronne)
    "Buildings in Hauts-de-Seine",
    "Buildings in Seine-Saint-Denis",
    "Streets in Val-de-Marne",
    "Haussmann architecture",
    "Houses in Île-de-France",
    # --- DENSIFICATION photo COULEUR moderne (2026-06) ---
    # Wiki Loves Monuments = gros volume CC-BY récent, photos couleur HD.
    "Images from Wiki Loves Monuments 2018 in France",
    "Images from Wiki Loves Monuments 2019 in France",
    "Images from Wiki Loves Monuments 2020 in France",
    "Images from Wiki Loves Monuments 2021 in France",
    "Images from Wiki Loves Monuments 2022 in France",
    "21st-century architecture in Paris",
    "Contemporary architecture in France",
    "Modern architecture in Paris",
    # Communes IDF nominatives (petite couronne, registre Nogent/voisines)
    "Vincennes",
    "Saint-Mandé",
    "Maisons-Alfort",
    "Joinville-le-Pont",
    "Le Perreux-sur-Marne",
    "Fontenay-sous-Bois",
    "Charenton-le-Pont",
    "Montreuil, Seine-Saint-Denis",
    "Boulogne-Billancourt",
    "Buildings in Boulogne-Billancourt",
    "Buildings in Vincennes",
    "Buildings in Montreuil (Seine-Saint-Denis)",
]
DEPTH = 2  # profondeur de descente dans les sous-catégories

# Requêtes de recherche full-text Commons (generator=search). Bien plus
# productif que de marcher des catégories-conteneurs vides : la recherche
# renvoie directement des fichiers pertinents en masse. On combine intitulé
# (titre/desc) + incategory pour cibler archi/rue Paris/IDF.
SEARCH_QUERIES = [
    'facade building Paris', 'immeuble Paris rue', 'rue Paris façade',
    'haussmannian building Paris', 'immeuble haussmannien',
    'apartment building Paris', 'street Paris buildings',
    'building Nogent-sur-Marne', 'Val-de-Marne immeuble rue',
    'maison meulière', 'meulière façade', 'pavillon meulière Île-de-France',
    'townhouse France facade', 'immeuble brique Paris',
    'rue Boulogne-Billancourt immeuble', 'Vincennes immeuble façade',
    'Saint-Maur immeuble rue', 'Charenton immeuble façade',
    'building Hauts-de-Seine street', 'Seine-Saint-Denis immeuble rue',
    'Île-de-France residential building street',
    'immeuble pierre de taille Paris', 'rue commerçante Paris façade',
    'building corner Paris street', 'facade brick apartment Paris',
    # --- DENSIFICATION couleur moderne : sources récentes + communes IDF ---
    'Wiki Loves Monuments France immeuble',
    'contemporary architecture Paris building',
    '21st century building Paris facade',
    'immeuble moderne Île-de-France rue',
    'immeuble Vincennes rue', 'rue Vincennes façade',
    'immeuble Saint-Mandé', 'Maisons-Alfort immeuble rue',
    'Joinville-le-Pont immeuble', 'Le Perreux-sur-Marne immeuble rue',
    'Fontenay-sous-Bois immeuble', 'Nogent-sur-Marne rue immeuble',
    'Charenton-le-Pont immeuble rue', 'Montreuil Seine-Saint-Denis immeuble rue',
    # mots-clés rue/contexte (pas que façade frontale)
    'avenue Paris immeubles', 'carrefour Paris immeuble',
    'street view Paris buildings', 'rue résidentielle Île-de-France',
    'boulevard Paris immeubles façade', 'place Paris immeubles',
]

# Filtre licence STRICT — seules ces familles sont acceptées.
ALLOWED_LICENSE_TOKENS = (
    "cc0", "cc-by", "cc by", "public domain", "publicdomain", "pd-",
)
# Rejet explicite (en plus de l'absence de match ci-dessus).
DENY_LICENSE_TOKENS = (
    "fair use", "fairuse", "non-free", "nonfree", "all rights reserved",
    "copyrighted", "noncommercial", "non-commercial", "nc-", "-nc",
)

ALLOWED_MIME = {"image/jpeg", "image/png"}
EXT_FOR_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}

# Rejet par mots-clés du titre (cartes/plans/logos/blasons/SVG-isés…).
TITLE_DENY = (
    "map", "plan ", "blason", "coat of arms", "logo", "diagram",
    "carte", "schéma", "schema", "icon", "flag", "drapeau", "armoiries",
    # archival / scans anciens (sépia / N&B) — on les évite à la source pour
    # densifier en photo COULEUR moderne. Le gate aval (build) reste la garde
    # finale, mais autant ne pas télécharger ces scans.
    "engraving", "gravure", "lithograph", "lithographie", "postcard",
    "carte postale", "drawing", "dessin", "estampe", "daguerreotype",
    "1850", "1860", "1870", "1880", "1890", "1900", "1910", "1920",
    "circa 18", "vers 18", "ancien plan",
)


def api_get(params, session, retries=5):
    """Appel API poli avec maxlag + backoff."""
    base = {"format": "json", "maxlag": "5"}
    base.update(params)
    for attempt in range(retries):
        try:
            r = session.get(API, params=base, timeout=60)
            if r.status_code == 200:
                data = r.json()
                if "error" in data and data["error"].get("code") == "maxlag":
                    wait = min(30, 5 * (attempt + 1))
                    print(f"    [maxlag] pause {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                return data
            elif r.status_code in (429, 503):
                wait = min(60, 10 * (attempt + 1))
                print(f"    [http {r.status_code}] pause {wait}s", flush=True)
                time.sleep(wait)
                continue
            else:
                print(f"    [http {r.status_code}] {r.text[:120]}", flush=True)
                return None
        except requests.RequestException as ex:
            wait = min(30, 5 * (attempt + 1))
            print(f"    [neterr] {ex} — pause {wait}s", flush=True)
            time.sleep(wait)
    return None


def get_subcategories(cat, session):
    """Sous-catégories directes de `cat` (sans le préfixe 'Category:')."""
    subs = []
    cont = {}
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{cat}",
            "cmtype": "subcat",
            "cmlimit": "500",
        }
        params.update(cont)
        data = api_get(params, session)
        if not data:
            break
        for m in data.get("query", {}).get("categorymembers", []):
            title = m["title"]
            if title.startswith("Category:"):
                subs.append(title[len("Category:"):])
        if "continue" in data:
            cont = data["continue"]
            time.sleep(0.3)
        else:
            break
    return subs


# NB : on n'effectue PAS de BFS complet d'abord (trop lent : des milliers de
# sous-catégories à explorer avant le moindre téléchargement). On utilise une
# file (cat, depth) et on EXPANSE PARESSEUSEMENT : chaque catégorie est scrapée
# immédiatement, puis ses sous-catégories (si depth < DEPTH) sont ajoutées en
# queue. Les téléchargements démarrent dès la 1re catégorie.


def license_ok(extmeta):
    """Vrai si la licence est CC0 / CC-BY / CC-BY-SA / domaine public.
    On lit plusieurs champs et on rejette tout ce qui est ambigu/non-libre."""
    def val(k):
        d = extmeta.get(k)
        return (d.get("value", "") if isinstance(d, dict) else "") or ""

    short = val("LicenseShortName").lower()
    lic = val("License").lower()
    usage = val("UsageTerms").lower()
    copyrighted = val("Copyrighted").lower()  # "True"/"False"
    blob = " ".join([short, lic, usage])

    # Rejet explicite des tokens non-libres.
    if any(tok in blob for tok in DENY_LICENSE_TOKENS):
        # 'copyrighted: true' seul n'est PAS rédhibitoire (CC-BY est copyrighted),
        # mais les tokens NC / fair use / all-rights le sont.
        return False
    # Accepte si un token libre apparaît.
    if any(tok in blob for tok in ALLOWED_LICENSE_TOKENS):
        return True
    # Domaine public souvent signalé par Copyrighted=False sans LicenseShortName.
    if copyrighted == "false":
        return True
    return False


def title_ok(title):
    t = title.lower()
    return not any(tok in t for tok in TITLE_DENY)


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"sha1_seen": [], "cats_done": []}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=4500,
                    help="nombre d'images à télécharger (cible)")
    ap.add_argument("--max-per-cat", type=int, default=1200,
                    help="plafond d'images par catégorie (diversité)")
    ap.add_argument("--min-width", type=int, default=1024,
                    help="largeur mini souhaitée (fallback 768)")
    ap.add_argument("--iiurlwidth", type=int, default=1280,
                    help="largeur de la vignette HD demandée à l'API")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    state = load_state()
    sha1_seen = set(state["sha1_seen"])
    cats_done = set(state["cats_done"])

    # nb déjà téléchargées sur disque (reprise)
    existing = sum(1 for p in OUT.glob("*")
                   if p.suffix.lower() in (".jpg", ".png"))
    downloaded = existing
    print(f"[commons] reprise : {downloaded} déjà sur disque, "
          f"{len(sha1_seen)} sha1 connus", flush=True)

    # compteurs mutables (partagés avec la closure process_page)
    ctr = {"dl": downloaded, "lic": 0, "mime": 0, "small": 0,
           "title": 0, "dup": 0}

    attr_f = ATTR_PATH.open("a")

    def process_page(page):
        """Traite une page imageinfo : filtres → téléchargement → attribution.
        Retourne True si téléchargée. Met à jour ctr & sha1_seen."""
        title = page.get("title", "")
        ii = page.get("imageinfo")
        if not ii:
            return False
        info = ii[0]
        mime = info.get("mime", "")
        sha1 = info.get("sha1", "")
        width = info.get("width", 0)
        extmeta = info.get("extmetadata", {}) or {}

        if mime not in ALLOWED_MIME:
            ctr["mime"] += 1; return False
        if not title_ok(title):
            ctr["title"] += 1; return False
        if sha1 and sha1 in sha1_seen:
            ctr["dup"] += 1; return False
        if not license_ok(extmeta):
            ctr["lic"] += 1; return False
        if width and width < 768:
            ctr["small"] += 1; return False

        dl_url = info.get("thumburl") or info.get("url")
        if not dl_url:
            return False
        ext = EXT_FOR_MIME.get(mime, ".jpg")
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in title.replace("File:", ""))[:90]
        out_path = OUT / f"{(sha1 or str(ctr['dl']))[:12]}_{safe}{ext}"
        if out_path.exists():
            if sha1:
                sha1_seen.add(sha1)
            ctr["dup"] += 1; return False

        try:
            resp = session.get(dl_url, timeout=90)
            if resp.status_code != 200 or len(resp.content) < 8000:
                return False
            out_path.write_bytes(resp.content)
        except requests.RequestException as ex:
            print(f"    !! dl {title[:40]}: {ex}", flush=True)
            return False

        if sha1:
            sha1_seen.add(sha1)

        def mval(k):
            d = extmeta.get(k)
            return (d.get("value", "") if isinstance(d, dict) else "") or ""

        attr_f.write(json.dumps({
            "file": out_path.name, "title": title,
            "author": mval("Artist"), "license": mval("LicenseShortName"),
            "license_url": mval("LicenseUrl"), "credit": mval("Credit"),
            "source_url": info.get("descriptionurl") or info.get("url"),
            "width": width,
        }, ensure_ascii=False) + "\n")
        attr_f.flush()

        ctr["dl"] += 1
        if ctr["dl"] % 50 == 0:
            print(f"    … {ctr['dl']} téléchargées (rej lic {ctr['lic']} "
                  f"dup {ctr['dup']} small {ctr['small']} mime {ctr['mime']})",
                  flush=True)
            state["sha1_seen"] = list(sha1_seen)
            save_state(state)
        return True

    try:
        # ---- PASSE 1 : recherche full-text (la plus productive) -------------
        for qi, q in enumerate(SEARCH_QUERIES):
            if ctr["dl"] >= args.target:
                break
            key = f"search::{q}"
            if key in cats_done:
                continue
            print(f"\n[search {qi+1}/{len(SEARCH_QUERIES)}] '{q}' "
                  f"(total dl {ctr['dl']}/{args.target})", flush=True)
            got = 0
            cont = {}
            while ctr["dl"] < args.target and got < args.max_per_cat:
                params = {
                    "action": "query", "generator": "search",
                    "gsrsearch": f"filetype:bitmap {q}",
                    "gsrnamespace": "6",  # File:
                    "gsrlimit": "100",
                    "prop": "imageinfo",
                    "iiprop": "url|extmetadata|sha1|size|mime",
                    "iiurlwidth": str(args.iiurlwidth),
                }
                params.update(cont)
                data = api_get(params, session)
                if not data:
                    break
                pages = data.get("query", {}).get("pages", {})
                for page in pages.values():
                    if ctr["dl"] >= args.target or got >= args.max_per_cat:
                        break
                    if process_page(page):
                        got += 1
                if "continue" in data:
                    cont = data["continue"]
                    time.sleep(0.4)
                else:
                    break
            cats_done.add(key)
            state["sha1_seen"] = list(sha1_seen)
            state["cats_done"] = list(cats_done)
            save_state(state)
            print(f"  → {got} pour cette requête", flush=True)

        # ---- PASSE 2 : marche de catégories (file paresseuse) ---------------
        from collections import deque
        queue = deque((c, 0) for c in SEED_CATEGORIES)
        queued = set(SEED_CATEGORIES)
        ci = 0
        while queue and ctr["dl"] < args.target:
            cat, cdepth = queue.popleft()
            if cdepth < DEPTH:
                for s in get_subcategories(cat, session):
                    if s not in queued:
                        queued.add(s)
                        queue.append((s, cdepth + 1))
                time.sleep(0.2)
            if cat in cats_done:
                continue
            ci += 1
            print(f"\n[cat {ci} | depth {cdepth} | queue {len(queue)}] "
                  f"Category:{cat} (total dl {ctr['dl']}/{args.target})",
                  flush=True)
            got = 0
            cont = {}
            while ctr["dl"] < args.target and got < args.max_per_cat:
                params = {
                    "action": "query", "generator": "categorymembers",
                    "gcmtitle": f"Category:{cat}", "gcmtype": "file",
                    "gcmlimit": "500",
                    "prop": "imageinfo",
                    "iiprop": "url|extmetadata|sha1|size|mime",
                    "iiurlwidth": str(args.iiurlwidth),
                }
                params.update(cont)
                data = api_get(params, session)
                if not data:
                    break
                pages = data.get("query", {}).get("pages", {})
                for page in pages.values():
                    if ctr["dl"] >= args.target or got >= args.max_per_cat:
                        break
                    if process_page(page):
                        got += 1
                if "continue" in data:
                    cont = data["continue"]
                    time.sleep(0.4)
                else:
                    break
            cats_done.add(cat)
            state["sha1_seen"] = list(sha1_seen)
            state["cats_done"] = list(cats_done)
            save_state(state)
            print(f"  → {got} de cette catégorie", flush=True)
    finally:
        attr_f.close()
        state["sha1_seen"] = list(sha1_seen)
        state["cats_done"] = list(cats_done)
        save_state(state)

    print(f"\n[commons] === FINI ===", flush=True)
    print(f"  téléchargées (total disque) : {ctr['dl']}", flush=True)
    print(f"  rejet licence non-libre     : {ctr['lic']}", flush=True)
    print(f"  rejet mime (svg/gif/…)      : {ctr['mime']}", flush=True)
    print(f"  rejet titre (map/logo/…)    : {ctr['title']}", flush=True)
    print(f"  rejet trop petit (<768)     : {ctr['small']}", flush=True)
    print(f"  rejet doublon sha1          : {ctr['dup']}", flush=True)
    print(f"  attribution → {ATTR_PATH}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
