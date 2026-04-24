"use client";

import type { BuildingModelNiveau } from "@/lib/types";
import { bboxOf, type Coord } from "./plan-utils";

interface CotationsLayerProps {
  niveau: BuildingModelNiveau;
  footprint: Coord[];
  project: (c: Coord) => Coord;
  scale: number;
  /** Minimum wall length (m) to cote — skip noise */
  minEdgeM?: number;
}

/**
 * PC-grade cotations layer — exterior perimeter, interior room dimensions,
 * and opening widths. Rendered as a separate overlay so that the base
 * `NiveauPlan` can stay uncluttered when `showCotations=false`.
 *
 * Convention architecturale :
 *  - Cotes extérieures en chaîne : trait parallèle à chaque façade, décalé
 *    vers l'extérieur de 1.5 m, tickmarks aux sommets.
 *  - Cotes intérieures : dimensions W × H lisibles au centre de chaque
 *    pièce dont l'aire projetée le permet.
 *  - Cotes d'ouvertures : largeur en cm au-dessus de l'ouverture.
 */
export function CotationsLayer({
  niveau,
  footprint,
  project,
  scale,
  minEdgeM = 1.5,
}: CotationsLayerProps) {
  return (
    <g data-cotations-layer="true" pointerEvents="none">
      <ExteriorPerimeterCotes footprint={footprint} project={project} scale={scale} minEdgeM={minEdgeM} />
      {niveau.cellules.map((cell) =>
        cell.rooms.map((room) => (
          <RoomDimLabel key={`${cell.id}-${room.id}`} room={room} project={project} scale={scale} />
        )),
      )}
      {niveau.cellules.map((cell) => (
        <OpeningCotes
          key={`op-${cell.id}`}
          cell={cell}
          project={project}
          scale={scale}
          footprint={footprint}
        />
      ))}
    </g>
  );
}

/* ───────── Exterior perimeter cotes ───────── */

function ExteriorPerimeterCotes({
  footprint,
  project,
  scale,
  minEdgeM,
}: {
  footprint: Coord[];
  project: (c: Coord) => Coord;
  scale: number;
  minEdgeM: number;
}) {
  if (footprint.length < 3) return null;
  // Determine polygon orientation (signed area > 0 = CCW in math convention,
  // but SVG y goes down — we just pick the side that is visually outside).
  const bb = bboxOf(footprint);
  if (!bb) return null;
  const cx = (bb.minx + bb.maxx) / 2;
  const cy = (bb.miny + bb.maxy) / 2;

  const OFFSET_M = 1.5;
  const offsetPx = OFFSET_M * scale;

  return (
    <g>
      {footprint.map((a, i) => {
        const b = footprint[(i + 1) % footprint.length];
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len < minEdgeM) return null;
        // World-space edge normal pointing away from centroid
        const mx = (a[0] + b[0]) / 2;
        const my = (a[1] + b[1]) / 2;
        const outwardW: Coord = [mx - cx, my - cy];
        // Rotate the edge 90° both ways in world-space, pick the direction
        // that has positive dot product with outwardW.
        const ex = b[0] - a[0];
        const ey = b[1] - a[1];
        const n1: Coord = [-ey / len, ex / len];
        const n2: Coord = [ey / len, -ex / len];
        const dot = (v1: Coord, v2: Coord) => v1[0] * v2[0] + v1[1] * v2[1];
        const n: Coord = dot(n1, outwardW) >= dot(n2, outwardW) ? n1 : n2;

        const aOff: Coord = [a[0] + n[0] * OFFSET_M, a[1] + n[1] * OFFSET_M];
        const bOff: Coord = [b[0] + n[0] * OFFSET_M, b[1] + n[1] * OFFSET_M];
        const mOff: Coord = [mx + n[0] * OFFSET_M, my + n[1] * OFFSET_M];

        const [pax, pay] = project(aOff);
        const [pbx, pby] = project(bOff);
        const [pmx, pmy] = project(mOff);

        // For the ticks at each end, extend perpendicular to dim line (= along n)
        const projOrig = project(a);
        const projEnd = project(b);

        // Text orientation: keep it readable; rotate with the edge
        const angDeg = (Math.atan2(pby - pay, pbx - pax) * 180) / Math.PI;
        // If text would be upside-down, flip 180°
        const flipText = angDeg > 90 || angDeg < -90;
        const tAngle = flipText ? angDeg + 180 : angDeg;

        return (
          <g key={i}>
            {/* Witness lines: from building corner to dim line */}
            <line x1={projOrig[0]} y1={projOrig[1]} x2={pax} y2={pay} stroke="#0f172a" strokeWidth={0.4} strokeDasharray="2 2" />
            <line x1={projEnd[0]} y1={projEnd[1]} x2={pbx} y2={pby} stroke="#0f172a" strokeWidth={0.4} strokeDasharray="2 2" />
            {/* Dim line */}
            <line x1={pax} y1={pay} x2={pbx} y2={pby} stroke="#0f172a" strokeWidth={0.7} />
            {/* End ticks — short perpendicular marks (2 mm diag cross) */}
            <Tick x={pax} y={pay} angDeg={angDeg} />
            <Tick x={pbx} y={pby} angDeg={angDeg} />
            {/* Label */}
            <text
              x={pmx}
              y={pmy - 2}
              fontSize={9.5}
              fontWeight={700}
              fill="#0f172a"
              textAnchor="middle"
              transform={`rotate(${tAngle} ${pmx} ${pmy})`}
            >
              {len.toFixed(2)} m
            </text>
          </g>
        );
      })}

      {/* Global totals: W × H of the footprint bbox */}
      {(() => {
        const totalW = bb.maxx - bb.minx;
        const totalH = bb.maxy - bb.miny;
        const [x1, y1] = project([bb.minx, bb.miny - 3.5]);
        const [x2] = project([bb.maxx, bb.miny - 3.5]);
        const [xL, yL] = project([bb.maxx + 3.5, bb.maxy]);
        const [, yH] = project([bb.maxx + 3.5, bb.miny]);
        return (
          <g opacity={0.85}>
            {/* Bottom total */}
            <line x1={x1} y1={y1} x2={x2} y2={y1} stroke="#334155" strokeWidth={0.8} />
            <polygon points={`${x1},${y1} ${x1 + 5},${y1 - 3} ${x1 + 5},${y1 + 3}`} fill="#334155" />
            <polygon points={`${x2},${y1} ${x2 - 5},${y1 - 3} ${x2 - 5},${y1 + 3}`} fill="#334155" />
            <text x={(x1 + x2) / 2} y={y1 - 4} fontSize={10.5} fontWeight={800} fill="#334155" textAnchor="middle">
              ↔ {totalW.toFixed(2)} m
            </text>
            {/* Right total */}
            <line x1={xL} y1={yL} x2={xL} y2={yH} stroke="#334155" strokeWidth={0.8} />
            <polygon points={`${xL},${yL} ${xL - 3},${yL - 5} ${xL + 3},${yL - 5}`} fill="#334155" />
            <polygon points={`${xL},${yH} ${xL - 3},${yH + 5} ${xL + 3},${yH + 5}`} fill="#334155" />
            <text
              x={xL + 10}
              y={(yL + yH) / 2}
              fontSize={10.5}
              fontWeight={800}
              fill="#334155"
              dominantBaseline="middle"
              transform={`rotate(-90 ${xL + 10} ${(yL + yH) / 2})`}
            >
              ↕ {totalH.toFixed(2)} m
            </text>
          </g>
        );
      })()}
    </g>
  );
}

function Tick({ x, y, angDeg }: { x: number; y: number; angDeg: number }) {
  const L = 3.2;
  return (
    <g transform={`rotate(${angDeg + 45} ${x} ${y})`}>
      <line x1={x - L} y1={y} x2={x + L} y2={y} stroke="#0f172a" strokeWidth={0.9} />
    </g>
  );
}

/* ───────── Interior room dimension labels ───────── */

function RoomDimLabel({
  room,
  project,
  scale,
}: {
  room: { id: string; polygon_xy: Array<[number, number]>; surface_m2: number };
  project: (c: Coord) => Coord;
  scale: number;
}) {
  const bb = bboxOf(room.polygon_xy as Coord[]);
  if (!bb) return null;
  const w = bb.maxx - bb.minx;
  const h = bb.maxy - bb.miny;
  // Skip noise rooms and rooms too small to accept a 3rd line of label
  // without colliding with the name + m² labels managed by RoomLabel.
  if (room.surface_m2 < 4) return null;
  const wPx = w * scale;
  const hPx = h * scale;
  if (wPx < 60 || hPx < 50) return null;
  // Place dim label near the BOTTOM of the projected room polygon, inside.
  // World y-axis and SVG y-axis are flipped by the projector: world bb.miny
  // (south) projects to the LARGE SVG y (bottom of screen). So the "inside
  // bottom" position is project(midx, bb.miny) minus a few px (upward in SVG).
  const [xMid, ySvgBottom] = project([(bb.minx + bb.maxx) / 2, bb.miny]);
  const yLabel = ySvgBottom - 5;
  return (
    <g>
      <rect
        x={xMid - 32}
        y={yLabel - 8}
        width={64}
        height={11}
        rx={1.5}
        fill="white"
        opacity={0.78}
      />
      <text
        x={xMid}
        y={yLabel}
        fontSize={7.5}
        fill="#334155"
        textAnchor="middle"
        fontStyle="italic"
      >
        {w.toFixed(2)} × {h.toFixed(2)} m
      </text>
    </g>
  );
}

/* ───────── Opening cotes (width in cm, on exterior walls only) ───────── */

function OpeningCotes({
  cell,
  project,
  scale,
  footprint,
}: {
  cell: {
    walls: Array<{ id: string; geometry: { coords: Array<[number, number]> } }>;
    openings: Array<{ id: string; wall_id: string; position_along_wall_cm: number; width_cm: number; type: string }>;
  };
  project: (c: Coord) => Coord;
  scale: number;
  footprint: Coord[];
}) {
  if (!cell.openings?.length || !cell.walls?.length) return null;
  const wallById = new Map(cell.walls.map((w) => [w.id, w] as const));
  return (
    <g>
      {cell.openings.map((op) => {
        const wall = wallById.get(op.wall_id);
        if (!wall) return null;
        const coords = wall.geometry?.coords as Coord[] | undefined;
        if (!coords || coords.length < 2) return null;
        if (!isOnPerimeter(coords, footprint)) return null;  // ext only
        // Opening center = position_along_wall_cm / 100 along the wall
        const [a, b] = coords;
        const wallLen = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (wallLen < 0.2) return null;
        const t = op.position_along_wall_cm / 100 / wallLen;
        const cxW = a[0] + t * (b[0] - a[0]);
        const cyW = a[1] + t * (b[1] - a[1]);
        // Offset the label OUTWARD of the wall (perpendicular, centroid-away)
        const cbb = bboxOf(footprint);
        if (!cbb) return null;
        const bx = (cbb.minx + cbb.maxx) / 2;
        const by = (cbb.miny + cbb.maxy) / 2;
        const dx = b[0] - a[0];
        const dy = b[1] - a[1];
        const len = Math.hypot(dx, dy);
        const n1: Coord = [-dy / len, dx / len];
        const n2: Coord = [dy / len, -dx / len];
        const dot = (v1: Coord, v2: Coord) => v1[0] * v2[0] + v1[1] * v2[1];
        const outW: Coord = [cxW - bx, cyW - by];
        const n = dot(n1, outW) >= dot(n2, outW) ? n1 : n2;
        const OFF = 0.6;
        const [px, py] = project([cxW + n[0] * OFF, cyW + n[1] * OFF]);

        const w = op.width_cm;
        const tone = op.type === "porte_fenetre" ? "#0c4a6e" : op.type === "fenetre" ? "#0284c7" : "#b45309";
        return (
          <g key={op.id}>
            <rect x={px - 12} y={py - 6} width={24} height={12} rx={2} fill="white" stroke={tone} strokeWidth={0.7} opacity={0.95} />
            <text x={px} y={py + 3.5} fontSize={8} fontWeight={700} fill={tone} textAnchor="middle">
              {w}
            </text>
          </g>
        );
      })}
    </g>
  );
}

/**
 * Test whether a wall's midpoint lies on (within ~0.3m of) any edge of the
 * building footprint — indicating the wall is part of the building's external
 * envelope (not an interior partition).
 */
function isOnPerimeter(wallCoords: Coord[], footprint: Coord[]): boolean {
  if (wallCoords.length < 2 || footprint.length < 3) return false;
  const [a, b] = wallCoords;
  const mx = (a[0] + b[0]) / 2;
  const my = (a[1] + b[1]) / 2;
  const TOL = 0.3;
  for (let i = 0; i < footprint.length; i++) {
    const fa = footprint[i];
    const fb = footprint[(i + 1) % footprint.length];
    // Distance from (mx, my) to segment fa-fb
    const vx = fb[0] - fa[0];
    const vy = fb[1] - fa[1];
    const len2 = vx * vx + vy * vy;
    if (len2 < 1e-6) continue;
    let t = ((mx - fa[0]) * vx + (my - fa[1]) * vy) / len2;
    t = Math.max(0, Math.min(1, t));
    const qx = fa[0] + t * vx;
    const qy = fa[1] + t * vy;
    const d = Math.hypot(mx - qx, my - qy);
    if (d < TOL) return true;
  }
  return false;
}
