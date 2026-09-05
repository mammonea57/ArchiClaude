"""Generate the static curation UI from the pool manifest.

Reads `refs/style_dataset/curate_pool/manifest.json` and writes
`refs/style_dataset/curate_pool/curate.html` — a single static page
the user opens directly in Chrome/Safari.

Features:
    - Grid of thumbnails (all manifest items)
    - Click thumbnail toggles ❤️ (selection persisted in localStorage)
    - Filters : aesthetic score min, search caption, hide/show selected
    - Click thumbnail again or hover → preview full-size in a sidebar
    - "Export selection" button downloads a JSON file with the picked ids
    - Counter shows N selected / N total

The user then runs `apply_curate_selection.py selection.json` to copy
their picks into `refs/style_dataset/manual_refs/`.

Usage:
    .venv/bin/python apps/render-service/scripts/generate_curate_ui.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POOL_DIR = REPO_ROOT / "refs" / "style_dataset" / "curate_pool"


HTML_TEMPLATE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>ArchiClaude — Curate LoRA refs</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0;
         background: #1a1a1c; color: #eee; }
  header { position: sticky; top: 0; background: #222; padding: 10px 18px;
           display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
           border-bottom: 1px solid #333; z-index: 10; }
  h1 { font-size: 16px; margin: 0; color: #f5f5f5; font-weight: 600; }
  input[type=text], input[type=number] {
    background: #2a2a2c; color: #eee; border: 1px solid #444; padding: 6px 10px;
    border-radius: 4px; font-size: 13px; }
  input[type=text] { width: 220px; }
  input[type=number] { width: 70px; }
  button { background: #ffcb05; color: #111; border: none; padding: 8px 14px;
           border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 13px; }
  button:hover { background: #fff200; }
  button.secondary { background: #3a3a3c; color: #eee; }
  button.secondary:hover { background: #4a4a4c; }
  .counter { font-weight: 600; color: #ffcb05; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
          gap: 8px; padding: 12px; }
  .card { position: relative; aspect-ratio: 1; overflow: hidden;
          border-radius: 6px; cursor: pointer; background: #2a2a2c;
          transition: transform 0.1s; }
  .card:hover { transform: scale(1.03); z-index: 2; }
  .card img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .card .score { position: absolute; top: 4px; left: 4px; background: rgba(0,0,0,0.7);
                 padding: 1px 6px; font-size: 11px; border-radius: 3px;
                 color: #ffcb05; font-weight: 600; }
  .card .pick { position: absolute; top: 4px; right: 4px; font-size: 22px;
                opacity: 0; transition: opacity 0.1s; line-height: 1; }
  .card.selected { outline: 3px solid #ffcb05; }
  .card.selected .pick { opacity: 1; }
  .card.hidden { display: none; }
  .empty { padding: 40px; text-align: center; color: #888; }
  .preview {
    position: fixed; right: 12px; top: 70px; width: 340px;
    background: #2a2a2c; border-radius: 6px; padding: 10px;
    display: none; z-index: 5; box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  }
  .preview img { width: 100%; border-radius: 4px; }
  .preview .caption { font-size: 11px; color: #aaa; margin-top: 6px;
                      max-height: 100px; overflow-y: auto; }
</style>
</head>
<body>
<header>
  <h1>ArchiClaude — Curate LoRA refs</h1>
  <input type="text" id="search" placeholder="Search caption…">
  <label>Min score
    <input type="number" id="minScore" value="0" min="0" max="10" step="0.1">
  </label>
  <label><input type="checkbox" id="onlySelected"> Only ❤️</label>
  <button class="secondary" id="clearSel">Clear selection</button>
  <button id="exportBtn">Export selection</button>
  <span class="counter"><span id="selCount">0</span> / <span id="totalCount">{{ TOTAL }}</span> selected</span>
</header>

<div class="grid" id="grid"></div>
<div class="empty" id="empty" style="display: none;">No matches.</div>

<div class="preview" id="preview">
  <img id="previewImg" src="">
  <div class="caption" id="previewCaption"></div>
</div>

<script>
const ITEMS = {{ ITEMS_JSON }};
const STORAGE_KEY = 'archfr_curate_selection_v1';

let selection = new Set();
try {
  selection = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
} catch (e) {}

const grid = document.getElementById('grid');
const empty = document.getElementById('empty');
const search = document.getElementById('search');
const minScore = document.getElementById('minScore');
const onlySelected = document.getElementById('onlySelected');
const selCount = document.getElementById('selCount');
const preview = document.getElementById('preview');
const previewImg = document.getElementById('previewImg');
const previewCaption = document.getElementById('previewCaption');

function render() {
  grid.innerHTML = '';
  const q = search.value.trim().toLowerCase();
  const ms = parseFloat(minScore.value || 0);
  const onlySel = onlySelected.checked;
  let visible = 0;
  for (const it of ITEMS) {
    const matchQ = !q || it.caption.toLowerCase().includes(q);
    const matchS = it.aesthetic_score >= ms;
    const matchSel = !onlySel || selection.has(it.id);
    if (!(matchQ && matchS && matchSel)) continue;
    visible++;
    const card = document.createElement('div');
    card.className = 'card' + (selection.has(it.id) ? ' selected' : '');
    card.dataset.id = it.id;
    card.innerHTML =
      '<img src="' + it.thumb + '" loading="lazy">' +
      '<div class="score">' + it.aesthetic_score.toFixed(1) + '</div>' +
      '<div class="pick">❤️</div>';
    card.addEventListener('click', () => toggleSel(it.id, card));
    card.addEventListener('mouseenter', () => showPreview(it));
    grid.appendChild(card);
  }
  empty.style.display = visible ? 'none' : 'block';
  selCount.textContent = selection.size;
}

function toggleSel(id, card) {
  if (selection.has(id)) {
    selection.delete(id);
    card.classList.remove('selected');
  } else {
    selection.add(id);
    card.classList.add('selected');
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...selection]));
  selCount.textContent = selection.size;
}

function showPreview(it) {
  preview.style.display = 'block';
  previewImg.src = it.full;
  previewCaption.textContent = 'aes ' + it.aesthetic_score.toFixed(1)
    + ' | ' + it.caption;
}

document.getElementById('clearSel').addEventListener('click', () => {
  if (!confirm('Clear all selections?')) return;
  selection.clear();
  localStorage.setItem(STORAGE_KEY, '[]');
  render();
});

document.getElementById('exportBtn').addEventListener('click', () => {
  const data = { selection: [...selection], exported_at: new Date().toISOString() };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'selection.json';
  a.click();
  URL.revokeObjectURL(url);
});

search.addEventListener('input', render);
minScore.addEventListener('input', render);
onlySelected.addEventListener('change', render);

render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-dir", type=Path, default=DEFAULT_POOL_DIR)
    args = ap.parse_args()

    manifest_path = args.pool_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Manifest not found : {manifest_path}")
        print("Run build_curate_pool.py first.")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    html = (
        HTML_TEMPLATE
        .replace("{{ TOTAL }}", str(len(manifest)))
        .replace("{{ ITEMS_JSON }}", json.dumps(manifest, ensure_ascii=False))
    )
    out_path = args.pool_dir / "curate.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ UI generated : {out_path}")
    print(f"   Open in browser : open '{out_path}'")
    print(f"   Total items     : {len(manifest)}")


if __name__ == "__main__":
    main()
