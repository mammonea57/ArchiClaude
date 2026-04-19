"use client";

import type { BuildingModelPayload } from "@/lib/types";

interface PlanMasseProps {
  bm: BuildingModelPayload;
  width?: number;
  height?: number;
}

type Coord = [number, number];

function coordsFromGeoJSON(geojson: unknown): Coord[] {
  // GeoJSON Polygon: { coordinates: [ [ [x,y], ... ] ] }
  if (!geojson || typeof geojson !== "object") return [];
  const coords = (geojson as { coordinates?: unknown }).coordinates;
  if (!Array.isArray(coords) || !Array.isArray(coords[0])) return [];
  const ring = coords[0] as unknown[];
  const out: Coord[] = [];
  for (const p of ring) {
    if (Array.isArray(p) && p.length >= 2 && typeof p[0] === "number" && typeof p[1] === "number") {
      out.push([p[0], p[1]]);
    }
  }
  return out;
}

function bbox(pts: Coord[]): { minx: number; miny: number; maxx: number; maxy: number } | null {
  if (pts.length === 0) return null;
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const [x, y] of pts) {
    if (x < minx) minx = x;
    if (y < miny) miny = y;
    if (x > maxx) maxx = x;
    if (y > maxy) maxy = y;
  }
  return { minx, miny, maxx, maxy };
}

export function PlanMasse({ bm, width = 600, height = 400 }: PlanMasseProps) {
  // Get parcelle from metadata if available, otherwise derive from BM.site
  const parcelle = coordsFromGeoJSON(bm.site?.parcelle_geojson);
  const footprint = coordsFromGeoJSON(bm.envelope?.footprint_geojson);

  const box = bbox([...parcelle, ...footprint]);
  if (!box) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg p-10 text-sm text-slate-400 border border-slate-100">
        Géométrie parcelle/bâtiment indisponible.
      </div>
    );
  }

  const padding = 30;
  const w = (box.maxx - box.minx) || 1;
  const h = (box.maxy - box.miny) || 1;
  const scale = Math.min((width - 2 * padding) / w, (height - 2 * padding) / h);

  const project = ([x, y]: Coord): Coord => [
    padding + (x - box.minx) * scale,
    height - padding - (y - box.miny) * scale,
  ];

  const toPath = (pts: Coord[]): string => {
    if (pts.length === 0) return "";
    const [p0x, p0y] = project(pts[0]);
    const rest = pts.slice(1).map((p) => {
      const [px, py] = project(p);
      return `L ${px.toFixed(1)} ${py.toFixed(1)}`;
    }).join(" ");
    return `M ${p0x.toFixed(1)} ${p0y.toFixed(1)} ${rest} Z`;
  };

  const [coreX, coreY] = project(bm.core.position_xy);
  const coreR = Math.sqrt(bm.core.surface_m2) * scale / 2;

  // North arrow in top-right
  const northX = width - 28;
  const northY = 28;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="bg-white border border-slate-100 rounded-lg"
    >
      {/* Parcelle */}
      {parcelle.length > 0 && (
        <path
          d={toPath(parcelle)}
          fill="#f8fafc"
          stroke="#94a3b8"
          strokeWidth={1.5}
          strokeDasharray="4 3"
        />
      )}
      {/* Footprint */}
      {footprint.length > 0 && (
        <path
          d={toPath(footprint)}
          fill="#cbd5e1"
          stroke="#334155"
          strokeWidth={2}
          fillOpacity={0.6}
        />
      )}
      {/* Core */}
      <circle cx={coreX} cy={coreY} r={coreR} fill="#ef4444" fillOpacity={0.3} stroke="#b91c1c" strokeWidth={1.5} />
      <text x={coreX} y={coreY} textAnchor="middle" dominantBaseline="middle" fontSize={9} fill="#7f1d1d">
        noyau
      </text>

      {/* Voirie label */}
      {bm.site.voirie_orientations[0] && (
        <text
          x={width / 2}
          y={height - 8}
          textAnchor="middle"
          fontSize={10}
          fill="#64748b"
        >
          Voirie : {bm.site.voirie_orientations.join(", ")}
        </text>
      )}

      {/* Labels */}
      <text x={padding} y={16} fontSize={11} fontWeight={600} fill="#334155">
        Plan de masse
      </text>
      <text x={padding} y={height - 8} fontSize={10} fill="#64748b">
        Parcelle {Math.round(bm.site.parcelle_surface_m2)} m² · Emprise {Math.round(bm.envelope.emprise_m2)} m²
      </text>

      {/* North arrow */}
      <g transform={`translate(${northX}, ${northY})`}>
        <polygon points="0,-10 4,4 0,1 -4,4" fill="#0f172a" />
        <text y={18} textAnchor="middle" fontSize={10} fill="#334155" fontWeight={600}>N</text>
      </g>
    </svg>
  );
}
