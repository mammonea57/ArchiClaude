#!/usr/bin/env python3
"""Generate refs/renders/index.html from all PNG files in refs/renders/.

Filename convention:
    YYYY-MM-DD_HHMMSS_iter###_<blender|flux_finish>_<...>.png
or  YYYY-MM-DD_iter###_<...>.png  (manual persist)

The script groups iters and emits a card for each, sorted newest first.
A sidecar .meta.json file (same basename) can override label / description /
verdict ('ok' | 'mixed' | 'bug').
"""
from __future__ import annotations
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from html import escape

# Date en tête de nom (YYYY-MM-DD[_HHMMSS]) ou date compacte 202X MM DD en suffixe
# (ex. B_greenery_carrefour_haut_20260624.png). Sert au TRI CHRONOLOGIQUE réel :
# le tri par nom de fichier plaçait les rendus sans date en préfixe n'importe où.
_DATE_LEAD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:_(\d{2})(\d{2})(\d{2}))?")
_DATE_COMPACT = re.compile(r"(202\d)(0\d|1[0-2])([0-3]\d)")


def render_datetime(png: Path) -> datetime:
    """Date RÉELLE d'un rendu : parsée du nom si possible, sinon mtime fichier."""
    name = png.name
    m = _DATE_LEAD.match(name)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]),
                            int(m[4] or 0), int(m[5] or 0), int(m[6] or 0))
        except ValueError:
            pass
    m = _DATE_COMPACT.search(name)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(png.stat().st_mtime)
    except OSError:
        return datetime.min

RENDERS_DIR = Path(__file__).resolve().parent.parent / "refs" / "renders"
OUT_HTML = RENDERS_DIR / "index.html"

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1a1a1a; color: #eee; font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 24px; }
h1 { font-size: 22px; font-weight: 500; margin-bottom: 8px; }
h2 { font-size: 14px; font-weight: 500; margin: 24px 0 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
p { color: #aaa; margin-bottom: 24px; font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.card { background: #2a2a2a; border-radius: 8px; overflow: hidden; }
.card.bug { background: #2a1a1a; }
.card.ok { background: #1a2a1a; }
.card.mixed { background: #2a2a1a; }
.card img { width: 100%; display: block; cursor: zoom-in; }
.meta { padding: 12px 14px; font-size: 13px; line-height: 1.5; }
.label { font-weight: 700; font-size: 14px; margin-bottom: 4px; }
.desc { color: #aaa; font-size: 12px; }
.timestamp { color: #666; font-size: 10px; font-family: monospace; }
.verdict { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; margin-top: 6px; }
.v-bug { background: #5a2222; color: #faa; }
.v-ok { background: #225a22; color: #afa; }
.v-mixed { background: #5a4a22; color: #fda; }
.modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.95); z-index: 100; justify-content: center; align-items: center; cursor: zoom-out; }
.modal.open { display: flex; }
.modal img { max-width: 95%; max-height: 95%; }
"""

# Filename pattern: capture date, time (optional), iter, kind, rest
NAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:_(?P<time>\d{6}))?"
    r"(?:_iter(?P<iter>\d+))?"
    r"_(?P<kind>blender|flux_finish)?"
    r"(?P<rest>.*)\.png$"
)


def parse_render_name(name: str) -> dict:
    m = NAME_RE.match(name)
    if not m:
        return {"date": "?", "time": "", "iter": "?", "kind": "?", "rest": name, "raw": name}
    g = m.groupdict()
    g["raw"] = name
    g["time"] = g["time"] or ""
    g["iter"] = g["iter"] or ""
    g["kind"] = g["kind"] or "?"
    g["rest"] = (g["rest"] or "").lstrip("_").replace("_", " ")
    return g


def load_meta(png_path: Path) -> dict:
    meta_path = png_path.with_suffix(".meta.json")
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except Exception:
            return {}
    return {}


def render_card(png: Path) -> str:
    p = parse_render_name(png.name)
    meta = load_meta(png)
    # Verdict : UNIQUEMENT si un meta.json le déclare explicitement. On ne colore
    # plus « ok » (vert = réussi) par défaut — trompeur sur des rendus d'essai/debug.
    verdict = meta.get("verdict", "")
    low = png.name.lower()
    if not verdict and any(k in low for k in ("invente", "compare", "debug", "_ko", "fail")):
        verdict = "bug"
    if p["iter"]:
        label = meta.get("label", f"#{p['iter']} — {p['kind']} {p['rest']}".strip())
    else:
        label = meta.get("label", png.stem.replace("_", " "))
    dt = render_datetime(png)
    desc = meta.get("description", f"{png.parent.name}/{png.name}")
    img_src = png.relative_to(RENDERS_DIR).as_posix()  # inclut les sous-dossiers
    card_cls = f"card {escape(verdict)}" if verdict else "card"
    badge = (f'<span class="verdict v-{escape(verdict)}">{escape(verdict)}</span>'
             if verdict else "")
    return f"""
    <div class="{card_cls}">
      <img src="{escape(img_src)}" onclick="openModal(this.src)" loading="lazy">
      <div class="meta">
        <div class="label">{escape(label)}</div>
        <div class="desc">{escape(desc)}</div>
        <div class="timestamp">{escape(dt.strftime('%Y-%m-%d %H:%M'))} · {escape(img_src)}</div>
        {badge}
      </div>
    </div>
    """


def main() -> int:
    if not RENDERS_DIR.exists():
        print(f"!! renders dir does not exist : {RENDERS_DIR}", file=sys.stderr)
        return 1
    # Scan RÉCURSIF : inclut les rendus rangés en sous-dossiers (finals
    # nogent_B_canny_final/, ultimate_parisian_consistency/, POC_verdict/, …) qui
    # étaient INVISIBLES avec l'ancien glob plat. On écarte les doublons Finder
    # « … 2.png » et la vignette d'index.
    pngs = [p for p in RENDERS_DIR.rglob("*.png")
            if " 2.png" not in p.name and p.name not in ("index.png",)]
    if not pngs:
        print(f"!! no PNGs in {RENDERS_DIR}", file=sys.stderr)
        return 1

    # TRI CHRONOLOGIQUE RÉEL (demande user) : par date décroissante (nom sinon
    # mtime), puis GROUPÉ PAR JOUR — le jour le plus récent en haut. Fini le tri
    # par iter# qui mélangeait l'ordre.
    pngs.sort(key=render_datetime, reverse=True)
    by_day: "OrderedDict[str, list[Path]]" = OrderedDict()
    for png in pngs:
        day = render_datetime(png).strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(png)

    cards_html = ""
    for day, items in by_day.items():
        cards_html += f'<h2>{escape(day)} · {len(items)} rendu(s)</h2>\n<div class="grid">\n'
        for png in items:
            cards_html += render_card(png)
        cards_html += "</div>\n"
    iter_keys = by_day  # pour le message final (nb de groupes = nb de jours)

    history_link = ""
    history_md = RENDERS_DIR / "HISTORY.md"
    if history_md.exists():
        history_link = (
            f'<p>📜 Historique complet iters #200-254 (PNGs perdus au reboot 2026-05-08 mais '
            f'descriptions reconstituées) → <a href="HISTORY.md" style="color:#4af">HISTORY.md</a></p>'
        )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>ArchiClaude — historique renders</title>
<style>{CSS}</style>
</head>
<body>
<h1>ArchiClaude — historique renders persistant</h1>
<p>Auto-généré depuis <code>refs/renders/</code> ({len(pngs)} renders PNG).
Survit aux reboots. Re-générer manuellement avec <code>python3 scripts/gen_render_gallery.py</code>
(auto-régen après chaque modal run).</p>
{history_link}
{cards_html}
<div class="modal" id="modal" onclick="this.classList.remove('open')"><img id="modal-img"></div>
<script>
function openModal(src) {{
  const m = document.getElementById('modal');
  const img = document.getElementById('modal-img');
  img.src = src;
  m.classList.add('open');
}}
</script>
</body>
</html>"""

    OUT_HTML.write_text(html)
    print(f"✓ wrote {OUT_HTML} ({len(pngs)} renders, {len(iter_keys)} jours)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
