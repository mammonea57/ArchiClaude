"use client";

import type {
  BuildingModelNiveau,
  BuildingModelCellule,
  BuildingModelCirculation,
  BuildingModelOpening,
  BuildingModelWall,
  BuildingModelRoom,
} from "@/lib/types";
import {
  bboxOf, makeProjector, polygonCentroid, ringToPath,
  roomLabelFr, roomLabelShort, roomLabelTiny,
  type Coord,
} from "./plan-utils";
import { PlanPatterns, NorthArrow, ScaleBar, TitleBlock } from "./plan-patterns";
import {
  Sofa3p, DiningTable,
  Bed, Wardrobe, Desk,
  KitchenLinear,
  Bathtub, ShowerStall, Washbasin, Toilet,
  StorageUnit,
  PatioTable, PottedPlant,
} from "./furniture";

interface NiveauPlanProps {
  niveau: BuildingModelNiveau;
  corePosition?: [number, number];
  coreSurfaceM2?: number;
  hasAscenseur?: boolean;
  voirieSide?: string;
  isRdc?: boolean;
  width?: number;
  height?: number;
  northAngleDeg?: number;
  projectName?: string;
}

export function NiveauPlan({
  niveau,
  corePosition,
  coreSurfaceM2 = 22,
  hasAscenseur = true,
  voirieSide = "sud",
  isRdc = false,
  width = 900,
  height = 620,
  northAngleDeg = 0,
  projectName,
}: NiveauPlanProps) {
  const allPts: Coord[] = niveau.cellules.flatMap((c) => c.polygon_xy);
  const circulations = niveau.circulations_communes ?? [];
  for (const c of circulations) allPts.push(...c.polygon_xy);
  if (corePosition) allPts.push(corePosition);
  const box = bboxOf(allPts);

  if (!box || niveau.cellules.length === 0) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg p-10 text-sm text-slate-400 border border-slate-100 w-full h-[360px]">
        Aucune cellule placée à ce niveau.
      </div>
    );
  }

  // Reserve the TOP 80 px for the sheet header (rect at y=20-58 + title
  // text). Pass a clipped-height projection so top apts never slip under
  // the header.
  const HEADER_PX = 80;
  const FOOTER_PX = 90;  // scale bar + title block at bottom
  const plan_h = height - HEADER_PX - FOOTER_PX;
  const { scale, project: baseProject } = makeProjector(box, width, plan_h, 24);
  // Shift every projected y by HEADER_PX so the plan starts below the header.
  const project = (c: Coord): Coord => {
    const [x, y] = baseProject(c);
    return [x, y + HEADER_PX];
  };

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

      {/* Palier (circulation commune) */}
      {circulations.map((circ) => (
        <PalierLayer key={circ.id} circulation={circ} scale={scale} project={project} />
      ))}

      {/* Core (escalier top-left, ASC top-right, palier strip bottom).
          The palier sits SOUTH of the stairs/ASC so it flows naturally
          into the south-facing hall on RDC and into the corridors on
          upper floors. */}
      {corePosition && (
        <CoreLayer
          position={corePosition}
          surfaceM2={coreSurfaceM2}
          hasAscenseur={hasAscenseur}
          scale={scale}
          project={project}
        />
      )}

      {/* RDC main entrance from voirie — position it at the corridor end
          that reaches the voirie wall (so entering leads to the corridor,
          not into an apartment) */}
      {isRdc && corePosition && (
        <MainEntrance
          corePosition={corePosition}
          voirieSide={voirieSide}
          box={box}
          circulations={circulations}
          scale={scale}
          project={project}
        />
      )}

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
          key={`${cellule.id}-${op.id}`}
          opening={op}
          walls={cellule.walls}
          scale={scale}
          project={project}
        />
      ))}

      {/* Furniture per room — each wrapped in a clipPath so pieces never
          spill outside their room even if sized bigger than the room. */}
      {cellule.rooms.map((r) => {
        const clipId = `clip-${cellule.id}-${r.id}`;
        return (
          <g key={`furn-${r.id}`}>
            <defs>
              <clipPath id={clipId}>
                <path d={ringToPath(r.polygon_xy, project)} />
              </clipPath>
            </defs>
            <g clipPath={`url(#${clipId})`}>
              <FurnitureInRoom room={r} scale={scale} project={project} />
            </g>
          </g>
        );
      })}

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
  const bbox = bboxOf(room.polygon_xy);
  if (!bbox) return null;
  const [cxw, cyw] = polygonCentroid(room.polygon_xy);
  const [cx, cy] = project([cxw, cyw]);
  const widthPx = (bbox.maxx - bbox.minx) * scale;
  const depthPx = (bbox.maxy - bbox.miny) * scale;

  // Decide labeling strategy based on room pixel dimensions
  const rotate = widthPx < 60 && depthPx > widthPx * 1.4;
  const longDim = rotate ? depthPx : widthPx;

  let label: string;
  let fontSize: number;
  let showSurface: boolean;

  if (longDim < 55) {
    label = roomLabelTiny(room.type);
    fontSize = 7.5;
    showSurface = false;
  } else if (longDim < 100) {
    label = roomLabelTiny(room.type);
    fontSize = 9;
    showSurface = room.surface_m2 > 6;
  } else if (longDim < 150) {
    label = roomLabelShort(room.type);
    fontSize = 10;
    showSurface = true;
  } else {
    label = roomLabelFr(room.type, room.label_fr);
    fontSize = 11;
    showSurface = true;
  }

  const surface = room.surface_m2.toFixed(1).replace(".", ",");
  const transform = rotate ? `rotate(-90 ${cx} ${cy})` : undefined;
  const dy = fontSize <= 8 ? 0 : 2;

  return (
    <g style={{ pointerEvents: "none" }} transform={transform}>
      <text
        x={cx}
        y={cy + dy}
        textAnchor="middle"
        fontSize={fontSize}
        fontWeight={600}
        fill="#0f172a"
      >
        {label}
      </text>
      {showSurface && (
        <text
          x={cx}
          y={cy + dy + fontSize + 1}
          textAnchor="middle"
          fontSize={Math.max(7, fontSize - 1.5)}
          fill="#475569"
        >
          {surface} m²
        </text>
      )}
    </g>
  );
}

function TypologieTag({ cellule, project }: { cellule: BuildingModelCellule; project: (c: Coord) => Coord }) {
  const bbox = bboxOf(cellule.polygon_xy);
  if (!bbox) return null;
  const [tx, ty] = project([bbox.minx, bbox.maxy]);
  // Apt number: extract "03" from "R+0.03"
  const m = cellule.id.match(/\.(\d+)$/);
  const aptNum = m?.[1] ?? cellule.id;
  return (
    <g transform={`translate(${tx + 4}, ${ty + 16})`}>
      {/* typologie badge (left) */}
      <rect x={0} y={-12} rx={2} ry={2} width={30} height={16} fill="#0f172a" />
      <text x={15} y={0} textAnchor="middle" fontSize={10} fontWeight={700} fill="white" letterSpacing="0.4">
        {cellule.typologie}
      </text>
      {/* apt number badge (right, shorter) */}
      <rect x={32} y={-12} rx={2} ry={2} width={26} height={16} fill="#dc2626" />
      <text x={45} y={0} textAnchor="middle" fontSize={10} fontWeight={700} fill="white">
        {aptNum}
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
  // Skip furniture entirely if the rendered room is less than ~40px — labels
  // take priority in tiny cells.
  if (widthM * scale < 40 || depthM * scale < 40) return null;

  const [cxw, cyw] = [(bbox.minx + bbox.maxx) / 2, (bbox.miny + bbox.maxy) / 2];
  const [cx, cy] = project([cxw, cyw]);
  // Projected room half-dimensions (used to offset furniture without spilling)
  const halfW = (widthM * scale) / 2;
  const halfH = (depthM * scale) / 2;

  // Choose best-fitting furniture based on room size + type
  switch (room.type) {
    case "sejour":
    case "sejour_cuisine": {
      // Layout planned top-to-bottom without overlap.
      // Slots are pinned to room edges (1/6, 3/6, 5/6 of depth) so each piece
      // has its own band whatever the room size.
      const hasKitchen = room.type === "sejour_cuisine" && widthM >= 3.2 && depthM >= 3;
      const hasDining = widthM >= 3.2 && depthM >= 3.5;
      const hasSofaSet = widthM >= 2.5 && depthM >= 2.8;
      // Bands: kitchen (top), sofa (upper-middle), dining (lower)
      const topY = cy - halfH + 0.18 * halfH * 2;
      const midY = cy - halfH + 0.50 * halfH * 2;
      const bottomY = cy - halfH + 0.82 * halfH * 2;
      return (
        <g style={{ pointerEvents: "none" }}>
          {hasKitchen && (
            <g transform={`translate(${cx}, ${topY})`}>
              <KitchenLinear scale={scale} lengthCm={Math.min(widthM * 80, 300)} />
            </g>
          )}
          {hasSofaSet && (
            <g transform={`translate(${cx}, ${midY})`}>
              <Sofa3p scale={scale} />
            </g>
          )}
          {hasDining && (
            <g transform={`translate(${cx}, ${bottomY})`}>
              <DiningTable scale={scale} seats={widthM >= 4.5 ? 6 : 4} />
            </g>
          )}
        </g>
      );
    }
    case "cuisine": {
      // Linear kitchen against one wall, scaled to room width
      const lenCm = Math.min(widthM * 85, 300);
      return (
        <g style={{ pointerEvents: "none" }} transform={`translate(${cx}, ${cy - halfH * 0.6})`}>
          <KitchenLinear scale={scale} lengthCm={lenCm} />
        </g>
      );
    }
    case "chambre_parents": {
      // Bed at the façade end (top), wardrobe against the back wall (bottom)
      const bedY = cy - halfH + 0.35 * 2 * halfH;
      const wardY = cy - halfH + 0.85 * 2 * halfH;
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx}, ${bedY})`}>
            <Bed scale={scale} size={widthM >= 3 ? "queen" : "double"} />
          </g>
          {widthM >= 2.5 && depthM >= 3.5 && (
            <g transform={`translate(${cx}, ${wardY})`}>
              <Wardrobe scale={scale} widthCm={Math.min(widthM * 80, 220)} />
            </g>
          )}
        </g>
      );
    }
    case "chambre_enfant":
    case "chambre_supp": {
      const bedY = cy - halfH + 0.38 * 2 * halfH;
      const deskY = cy - halfH + 0.85 * 2 * halfH;
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx}, ${bedY})`}>
            <Bed scale={scale} size={widthM >= 2.8 ? "double" : "single"} />
          </g>
          {depthM >= 3.2 && (
            <g transform={`translate(${cx}, ${deskY})`}>
              <Desk scale={scale} />
            </g>
          )}
        </g>
      );
    }
    case "sdb":
    case "wc_sdb": {
      // Bathtub on the long wall, washbasin + toilet on opposite side
      const isPortrait = depthM >= widthM;
      if (isPortrait) {
        return (
          <g style={{ pointerEvents: "none" }}>
            <g transform={`translate(${cx}, ${cy - halfH * 0.55}) rotate(90)`}>
              <Bathtub scale={scale} />
            </g>
            <g transform={`translate(${cx}, ${cy + halfH * 0.2})`}>
              <Washbasin scale={scale} />
            </g>
            {room.type === "wc_sdb" && (
              <g transform={`translate(${cx}, ${cy + halfH * 0.75})`}>
                <Toilet scale={scale} />
              </g>
            )}
          </g>
        );
      }
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx - halfW * 0.55}, ${cy})`}>
            <Bathtub scale={scale} />
          </g>
          <g transform={`translate(${cx + halfW * 0.45}, ${cy - halfH * 0.35})`}>
            <Washbasin scale={scale} />
          </g>
          {room.type === "wc_sdb" && (
            <g transform={`translate(${cx + halfW * 0.45}, ${cy + halfH * 0.45})`}>
              <Toilet scale={scale} />
            </g>
          )}
        </g>
      );
    }
    case "salle_de_douche": {
      const isPortrait = depthM >= widthM;
      if (isPortrait) {
        return (
          <g style={{ pointerEvents: "none" }}>
            <g transform={`translate(${cx}, ${cy - halfH * 0.45})`}>
              <ShowerStall scale={scale} />
            </g>
            <g transform={`translate(${cx}, ${cy + halfH * 0.5})`}>
              <Washbasin scale={scale} />
            </g>
          </g>
        );
      }
      return (
        <g style={{ pointerEvents: "none" }}>
          <g transform={`translate(${cx - halfW * 0.45}, ${cy})`}>
            <ShowerStall scale={scale} />
          </g>
          <g transform={`translate(${cx + halfW * 0.45}, ${cy})`}>
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
        <g style={{ pointerEvents: "none" }} transform={`translate(${cx}, ${cy - halfH * 0.5})`}>
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

/* ═══════════════════════════ CORE + PALIER ═══════════════════════════ */

function PalierLayer({ circulation, scale, project }: {
  circulation: BuildingModelCirculation;
  scale: number;
  project: (c: Coord) => Coord;
}) {
  const centroid = polygonCentroid(circulation.polygon_xy);
  const [lx, ly] = project(centroid);
  // Hall/corridor/palier circulations share edges; using the previous
  // thick stroke drew a double-line at every junction that read as a
  // wall. Render with a thinner stroke so adjacent circulations visually
  // connect (passage from palier to corridors).
  const isCorePalier = (circulation.id ?? "").toLowerCase().startsWith("palier");
  const stroke = Math.max(1, 0.05 * scale);
  return (
    <g style={{ pointerEvents: "none" }}>
      <path
        d={ringToPath(circulation.polygon_xy, project)}
        fill="url(#pat-tiles)"
        stroke="#0f172a"
        strokeWidth={stroke}
        strokeLinejoin="round"
      />
      {/* Only the core-palier and hall keep their label inline — corridors
          already have their width annotated via the plan legend. */}
      {!isCorePalier && (
        <>
          <text x={lx} y={ly + 3} textAnchor="middle" fontSize={10} fontWeight={600} fill="#475569">
            palier
          </text>
          <text x={lx} y={ly + 15} textAnchor="middle" fontSize={8.5} fill="#64748b">
            {circulation.largeur_min_cm} cm
          </text>
        </>
      )}
    </g>
  );
}

function CoreLayer({
  position,
  surfaceM2,
  hasAscenseur,
  scale,
  project,
}: {
  position: [number, number];
  surfaceM2: number;
  hasAscenseur: boolean;
  scale: number;
  project: (c: Coord) => Coord;
}) {
  // Layout convention (user spec, maximises usable space + exterior views):
  //   Top 62 % : escalier (left 58 %) + ASC (right 42 %)
  //   Bottom 38 % : palier strip (landing that connects to the corridor
  //                  AND to the voirie-facing hall)
  // This replaces the previous "whole core = palier with stairs inside"
  // rendering so the palier is actually a distinct landing zone at the
  // south of the core (adjacent to the hall) and the stairs/ASC sit on
  // the north side.
  const side = Math.sqrt(surfaceM2);
  const [cxM, cyM] = position;
  // Project the core's SW (world small-x, small-y) and NE corners. Because
  // the projector flips Y (SVG y grows down, world y grows up), SW maps to
  // the PIXEL BOTTOM-LEFT and NE to the PIXEL TOP-RIGHT. Compute the
  // unambiguous pixel-rect top-left with min().
  const [pswX, pswY] = project([cxM - side / 2, cyM - side / 2]);
  const [pneX, pneY] = project([cxM + side / 2, cyM + side / 2]);
  const rectLeft = Math.min(pswX, pneX);
  const rectTop = Math.min(pswY, pneY); // pixel-top of the core on screen
  const fullW = Math.abs(pneX - pswX);
  const fullH = Math.abs(pneY - pswY);

  const STAIRS_ZONE_FRAC = 0.62;
  const PALIER_ZONE_FRAC = 0.38;
  const STAIR_W_FRAC = 0.58;
  const ASC_W_FRAC = 0.42;

  const topZoneH = fullH * STAIRS_ZONE_FRAC; // stairs + ASC (pixel TOP of core)
  const palierZoneH = fullH * PALIER_ZONE_FRAC; // palier strip (pixel BOTTOM = world SOUTH)

  const stairRect = {
    x: rectLeft,
    y: rectTop,
    w: fullW * STAIR_W_FRAC,
    h: topZoneH,
  };
  const elevRect = {
    x: rectLeft + fullW * STAIR_W_FRAC,
    y: rectTop + topZoneH * 0.18,
    w: fullW * ASC_W_FRAC,
    h: topZoneH * 0.64,
  };

  const NB_TREADS = 11;

  return (
    <g style={{ pointerEvents: "none" }}>
      {/* 1. Erase the palier tile pattern on the TOP zone (pixel top =
            world north) so stairs + ASC appear on a clean white
            background. Bottom zone (pixel bottom = world south) keeps
            its tile pattern drawn earlier by PalierLayer. */}
      <rect x={rectLeft} y={rectTop} width={fullW} height={topZoneH} fill="white" />

      {/* 2. Black separator line between top (stairs+ASC) and bottom
            (palier) zones — visually confirms the two-zone split. */}
      <line
        x1={rectLeft}
        y1={rectTop + topZoneH}
        x2={rectLeft + fullW}
        y2={rectTop + topZoneH}
        stroke="#0f172a"
        strokeWidth={1.4}
      />

      {/* 3. Stairs rectangle (top-left) */}
      <rect
        x={stairRect.x}
        y={stairRect.y}
        width={stairRect.w}
        height={stairRect.h}
        fill="#e2e8f0"
        stroke="#0f172a"
        strokeWidth={1.4}
      />
      {/* Vertical tread lines across the stair box */}
      {Array.from({ length: NB_TREADS }).map((_, i) => {
        const frac = (i + 0.5) / NB_TREADS;
        const x = stairRect.x + stairRect.w * frac;
        return (
          <line
            key={i}
            x1={x}
            y1={stairRect.y + 4}
            x2={x}
            y2={stairRect.y + stairRect.h - 4}
            stroke="#475569"
            strokeWidth={0.5}
          />
        );
      })}
      {/* Diagonal UP arrow from bottom-left to top-right of the stairs */}
      <path
        d={`M ${stairRect.x + 6} ${stairRect.y + stairRect.h - 6} L ${stairRect.x + stairRect.w - 6} ${stairRect.y + 10}`}
        stroke="#0f172a"
        strokeWidth={0.8}
        markerEnd="url(#arrow-n)"
      />
      <text
        x={stairRect.x + 4}
        y={stairRect.y + stairRect.h - 10}
        fontSize={8}
        fill="#475569"
      >
        UP
      </text>
      <text
        x={stairRect.x + stairRect.w / 2}
        y={stairRect.y + 14}
        textAnchor="middle"
        fontSize={8.5}
        fontWeight={600}
        fill="#475569"
      >
        escalier
      </text>

      {/* 4. Elevator (top-right, beside the stairs in the SAME top zone) */}
      {hasAscenseur && (
        <g>
          <rect
            x={elevRect.x}
            y={elevRect.y}
            width={elevRect.w}
            height={elevRect.h}
            fill="#f8fafc"
            stroke="#0f172a"
            strokeWidth={1.2}
          />
          <line
            x1={elevRect.x + 2}
            y1={elevRect.y + elevRect.h / 2}
            x2={elevRect.x + elevRect.w - 2}
            y2={elevRect.y + elevRect.h / 2}
            stroke="#475569"
            strokeWidth={0.5}
            strokeDasharray="2 2"
          />
          <text
            x={elevRect.x + elevRect.w / 2}
            y={elevRect.y + elevRect.h / 2 + 3}
            textAnchor="middle"
            fontSize={8}
            fontWeight={700}
            fill="#334155"
          >
            ASC
          </text>
        </g>
      )}

      {/* 5. Palier label in the BOTTOM strip (the palier tiles from
             PalierLayer are still visible there). */}
      <text
        x={rectLeft + fullW / 2}
        y={rectTop + topZoneH + palierZoneH / 2 - 2}
        textAnchor="middle"
        fontSize={9.5}
        fontWeight={600}
        fill="#334155"
      >
        palier
      </text>
      <text
        x={rectLeft + fullW / 2}
        y={rectTop + topZoneH + palierZoneH / 2 + 10}
        textAnchor="middle"
        fontSize={8}
        fill="#64748b"
      >
        140 cm
      </text>
    </g>
  );
}

function MainEntrance({
  corePosition, voirieSide, box, circulations, scale, project,
}: {
  corePosition: [number, number];
  voirieSide: string;
  box: { minx: number; miny: number; maxx: number; maxy: number };
  circulations: BuildingModelCirculation[];
  scale: number;
  project: (c: Coord) => Coord;
}) {
  const [cxM, cyM] = corePosition;

  // Find the CIRCULATION polygon that reaches the voirie edge — the street
  // door opens into that corridor, not into an apartment. Pick the
  // corridor whose bbox touches the voirie wall (miny for sud, maxy for
  // nord, etc.).
  let doorMx = cxM;
  let doorMy = cyM;
  let arrowDx = 0, arrowDy = -1;

  const touches = (ci: BuildingModelCirculation, side: string) => {
    if (!ci.polygon_xy || ci.polygon_xy.length < 3) return false;
    const xs = ci.polygon_xy.map((p) => p[0]);
    const ys = ci.polygon_xy.map((p) => p[1]);
    if (side === "sud")   return Math.abs(Math.min(...ys) - box.miny) < 0.35;
    if (side === "nord")  return Math.abs(box.maxy - Math.max(...ys)) < 0.35;
    if (side === "ouest") return Math.abs(Math.min(...xs) - box.minx) < 0.35;
    if (side === "est")   return Math.abs(box.maxx - Math.max(...xs)) < 0.35;
    return false;
  };

  // The main door must land INSIDE a circulation polygon that reaches
  // the voirie wall. Preference order:
  //   1. Dedicated lobby (hall_ prefix) — its x-mid equals the core by design.
  //   2. Any wing corridor whose polygon touches the voirie — use the one
  //      whose mid-axis is closest to the core so the entry-to-stairs
  //      walk is as short as possible.
  //   3. Last-resort fallback at the core's projection on voirie (may
  //      land on a wall if no corridor reaches the boundary).
  const reaching = circulations.filter((c) => touches(c, voirieSide));
  const hall = reaching.find((c) => (c.id ?? "").toLowerCase().startsWith("hall_"));
  const perpIsX = voirieSide === "sud" || voirieSide === "nord";
  const coreKey = perpIsX ? cxM : cyM;
  const midAlongPerp = (c: BuildingModelCirculation) => {
    const vals = c.polygon_xy.map((p) => (perpIsX ? p[0] : p[1]));
    return (Math.min(...vals) + Math.max(...vals)) / 2;
  };
  let chosen: BuildingModelCirculation | null = hall ?? null;
  if (!chosen && reaching.length > 0) {
    chosen = [...reaching].sort(
      (a, b) => Math.abs(midAlongPerp(a) - coreKey) - Math.abs(midAlongPerp(b) - coreKey),
    )[0];
  }

  if (voirieSide === "sud") {
    doorMy = box.miny;
    arrowDy = -1;
    doorMx = chosen ? midAlongPerp(chosen) : cxM;
  } else if (voirieSide === "nord") {
    doorMy = box.maxy;
    arrowDy = 1;
    doorMx = chosen ? midAlongPerp(chosen) : cxM;
  } else if (voirieSide === "est") {
    doorMx = box.maxx;
    arrowDx = 1;
    arrowDy = 0;
    doorMy = chosen ? midAlongPerp(chosen) : cyM;
  } else {
    // ouest
    doorMx = box.minx;
    arrowDx = -1;
    arrowDy = 0;
    doorMy = chosen ? midAlongPerp(chosen) : cyM;
  }

  const [dx, dy] = project([doorMx, doorMy]);
  const [coreX, coreY] = project(corePosition);

  // Door width in pixels — 1.4 m PMR door
  const doorWidthPx = Math.max(18, 1.4 * scale);
  const doorDepthPx = Math.max(6, 0.3 * scale);
  // Orient the door gap perpendicular to the voirie wall
  const isHorizontalWall = voirieSide === "sud" || voirieSide === "nord";

  return (
    <g style={{ pointerEvents: "none" }}>
      {/* 1. White rectangle that erases the building's outer wall at the
             door position — visually creates an OPENING in the envelope. */}
      {isHorizontalWall ? (
        <rect
          x={dx - doorWidthPx / 2}
          y={dy - doorDepthPx / 2}
          width={doorWidthPx}
          height={doorDepthPx}
          fill="white"
        />
      ) : (
        <rect
          x={dx - doorDepthPx / 2}
          y={dy - doorWidthPx / 2}
          width={doorDepthPx}
          height={doorWidthPx}
          fill="white"
        />
      )}

      {/* 2. Glass door — double lines on the gap edges + a swing arc */}
      {isHorizontalWall ? (
        <>
          <line x1={dx - doorWidthPx / 2} y1={dy} x2={dx + doorWidthPx / 2} y2={dy} stroke="#0c4a6e" strokeWidth={1} />
          <line x1={dx - doorWidthPx / 2} y1={dy - 2} x2={dx + doorWidthPx / 2} y2={dy - 2} stroke="#7dd3fc" strokeWidth={0.8} />
          <line x1={dx - doorWidthPx / 2} y1={dy + 2} x2={dx + doorWidthPx / 2} y2={dy + 2} stroke="#7dd3fc" strokeWidth={0.8} />
          {/* Door leaf (half of the width swings open) + arc */}
          <line
            x1={dx - doorWidthPx / 2}
            y1={dy}
            x2={dx}
            y2={dy - arrowDy * doorWidthPx / 2}
            stroke="#0f172a"
            strokeWidth={1.3}
          />
          <path
            d={`M ${dx - doorWidthPx / 2} ${dy} A ${doorWidthPx / 2} ${doorWidthPx / 2} 0 0 ${arrowDy < 0 ? 0 : 1} ${dx} ${dy - arrowDy * doorWidthPx / 2}`}
            fill="none"
            stroke="#64748b"
            strokeWidth={0.6}
            strokeDasharray="2 2"
          />
        </>
      ) : (
        <>
          <line x1={dx} y1={dy - doorWidthPx / 2} x2={dx} y2={dy + doorWidthPx / 2} stroke="#0c4a6e" strokeWidth={1} />
          <line x1={dx - 2} y1={dy - doorWidthPx / 2} x2={dx - 2} y2={dy + doorWidthPx / 2} stroke="#7dd3fc" strokeWidth={0.8} />
          <line x1={dx + 2} y1={dy - doorWidthPx / 2} x2={dx + 2} y2={dy + doorWidthPx / 2} stroke="#7dd3fc" strokeWidth={0.8} />
          <line
            x1={dx}
            y1={dy - doorWidthPx / 2}
            x2={dx - arrowDx * doorWidthPx / 2}
            y2={dy}
            stroke="#0f172a"
            strokeWidth={1.3}
          />
          <path
            d={`M ${dx} ${dy - doorWidthPx / 2} A ${doorWidthPx / 2} ${doorWidthPx / 2} 0 0 ${arrowDx < 0 ? 1 : 0} ${dx - arrowDx * doorWidthPx / 2} ${dy}`}
            fill="none"
            stroke="#64748b"
            strokeWidth={0.6}
            strokeDasharray="2 2"
          />
        </>
      )}

      {/* 3. Dashed path from the door to the core (just inside the corridor) */}
      <line
        x1={dx - arrowDx * doorWidthPx * 0.5}
        y1={dy - arrowDy * doorWidthPx * 0.5}
        x2={coreX}
        y2={coreY}
        stroke="#b45309"
        strokeWidth={1}
        strokeDasharray="3 3"
        opacity={0.6}
      />

      {/* 4. External label outside the building, not on top of the wall */}
      <text
        x={dx + arrowDy * (doorWidthPx / 2 + 10) * -1}
        y={dy - arrowDy * (doorDepthPx + 12)}
        textAnchor="middle"
        fontSize={10}
        fontWeight={700}
        fill="#b45309"
      >
        Entrée
      </text>
      <text
        x={dx + arrowDy * (doorWidthPx / 2 + 10) * -1}
        y={dy - arrowDy * (doorDepthPx + 24)}
        textAnchor="middle"
        fontSize={8}
        fill="#b45309"
      >
        ↓ Rue
      </text>
    </g>
  );
}
