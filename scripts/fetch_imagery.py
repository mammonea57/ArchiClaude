#!/usr/bin/env python3
"""Fetch Google Street View / satellite imagery on demand, save PNG, print path.

REFERENCE/VIEWING ONLY — never for 3D reconstruction (Google ToS). The 3D
geometry source stays IGN BDTopo. This just lets Claude *look* at the real site.

API key resolution (first found wins):
  1. env GOOGLE_MAPS_API_KEY
  2. ~/.config/archiclaude/gmaps_key   (single line)
  3. .env in repo root containing GOOGLE_MAPS_API_KEY=...

Usage:
  python scripts/fetch_imagery.py streetview <lat> <lng> [heading] [pitch] [fov] [label]
  python scripts/fetch_imagery.py aerial     <lat> <lng> [zoom] [label]
  python scripts/fetch_imagery.py check       <lat> <lng>      # free metadata: imagery exists?

Output: refs/streetview/<label-or-coords>_<kind>.png
"""
from __future__ import annotations
import os
import sys
import json
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "refs" / "streetview"


def get_key() -> str:
    k = os.environ.get("GOOGLE_MAPS_API_KEY")
    if k:
        return k.strip()
    cfg = Path.home() / ".config" / "archiclaude" / "gmaps_key"
    if cfg.is_file():
        return cfg.read_text().strip()
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("GOOGLE_MAPS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("!! No API key. Set GOOGLE_MAPS_API_KEY env, or ~/.config/archiclaude/gmaps_key, or .env")


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def main() -> int:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    kind, lat, lng = sys.argv[1], sys.argv[2], sys.argv[3]
    key = get_key()
    OUT.mkdir(parents=True, exist_ok=True)
    base = "https://maps.googleapis.com/maps/api"

    if kind == "check":
        url = f"{base}/streetview/metadata?location={lat},{lng}&key={key}"
        meta = json.loads(_fetch(url))
        print(json.dumps(meta, indent=2))
        return 0

    if kind == "streetview":
        heading = sys.argv[4] if len(sys.argv) > 4 else "0"
        pitch = sys.argv[5] if len(sys.argv) > 5 else "0"
        fov = sys.argv[6] if len(sys.argv) > 6 else "90"
        label = sys.argv[7] if len(sys.argv) > 7 else f"{lat}_{lng}_h{heading}"
        # metadata first (free) — confirm imagery exists, avoids a grey "no imagery" image
        meta = json.loads(_fetch(f"{base}/streetview/metadata?location={lat},{lng}&key={key}"))
        if meta.get("status") != "OK":
            sys.exit(f"!! No Street View imagery here (status={meta.get('status')})")
        q = urllib.parse.urlencode({"size": "640x640", "location": f"{lat},{lng}",
                                    "heading": heading, "pitch": pitch, "fov": fov, "key": key})
        data = _fetch(f"{base}/streetview?{q}")
        out = OUT / f"{label}_sv.png"
    elif kind == "aerial":
        zoom = sys.argv[4] if len(sys.argv) > 4 else "19"
        label = sys.argv[5] if len(sys.argv) > 5 else f"{lat}_{lng}_z{zoom}"
        q = urllib.parse.urlencode({"center": f"{lat},{lng}", "zoom": zoom, "size": "640x640",
                                    "maptype": "satellite", "key": key})
        data = _fetch(f"{base}/staticmap?{q}")
        out = OUT / f"{label}_aerial.png"
    else:
        sys.exit(f"!! unknown kind '{kind}' (streetview|aerial|check)")

    out.write_bytes(data)
    print(f"OK {len(data):,}B -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
