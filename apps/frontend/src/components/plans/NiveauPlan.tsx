"use client";

import type {
  BuildingModelNiveau,
  BuildingModelCellule,
  BuildingModelOpening,
  BuildingModelWall,
  BuildingModelRoom,
} from "@/lib/types";
import {
  bboxOf, makeProjector, polygonCentroid, ringToPath,
  roomLabelFr, roomLabelShort,
  type Coord,
} from "./plan-utils";
import { PlanPatterns, NorthArrow, ScaleBar, TitleBlock } from "./plan-patterns";
import {
  Sofa3p, Armchair, CoffeeTable, DiningTable, TvUnit,
  Bed, Wardrobe, Desk,
  KitchenLinear, KitchenIsland,
  Bathtub, ShowerStall, Washbasin, Toilet,
  StorageUnit,
  PatioTable, PottedPlant,
} from "./furniture";

interface NiveauPlanProps {
  niveau: BuildingModelNiveau;
  width?: number;
  height?: number;
  northAngleDeg?: number;
  projectName?: string;
}

export function NiveauPlan({
  niveau,
  width = 900,
  height = 620,
  northAngleDeg = 0,
  projectName,
}: NiveauPlanProps) {
  const allPts: Coord[] = niveau.cellules.flatMap((c) => c.polygon_xy);
  const box = bboxOf(allPts);

  if (!box || niveau.cellules.length === 0) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg p-10 text-sm text-slate-400 border border-slate-100 w-full h-[360px]">
        Aucune cellule placée à ce niveau.
      </div>
    );
  }

  const { scale, project } = makeProjector(box, width, height - 60, 44);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="bg-white border border-slate-200 rounded-lg"
      style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
    >
      <PlanPatterns />

      {/* Sheet background */}
      <rect x={0} y={0} width={width} height={height} fill="#fafaf9" />

      {/* Border frame */}
      <rect x={12} y={12} width={width - 24} height={height - 24} fill="white" stroke="#0f172a" strokeWidth={0.6} />

      {/* Cellules */}
      {niveau.cellules.map((c) => (
        <CelluleLayer key={c.id} cellule={c} scale={scale} project={project} />
      ))}

      {/* Sheet header */}
      <g>
        <rect x={20} y={20} width={width - 40} height={38} fill="white" />
        <line x1={20} y1={58} x2={width - 20} y2={58} stroke="#0f172a" strokeWidth={0.5} />
        <text x={30} y={40} fontSize={15} fontWeight={700} fill="#0f172a">
          Plan de niveau — {niveau.code}
        </text>
        <text x={30} y={54} fontSize={10.5} fill="#475569">
          {niveau.usage_principal} · HSP {niveau.hauteur_sous_plafond_m} m · {Math.round(niveau.surface_plancher_m2)} m² plancher
          {projectName ? ` · ${projectName}` : ""}
        </text>
      </g>

      {/* Scale bar */}
      <ScaleBar x={34} y={height - 36} scalePxPerM={scale} meters={5} />

      {/* North arrow */}
      <NorthArrow x={width - 60} y={98} size={50} rotationDeg={northAngleDeg} />

      {/* Title block */}
      <TitleBlock
        x={width - 232}
        y={height - 68}
        title={`Plan niveau ${niveau.code}`}
        subtitle={`${niveau.usage_principal} · 1:100`}
        sheetCode={`PA-${String(niveau.index + 10).padStart(2, "0")}`}
      />
    </svg>
  );
}

/* ═══════════════════════════ CELLULE ═══════════════════════════ */

interface LayerProps {
  cellule: BuildingModelCellule;
  scale: number;
  project: (c: Coord) => Coord;
}

function CelluleLayer({ cellule, scale, project }: LayerProps) {
  return (
    <g>
      {/* Rooms — fill first */}
      {cellule.rooms.map((r) => (
        <RoomFloor key={r.id} room={r} project={project} />
      ))}

      {/* Cellule envelope (thick outer walls ~20cm) */}
      <CelluleEnvelope cellule={cellule} scale={scale} project={project} />

      {/* Internal walls */}
      {cellule.walls.filter((w) => w.type !== "porteur").map((w) => (
        <WallSegment key={w.id} wall={w} project={project} thickCm={10} />
      ))}

      {/* Openings on top of walls */}
      {cellule.openings.map((op) => (
        <OpeningMark
          key={op.id}
          opening={op}
          walls={cellule.walls}
          scale={scale}
          project={project}
        />
      ))}

      {/* Furniture per room */}
      {cellule.rooms.map((r) => (
        <FurnitureInRoom key={`furn-${r.id}`} room={r} scale={scale} project={project} />
      ))}

      {/* Labels on top */}
      {cellule.rooms.map((r) => (
        <RoomLabel key={`lbl-${r.id}`} room={r} scale={scale} project={project} />
      ))}

      {/* Typologie tag */}
      {cellule.typologie && (
        <TypologieTag cellule={cellule} project={project} />
      )}
    </g>
  );
}

function RoomFloor({ room, project }: { room: BuildingModelRoom; project: (c: Coord) => Coord }) {
  const pattern = floorPattern(room.type);
  return (
    <path
      d={ringToPath(room.polygon_xy, project)}
      fill={`url(#${pattern})`}
      stroke="none"
    />
  );
}

function floorPattern(type: string): string {
  switch (type) {
    case "sdb":
    case "salle_de_douche":
    case "wc":
    case "wc_sdb":
      return "pat-tiles-small";
    case "cuisine":
      return "pat-tiles";
    case "entree":
      return "pat-tiles";
    case "chambre_parents":
    case "chambre_enfant":
    case "chambre_supp":
      return "pat-parquet-warm";
    case "loggia":
      return "pat-deck";
    case "sejour":
    case "sejour_cuisine":
      return "pat-parquet";
    case "cellier":
    case "placard_technique":
      return "pat-tiles";
    default:
      return "pat-parquet";
  }
}

function CelluleEnvelope({ cellule, scale, project }: LayerProps) {
  // Render as thick stroke — approximate 20cm wall = ~0.20m * scale
  const thick = Math.max(3.5, 0.20 * scale);
  return (
    <path
      d={ringToPath(cellule.polygon_xy, project)}
      fill="none"
      stroke="#0f172a"
      strokeWidth={thick}
      strokeLinejoin="miter"
      strokeLinecap="butt"
    />
  );
}

function WallSegment({
  wall, project, thickCm,
}: { wall: BuildingModelWall; project: (c: Coord) => Coord; thickCm: number }) {
  const coords = wall.geometry?.coords;
  if (!coords || coords.length < 2) return null;
  const a = coords[0] as Coord;
  const b = coords[1] as Coord;
  const [ax, ay] = project(a);
  const [bx, by] = project(b);
  // thin interior walls rendered as double stroke (thick + white inset = drywall look)
  const outer = Math.max(1.6, (thickCm / 100) * 12);
  return (
    <g>
      <line x1={ax} y1={ay} x2={bx} y2={by} stroke="#1e293b" strokeWidth={outer} strokeLinecap="butt" />
    </g>
  );
}

function OpeningMark({
  opening, walls, scale, project,
}: {
  opening: BuildingModelOpening;
  walls: BuildingModelWall[];
  scale: number;
  project: (c: Coord) => Coord;
}) {
  const wall = walls.find((w) => w.id === opening.wall_id);
  if (!wall) return null;
  const coords = wall.geometry?.coords;
  if (!coords || coords.length < 2) return null;
  const a = coords[0] as Coord;
  const b = coords[1] as Coord;

  const wallLengthM = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (wallLengthM === 0) return null;
  const posM = opening.position_along_wall_cm / 100;
  const widthM = opening.width_cm / 100;
  const t0 = Math.max(0, (posM - widthM / 2) / wallLengthM);
  const t1 = Math.min(1, (posM + widthM / 2) / wallLengthM);

  const p0: Coord = [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0];
  const p1: Coord = [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1];
  const [p0x, p0y] = project(p0);
  const [p1x, p1y] = project(p1);
  const dx = p1x - p0x;
  const dy = p1y - p0y;
  const len = Math.hypot(dx, dy);
  const nx = -dy / (len || 1);
  const ny = dx / (len || 1);

  const isWindow = ["fenetre", "porte_fenetre", "baie_coulissante"].includes(opening.type);
  const isDoor = ["porte_entree", "porte_interieure"].includes(opening.type);
  const gapThickness = Math.max(3.5, 0.20 * scale) + 0.5;

  if (isWindow) {
    // White gap across wall
    return (
      <g>
        <line x1={p0x} y1={p0y} x2={p1x} y2={p1y} stroke="white" strokeWidth={gapThickness} />
        {/* window frame 2 lines with glass */}
        <line x1={p0x + nx * 2} y1={p0y + ny * 2} x2={p1x + nx * 2} y2={p1y + ny * 2} stroke="#0369a1" strokeWidth={0.7} />
        <line x1={p0x - nx * 2} y1={p0y - ny * 2} x2={p1x - nx * 2} y2={p1y - ny * 2} stroke="#0369a1" strokeWidth={0.7} />
        {/* glass sill line */}
        <line x1={p0x} y1={p0y} x2={p1x} y2={p1y} stroke="#bae6fd" strokeWidth={1.5} />
        <line x1={p0x} y1={p0y} x2={p1x} y2={p1y} stroke="#0f172a" strokeWidth={0.3} strokeDasharray="3 2" />
      </g>
    );
  }

  if (isDoor) {
    // Arc door with leaf
    const r = len;
    // leaf from p0, rotating into the room (perpendicular to wall)
    const ex = p0x + r * nx;
    const ey = p0y + r * ny;
    return (
      <g>
        {/* gap */}
        <line x1={p0x} y1={p0y} x2={p1x} y2={p1y} stroke="white" strokeWidth={gapThickness} />
        {/* wall return lines at jambs */}
        <line x1={p0x} y1={p0y} x2={p0x + nx * 2} y2={p0y + ny * 2} stroke="#1e293b" strokeWidth={1} />
        <line x1={p1x} y1={p1y} x2={p1x - nx * 2} y2={p1y - ny * 2} stroke="#1e293b" strokeWidth={1} />
        {/* leaf */}
        <line x1={p0x} y1={p0y} x2={ex} y2={ey} stroke="#0f172a" strokeWidth={1.3} />
        {/* arc */}
        <path
          d={`M ${p1x.toFixed(2)} ${p1y.toFixed(2)} A ${r.toFixed(2)} ${r.toFixed(2)} 0 0 0 ${ex.toFixed(2)} ${ey.toFixed(2)}`}
          fill="none"
          stroke="#64748b"
          strokeWidth={0.5}
          strokeDasharray="2 2"
        />
        {/* hinge dot */}
        <circle cx={p0x} cy={p0y} r={1.2} fill="#0f172a" />
      </g>
    );
  }

  return null;
}

function RoomLabel({ room, scale, project }: { room: BuildingModelRoom; scale: number; project: (c: Coord) => Coord }) {
  const [cxw, cyw] = polygonCentroid(room.polygon_xy);
  const [cx, cy] = project([cxw, cyw]);
  const bbox = bboxOf(room.polygon_xy);
  const projectedW = bbox ? (bbox.maxx - bbox.minx) * scale : 80;
  const useShort = projectedW < 110;
  const label = useShort ? roomLabelShort(room.type) : roomLabelFr(room.type, room.label_fr);
  const surface = room.surface_m2.toFixed(2).replace(".", ",");

  // Label anchored near room centroid, offset down away from furniture
  return (
    <g style={{ pointerEvents: "none" }}>
      <text x={cx} y={cy + (scale > 35 ? 22 : 14)} textAnchor="middle" fontSize={11} fontWeight={600} fill="#0f172a">
        {label}
      </text>
      <text x={cx} y={cy + (scale > 35 ? 36 : 26)} textAnchor="middle" fontSize={9.5} fill="#475569">
        {surface} m²
      </text>
    </g>
  );
}

function TypologieTag({ cellule, project }: { cellule: BuildingModelCellule; project: (c: Coord) => Coord }) {
  const bbox = bboxOf(cellule.polygon_xy);
  if (!bbox) return null;
  const [tx, ty] = project([bbox.minx, bbox.maxy]);
  return (
    <g transform={`translate(${tx + 4}, ${ty + 16})`}>
      <rect x={0} y={-12} rx={2} ry={2} width={38} height={16} fill="#0f172a" />
      <text x={19} y={0} textAnchor="middle" fontSize={10} fontWeight={700} fill="white" letterSpacing="0.4">
        {cellule.typologie}
      </text>
    </g>
  );
}

/* ═══════════════════════════ FURNITURE ═══════════════════════════ */

function FurnitureInRoom({
  room, scale, project,
}: { room: BuildingModelRoom; scale: number; project: (c: Coord) => Coord }) {
  const bbox = bboxOf(room.polygon_xy);
  if (!bbox) return null;
  const widthM = bbox.maxx - bbox.minx;
  const depthM = bbox.maxy - bbox.miny;
  if (widthM < 1.2 || depthM < 1.2) return null;

  const [cxw, cyw] = [(bbox.minx + bbox.maxx) / 2, (bbox.miny + bbox.maxy) / 2];
  const [cx, cy] = project([cxw, cyw]);

  // Choose best-fitting furniture based on room size + type
  switch (room.type) {
    case "sejour":
    case "sejour_cuisine": {
      // For sejour_cuisine, split layout: kitchen + living + dining
      const showIsland = widthM >= 5.5 && depthM >= 4;
      const showDining = widthM >= 3.5 && depthM >= 3.5;
      return (
        <g style={{ pointerEvents: "none" }}>
          {/* TV unit at top */}
          {depthM >= 4 && (
            <g transform={`translate(${cx}, ${cy - (depthM * scale) * 0.36})`}>
              <TvUnit scale={scale} />
            </g>
          )}
          {/* Sofa below TV */}
          <g transform={`translate(${cx}, ${cy - (depthM * scale) * 0.18})`}>
            <Sofa3p scale={scale} />
          </g>
          {/* Coffee table */}
          <g transform={`translate(${cx}, ${cy + (depthM * scale) * 0.02})`}>
            <CoffeeTable scale={scale} />
          </g>
          {/* Armchair */}
          {widthM > 4.5 && (
            <g transform={`translate(${cx + (widthM * scale) * 0.3}, ${cy - (depthM * scale) * 0.02})`}>
              <Armchair scale={scale} />
            </g>
          )}
          {/* Dining / kitchen side */}
          {showDining && (
            <g transform={`translate(${cx}, ${cy + (depthM * scale) * 0.22})`}>
              <DiningTable scale={scale} seats={widthM >= 5 ? 6 : 4} />
            </g>
          )}
          {showIsland && (
            <g transform={`translate(${cx}, ${cy + (depthM * scale) * 0.4})`}>
              <KitchenIsland scale={scale} />
            </g>
          )}
        </g>
      );
    }
    case "cuisine": {
      // Linear kitchen against top wall
      const lenCm = Math.min(widthM * 100 * 0.88, 360);
      return (
        <g style={{ pointerEvents: "none" }} transform={`translate(${cx}, ${cy - (depthM * scale) * 0.35})`}>
          <KitchenLinear scale={scale} lengthCm={lenCm} />
        </g>
      );
    }
    case "chambre_parents": {
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx}, ${cy - (depthM * scale) * 0.15})`}>
            <Bed scale={scale} size="queen" />
          </g>
          {widthM > 3.5 && (
            <g transform={`translate(${cx - (widthM * scale) * 0.35}, ${cy + (depthM * scale) * 0.3})`}>
              <Wardrobe scale={scale} widthCm={220} />
            </g>
          )}
          {widthM > 4 && (
            <g transform={`translate(${cx + (widthM * scale) * 0.3}, ${cy + (depthM * scale) * 0.3})`}>
              <Desk scale={scale} />
            </g>
          )}
        </g>
      );
    }
    case "chambre_enfant":
    case "chambre_supp": {
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx - (widthM * scale) * 0.15}, ${cy - (depthM * scale) * 0.15})`}>
            <Bed scale={scale} size={widthM > 3 ? "double" : "single"} />
          </g>
          <g transform={`translate(${cx + (widthM * scale) * 0.3}, ${cy + (depthM * scale) * 0.25})`}>
            <Desk scale={scale} />
          </g>
          <g transform={`translate(${cx + (widthM * scale) * 0.3}, ${cy - (depthM * scale) * 0.3})`}>
            <Wardrobe scale={scale} widthCm={120} />
          </g>
        </g>
      );
    }
    case "sdb":
    case "wc_sdb": {
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx - (widthM * scale) * 0.15}, ${cy - (depthM * scale) * 0.15})`}>
            <Bathtub scale={scale} />
          </g>
          <g transform={`translate(${cx + (widthM * scale) * 0.3}, ${cy - (depthM * scale) * 0.25})`}>
            <Washbasin scale={scale} />
          </g>
          {room.type === "wc_sdb" && (
            <g transform={`translate(${cx + (widthM * scale) * 0.3}, ${cy + (depthM * scale) * 0.25})`}>
              <Toilet scale={scale} />
            </g>
          )}
        </g>
      );
    }
    case "salle_de_douche": {
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx - (widthM * scale) * 0.2}, ${cy})`}>
            <ShowerStall scale={scale} />
          </g>
          <g transform={`translate(${cx + (widthM * scale) * 0.25}, ${cy - (depthM * scale) * 0.2})`}>
            <Washbasin scale={scale} />
          </g>
        </g>
      );
    }
    case "wc": {
      return (
        <g style={{ pointerEvents: "none" }} transform={`translate(${cx}, ${cy})`}>
          <Toilet scale={scale} />
        </g>
      );
    }
    case "cellier":
    case "placard_technique": {
      return (
        <g style={{ pointerEvents: "none" }} transform={`translate(${cx}, ${cy - (depthM * scale) * 0.3})`}>
          <StorageUnit scale={scale} widthCm={widthM * 80} depthCm={40} />
        </g>
      );
    }
    case "loggia": {
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx}, ${cy})`}>
            <PatioTable scale={scale} />
          </g>
          <g transform={`translate(${cx - (widthM * scale) * 0.32}, ${cy - (depthM * scale) * 0.3})`}>
            <PottedPlant scale={scale} size="M" />
          </g>
          <g transform={`translate(${cx + (widthM * scale) * 0.32}, ${cy + (depthM * scale) * 0.3})`}>
            <PottedPlant scale={scale} size="L" />
          </g>
        </g>
      );
    }
    case "entree":
      return null;
    default:
      return null;
  }
}
