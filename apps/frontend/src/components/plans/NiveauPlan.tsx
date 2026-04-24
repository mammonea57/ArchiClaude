"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import { CotationsLayer } from "./CotationsLayer";
import { BalconsJardinsLayer } from "./BalconsJardinsLayer";
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
  /** Footprint for PC-grade cotations overlay. Required if showCotations=true. */
  footprint?: [number, number][];
  /** Render the PC cotations overlay (exterior perimeter, room dims, opening widths). */
  showCotations?: boolean;
  /** Called when the user clicks an apartment. Empty string to deselect. */
  onSelectApt?: (aptId: string) => void;
  /** Currently selected apt id — renders a highlight outline around it. */
  selectedAptId?: string | null;
  /** Edit mode — shows draggable handles for openings/walls on the selected apt. */
  editMode?: boolean;
  /** Notifies parent of geometry changes made in edit mode. */
  onGeometryChange?: (payload: {
    apt_id: string;
    openings?: Array<{ opening_id: string; position_along_wall_cm: number }>;
    walls?: Array<{ wall_id: string; geometry: { type: "LineString"; coords: [number, number][] } }>;
    rooms?: Array<{ room_id: string; polygon_xy: [number, number][] }>;
  }) => void;
  /** Id of the opening clicked (non-drag) — parent uses it to show delete UI. */
  selectedOpeningId?: string | null;
  onSelectOpening?: (id: string | null) => void;
  /** Set to a non-null opening type to enter "add-opening" mode. In this
   * mode every wall of the selected apt becomes clickable; click a wall
   * to spawn a new opening at that position. */
  addOpeningType?: "fenetre" | "porte_fenetre" | "porte_interieure" | null;
  onAddOpening?: (op: {
    type: "fenetre" | "porte_fenetre" | "porte_interieure";
    wall_id: string;
    position_along_wall_cm: number;
  }) => void;
  /** Id of the wall selected (click on a cloison handle) — for delete UI. */
  selectedWallId?: string | null;
  onSelectWall?: (id: string | null) => void;
  /** Notifies parent when a wall has been dragged to a new position. */
  onWallMove?: (wallId: string, newCoords: [number, number][]) => void;
  /** Local overrides applied live while dragging a wall — keyed by wall id. */
  wallOverrides?: Record<string, [number, number][]>;
  /** Room polygon overrides so dragging a wall also visually reshapes rooms. */
  roomOverrides?: Record<string, [number, number][]>;
  /** Click on a corridor polygon → parent handles selection/delete. */
  selectedCirculationId?: string | null;
  onSelectCirculation?: (id: string | null) => void;
  /** Corridor polygon overrides (live drag preview). */
  circulationOverrides?: Record<string, [number, number][]>;
  onCirculationEdge?: (id: string, coords: [number, number][]) => void;
  selectedCirculationEdge?: number | null;
  onSelectCirculationEdge?: (idx: number | null) => void;
  /** Core element-level selection + drag (escalier / ascenseur / palier). */
  selectedCoreElement?: "escalier" | "ascenseur" | "palier" | null;
  onSelectCoreElement?: (el: "escalier" | "ascenseur" | "palier" | null) => void;
  /** Per-element live position overrides. */
  escalierCenter?: [number, number] | null;
  ascCenter?: [number, number] | null;
  palierCenter?: [number, number] | null;
  /** Notify parent when the user drags a sub-element. */
  onCoreElementMove?: (el: "escalier" | "ascenseur" | "palier", center: [number, number]) => void;
  /** Per-element hidden sides (persisted in BM core.{el}.hidden_sides). */
  escalierHiddenSides?: string[];
  ascHiddenSides?: string[];
  palierHiddenSides?: string[];
  /** Per-element "removed" flags — skip rendering entirely. */
  escalierRemoved?: boolean;
  ascRemoved?: boolean;
  palierRemoved?: boolean;
  /** Click a specific side of a core sub-element. */
  onSelectCoreSide?: (el: "escalier" | "ascenseur" | "palier", side: "nord" | "sud" | "est" | "ouest") => void;
  selectedCoreSide?: { el: "escalier" | "ascenseur" | "palier"; side: string } | null;
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
  onSelectApt,
  selectedAptId,
  editMode = false,
  onGeometryChange,
  selectedOpeningId,
  onSelectOpening,
  addOpeningType,
  onAddOpening,
  selectedWallId,
  onSelectWall,
  onWallMove,
  wallOverrides,
  roomOverrides,
  selectedCirculationId,
  onSelectCirculation,
  circulationOverrides,
  onCirculationEdge,
  selectedCirculationEdge,
  onSelectCirculationEdge,
  selectedCoreElement,
  onSelectCoreElement,
  escalierCenter,
  ascCenter,
  palierCenter,
  onCoreElementMove,
  escalierHiddenSides,
  ascHiddenSides,
  palierHiddenSides,
  escalierRemoved,
  ascRemoved,
  palierRemoved,
  onSelectCoreSide,
  selectedCoreSide,
  footprint,
  showCotations = false,
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
      data-niveau-plan="true"
      style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
    >
      <PlanPatterns />

      {/* Sheet background */}
      <rect x={0} y={0} width={width} height={height} fill="#fafaf9" />

      {/* Border frame */}
      <rect x={12} y={12} width={width - 24} height={height - 24} fill="white" stroke="#0f172a" strokeWidth={0.6} />

      {/* Enveloppe du bâtiment — background clair qui trace l'intérieur
          du L et masque la zone NOTCH (intérieur du L non construit). Sans
          ce fond, les jardins privatifs se dessinent dans la notch et
          l'ensemble ressemble à une croix au lieu d'un L. */}
      {footprint && footprint.length >= 3 && (
        <g>
          <path
            d={ringToPath(footprint, project)}
            fill="#f5f5f4"
            stroke="none"
          />
        </g>
      )}

      {/* Balcons (étages) / Jardins privatifs (RDC) — dessinés AVANT les
          cellules pour que le bâtiment les recouvre à la jonction mur. */}
      {footprint && footprint.length >= 3 && (
        <BalconsJardinsLayer
          niveau={niveau}
          footprint={footprint}
          project={project}
          scale={scale}
          isRdc={isRdc}
        />
      )}

      {/* Cellules — apply live wall/room overrides on the selected apt */}
      {niveau.cellules.map((c) => {
        const isEdited = c.id === selectedAptId;
        const displayedCell = isEdited && (wallOverrides || roomOverrides)
          ? {
              ...c,
              walls: (c.walls ?? []).map((w) =>
                wallOverrides?.[w.id]
                  ? { ...w, geometry: { ...w.geometry, coords: wallOverrides[w.id] } as typeof w.geometry }
                  : w,
              ),
              rooms: (c.rooms ?? []).map((r) =>
                roomOverrides?.[r.id]
                  ? { ...r, polygon_xy: roomOverrides[r.id] as typeof r.polygon_xy }
                  : r,
              ),
            }
          : c;
        return (
          <CelluleLayer
            key={c.id}
            cellule={displayedCell}
            scale={scale}
            project={project}
            onSelect={onSelectApt}
            isSelected={selectedAptId === c.id}
          />
        );
      })}

      {/* Palier (circulation commune) — apply live overrides for drag preview */}
      {circulations.map((circ) => {
        const override = circulationOverrides?.[circ.id];
        const displayed = override ? { ...circ, polygon_xy: override as typeof circ.polygon_xy } : circ;
        const selectable = editMode && onSelectCirculation;
        const isSel = selectedCirculationId === circ.id;
        return (
          <g
            key={circ.id}
            style={selectable ? { cursor: "pointer" } : undefined}
            onClick={selectable ? (e) => {
              e.stopPropagation();
              onSelectCirculation?.(circ.id === selectedCirculationId ? null : circ.id);
            } : undefined}
          >
            <PalierLayer circulation={displayed} scale={scale} project={project} />
            {isSel && (
              <path
                d={ringToPath(displayed.polygon_xy, project)}
                fill="none"
                stroke="#dc2626"
                strokeWidth={3}
                strokeDasharray="6 3"
                pointerEvents="none"
              />
            )}
          </g>
        );
      })}

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
          escalierCenter={escalierCenter ?? undefined}
          ascCenter={ascCenter ?? undefined}
          palierCenter={palierCenter ?? undefined}
          selectedCoreElement={editMode ? selectedCoreElement : null}
          onSelectCoreElement={editMode ? onSelectCoreElement : undefined}
          escalierHiddenSides={escalierHiddenSides}
          ascHiddenSides={ascHiddenSides}
          palierHiddenSides={palierHiddenSides}
          escalierRemoved={escalierRemoved}
          ascRemoved={ascRemoved}
          palierRemoved={palierRemoved}
          onSelectCoreSide={editMode ? onSelectCoreSide : undefined}
          selectedCoreSide={editMode ? selectedCoreSide : null}
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

      {/* Contour L FINAL par-dessus TOUT — garantit que la forme du
          bâtiment (L) soit lisible visuellement même avec les jardins
          qui débordent vers la notch. Sans ce trait, les jardins
          ceinturent les apts et masquent l'L → rendu cross. */}
      {footprint && footprint.length >= 3 && (
        <path
          d={ringToPath(footprint, project)}
          fill="none"
          stroke="#0f172a"
          strokeWidth={3.5}
          strokeLinejoin="miter"
          style={{ pointerEvents: "none" }}
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

      {/* PC-grade cotations overlay (opt-in) */}
      {showCotations && footprint && footprint.length >= 3 && (
        <CotationsLayer niveau={niveau} footprint={footprint} project={project} scale={scale} />
      )}

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

      {/* Edit-mode core element drag handles (escalier / asc / palier) */}
      {editMode && selectedCoreElement && corePosition && onCoreElementMove && (() => {
        const side = Math.sqrt(coreSurfaceM2);
        const [cx, cy] = corePosition;
        const defCenters = {
          escalier: [cx - side * 0.21, cy + side * 0.19] as [number, number],
          ascenseur: [cx + side * 0.29, cy + side * 0.19] as [number, number],
          palier: [cx, cy - side * 0.19] as [number, number],
        };
        const overrides = {
          escalier: escalierCenter,
          ascenseur: ascCenter,
          palier: palierCenter,
        };
        const el = selectedCoreElement;
        const pos = overrides[el] ?? defCenters[el];
        return (
          <CoreDragHandle
            position={pos}
            scale={scale}
            project={project}
            box={box}
            onMove={(c) => onCoreElementMove(el, c)}
          />
        );
      })()}

      {/* Edit-mode corridor edge handles */}
      {editMode && selectedCirculationId && onCirculationEdge && (() => {
        const circ = circulations.find((c) => c.id === selectedCirculationId);
        if (!circ) return null;
        const coords = (circulationOverrides?.[circ.id] ?? circ.polygon_xy) as [number, number][];
        return (
          <CirculationEdgeOverlay
            circulationId={circ.id}
            polygon={coords}
            scale={scale}
            project={project}
            box={box}
            onEdge={onCirculationEdge}
            selectedEdgeIdx={selectedCirculationEdge ?? null}
            onSelectEdge={onSelectCirculationEdge}
          />
        );
      })()}

      {/* Edit-mode drag handles for the selected apt */}
      {editMode && selectedAptId && (() => {
        const sel = niveau.cellules.find((c) => c.id === selectedAptId);
        if (!sel) return null;
        // Apply live overrides so the wall handles follow the dragged position
        const sel2 = (wallOverrides || roomOverrides)
          ? {
              ...sel,
              walls: (sel.walls ?? []).map((w) =>
                wallOverrides?.[w.id]
                  ? { ...w, geometry: { ...w.geometry, coords: wallOverrides[w.id] } as typeof w.geometry }
                  : w,
              ),
              rooms: (sel.rooms ?? []).map((r) =>
                roomOverrides?.[r.id]
                  ? { ...r, polygon_xy: roomOverrides[r.id] as typeof r.polygon_xy }
                  : r,
              ),
            }
          : sel;
        return (
          <EditOverlay
            cellule={sel2}
            scale={scale}
            project={project}
            box={box}
            width={width}
            headerPx={HEADER_PX}
            onGeometryChange={onGeometryChange}
            selectedOpeningId={selectedOpeningId}
            onSelectOpening={onSelectOpening}
            addOpeningType={addOpeningType}
            onAddOpening={onAddOpening}
            selectedWallId={selectedWallId}
            onSelectWall={onSelectWall}
            onWallMove={onWallMove}
          />
        );
      })()}
    </svg>
  );
}

/* ═══════════════════════════ CELLULE ═══════════════════════════ */

interface LayerProps {
  cellule: BuildingModelCellule;
  scale: number;
  project: (c: Coord) => Coord;
}

function CelluleLayer({
  cellule, scale, project,
  onSelect, isSelected,
}: LayerProps & { onSelect?: (id: string) => void; isSelected?: boolean }) {
  const [hover, setHover] = useState(false);
  const clickable = cellule.type === "logement" && !!onSelect;
  return (
    <g
      style={clickable ? { cursor: "pointer" } : undefined}
      onClick={clickable ? (e) => { e.stopPropagation(); onSelect!(cellule.id); } : undefined}
      onMouseEnter={clickable ? () => setHover(true) : undefined}
      onMouseLeave={clickable ? () => setHover(false) : undefined}
    >
      {/* Rooms — fill first */}
      {cellule.rooms.map((r) => (
        <RoomFloor key={r.id} room={r} project={project} />
      ))}

      {/* Selection highlight (drawn before walls so walls stay crisp) */}
      {isSelected && (
        <path
          d={ringToPath(cellule.polygon_xy, project)}
          fill="#2563eb"
          fillOpacity={0.12}
          stroke="#2563eb"
          strokeWidth={3}
          strokeDasharray="6 3"
        />
      )}

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

      {/* Hover overlay — drawn last so it's visible above room tiles.
          Faint blue tint signals the apt is clickable in edit mode. */}
      {clickable && hover && !isSelected && (
        <path
          d={ringToPath(cellule.polygon_xy, project)}
          fill="#3b82f6"
          fillOpacity={0.12}
          stroke="#2563eb"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          pointerEvents="none"
        />
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
  // `hidden_edges` is a list of edge indices (edge i goes from vertex i to
  // vertex (i+1)%n) whose stroke should not render. Lets the user remove a
  // "face" of a corridor visually without changing its walkable polygon.
  const hidden: number[] = (circulation as unknown as { hidden_edges?: number[] })
    .hidden_edges ?? [];
  const pts = circulation.polygon_xy;
  return (
    <g>
      {/* Fill without stroke */}
      <path
        d={ringToPath(pts, project)}
        fill="url(#pat-tiles)"
        stroke="none"
      />
      {/* Draw each edge as its own line so hidden ones can be skipped */}
      {pts.map((p, i) => {
        if (hidden.includes(i)) return null;
        const q = pts[(i + 1) % pts.length];
        const [x1, y1] = project(p);
        const [x2, y2] = project(q);
        return (
          <line key={`e-${i}`} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke="#0f172a"
            strokeWidth={stroke}
            strokeLinecap="round"
            pointerEvents="none"
          />
        );
      })}
      <path
        d={ringToPath(pts, project)}
        fill="none"
        stroke="transparent"
        strokeWidth={0}
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
  escalierCenter,
  ascCenter,
  palierCenter,
  selectedCoreElement,
  onSelectCoreElement,
  escalierHiddenSides,
  ascHiddenSides,
  palierHiddenSides,
  escalierRemoved,
  ascRemoved,
  palierRemoved,
  onSelectCoreSide,
  selectedCoreSide,
}: {
  position: [number, number];
  surfaceM2: number;
  hasAscenseur: boolean;
  scale: number;
  project: (c: Coord) => Coord;
  escalierCenter?: [number, number];
  ascCenter?: [number, number];
  palierCenter?: [number, number];
  selectedCoreElement?: "escalier" | "ascenseur" | "palier" | null;
  onSelectCoreElement?: (el: "escalier" | "ascenseur" | "palier" | null) => void;
  /** Per-element hidden wall sides (north/south/east/west). */
  escalierHiddenSides?: string[];
  ascHiddenSides?: string[];
  palierHiddenSides?: string[];
  /** Skip rendering this sub-element entirely (soft-delete via BM flag). */
  escalierRemoved?: boolean;
  ascRemoved?: boolean;
  palierRemoved?: boolean;
  /** Click on a specific side (N/S/E/O) of a core element. */
  onSelectCoreSide?: (el: "escalier" | "ascenseur" | "palier", side: "nord" | "sud" | "est" | "ouest") => void;
  selectedCoreSide?: { el: "escalier" | "ascenseur" | "palier"; side: string } | null;
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

  // Element sizes in world meters (consistent across plans)
  const STAIR_W_M = side * 0.58;
  const STAIR_H_M = side * 0.62;
  const ASC_W_M = side * 0.42;
  const ASC_H_M = side * 0.40;
  const PAL_W_M = side;
  const PAL_H_M = side * 0.38;

  // Default centers relative to core center (match legacy layout)
  const defStairC: [number, number] = [cxM - side * 0.21, cyM + side * 0.19];
  const defAscC: [number, number] = [cxM + side * 0.29, cyM + side * 0.19];
  const defPalC: [number, number] = [cxM, cyM - side * 0.19];

  const stairC = escalierCenter ?? defStairC;
  const ascC = ascCenter ?? defAscC;
  const palC = palierCenter ?? defPalC;

  // Helper: convert center+size (world) to pixel rect {x,y,w,h}
  const toPixelRect = (c: [number, number], wM: number, hM: number) => {
    const [pswX, pswY] = project([c[0] - wM / 2, c[1] - hM / 2]);
    const [pneX, pneY] = project([c[0] + wM / 2, c[1] + hM / 2]);
    return {
      x: Math.min(pswX, pneX),
      y: Math.min(pswY, pneY),
      w: Math.abs(pneX - pswX),
      h: Math.abs(pneY - pswY),
    };
  };

  const stairRect = toPixelRect(stairC, STAIR_W_M, STAIR_H_M);
  const elevRect = toPixelRect(ascC, ASC_W_M, ASC_H_M);
  const palierRect = toPixelRect(palC, PAL_W_M, PAL_H_M);

  const NB_TREADS = 11;
  const selEscalier = selectedCoreElement === "escalier";
  const selAsc = selectedCoreElement === "ascenseur";
  const selPalier = selectedCoreElement === "palier";

  const clickable = !!onSelectCoreElement;

  /** Render the 4 sides of a core-sub-rect as independent <line>s so the
   * user can click any one and hide it (e.g. "remove the north side of
   * the palier square"). */
  const RectSides = ({
    rect, hidden = [], el, selected, baseStrokeWidth,
  }: {
    rect: { x: number; y: number; w: number; h: number };
    hidden?: string[];
    el: "escalier" | "ascenseur" | "palier";
    selected: boolean;
    baseStrokeWidth: number;
  }) => {
    const sides: Array<{ side: "nord" | "sud" | "est" | "ouest"; x1: number; y1: number; x2: number; y2: number }> = [
      // SVG y grows down but world y grows up, so the rect's top-in-SVG is "north" in world.
      { side: "nord", x1: rect.x, y1: rect.y, x2: rect.x + rect.w, y2: rect.y },
      { side: "sud", x1: rect.x, y1: rect.y + rect.h, x2: rect.x + rect.w, y2: rect.y + rect.h },
      { side: "ouest", x1: rect.x, y1: rect.y, x2: rect.x, y2: rect.y + rect.h },
      { side: "est", x1: rect.x + rect.w, y1: rect.y, x2: rect.x + rect.w, y2: rect.y + rect.h },
    ];
    return (
      <g>
        {sides.map(({ side, x1, y1, x2, y2 }) => {
          if (hidden.includes(side)) return null;
          const isSideSelected = selectedCoreSide?.el === el && selectedCoreSide?.side === side;
          const overallSelected = selected;
          const stroke = isSideSelected ? "#dc2626" : overallSelected ? "#dc2626" : "#0f172a";
          const sw = isSideSelected ? 3.5 : overallSelected ? 2 : baseStrokeWidth;
          return (
            <g key={side}>
              {/* Thick transparent hit area so tiny clicks still register */}
              {onSelectCoreSide && (
                <line x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke="white" strokeOpacity={0.001} strokeWidth={14}
                  style={{ cursor: "pointer" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectCoreSide(el, side);
                  }}
                />
              )}
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke} strokeWidth={sw}
                strokeDasharray={isSideSelected ? "4 3" : undefined}
                pointerEvents="none"
              />
            </g>
          );
        })}
      </g>
    );
  };

  return (
    <g>
      {/* Palier strip (clickable) */}
      {!palierRemoved && (
      <g
        style={clickable ? { cursor: "pointer" } : undefined}
        onClick={clickable ? (e) => {
          e.stopPropagation();
          onSelectCoreElement!(selPalier ? null : "palier");
        } : undefined}
      >
        <rect
          x={palierRect.x} y={palierRect.y}
          width={palierRect.w} height={palierRect.h}
          fill="url(#pat-tiles)"
          stroke="none"
        />
        <RectSides rect={palierRect} hidden={palierHiddenSides} el="palier" selected={selPalier} baseStrokeWidth={1.2} />
      </g>
      )}

      {/* Stairs rectangle (clickable) */}
      {!escalierRemoved && (
      <g
        style={clickable ? { cursor: "pointer" } : undefined}
        onClick={clickable ? (e) => {
          e.stopPropagation();
          onSelectCoreElement!(selEscalier ? null : "escalier");
        } : undefined}
      >
      <rect
        x={stairRect.x}
        y={stairRect.y}
        width={stairRect.w}
        height={stairRect.h}
        fill="#e2e8f0"
        stroke="none"
      />
      <RectSides rect={stairRect} hidden={escalierHiddenSides} el="escalier" selected={selEscalier} baseStrokeWidth={1.4} />
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
      </g>
      )}

      {/* Elevator (clickable) — now independently positionable */}
      {hasAscenseur && !ascRemoved && (
        <g
          style={clickable ? { cursor: "pointer" } : undefined}
          onClick={clickable ? (e) => {
            e.stopPropagation();
            onSelectCoreElement!(selAsc ? null : "ascenseur");
          } : undefined}
        >
          <rect
            x={elevRect.x}
            y={elevRect.y}
            width={elevRect.w}
            height={elevRect.h}
            fill="#f8fafc"
            stroke="none"
          />
          <RectSides rect={elevRect} hidden={ascHiddenSides} el="ascenseur" selected={selAsc} baseStrokeWidth={1.2} />
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

      {/* Palier label (centered on palier rect) */}
      {!palierRemoved && (
        <>
          <text
            x={palierRect.x + palierRect.w / 2}
            y={palierRect.y + palierRect.h / 2 - 2}
            textAnchor="middle"
            fontSize={9.5}
            fontWeight={600}
            fill="#334155"
            pointerEvents="none"
          >
            palier
          </text>
          <text
            x={palierRect.x + palierRect.w / 2}
            y={palierRect.y + palierRect.h / 2 + 10}
            textAnchor="middle"
            fontSize={8}
            fill="#64748b"
            pointerEvents="none"
          >
            140 cm
          </text>
        </>
      )}
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
  // The door must land INSIDE the corridor at the voirie edge. Using the
  // full polygon bbox can be misleading when the corridor is T-shaped
  // (narrow at voirie, wider further in for a connector). We therefore
  // take only the vertices actually sitting on the voirie wall and
  // midpoint THOSE — the resulting x is guaranteed to be inside the
  // polygon's voirie strip.
  const boundaryEps = 0.4;
  const midAtVoirie = (c: BuildingModelCirculation): number | null => {
    const pts = c.polygon_xy.filter((p) => {
      if (voirieSide === "sud") return Math.abs(p[1] - box.miny) < boundaryEps;
      if (voirieSide === "nord") return Math.abs(p[1] - box.maxy) < boundaryEps;
      if (voirieSide === "ouest") return Math.abs(p[0] - box.minx) < boundaryEps;
      return Math.abs(p[0] - box.maxx) < boundaryEps;
    });
    if (pts.length < 2) return null;
    const vals = pts.map((p) => (perpIsX ? p[0] : p[1]));
    return (Math.min(...vals) + Math.max(...vals)) / 2;
  };
  let chosen: BuildingModelCirculation | null = hall ?? null;
  if (!chosen && reaching.length > 0) {
    const sortable = reaching
      .map((c) => ({ c, mid: midAtVoirie(c) }))
      .filter((e): e is { c: BuildingModelCirculation; mid: number } => e.mid !== null);
    if (sortable.length > 0) {
      sortable.sort((a, b) => Math.abs(a.mid - coreKey) - Math.abs(b.mid - coreKey));
      chosen = sortable[0].c;
    }
  }

  const chosenMid = chosen ? midAtVoirie(chosen) : null;

  if (voirieSide === "sud") {
    doorMy = box.miny;
    arrowDy = -1;
    doorMx = chosenMid ?? cxM;
  } else if (voirieSide === "nord") {
    doorMy = box.maxy;
    arrowDy = 1;
    doorMx = chosenMid ?? cxM;
  } else if (voirieSide === "est") {
    doorMx = box.maxx;
    arrowDx = 1;
    arrowDy = 0;
    doorMy = chosenMid ?? cyM;
  } else {
    // ouest
    doorMx = box.minx;
    arrowDx = -1;
    arrowDy = 0;
    doorMy = chosenMid ?? cyM;
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


/* ═════════════════════ EDIT OVERLAY ═════════════════════ */

type BBox = { minx: number; miny: number; maxx: number; maxy: number };

/** Convert a pixel coord in the SVG back to world (meters). Mirrors
 * ``makeProjector`` in plan-utils.ts. */
function makeInverseProjector(
  box: BBox, width: number, planHeight: number, padding: number, headerPx: number,
) {
  const w = box.maxx - box.minx || 1;
  const h = box.maxy - box.miny || 1;
  const scale = Math.min((width - 2 * padding) / w, (planHeight - 2 * padding) / h);
  const drawnW = w * scale;
  const drawnH = h * scale;
  const offsetX = (width - drawnW) / 2;
  const offsetY = (planHeight - drawnH) / 2;
  return ([px, py]: [number, number]): [number, number] => [
    box.minx + (px - offsetX) / scale,
    box.miny + (planHeight - offsetY - (py - headerPx)) / scale,
  ];
}

function EditOverlay({
  cellule, scale, project, box, width, headerPx, onGeometryChange,
  selectedOpeningId, onSelectOpening,
  addOpeningType, onAddOpening,
  selectedWallId, onSelectWall, onWallMove,
}: {
  cellule: BuildingModelCellule;
  scale: number;
  project: (c: Coord) => Coord;
  box: BBox;
  width: number;
  headerPx: number;
  onGeometryChange?: NiveauPlanProps["onGeometryChange"];
  selectedOpeningId?: string | null;
  onSelectOpening?: (id: string | null) => void;
  addOpeningType?: "fenetre" | "porte_fenetre" | "porte_interieure" | null;
  onAddOpening?: (op: {
    type: "fenetre" | "porte_fenetre" | "porte_interieure";
    wall_id: string;
    position_along_wall_cm: number;
  }) => void;
  selectedWallId?: string | null;
  onSelectWall?: (id: string | null) => void;
  onWallMove?: (wallId: string, newCoords: [number, number][]) => void;
}) {
  const [openingOverrides, setOpeningOverrides] = useState<Record<string, number>>({});
  const [draggingId, setDraggingId] = useState<string | null>(null);

  const walls = cellule.walls ?? [];
  const wallMap = new Map(walls.map((w) => [w.id, w]));

  // Convert a mouse/touch client point to world meters by walking up to
  // the enclosing <svg> and using its CTM. Robust to window resize/zoom.
  const clientToWorld = useCallback(
    (clientX: number, clientY: number, svgEl: SVGSVGElement): [number, number] | null => {
      const pt = svgEl.createSVGPoint();
      pt.x = clientX;
      pt.y = clientY;
      const ctm = svgEl.getScreenCTM();
      if (!ctm) return null;
      const p = pt.matrixTransform(ctm.inverse());
      const [refPx, refPy] = project([box.minx, box.miny]);
      return [
        box.minx + (p.x - refPx) / scale,
        box.miny + (refPy - p.y) / scale,
      ];
    },
    [box, project, scale],
  );

  // SVG ref captured at drag-start. Stored in a ref so we always
  // operate on the SAME <svg> the user clicked (crucial when multiple
  // plans are rendered — the thumbnail AND the dialog share the same
  // data-attribute).
  const dragSvgRef = useRef<SVGSVGElement | null>(null);

  // Global drag listeners — attached once dragging starts, cleaned up on
  // release. Using document listeners is more reliable than SVG pointer
  // capture across browsers.
  useEffect(() => {
    if (!draggingId) return;
    const op = (cellule.openings ?? []).find((o) => o.id === draggingId);
    if (!op) return;
    const wall = wallMap.get(op.wall_id);
    if (!wall) return;
    const coords = wall.geometry?.coords as [number, number][] | undefined;
    if (!coords || coords.length < 2) return;
    const [a, b] = coords;
    const wx = b[0] - a[0];
    const wy = b[1] - a[1];
    const wallLenM = Math.hypot(wx, wy);
    const wallLenCm = wallLenM * 100;
    const wallLen2 = wx * wx + wy * wy;
    if (wallLen2 < 1e-6) return;

    const onMove = (e: MouseEvent) => {
      const svgEl = dragSvgRef.current;
      if (!svgEl) return;
      const world = clientToWorld(e.clientX, e.clientY, svgEl);
      if (!world) return;
      const dx = world[0] - a[0];
      const dy = world[1] - a[1];
      const t = (dx * wx + dy * wy) / wallLen2;
      const clamped = Math.max(0.05, Math.min(0.95, t));
      const newPosCm = Math.round((clamped * wallLenCm) / 5) * 5;
      setOpeningOverrides((prev) => ({ ...prev, [op.id]: newPosCm }));
    };
    const onUp = () => {
      setDraggingId(null);
      dragSvgRef.current = null;
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [draggingId, cellule.openings, wallMap, clientToWorld]);

  // On drag release commit the change upstream (so the parent can save)
  const lastDraggedIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (draggingId) {
      lastDraggedIdRef.current = draggingId;
      return;
    }
    const id = lastDraggedIdRef.current;
    if (!id || !onGeometryChange) return;
    const pos = openingOverrides[id];
    if (pos == null) return;
    onGeometryChange({
      apt_id: cellule.id,
      openings: [{ opening_id: id, position_along_wall_cm: pos }],
    });
    lastDraggedIdRef.current = null;
  }, [draggingId, openingOverrides, onGeometryChange, cellule.id]);

  function OpeningHandle({ op }: { op: BuildingModelOpening }) {
    const wall = wallMap.get(op.wall_id);
    if (!wall) return null;
    const coords = wall.geometry?.coords as [number, number][] | undefined;
    if (!coords || coords.length < 2) return null;
    const [a, b] = coords;
    const wallLenM = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const wallLenCm = wallLenM * 100;
    const posCm = openingOverrides[op.id] ?? op.position_along_wall_cm ?? wallLenCm / 2;
    const t = Math.max(0, Math.min(1, posCm / Math.max(1, wallLenCm)));
    const world: [number, number] = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
    const [px, py] = project(world);

    const isDoor = op.type === "porte_entree" || op.type === "porte_interieure";
    const fill = isDoor ? "#f59e0b" : "#0ea5e9";
    const isActive = draggingId === op.id;
    const isSelected = selectedOpeningId === op.id;
    const radius = isActive || isSelected ? 10 : 8;
    return (
      <g
        onMouseDown={(e) => {
          e.stopPropagation();
          e.preventDefault();
          // Capture the ACTUAL SVG we're inside (handles the case where
          // multiple plans share the same [data-niveau-plan] attribute).
          const svgEl = (e.currentTarget as SVGElement).ownerSVGElement;
          if (svgEl) dragSvgRef.current = svgEl;
          onSelectOpening?.(op.id);
          setDraggingId(op.id);
        }}
        style={{ cursor: isActive ? "grabbing" : "grab" }}
      >
        <circle cx={px} cy={py} r={18} fill="white" fillOpacity={0.001} />
        <circle
          cx={px} cy={py}
          r={radius}
          fill={fill}
          stroke={isSelected ? "#dc2626" : "white"}
          strokeWidth={isSelected ? 3 : 2}
        />
        <text x={px} y={py + 3} textAnchor="middle" fontSize={9} fill="white" fontWeight={700}>
          {isDoor ? "⇅" : "◇"}
        </text>
      </g>
    );
  }

  // --- Add-opening mode: overlay clickable hit zones on each candidate wall
  const exteriorTypes: Record<string, true> = {
    fenetre: true, porte_fenetre: true,
  };
  const isExteriorAdd = addOpeningType ? addOpeningType in exteriorTypes : false;

  function WallHitZone({ wall }: { wall: BuildingModelWall }) {
    const coords = wall.geometry?.coords as [number, number][] | undefined;
    if (!coords || coords.length < 2) return null;
    // Exterior openings go on PORTEUR walls (perimeter); interior on
    // cloisons. Filter by wall type for clarity.
    const isPorteur = wall.type === "porteur";
    if (isExteriorAdd && !isPorteur) return null;
    if (!isExteriorAdd && isPorteur) return null;
    const [a, b] = coords;
    const [ax, ay] = project(a);
    const [bx, by] = project(b);
    // Thick transparent line as hit zone
    const onClick = (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!onAddOpening || !addOpeningType) return;
      const svgEl = (e.currentTarget as SVGElement).ownerSVGElement;
      if (!svgEl) return;
      const world = clientToWorld(e.clientX, e.clientY, svgEl);
      if (!world) return;
      const dx = world[0] - a[0];
      const dy = world[1] - a[1];
      const wx = b[0] - a[0];
      const wy = b[1] - a[1];
      const wallLen2 = wx * wx + wy * wy;
      if (wallLen2 < 1e-6) return;
      const t = Math.max(0.05, Math.min(0.95, (dx * wx + dy * wy) / wallLen2));
      const wallLenCm = Math.hypot(wx, wy) * 100;
      const pos = Math.round((t * wallLenCm) / 5) * 5;
      onAddOpening({
        type: addOpeningType,
        wall_id: wall.id,
        position_along_wall_cm: pos,
      });
    };
    return (
      <g onClick={onClick} style={{ cursor: "crosshair" }}>
        {/* Transparent fat line for clicking */}
        <line x1={ax} y1={ay} x2={bx} y2={by} stroke="white" strokeOpacity={0.001} strokeWidth={16} />
        {/* Visible highlight */}
        <line x1={ax} y1={ay} x2={bx} y2={by} stroke="#22c55e" strokeWidth={3} strokeDasharray="6 3" />
      </g>
    );
  }

  // ─── Wall dragging (cloisons internes) ───
  const [draggingWallId, setDraggingWallId] = useState<string | null>(null);
  const wallSvgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (!draggingWallId) return;
    const wall = (cellule.walls ?? []).find((w) => w.id === draggingWallId);
    if (!wall || wall.type === "porteur") return;
    const coords = wall.geometry?.coords as [number, number][] | undefined;
    if (!coords || coords.length < 2) return;
    const [a, b] = coords;
    const isVertical = Math.abs(b[0] - a[0]) < 0.01;
    const isHorizontal = Math.abs(b[1] - a[1]) < 0.01;
    if (!isVertical && !isHorizontal) return; // only axis-aligned walls

    const onMove = (e: MouseEvent) => {
      const svgEl = wallSvgRef.current;
      if (!svgEl) return;
      const world = clientToWorld(e.clientX, e.clientY, svgEl);
      if (!world) return;
      let newCoords: [number, number][];
      if (isVertical) {
        // Clamp to apt bbox to stay inside the cellule
        const aptXs = cellule.polygon_xy.map((p) => p[0]);
        const newX = Math.max(
          Math.min(...aptXs) + 0.5,
          Math.min(Math.max(...aptXs) - 0.5, Math.round(world[0] * 10) / 10),
        );
        newCoords = [[newX, a[1]], [newX, b[1]]];
      } else {
        const aptYs = cellule.polygon_xy.map((p) => p[1]);
        const newY = Math.max(
          Math.min(...aptYs) + 0.5,
          Math.min(Math.max(...aptYs) - 0.5, Math.round(world[1] * 10) / 10),
        );
        newCoords = [[a[0], newY], [b[0], newY]];
      }
      onWallMove?.(draggingWallId, newCoords);
    };
    const onUp = () => {
      setDraggingWallId(null);
      wallSvgRef.current = null;
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [draggingWallId, cellule, clientToWorld, onWallMove]);

  function WallHandle({ wall }: { wall: BuildingModelWall }) {
    const coords = wall.geometry?.coords as [number, number][] | undefined;
    if (!coords || coords.length < 2) return null;
    const [a, b] = coords;
    const [ax, ay] = project(a);
    const [bx, by] = project(b);
    const midWorld: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const [mx, my] = project(midWorld);
    const isSelected = selectedWallId === wall.id;
    const isActive = draggingWallId === wall.id;
    const isPorteur = wall.type === "porteur";
    const fill = isPorteur ? "#64748b" : "#8b5cf6";

    const onSelectMouseDown = (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      const svgEl = (e.currentTarget as SVGElement).ownerSVGElement;
      if (svgEl) wallSvgRef.current = svgEl;
      onSelectWall?.(wall.id);
      // Drag only for cloisons (non-porteur)
      if (!isPorteur) setDraggingWallId(wall.id);
    };

    return (
      <g>
        {/* Entire wall length as invisible click target (16 px wide) */}
        <line
          x1={ax} y1={ay} x2={bx} y2={by}
          stroke="white" strokeOpacity={0.001}
          strokeWidth={16}
          style={{ cursor: isActive ? "grabbing" : isPorteur ? "pointer" : "grab" }}
          onMouseDown={onSelectMouseDown}
        />
        {/* Visible highlight along selected wall so user sees what they picked */}
        {isSelected && (
          <line
            x1={ax} y1={ay} x2={bx} y2={by}
            stroke="#dc2626"
            strokeWidth={4}
            strokeDasharray="5 3"
            pointerEvents="none"
          />
        )}
        {/* Small midpoint handle (color-coded) for drag/visual reference */}
        <g
          onMouseDown={onSelectMouseDown}
          style={{ cursor: isActive ? "grabbing" : isPorteur ? "pointer" : "grab" }}
        >
          <circle cx={mx} cy={my} r={14} fill="white" fillOpacity={0.001} />
          <rect
            x={mx - 6} y={my - 6}
            width={12} height={12}
            rx={2}
            fill={fill}
            stroke={isSelected ? "#dc2626" : "white"}
            strokeWidth={isSelected ? 3 : 2}
          />
          <text x={mx} y={my + 3} textAnchor="middle" fontSize={8} fill="white" fontWeight={700}>
            {isPorteur ? "■" : "↔"}
          </text>
        </g>
      </g>
    );
  }

  const openings = cellule.openings ?? [];
  void headerPx; void width;
  return (
    <g>
      {addOpeningType && walls.map((w) => (
        <WallHitZone key={w.id} wall={w} />
      ))}
      {/* Wall drag handles — only for internal cloisons, only when not in add-opening mode */}
      {!addOpeningType && walls.map((w) => (
        <WallHandle key={`wh-${w.id}`} wall={w} />
      ))}
      {openings.map((op) => (
        <OpeningHandle key={op.id} op={op} />
      ))}
    </g>
  );
}


/* ═══════════════════ CORE DRAG HANDLE ═══════════════════ */

function CoreDragHandle({
  position, scale, project, box, onMove,
}: {
  position: [number, number];
  scale: number;
  project: (c: Coord) => Coord;
  box: BBox;
  onMove: (pos: [number, number]) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [px, py] = project(position);

  useEffect(() => {
    if (!dragging) return;
    const onMouseMove = (e: MouseEvent) => {
      const svgEl = svgRef.current;
      if (!svgEl) return;
      const pt = svgEl.createSVGPoint();
      pt.x = e.clientX; pt.y = e.clientY;
      const ctm = svgEl.getScreenCTM();
      if (!ctm) return;
      const p = pt.matrixTransform(ctm.inverse());
      const [refPx, refPy] = project([box.minx, box.miny]);
      const x = box.minx + (p.x - refPx) / scale;
      const y = box.miny + (refPy - p.y) / scale;
      // Snap to 10cm
      onMove([Math.round(x * 10) / 10, Math.round(y * 10) / 10]);
    };
    const onUp = () => { setDragging(false); svgRef.current = null; };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [dragging, box, project, scale, onMove]);

  return (
    <g
      onMouseDown={(e) => {
        e.stopPropagation();
        e.preventDefault();
        svgRef.current = (e.currentTarget as SVGElement).ownerSVGElement;
        setDragging(true);
      }}
      style={{ cursor: dragging ? "grabbing" : "move" }}
    >
      <circle cx={px} cy={py} r={22} fill="white" fillOpacity={0.001} />
      <circle cx={px} cy={py} r={14} fill="#0ea5e9" stroke="white" strokeWidth={3} />
      <text x={px} y={py + 5} textAnchor="middle" fontSize={14} fontWeight={700} fill="white">
        ✢
      </text>
    </g>
  );
}


/* ═══════════════════ CIRCULATION EDGE OVERLAY ═══════════════════ */

function CirculationEdgeOverlay({
  circulationId, polygon, scale, project, box, onEdge,
  onSelectEdge, selectedEdgeIdx,
}: {
  circulationId: string;
  polygon: [number, number][];
  scale: number;
  project: (c: Coord) => Coord;
  box: BBox;
  onEdge: (id: string, coords: [number, number][]) => void;
  onSelectEdge?: (idx: number | null) => void;
  selectedEdgeIdx?: number | null;
}) {
  const [draggingEdgeIdx, setDraggingEdgeIdx] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (draggingEdgeIdx == null) return;
    const i = draggingEdgeIdx;
    const a = polygon[i];
    const b = polygon[(i + 1) % polygon.length];
    const isVertical = Math.abs(a[0] - b[0]) < 0.01;
    const isHorizontal = Math.abs(a[1] - b[1]) < 0.01;
    if (!isVertical && !isHorizontal) return;

    const onMove = (e: MouseEvent) => {
      const svgEl = svgRef.current;
      if (!svgEl) return;
      const pt = svgEl.createSVGPoint();
      pt.x = e.clientX; pt.y = e.clientY;
      const ctm = svgEl.getScreenCTM();
      if (!ctm) return;
      const p = pt.matrixTransform(ctm.inverse());
      const [refPx, refPy] = project([box.minx, box.miny]);
      const worldX = box.minx + (p.x - refPx) / scale;
      const worldY = box.miny + (refPy - p.y) / scale;

      // Update both endpoints of this edge (axis-aligned move)
      const newPolygon = polygon.map((pt, idx) => {
        const isEdgePt = idx === i || idx === (i + 1) % polygon.length;
        if (!isEdgePt) return pt;
        if (isVertical) return [Math.round(worldX * 10) / 10, pt[1]] as [number, number];
        return [pt[0], Math.round(worldY * 10) / 10] as [number, number];
      }) as [number, number][];
      onEdge(circulationId, newPolygon);
    };
    const onUp = () => { setDraggingEdgeIdx(null); svgRef.current = null; };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [draggingEdgeIdx, polygon, box, project, scale, circulationId, onEdge]);

  return (
    <g>
      {polygon.map((a, i) => {
        const b = polygon[(i + 1) % polygon.length];
        const isVertical = Math.abs(a[0] - b[0]) < 0.01;
        const isHorizontal = Math.abs(a[1] - b[1]) < 0.01;
        const [ax, ay] = project(a);
        const [bx, by] = project(b);
        const midWorld: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        const [mx, my] = project(midWorld);
        const active = draggingEdgeIdx === i;
        const isSelected = selectedEdgeIdx === i;
        const draggable = isVertical || isHorizontal;
        return (
          <g key={`ce-${i}`}>
            {/* Entire edge clickable (for select + visual feedback) */}
            <line x1={ax} y1={ay} x2={bx} y2={by}
              stroke="white" strokeOpacity={0.001} strokeWidth={16}
              style={{ cursor: "pointer" }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectEdge?.(isSelected ? null : i);
              }}
            />
            {isSelected && (
              <line x1={ax} y1={ay} x2={bx} y2={by}
                stroke="#dc2626" strokeWidth={4} strokeDasharray="5 3" pointerEvents="none"
              />
            )}
            {/* Midpoint drag handle (only if axis-aligned) */}
            {draggable && (
              <g
                onMouseDown={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  svgRef.current = (e.currentTarget as SVGElement).ownerSVGElement;
                  onSelectEdge?.(i);
                  setDraggingEdgeIdx(i);
                }}
                style={{ cursor: active ? "grabbing" : "grab" }}
              >
                <circle cx={mx} cy={my} r={16} fill="white" fillOpacity={0.001} />
                <rect x={mx - 6} y={my - 6} width={12} height={12} rx={2}
                  fill="#ec4899" stroke={isSelected ? "#dc2626" : "white"} strokeWidth={isSelected ? 3 : 2} />
              </g>
            )}
          </g>
        );
      })}
    </g>
  );
}
