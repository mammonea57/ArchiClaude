"""ArchiClaude texture pipeline — Polyhaven-backed material library.

The flow :
  1. `library.py` declares MATERIAL_LIBRARY : our internal material names
     mapped to Polyhaven asset slugs + tiling/color hints.
  2. `download_polyhaven.py` (host script) downloads the maps to
     `textures_cache/<name>/` via the public Polyhaven REST API. No auth.
  3. `import_to_ue5.py` (UE5 Python script) imports the textures and
     creates a MaterialInstance at `/Game/AC/Materials/M_<name>` for each.
  4. `import_scene_to_ue5.py` then looks up `/Game/AC/Materials/M_<name>`
     and falls back to a flat color material when missing.
"""
