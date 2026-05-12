"""Diagnose roof attique coverage."""
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.depth_map import _polygon_inset, _polygon_top_quads
from src.scene_mesh import clip_footprint_to_parcelle
from shapely.geometry import Polygon as ShPoly

with urllib.request.urlopen('http://localhost:8000/api/v1/projects/e9a960c8-081f-4c42-a65b-619610a61134/building_model') as r:
    bm = json.load(r)
m = bm['model_json']
fp = [(p[0], p[1]) for p in m['envelope']['footprint_geojson']['coordinates'][0]]
parc = [(p[0], p[1]) for p in m['site']['parcelle_geojson']['coordinates'][0][:-1]]
h = float(m['envelope']['hauteur_totale_m'])
def _ring_area(r):
    n=len(r); a=0.0
    for i in range(n):
        x1,y1=r[i]; x2,y2=r[(i+1)%n]
        a+=x1*y2-x2*y1
    return abs(a)/2
clipped = clip_footprint_to_parcelle(fp, parc)
fp_clipped = max(clipped, key=_ring_area)
print(f'clipped fp: {len(fp_clipped)} pts, area {ShPoly(fp_clipped).area:.1f} m²')

setback = _polygon_inset(fp_clipped, 1.5)
print(f'setback (attique inset 1.5m): {len(setback)} pts, area {ShPoly(setback).area:.1f} m²')
top_quads = _polygon_top_quads(setback, h)
print(f'top roof triangles: {len(top_quads)}')

def _tri_area(t):
    a, b, c = t.v0, t.v1, t.v2
    return abs((b[0]-a[0])*(c[1]-a[1]) - (c[0]-a[0])*(b[1]-a[1]))/2
covered = sum(_tri_area(t) for t in top_quads)
target = ShPoly(setback).area
print(f'top roof covered: {covered:.1f} m² / {target:.1f} m² target')
print(f'COVERAGE: {covered/target*100:.1f}%')
