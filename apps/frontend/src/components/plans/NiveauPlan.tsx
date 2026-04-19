"use client";

import type { BuildingModelNiveau, BuildingModelCellule } from "@/lib/types";

interface NiveauPlanProps {
  niveau: BuildingModelNiveau;
  footprintPolygon?: Array<[number, number]>;
  width?: number;
  height?: number;
}

const CELLULE_FILL: Record<BuildingModelCellule["type"], string> = {
  logement: "#cbe9da",
  commerce: "#fde68a",
  tertiaire: "#ddd6fe",
  parking: "#e5e7eb",
  local_commun: "#dbeafe",
};

const CELLULE_STROKE: Record<BuildingModelCellule["type"], string> = {
  logement: "#047857",
  commerce: "#b45309",
  tertiaire: "#6d28d9",
  parking: "#4b5563",
  local_commun: "#1d4ed8",
};

function bboxFromCellules(cellules: BuildingModelCellule[]): {
  minx: number; miny: number; maxx: number; maxy: number;
} | null {
  if (cellules.length === 0) return null;
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const c of cellules) {
    for (const [x, y] of c.polygon_xy) {
      if (x < minx) minx = x;
      if (y < miny) miny = y;
      if (x > maxx) maxx = x;
      if (y > maxy) maxy = y;
    }
  }
  return { minx, miny, maxx, maxy };
}

/** Render a floor plan as an SVG. Coordinates flipped on Y (SVG y grows down). */
export function NiveauPlan({ niveau, width = 600, height = 400 }: NiveauPlanProps) {
  const bbox = bboxFromCellules(niveau.cellules);

  if (!bbox) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg p-10 text-sm text-slate-400 border border-slate-100">
        Aucune cellule placée à ce niveau.
      </div>
    );
  }

  const padding = 20;
  const w = bbox.maxx - bbox.minx || 1;
  const h = bbox.maxy - bbox.miny || 1;
  const scale = Math.min((width - 2 * padding) / w, (height - 2 * padding) / h);

  // Map world (x, y) → SVG (x, height - y) (Y flip) with padding + centered scaling
  const project = (x: number, y: number): [number, number] => [
    padding + (x - bbox.minx) * scale,
    height - padding - (y - bbox.miny) * scale,
  ];

  const polyToPath = (coords: Array<[number, number]>): string => {
    if (coords.length === 0) return "";
    const [x0, y0] = project(coords[0][0], coords[0][1]);
    const rest = coords
      .slice(1)
      .map(([x, y]) => {
        const [px, py] = project(x, y);
        return `L ${px.toFixed(1)} ${py.toFixed(1)}`;
      })
      .join(" ");
    return `M ${x0.toFixed(1)} ${y0.toFixed(1)} ${rest} Z`;
  };

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="bg-white border border-slate-100 rounded-lg"
    >
      {/* Cellules */}
      {niveau.cellules.map((c) => {
        const [labelX, labelY] = (() => {
          let cx = 0, cy = 0;
          for (const [x, y] of c.polygon_xy) { cx += x; cy += y; }
          cx /= c.polygon_xy.length;
          cy /= c.polygon_xy.length;
          return project(cx, cy);
        })();
        return (
          <g key={c.id}>
            <path
              d={polyToPath(c.polygon_xy)}
              fill={CELLULE_FILL[c.type]}
              stroke={CELLULE_STROKE[c.type]}
              strokeWidth={1.5}
              fillOpacity={0.4}
            />
            {c.rooms.map((r) => (
              <path
                key={`${c.id}_${r.id}`}
                d={polyToPath(r.polygon_xy)}
                fill="none"
                stroke={CELLULE_STROKE[c.type]}
                strokeWidth={0.8}
                strokeOpacity={0.6}
                strokeDasharray="3 2"
              />
            ))}
            <text
              x={labelX}
              y={labelY}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={11}
              fontWeight={600}
              fill={CELLULE_STROKE[c.type]}
            >
              {c.typologie ?? c.type}
            </text>
            <text
              x={labelX}
              y={labelY + 12}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={9}
              fill="#475569"
            >
              {Math.round(c.surface_m2)} m²
            </text>
          </g>
        );
      })}
    </svg>
  );
}
