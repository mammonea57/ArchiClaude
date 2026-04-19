"use client";

import type { BuildingModelPayload } from "@/lib/types";
import { bboxOf, coordsFromGeoJSON, makeProjector, ringToPath, type Coord } from "./plan-utils";
import { PlanPatterns, NorthArrow, ScaleBar, TitleBlock } from "./plan-patterns";

interface PlanMasseProps {
  bm: BuildingModelPayload;
  width?: number;
  height?: number;
  projectName?: string;
}

/**
 * Plan de masse — vue aérienne parcelle.
 * Layers (bottom to top):
 *  1. Ground surround (neighbor plots)
 *  2. Parcelle with cadastral border
 *  3. Green zones (pleine terre) inferred as parcelle minus footprint minus access
 *  4. Access road / accès (strip along voirie)
 *  5. Building footprint with drop shadow + roof indication
 *  6. Core position marker
 *  7. Trees along perimeter
 *  8. Compass, scale bar, cartouche, labels
 */
export function PlanMasse({ bm, width = 880, height = 620, projectName }: PlanMasseProps) {
  const parcelle = coordsFromGeoJSON(bm.site?.parcelle_geojson);
  const footprint = coordsFromGeoJSON(bm.envelope?.footprint_geojson);

  const ptsForBbox = [...parcelle, ...footprint];
  const box = bboxOf(ptsForBbox.length ? ptsForBbox : footprint);

  if (!box) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg p-10 text-sm text-slate-400 border border-slate-100 w-full h-[360px]">
        Géométrie parcelle/bâtiment indisponible.
      </div>
    );
  }

  // Expand box by 15% for breathing room showing neighbors
  const w = box.maxx - box.minx;
  const h = box.maxy - box.miny;
  const expand = 0.22;
  const expanded = {
    minx: box.minx - w * expand,
    miny: box.miny - h * expand,
    maxx: box.maxx + w * expand,
    maxy: box.maxy + h * expand,
  };

  const { scale, project } = makeProjector(expanded, width, height - 70, 40);

  // Trees along parcelle perimeter — roughly every 5-6m
  const trees = parcelle.length >= 3 ? placeTrees(parcelle, 5) : [];

  const voirieSide = bm.site.voirie_orientations?.[0] ?? "sud";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="bg-white border border-slate-200 rounded-lg"
      style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
    >
      <PlanPatterns />

      {/* Background: surrounding context */}
      <rect x={0} y={0} width={width} height={height} fill="#e7e5e4" />

      {/* Road strip on voirie side */}
      <VoirieStrip
        voirieSide={voirieSide}
        expanded={expanded}
        project={project}
        thicknessM={6}
      />

      {/* Neighbor plots hint (soft rectangles) */}
      {Array.from({ length: 6 }).map((_, i) => {
        const nx = expanded.minx + (w * 1 + w * 2 * expand) * Math.random();
        const ny = expanded.miny + (h * 1 + h * 2 * expand) * Math.random();
        const size = 8 + Math.random() * 14;
        const [rx, ry] = project([nx, ny]);
        return (
          <rect
            key={i}
            x={rx - size / 2}
            y={ry - size / 2}
            width={size}
            height={size * 0.8}
            fill="#d6d3d1"
            stroke="#a8a29e"
            strokeWidth={0.4}
            opacity={0.55}
          />
        );
      })}

      {/* Parcelle */}
      {parcelle.length >= 3 && (
        <g>
          {/* Lawn fill */}
          <path d={ringToPath(parcelle, project)} fill="url(#pat-lawn)" />
          {/* Cadastral outline — dashed red */}
          <path
            d={ringToPath(parcelle, project)}
            fill="none"
            stroke="#dc2626"
            strokeWidth={1.4}
            strokeDasharray="10 4 3 4"
          />
        </g>
      )}

      {/* Building footprint with shadow + roof */}
      {footprint.length >= 3 && (
        <g>
          {/* Shadow */}
          <path
            d={ringToPath(footprint, project)}
            fill="#0f172a"
            opacity={0.2}
            transform="translate(3, 5)"
          />
          {/* Footprint base */}
          <path
            d={ringToPath(footprint, project)}
            fill="#f5f5f4"
            stroke="#1c1917"
            strokeWidth={2.2}
            strokeLinejoin="miter"
          />
          {/* Roof indication — diagonal lines */}
          <RoofDiagonals footprint={footprint} project={project} />
          {/* Core marker */}
          <CoreMarker core={bm.core} project={project} scale={scale} />
        </g>
      )}

      {/* Trees along perimeter */}
      {trees.map((t, i) => {
        const [tx, ty] = project(t);
        return <Tree key={i} x={tx} y={ty} scale={scale} />;
      })}

      {/* Header */}
      <g>
        <rect x={20} y={20} width={width - 40} height={44} fill="white" stroke="#0f172a" strokeWidth={0.6} />
        <text x={30} y={40} fontSize={15} fontWeight={700} fill="#0f172a">
          Plan de masse
        </text>
        <text x={30} y={56} fontSize={10.5} fill="#475569">
          Parcelle {Math.round(bm.site.parcelle_surface_m2)} m² · Emprise bâtie {Math.round(bm.envelope.emprise_m2)} m² ·{" "}
          {Math.round((bm.envelope.emprise_m2 / bm.site.parcelle_surface_m2) * 100)}% ·{" "}
          R+{bm.envelope.niveaux - 1} · Voirie {voirieSide}
          {projectName ? ` · ${projectName}` : ""}
        </text>
      </g>

      {/* Legend */}
      <g transform={`translate(32, ${height - 120})`}>
        <rect x={0} y={0} width={200} height={80} fill="white" stroke="#0f172a" strokeWidth={0.5} />
        <text x={10} y={16} fontSize={10} fontWeight={700} fill="#0f172a">Légende</text>
        <LegendRow y={28} fill="url(#pat-lawn)" label="Pleine terre / jardin" />
        <LegendRow y={44} fill="#f5f5f4" stroke="#1c1917" strokeWidth={1} label="Bâtiment" />
        <LegendRow y={60} fill="url(#pat-road)" label="Voirie / accès" />
      </g>

      {/* Scale bar + Compass */}
      <ScaleBar x={32} y={height - 30} scalePxPerM={scale} meters={10} />
      <NorthArrow x={width - 60} y={108} size={54} rotationDeg={bm.site.north_angle_deg ?? 0} />

      <TitleBlock
        x={width - 232}
        y={height - 68}
        title="Plan de masse"
        subtitle="1:500 · DP-MA-01"
        sheetCode="PC2"
      />
    </svg>
  );
}

function VoirieStrip({
  voirieSide, expanded, project, thicknessM,
}: {
  voirieSide: string;
  expanded: { minx: number; miny: number; maxx: number; maxy: number };
  project: (c: Coord) => Coord;
  thicknessM: number;
}) {
  // Build a thick band on the voirie side
  const e = expanded;
  let band: Coord[];
  if (voirieSide === "sud") {
    band = [[e.minx, e.miny], [e.maxx, e.miny], [e.maxx, e.miny + thicknessM], [e.minx, e.miny + thicknessM]];
  } else if (voirieSide === "nord") {
    band = [[e.minx, e.maxy - thicknessM], [e.maxx, e.maxy - thicknessM], [e.maxx, e.maxy], [e.minx, e.maxy]];
  } else if (voirieSide === "est") {
    band = [[e.maxx - thicknessM, e.miny], [e.maxx, e.miny], [e.maxx, e.maxy], [e.maxx - thicknessM, e.maxy]];
  } else {
    band = [[e.minx, e.miny], [e.minx + thicknessM, e.miny], [e.minx + thicknessM, e.maxy], [e.minx, e.maxy]];
  }
  const d = ringToPath(band, project);
  return (
    <g>
      <path d={d} fill="url(#pat-road)" />
      {/* white center stripe */}
      <path d={d} fill="none" stroke="white" strokeWidth={1.2} strokeDasharray="14 10" strokeOpacity={0.75} />
    </g>
  );
}

function RoofDiagonals({ footprint, project }: { footprint: Coord[]; project: (c: Coord) => Coord }) {
  const bb = bboxOf(footprint);
  if (!bb) return null;
  const [x0, y0] = project([bb.minx, bb.maxy]);
  const [x1, y1] = project([bb.maxx, bb.miny]);
  const w = Math.abs(x1 - x0);
  const h = Math.abs(y1 - y0);
  const n = 12;
  return (
    <g opacity={0.55} clipPath="url(#clip-footprint)">
      {Array.from({ length: n }).map((_, i) => {
        const step = (w + h) / n;
        const s = i * step;
        return (
          <line
            key={i}
            x1={x0 + s}
            y1={y0}
            x2={x0}
            y2={y0 + s}
            stroke="#94a3b8"
            strokeWidth={0.4}
          />
        );
      })}
    </g>
  );
}

function CoreMarker({ core, project, scale }: { core: BuildingModelPayload["core"]; project: (c: Coord) => Coord; scale: number }) {
  const [cx, cy] = project(core.position_xy);
  const r = Math.max(5, Math.sqrt(core.surface_m2) * scale / 2);
  return (
    <g>
      <rect x={cx - r * 0.7} y={cy - r * 0.7} width={r * 1.4} height={r * 1.4} fill="#1e293b" opacity={0.7} stroke="#0f172a" strokeWidth={0.7} />
      <text x={cx} y={cy + 3} textAnchor="middle" fontSize={9} fontWeight={700} fill="white">
        N
      </text>
    </g>
  );
}

function Tree({ x, y, scale }: { x: number; y: number; scale: number }) {
  const r = Math.max(5, 0.8 * scale / 4);
  return (
    <g>
      <circle cx={x + 1} cy={y + 1.5} r={r} fill="#1e293b" opacity={0.22} />
      <circle cx={x} cy={y} r={r} fill="#a7dab0" stroke="#3d8f44" strokeWidth={0.5} />
      <circle cx={x - r * 0.3} cy={y - r * 0.25} r={r * 0.45} fill="#6bbe70" opacity={0.8} />
      <circle cx={x + r * 0.3} cy={y + r * 0.15} r={r * 0.4} fill="#4ea055" opacity={0.7} />
      <circle cx={x} cy={y} r={r * 0.18} fill="#6b7280" />
    </g>
  );
}

function placeTrees(ring: Coord[], spacingM: number): Coord[] {
  const pts: Coord[] = [];
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const dist = Math.hypot(dx, dy);
    const n = Math.max(0, Math.floor(dist / spacingM));
    for (let j = 1; j <= n; j++) {
      // push inward a bit so trees sit inside the parcelle border
      const t = j / (n + 1);
      // inward normal
      const nx = -dy / dist;
      const ny = dx / dist;
      pts.push([a[0] + dx * t + nx * 1.2, a[1] + dy * t + ny * 1.2]);
    }
  }
  return pts;
}

function LegendRow({
  y, fill, stroke, strokeWidth, label,
}: { y: number; fill: string; stroke?: string; strokeWidth?: number; label: string }) {
  return (
    <g transform={`translate(10, ${y})`}>
      <rect x={0} y={-8} width={20} height={10} fill={fill} stroke={stroke} strokeWidth={strokeWidth ?? 0.4} />
      <text x={28} y={1} fontSize={9.5} fill="#334155">{label}</text>
    </g>
  );
}
