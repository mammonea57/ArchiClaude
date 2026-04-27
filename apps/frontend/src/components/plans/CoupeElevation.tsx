"use client";

import type { BuildingModelPayload } from "@/lib/types";
import { PlanPatterns, NorthArrow, ScaleBar, TitleBlock } from "./plan-patterns";
import {
  bboxOf,
  coordsFromGeoJSON,
  polygonLineIntersectIntervals,
  roomLabelTiny,
  segmentCrossAxis,
  type Coord,
} from "./plan-utils";

const SIDE_LABEL: Record<"nord" | "sud" | "est" | "ouest", string> = {
  nord: "Nord",
  sud: "Sud",
  est: "Est",
  ouest: "Ouest",
};

const FACADE_SHEET: Record<"nord" | "sud" | "est" | "ouest", 1 | 2 | 3 | 4> = {
  nord: 1,
  sud: 2,
  est: 3,
  ouest: 4,
};

type FacadeSide = "nord" | "sud" | "est" | "ouest";

/** A façade silhouette segment in WORLD coordinates.
 *  - For N/S sides: startCoord/endCoord are world X; depth is world Y of the visible face.
 *  - For E/O sides: startCoord/endCoord are world Y; depth is world X of the visible face.
 *  - isFront = the closest face to the viewer (not recessed). */
type FacadeSegment = {
  startCoord: number;
  endCoord: number;
  depth: number;
  isFront: boolean;
  /** Distance (in world meters) by which this segment is recessed from the front-most plane. 0 if isFront. */
  recessM: number;
};

/** Project a closed footprint polygon (axis-aligned segments expected) onto the
 *  cardinal direction `side` and return the visible face per perpendicular interval.
 *  Two stepped segments → L-shape silhouette; single segment → flat façade. */
function computeFacadeSilhouette(
  footprint: number[][],
  side: FacadeSide,
): FacadeSegment[] {
  // Walls perpendicular to the viewing axis = candidate faces.
  type Wall = { startCoord: number; endCoord: number; depth: number };
  const walls: Wall[] = [];
  for (let i = 0; i < footprint.length - 1; i++) {
    const [x1, y1] = footprint[i];
    const [x2, y2] = footprint[i + 1];
    if (side === "nord" || side === "sud") {
      // Horizontal walls (constant y) face north/south.
      if (Math.abs(y1 - y2) > 0.05) continue;
      const startCoord = Math.min(x1, x2);
      const endCoord = Math.max(x1, x2);
      walls.push({ startCoord, endCoord, depth: (y1 + y2) / 2 });
    } else {
      // Vertical walls (constant x) face east/west.
      if (Math.abs(x1 - x2) > 0.05) continue;
      const startCoord = Math.min(y1, y2);
      const endCoord = Math.max(y1, y2);
      walls.push({ startCoord, endCoord, depth: (x1 + x2) / 2 });
    }
  }
  if (walls.length === 0) return [];

  // Sweep all break points; for each interval pick the visible-face depth.
  const breakPoints = new Set<number>();
  for (const w of walls) {
    breakPoints.add(w.startCoord);
    breakPoints.add(w.endCoord);
  }
  const sorted = [...breakPoints].sort((a, b) => a - b);

  const pickFront = side === "sud" || side === "ouest"
    ? (vals: number[]) => Math.min(...vals)
    : (vals: number[]) => Math.max(...vals);

  type Iv = { startCoord: number; endCoord: number; depth: number };
  const ivs: Iv[] = [];
  for (let i = 0; i < sorted.length - 1; i++) {
    const start = sorted[i];
    const end = sorted[i + 1];
    if (end - start < 0.05) continue;
    const mid = (start + end) / 2;
    const candidates = walls.filter((w) => w.startCoord <= mid && w.endCoord >= mid);
    if (candidates.length === 0) continue;
    const depth = pickFront(candidates.map((c) => c.depth));
    ivs.push({ startCoord: start, endCoord: end, depth });
  }
  // Coalesce adjacent intervals with same depth.
  const merged: Iv[] = [];
  for (const iv of ivs) {
    const last = merged[merged.length - 1];
    if (last && Math.abs(last.endCoord - iv.startCoord) < 0.05 && Math.abs(last.depth - iv.depth) < 0.05) {
      last.endCoord = iv.endCoord;
    } else {
      merged.push({ ...iv });
    }
  }
  if (merged.length === 0) return [];

  // Front-most plane and per-segment recess distance.
  const allDepths = merged.map((m) => m.depth);
  const frontDepth = side === "sud" || side === "ouest" ? Math.min(...allDepths) : Math.max(...allDepths);
  return merged.map((m) => ({
    startCoord: m.startCoord,
    endCoord: m.endCoord,
    depth: m.depth,
    isFront: Math.abs(m.depth - frontDepth) < 0.05,
    recessM: Math.abs(m.depth - frontDepth),
  }));
}

interface CoupeElevationProps {
  bm: BuildingModelPayload;
  mode: "coupe" | "facade";
  /** For mode="coupe" only: "AA" = transversale (y-axis), "BB" = longitudinale (x-axis). Default "AA". */
  cutAxis?: "AA" | "BB";
  /** For mode="facade" only: cardinal side being drawn. Default = first voirie side, fallback "sud". */
  facadeSide?: FacadeSide;
  width?: number;
  height?: number;
  projectName?: string;
}

/**
 * Section (coupe) or elevation (façade) drawn from BM envelope + niveaux.
 * - Coupe: ground hatch, concrete slabs (filled), rooms per story, stairs marker
 * - Façade: wall finish pattern, window grid, parapet, ground line
 * Both: scale bar on side, height dimensions, story codes, title block.
 */
export function CoupeElevation({
  bm, mode, cutAxis = "AA", facadeSide, width = 900, height = 620, projectName,
}: CoupeElevationProps) {
  const env = bm.envelope;
  const niveaux = [...bm.niveaux].sort((a, b) => a.index - b.index);
  const voirieAll = (bm.site.voirie_orientations ?? ["sud"]) as FacadeSide[];
  const voirieFirst = (voirieAll[0] ?? "sud") as FacadeSide;
  const side: FacadeSide = facadeSide ?? voirieFirst;
  // Corner buildings have multiple voirie sides — treat ALL of them as
  // principale so each gets balcons filants + door entrance treatment.
  const isVoirieSide = mode === "facade" && voirieAll.includes(side);
  const isMainVoirie = mode === "facade" && side === voirieFirst;

  // Horizontal span from footprint bbox (mode-dependent)
  let spanM = Math.sqrt(env.emprise_m2);
  let facadeSilhouette: FacadeSegment[] = [];
  let facadeWorldStart = 0; // World coord that maps to facade_x = 0 (left edge)
  let facadeWorldDir: 1 | -1 = 1; // +1 if facade_x increases with world coord, -1 if reversed
  const footprint = env.footprint_geojson as { coordinates?: number[][][] } | undefined;
  if (footprint?.coordinates?.[0]) {
    const coords = footprint.coordinates[0];
    const xs = coords.map((c) => c[0]);
    const ys = coords.map((c) => c[1]);
    const w = Math.max(...xs) - Math.min(...xs);
    const h = Math.max(...ys) - Math.min(...ys);
    // N/S façades = x-extent (horizontal run). E/O façades = y-extent.
    // Coupe AA' = y-extent (transversale, perpendicular to voirie).
    // Coupe BB' = x-extent (longitudinale, parallel to voirie).
    if (mode === "facade") {
      spanM = (side === "nord" || side === "sud") ? w : h;
      facadeSilhouette = computeFacadeSilhouette(coords, side);
      // Architectural convention for façade drawings (viewer outside, facing
      // building):
      //   Sud: viewer at -Y, facade_x ↑ ⇒ world_x ↑   (left=west, right=east)
      //   Nord: viewer at +Y, facade_x ↑ ⇒ world_x ↓  (left=east, right=west)
      //   Est: viewer at +X, facade_x ↑ ⇒ world_y ↑   (left=south, right=north)
      //   Ouest: viewer at -X, facade_x ↑ ⇒ world_y ↓ (left=north, right=south)
      const xMin = Math.min(...xs), xMax = Math.max(...xs);
      const yMin = Math.min(...ys), yMax = Math.max(...ys);
      if (side === "sud") { facadeWorldStart = xMin; facadeWorldDir = 1; }
      else if (side === "nord") { facadeWorldStart = xMax; facadeWorldDir = -1; }
      else if (side === "est") { facadeWorldStart = yMin; facadeWorldDir = 1; }
      else { facadeWorldStart = yMax; facadeWorldDir = -1; }
    } else {
      spanM = cutAxis === "BB" ? w : h;
    }
  }

  // Total height + 1m for parapet + below-ground
  const totalHeightM = env.hauteur_totale_m + 1.2;
  const groundDepthM = 1.5;

  const padLeft = 80;
  const padRight = 60;
  // padTop = 110 leaves ~30px clearance between the title-bar bottom (y=58)
  // and the top of the parapet, so the ACROTÈRE label and the parapet itself
  // are no longer hidden behind the title bar's white fill.
  const padTop = 110;
  const padBottom = 90;
  const innerW = width - padLeft - padRight;
  const innerH = height - padTop - padBottom;

  const scaleX = innerW / (spanM + 2);
  const scaleY = innerH / (totalHeightM + groundDepthM);
  const scale = Math.min(scaleX, scaleY);

  // Adjusted so things fit
  const worldToPx = (xM: number, yM: number): [number, number] => {
    // y measured from ground (0) upwards
    const baseY = padTop + innerH - groundDepthM * scale;
    return [padLeft + xM * scale, baseY - yM * scale];
  };

  const [bx0, by0] = worldToPx(0, 0);
  const spanPx = spanM * scale;
  const totalHPx = env.hauteur_totale_m * scale;

  // Story Y positions (from ground up)
  type Story = { code: string; yBase: number; height: number; usage: string; hsp: number };
  const stories: Story[] = [];
  let y = 0;
  for (let i = 0; i < env.niveaux; i++) {
    const storyH = i === 0 ? env.hauteur_rdc_m : env.hauteur_etage_courant_m;
    stories.push({
      code: niveaux[i]?.code ?? `R+${i}`,
      yBase: y,
      height: storyH,
      usage: niveaux[i]?.usage_principal ?? "—",
      hsp: niveaux[i]?.hauteur_sous_plafond_m ?? storyH - 0.25,
    });
    y += storyH;
  }

  const parapetH = 1.1;
  const parapetPx = parapetH * scale;

  // Derived: openings per story (sample) — for façade grid
  const openingsByStory: number[] = stories.map((s, i) => {
    const niv = niveaux[i];
    if (!niv) return 0;
    return niv.cellules
      .flatMap((c) => c.openings ?? [])
      .filter((o) => ["fenetre", "porte_fenetre", "baie_coulissante"].includes(o.type))
      .length;
  });

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="bg-white border border-slate-200 rounded-lg"
      style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
    >
      <PlanPatterns />

      {/* Sheet border */}
      <rect x={12} y={12} width={width - 24} height={height - 24} fill="white" stroke="#0f172a" strokeWidth={0.6} />

      {/* Ground + below-ground hatch */}
      {mode === "coupe" ? (
        <CoupeGroundProfile
          x={padLeft - 30}
          width={innerW + 60}
          y={by0}
          depthPx={groundDepthM * scale}
          scale={scale}
          buildingX0={bx0}
          buildingX1={bx0 + spanPx}
        />
      ) : (
        <>
          <rect
            x={padLeft - 30}
            y={by0}
            width={innerW + 60}
            height={groundDepthM * scale}
            fill="url(#pat-ground)"
            stroke="#0f172a"
            strokeWidth={0.7}
          />
          <line
            x1={padLeft - 30}
            y1={by0}
            x2={padLeft + innerW + 30}
            y2={by0}
            stroke="#0f172a"
            strokeWidth={1.3}
          />
        </>
      )}

      {/* Sky fade above */}
      <rect x={padLeft - 30} y={padTop - 10} width={innerW + 60} height={by0 - padTop + 10} fill="#f8fafc" />

      {/* Building volume */}
      {mode === "coupe" ? (
        <CoupeBody
          bm={bm}
          cutAxis={cutAxis}
          stories={stories}
          worldToPx={worldToPx}
          spanPx={spanPx}
          scale={scale}
          parapetPx={parapetPx}
        />
      ) : (
        <FacadeBody
          stories={stories}
          openingsByStory={openingsByStory}
          worldToPx={worldToPx}
          spanPx={spanPx}
          scale={scale}
          parapetPx={parapetPx}
          env={env}
          showEntry={isMainVoirie}
          isVoirieAny={isVoirieSide}
          side={side}
          silhouette={facadeSilhouette}
          facadeWorldStart={facadeWorldStart}
          facadeWorldDir={facadeWorldDir}
        />
      )}

      {/* Width dimension under building (façade mode only) */}
      {mode === "facade" && (
        <WidthDim
          xLeft={bx0}
          xRight={bx0 + spanPx}
          y={by0 + 18}
          widthM={spanM}
        />
      )}

      {/* Renvois coupe AA' / BB' — marqueurs en BAS de la façade pointant
          vers les traces de coupe. Convention PC : cercle coté + lettre +
          tirets verticaux en pointillé remontant vers la façade.
          - AA' (transversale) → visible sur les façades perpendiculaires
            à la voirie principale.
          - BB' (longitudinale) → visible sur les façades parallèles à la
            voirie principale. */}
      {mode === "facade" && (() => {
        const isHorizontalVoirie = voirieFirst === "est" || voirieFirst === "ouest";
        const showAA = isHorizontalVoirie ? (side === "nord" || side === "sud") : (side === "est" || side === "ouest");
        const showBB = isHorizontalVoirie ? (side === "est" || side === "ouest") : (side === "nord" || side === "sud");
        const renderTrace = (label: string, fracX: number, key: string) => {
          const x = bx0 + spanPx * fracX;
          // Marqueur sur LE MUR à hauteur RDC (entre soubassement et fin
          // ground line) — visible sur le bâtiment, pas dans la zone cartouche.
          const yCircle = by0 - 16;
          const yTraceTop = padTop + 4;
          return (
            <g key={key}>
              {/* Trace pointillée verticale parcourant toute la hauteur du
                  bâtiment (le plan de coupe traverse). */}
              <line x1={x} y1={yTraceTop} x2={x} y2={yCircle - 8} stroke="#0f172a" strokeWidth={0.6} strokeDasharray="4 2" opacity={0.55} />
              {/* Petite flèche en haut indiquant le sens de regard */}
              <polygon points={`${x},${yTraceTop} ${x - 3},${yTraceTop + 6} ${x + 3},${yTraceTop + 6}`} fill="#0f172a" />
              {/* Cercle coté + lettre */}
              <circle cx={x} cy={yCircle} r={8} fill="white" stroke="#0f172a" strokeWidth={1.0} />
              <text x={x} y={yCircle + 3.2} textAnchor="middle" fontSize={9.5} fontWeight={700} fill="#0f172a" fontFamily="system-ui">
                {label}
              </text>
            </g>
          );
        };
        return (
          <g>
            {showAA && renderTrace("A", 0.5, "aa")}
            {showBB && renderTrace("B", 0.5, "bb")}
          </g>
        );
      })()}

      {/* Chaîne de cotes intermédiaires en bas — si le L silhouette comprend
          plusieurs segments, on cote chaque segment + le total. Convention PC
          (cotes empilées sous la cote totale). */}
      {mode === "facade" && facadeSilhouette.length > 1 && (() => {
        const yChain = by0 + 36;
        return (
          <g>
            {facadeSilhouette.map((s, i) => {
              const a = facadeWorldDir * (s.startCoord - facadeWorldStart);
              const b = facadeWorldDir * (s.endCoord - facadeWorldStart);
              const segStart = Math.min(a, b);
              const segEnd = Math.max(a, b);
              const x1 = bx0 + segStart * scale;
              const x2 = bx0 + segEnd * scale;
              const segM = segEnd - segStart;
              return (
                <g key={`cot-${i}`}>
                  <line x1={x1} y1={yChain} x2={x2} y2={yChain} stroke="#0f172a" strokeWidth={0.5} />
                  {/* Tirets verticaux aux extrémités */}
                  <line x1={x1} y1={yChain - 4} x2={x1} y2={yChain + 4} stroke="#0f172a" strokeWidth={0.7} />
                  <line x1={x2} y1={yChain - 4} x2={x2} y2={yChain + 4} stroke="#0f172a" strokeWidth={0.7} />
                  {/* Label cote au centre */}
                  <text x={(x1 + x2) / 2} y={yChain - 3} textAnchor="middle" fontSize={8.5} fontWeight={600} fill="#0f172a">
                    {segM.toFixed(2)} m
                  </text>
                  {/* Petit indicateur front/recessed */}
                  <text x={(x1 + x2) / 2} y={yChain + 11} textAnchor="middle" fontSize={6.5} fill="#64748b">
                    {s.isFront ? "Plan principal" : `Retrait ${s.recessM.toFixed(1)} m`}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })()}

      {/* Orientation diagram — shows which face is visible from overhead */}
      {mode === "facade" && (
        <FacadeOrientationBadge x={padLeft + 4} y={padTop + 6} side={side} />
      )}

      {/* Height dimension on the right.
          Coupe mode: pushed +30px out to leave room for NGT scale, AND total label dropped
          (NGT scale on the right + header subtitle already convey total height).
          Façade mode: standard offset, total label kept. */}
      <HeightDim
        x1={bx0 + spanPx + (mode === "coupe" ? 48 : 18)}
        yTop={by0 - totalHPx - parapetPx}
        yBottom={by0}
        totalHeightM={env.hauteur_totale_m}
        stories={stories}
        worldToPx={worldToPx}
        showTotal={mode === "facade"}
      />

      {/* NGT altimetric scale (right edge — both coupe and façade modes
          for PC consistency: every elevation must show the NGT cotation). */}
      {(mode === "coupe" || mode === "facade") && (
        <NGTScale
          x={width - padRight + 4}
          yGround={by0}
          stories={stories}
          worldToPx={worldToPx}
          totalHeightM={env.hauteur_totale_m}
        />
      )}

      {/* Légende matériaux — coupes show structural materials (béton, isolation,
          étanchéité); façades show finish materials (enduit, brique, bois,
          béton matricé, verre). Same component, different palette. */}
      {mode === "coupe" && (
        <LegendeMateriaux
          x={padLeft + 100}
          y={height - 60}
          maxWidth={width - padLeft - 100 - 240}
        />
      )}
      {mode === "facade" && (
        <LegendeMateriauxFacade
          x={padLeft + 100}
          y={height - 60}
          maxWidth={width - padLeft - 100 - 200}
        />
      )}

      {/* Story codes on the left axis (R+x at floor line of each story).
          HSP per niveau is intentionally NOT shown here — the values already
          appear in the subtitle ("RDC 3.2 m · étages courants 2.7 m") so
          repeating them per floor would just clutter the axis. */}
      {stories.map((s, i) => {
        const [, yTop] = worldToPx(0, s.yBase + s.height);
        return (
          <g key={i}>
            <line x1={padLeft - 30} y1={yTop} x2={padLeft - 4} y2={yTop} stroke="#475569" strokeWidth={0.5} strokeDasharray="3 2" />
            <text x={padLeft - 36} y={yTop + 4} textAnchor="end" fontSize={10} fontWeight={700} fill="#0f172a">
              {s.code}
            </text>
          </g>
        );
      })}

      {/* Header — title text shifts right in coupe mode to leave room for the
          compass at TOP-LEFT (inside the cartouche) */}
      <g>
        <rect x={20} y={20} width={width - 40} height={38} fill="white" />
        <line x1={20} y1={58} x2={width - 20} y2={58} stroke="#0f172a" strokeWidth={0.5} />
        {/* Title shifts right past the compass + its E/W labels (compass at x=39,
            size=22, E label extends to ~x=62) → start title at x=78 for clearance. */}
        <text x={mode === "coupe" ? 78 : 30} y={40} fontSize={15} fontWeight={700} fill="#0f172a">
          {mode === "coupe"
            ? (cutAxis === "BB" ? "Coupe B-B' — longitudinale" : "Coupe A-A' — transversale")
            : `Façade ${SIDE_LABEL[side]}${isMainVoirie ? " — principale (voirie)" : isVoirieSide ? " — secondaire (voirie)" : ""}`}
        </text>
        <text x={mode === "coupe" ? 78 : 30} y={54} fontSize={10.5} fill="#475569">
          R+{env.niveaux - 1} · hauteur {env.hauteur_totale_m} m · RDC {env.hauteur_rdc_m} m · étages courants {env.hauteur_etage_courant_m} m
          {projectName ? ` · ${projectName}` : ""}
        </text>

        {/* Efficacité plan — badge discret en haut droit du header */}
        {mode === "coupe" && (() => {
          const niveauxList = bm.niveaux ?? [];
          let shabM2 = 0, circM2 = 0, spM2 = 0;
          for (const n of niveauxList) {
            spM2 += n.surface_plancher_m2 ?? 0;
            for (const c of n.cellules ?? []) {
              if (c.type === "logement") shabM2 += c.surface_m2 ?? 0;
            }
            for (const c of n.circulations_communes ?? []) circM2 += c.surface_m2 ?? 0;
          }
          const effPct = spM2 > 0 ? Math.round((shabM2 / spM2) * 100) : 0;
          const circPct = spM2 > 0 ? Math.round((circM2 / spM2) * 100) : 0;
          const efficient = effPct >= 82;
          return (
            <g>
              <rect x={width - 232} y={28} width={200} height={22} rx={3}
                fill={efficient ? "#ecfdf5" : "#fef3c7"}
                stroke={efficient ? "#10b981" : "#f59e0b"} strokeWidth={0.8} />
              <text x={width - 222} y={43} fontSize={9.5} fontWeight={700}
                fill={efficient ? "#065f46" : "#92400e"}>
                Efficacité plan
              </text>
              <text x={width - 38} y={43} fontSize={9.5} fontWeight={700}
                fill={efficient ? "#065f46" : "#92400e"} textAnchor="end">
                SHAB {effPct}% · circ {circPct}%
              </text>
            </g>
          );
        })()}
      </g>

      {/* Compass + scale.
          Coupe mode: compass moved to TOP-LEFT inside the title cartouche to avoid
          colliding with the NGT scale on the right.
          Façade mode: stays top-right (FacadeOrientationBadge already occupies top-left). */}
      <NorthArrow
        x={mode === "coupe" ? 39 : width - 56}
        y={mode === "coupe" ? 36 : 98}
        size={mode === "coupe" ? 22 : 46}
        rotationDeg={bm.site.north_angle_deg ?? 0}
      />
      <ScaleBar x={padLeft} y={height - 32} scalePxPerM={scale} meters={5} />

      <TitleBlock
        x={width - 184}
        y={height - 68}
        width={180}
        title={mode === "coupe"
          ? (cutAxis === "BB" ? "Coupe B-B'" : "Coupe A-A'")
          : `Façade ${SIDE_LABEL[side]}`}
        subtitle={`1:100 · ${mode === "coupe"
          ? (cutAxis === "BB" ? "DP-CO-02" : "DP-CO-01")
          : `DP-FA-0${FACADE_SHEET[side]}`}`}
        sheetCode={mode === "coupe"
          ? (cutAxis === "BB" ? "PC3-2" : "PC3-1")
          : `PC5-${FACADE_SHEET[side]}`}
      />
    </svg>
  );
}

/* ─────────── Coupe body ─────────── */

type StoryT = { code: string; yBase: number; height: number; usage: string; hsp: number };

function CoupeBody({
  bm, cutAxis, stories, worldToPx, spanPx, scale, parapetPx,
}: {
  bm: BuildingModelPayload;
  cutAxis: "AA" | "BB";
  stories: StoryT[];
  worldToPx: (x: number, y: number) => [number, number];
  spanPx: number;
  scale: number;
  parapetPx: number;
}) {
  const footprint = coordsFromGeoJSON(bm.envelope?.footprint_geojson);
  const bb = bboxOf(footprint);
  // Axis perpendicular to cut line (the "cut" axis). AA' cuts at x=cx, BB' at y=cy.
  const perpAxis: "x" | "y" = cutAxis === "AA" ? "x" : "y";
  const cutPos = bb
    ? (cutAxis === "AA" ? (bb.minx + bb.maxx) / 2 : (bb.miny + bb.maxy) / 2)
    : 0;
  // Section-horizontal world-axis = the OTHER axis. Origin = min of that axis.
  const sectionOrigin = bb ? (cutAxis === "AA" ? bb.miny : bb.minx) : 0;
  const toSection = (worldQ: number) => worldQ - sectionOrigin;

  const footprintIntervals = polygonLineIntersectIntervals(footprint, perpAxis, cutPos);

  const niveaux = [...bm.niveaux].sort((a, b) => a.index - b.index);

  // Coupe-specific room palette — differentiates wet rooms, living areas,
  // bedrooms, circulation. Lighter than the shared roomStyle palette so
  // labels read clearly on the section.
  const coupeRoomFill = (roomType: string, fallbackUsage?: string): string => {
    const t = (roomType ?? "").toLowerCase();
    const u = (fallbackUsage ?? "").toLowerCase();
    if (["sejour", "sejour_cuisine", "cuisine"].includes(t)) return "#fff8e7";
    if (["entree", "couloir", "palier", "circulation", "degagement"].includes(t)) return "#f1f5f9";
    if (["chambre_parents", "chambre_enfant", "chambre_supp", "chambre"].includes(t)) return "#f0f4f8";
    if (["sdb", "wc", "wc_sdb", "salle_de_douche"].includes(t)) return "#e0f4f4";
    if (["loggia", "balcon", "terrasse"].includes(t)) return "#dcfce7";
    // Fallback on usage_principal of the level (e.g. "habitation_collectif")
    if (u.includes("habit")) return "#fff8e7";
    return "#f8fafc";
  };

  // Murs porteurs externes : 20 cm béton + isolation (rendus en hachuré).
  // Bumped visual minimum so the external walls read clearly against the
  // interior rooms even when scale shrinks.
  const wallW = Math.max(7, 0.20 * scale);
  // Refends inter-apts : 18 cm béton armé
  const refendW = Math.max(4.5, 0.18 * scale);
  // Dalle béton banché : 22 cm
  const slabH = Math.max(4, 0.22 * scale);
  // Acrotère : 110 cm haut × 30 cm épais + couvertine 5 cm.
  // Visual minimums increased — at typical scale the logical 110 cm renders
  // ~3 px which makes the acrotère imperceptible. Bump rendered min to 14 px
  // (acrotère) and 4 px (couvertine) so the parapet reads at any zoom.
  const acrotereHpx = Math.max(14, 1.10 * scale);
  const acrotereWpx = Math.max(7, 0.30 * scale);
  const couvertineHpx = Math.max(4, 0.05 * scale);
  // Bandeau (nez de dalle) — protrusion 5 cm aux deux extrémités du bâtiment.
  // Bumped minimum to 7 px so it's actually visible regardless of scale.
  const bandeauProtrusionPx = Math.max(7, 0.05 * scale);
  const bandeauHeightPx = Math.max(4, slabH);

  // Core for stair profile: we only draw the stair run if the cut line actually
  // intersects the core's escalier footprint. We assume stair has the same
  // center as the core and runs along the axis of the cut direction.
  const core = bm.core as {
    position_xy?: [number, number];
    escalier?: { position_xy?: [number, number]; width_m?: number; length_m?: number };
  };
  const esc = core.escalier;
  const stairPos = esc?.position_xy ?? core.position_xy;
  const stairSize = { w: esc?.width_m ?? 1.2, l: esc?.length_m ?? 2.6 };
  const stairCuts = stairPos && bb
    ? (() => {
        // Approximate stair bbox in world coords centered at stairPos.
        const [cxS, cyS] = stairPos;
        // Orient stair along the longer bbox axis of the building footprint.
        const fw = bb.maxx - bb.minx;
        const fh = bb.maxy - bb.miny;
        const runAlongX = fw >= fh;
        const hw = runAlongX ? stairSize.l / 2 : stairSize.w / 2;
        const hh = runAlongX ? stairSize.w / 2 : stairSize.l / 2;
        // Does the cut line pass through the stair bbox ?
        const crosses = perpAxis === "x"
          ? cutPos >= cxS - hw && cutPos <= cxS + hw
          : cutPos >= cyS - hh && cutPos <= cyS + hh;
        if (!crosses) return null;
        // Section-horizontal extent of the stair: the span of stair in the
        // OTHER axis (what the section shows).
        const sectCenter = perpAxis === "x" ? cyS : cxS;
        const sectHalf = perpAxis === "x" ? hh : hw;
        return {
          xStart: toSection(sectCenter - sectHalf),
          xEnd: toSection(sectCenter + sectHalf),
        };
      })()
    : null;

  return (
    <g>
      {/* Render each footprint segment independently (an L-shape cut may
          produce two disjoint envelopes). */}
      {footprintIntervals.map(([wA, wB], segIdx) => {
        const sA = toSection(wA);
        const sB = toSection(wB);
        const [xA, by0] = worldToPx(sA, 0);
        const [xB] = worldToPx(sB, 0);
        const segPx = xB - xA;
        const topStory = stories[stories.length - 1];
        const [, yTopTop] = worldToPx(sA, topStory.yBase + topStory.height);
        return (
          <g key={`seg-${segIdx}`}>
            {/* Outer walls (béton + isolation, hachurés) on both ends */}
            {stories.map((s, i) => {
              const [, yB] = worldToPx(sA, s.yBase);
              const [, yT] = worldToPx(sA, s.yBase + s.height);
              return (
                <g key={`ow-${segIdx}-${i}`}>
                  {/* Mur gauche : béton (extérieur) + isolation (intérieur).
                      Stroke épaissi à 2.5 px côté extérieur pour que l'enveloppe
                      soit lisible. */}
                  <rect x={xA} y={yT} width={wallW * 0.7} height={yB - yT} fill="url(#pat-beton-arme)" stroke="#0a0a0a" strokeWidth={2.5} />
                  <rect x={xA + wallW * 0.7} y={yT} width={wallW * 0.3} height={yB - yT} fill="url(#pat-isolation)" stroke="#0f172a" strokeWidth={0.5} />
                  {/* Mur droit : isolation (intérieur) + béton (extérieur) */}
                  <rect x={xB - wallW} y={yT} width={wallW * 0.3} height={yB - yT} fill="url(#pat-isolation)" stroke="#0f172a" strokeWidth={0.5} />
                  <rect x={xB - wallW * 0.7} y={yT} width={wallW * 0.7} height={yB - yT} fill="url(#pat-beton-arme)" stroke="#0a0a0a" strokeWidth={2.5} />
                </g>
              );
            })}

            {/* Slabs between stories — béton banché 22 cm, hachures horizontales.
                Each slab edge gets a small "bandeau" (nez de dalle) protruding 5 cm
                at the leftmost/rightmost edges — adds an architectural detail. */}
            {stories.map((s, i) => {
              const [, yB] = worldToPx(sA, s.yBase);
              return (
                <g key={`slab-${segIdx}-${i}`}>
                  {/* Slab itself — stroke épaissi à 1.4 px pour lisibilité */}
                  <rect
                    x={xA - 2}
                    y={yB - slabH}
                    width={segPx + 4}
                    height={slabH}
                    fill="url(#pat-beton-banche)"
                    stroke="#0a0a0a"
                    strokeWidth={1.4}
                  />
                  {/* Bandeau gauche — protrusion ~7 px beige soutenu (nez de dalle).
                      Couleur plus saturée et trait plus marqué pour qu'il soit
                      visible à toute échelle. */}
                  <rect
                    x={xA - 2 - bandeauProtrusionPx}
                    y={yB - slabH - 0.5}
                    width={bandeauProtrusionPx + 1}
                    height={bandeauHeightPx + 1}
                    fill="#c8b88a"
                    stroke="#0a0a0a"
                    strokeWidth={1.0}
                  />
                  {/* Bandeau droit — protrusion ~7 px beige soutenu (nez de dalle) */}
                  <rect
                    x={xB + 1}
                    y={yB - slabH - 0.5}
                    width={bandeauProtrusionPx + 1}
                    height={bandeauHeightPx + 1}
                    fill="#c8b88a"
                    stroke="#0a0a0a"
                    strokeWidth={1.0}
                  />
                </g>
              );
            })}

            {/* Toiture + acrotère détaillé */}
            <g>
              {/* Dalle haute (toit-terrasse) — béton banché, stroke épaissi */}
              <rect x={xA - 2} y={yTopTop - slabH} width={segPx + 4} height={slabH} fill="url(#pat-beton-banche)" stroke="#0a0a0a" strokeWidth={1.4} />
              {/* Membrane d'étanchéité sur la dalle (3 cm) */}
              <rect x={xA - 2} y={yTopTop - slabH - Math.max(2, 0.03 * scale)} width={segPx + 4} height={Math.max(2, 0.03 * scale)} fill="url(#pat-etancheite)" />
              {/* Acrotère gauche : strip vertical béton 30 cm × 110 cm.
                  Filled with darker grey BEHIND the béton-armé pattern so the
                  acrotère reads as a solid mass even at small render heights,
                  with a thick black border for contrast. */}
              <rect
                x={xA}
                y={yTopTop - slabH - acrotereHpx}
                width={acrotereWpx}
                height={acrotereHpx}
                fill="#6b7280"
              />
              <rect
                x={xA}
                y={yTopTop - slabH - acrotereHpx}
                width={acrotereWpx}
                height={acrotereHpx}
                fill="url(#pat-beton-arme)"
                stroke="#0a0a0a"
                strokeWidth={1.5}
              />
              {/* Acrotère droite */}
              <rect
                x={xB - acrotereWpx}
                y={yTopTop - slabH - acrotereHpx}
                width={acrotereWpx}
                height={acrotereHpx}
                fill="#6b7280"
              />
              <rect
                x={xB - acrotereWpx}
                y={yTopTop - slabH - acrotereHpx}
                width={acrotereWpx}
                height={acrotereHpx}
                fill="url(#pat-beton-arme)"
                stroke="#0a0a0a"
                strokeWidth={1.5}
              />
              {/* Label "ACROTÈRE" — placed in the clearance between the title
                  bar and the parapet (padTop = 110 reserves the space). */}
              <text
                x={(xA + xB) / 2}
                y={yTopTop - slabH - acrotereHpx - couvertineHpx - 6}
                fontSize={9.5}
                fontWeight={700}
                fill="#0f172a"
                textAnchor="middle"
              >
                ACROTÈRE
              </text>
              {/* Couvertine cap stone gauche — pierre claire (lighter grey)
                  pour contraster avec le béton sombre de l'acrotère, débord
                  1 cm avec larmier. */}
              <rect
                x={xA - 1.5}
                y={yTopTop - slabH - acrotereHpx - couvertineHpx}
                width={acrotereWpx + 3}
                height={couvertineHpx}
                fill="#a1a1aa"
                stroke="#0a0a0a"
                strokeWidth={1.2}
              />
              {/* Larmier (drip-edge) gauche */}
              <line x1={xA - 1.5} y1={yTopTop - slabH - acrotereHpx} x2={xA - 1.5} y2={yTopTop - slabH - acrotereHpx + 2.5} stroke="#0a0a0a" strokeWidth={1.0} />
              {/* Couvertine cap stone droite */}
              <rect
                x={xB - acrotereWpx - 1.5}
                y={yTopTop - slabH - acrotereHpx - couvertineHpx}
                width={acrotereWpx + 3}
                height={couvertineHpx}
                fill="#a1a1aa"
                stroke="#0a0a0a"
                strokeWidth={1.2}
              />
              {/* Larmier (drip-edge) droit */}
              <line x1={xB + 1.5} y1={yTopTop - slabH - acrotereHpx} x2={xB + 1.5} y2={yTopTop - slabH - acrotereHpx + 2.5} stroke="#0a0a0a" strokeWidth={1.0} />
              {/* Étanchéité face intérieure acrotère gauche (relevé) */}
              <rect
                x={xA + acrotereWpx}
                y={yTopTop - slabH - acrotereHpx * 0.8}
                width={Math.max(1.5, 0.03 * scale)}
                height={acrotereHpx * 0.8}
                fill="url(#pat-etancheite)"
              />
              {/* Étanchéité face intérieure acrotère droite */}
              <rect
                x={xB - acrotereWpx - Math.max(1.5, 0.03 * scale)}
                y={yTopTop - slabH - acrotereHpx * 0.8}
                width={Math.max(1.5, 0.03 * scale)}
                height={acrotereHpx * 0.8}
                fill="url(#pat-etancheite)"
              />
            </g>

            {/* Per-story contents: rooms (actual intersections) + interior-wall ticks */}
            {stories.map((s, i) => {
              const niv = niveaux[i];
              const [, yB] = worldToPx(sA, s.yBase);
              const [, yT] = worldToPx(sA, s.yBase + s.height);
              const innerY = yT + slabH;
              const innerH = (yB - yT) - slabH;
              const segWorldRange: [number, number] = [wA, wB];

              // Collect cellules cut by this cut line, clipped to this envelope segment
              type Piece = { wA: number; wB: number; label: string; tone: string; type: string };
              const pieces: Piece[] = [];
              for (const cell of niv?.cellules ?? []) {
                const intervals = polygonLineIntersectIntervals(
                  cell.polygon_xy as Coord[],
                  perpAxis,
                  cutPos,
                );
                for (const [ia, ib] of intervals) {
                  const a = Math.max(ia, segWorldRange[0]);
                  const b = Math.min(ib, segWorldRange[1]);
                  if (b - a < 0.2) continue;
                  // Pick the room type at segment midpoint if we can
                  const mid = (a + b) / 2;
                  let roomType = cell.typologie ?? "logement";
                  let roomLabel = (cell.typologie ?? "LGT").toUpperCase();
                  for (const r of cell.rooms ?? []) {
                    const rIntervals = polygonLineIntersectIntervals(
                      r.polygon_xy as Coord[],
                      perpAxis,
                      cutPos,
                    );
                    const hit = rIntervals.find(([ra, rb]) => mid >= ra && mid <= rb);
                    if (hit) {
                      roomType = r.type;
                      roomLabel = roomLabelTiny(r.type);
                      break;
                    }
                  }
                  // Coupe-specific differentiation by room category.
                  const tone = coupeRoomFill(roomType, niv?.usage_principal);
                  pieces.push({ wA: a, wB: b, label: roomLabel, tone, type: roomType });
                }
              }
              for (const circ of niv?.circulations_communes ?? []) {
                const intervals = polygonLineIntersectIntervals(
                  circ.polygon_xy as Coord[],
                  perpAxis,
                  cutPos,
                );
                for (const [ia, ib] of intervals) {
                  const a = Math.max(ia, segWorldRange[0]);
                  const b = Math.min(ib, segWorldRange[1]);
                  if (b - a < 0.2) continue;
                  pieces.push({ wA: a, wB: b, label: "Circ.", tone: coupeRoomFill("circulation"), type: "circulation" });
                }
              }
              // Sort L→R along section axis
              pieces.sort((p, q) => p.wA - q.wA);

              // Interior wall ticks: union of walls from all cellules whose
              // geometry crosses the cut line within [wA, wB]
              const wallTicks: number[] = [];
              for (const cell of niv?.cellules ?? []) {
                for (const w of cell.walls ?? []) {
                  if (w.type === "porteur") continue;  // outer porteur handled by envelope
                  const coords = w.geometry?.coords as Coord[] | undefined;
                  if (!coords || coords.length < 2) continue;
                  const hit = segmentCrossAxis(coords[0], coords[1], perpAxis, cutPos);
                  if (hit === null) continue;
                  if (hit < wA || hit > wB) continue;
                  wallTicks.push(hit);
                }
              }

              // Deduplicate wallTicks that land too close to a room boundary
              // (those are already drawn as the edge of the room fill).
              const roomEdges = new Set<number>();
              for (const p of pieces) {
                roomEdges.add(Math.round(p.wA * 10) / 10);
                roomEdges.add(Math.round(p.wB * 10) / 10);
              }
              const uniqueTicks = wallTicks.filter((wt) => {
                const key = Math.round(wt * 10) / 10;
                return !roomEdges.has(key);
              });

              return (
                <g key={`rooms-${segIdx}-${i}`}>
                  {/* Pass 1 — fills + edge refends (no labels yet, so nothing
                      drawn later can clip the labels). */}
                  {pieces.map((p, pi) => {
                    const pxA = worldToPx(toSection(p.wA), 0)[0];
                    const pxB = worldToPx(toSection(p.wB), 0)[0];
                    return (
                      <g key={pi}>
                        <rect x={pxA + 0.4} y={innerY} width={pxB - pxA - 0.8} height={innerH} fill={p.tone} opacity={0.95} />
                        {/* Refend béton armé 18 cm (solide, hachuré) à la limite de la pièce */}
                        <rect
                          x={pxB - refendW / 2}
                          y={innerY}
                          width={refendW}
                          height={innerH}
                          fill="url(#pat-beton-arme)"
                          stroke="#0f172a"
                          strokeWidth={0.5}
                        />
                      </g>
                    );
                  })}

                  {/* Refends inter-apts non-edge — solides 18 cm béton armé hachuré */}
                  {uniqueTicks.map((wt, wi) => {
                    const [xTick] = worldToPx(toSection(wt), 0);
                    return (
                      <rect
                        key={`wt-${wi}`}
                        x={xTick - refendW / 2}
                        y={innerY}
                        width={refendW}
                        height={innerH}
                        fill="url(#pat-beton-arme)"
                        stroke="#0f172a"
                        strokeWidth={0.5}
                      />
                    );
                  })}

                  {/* Slab bottom-shadow for floor separation */}
                  <line
                    x1={xA + wallW}
                    y1={innerY + innerH + 0.5}
                    x2={xB - wallW}
                    y2={innerY + innerH + 0.5}
                    stroke="#0f172a"
                    strokeWidth={0.35}
                    opacity={0.35}
                  />

                  {/* ─── Fenêtres en élévation sur les murs extérieurs ───
                      One window on each end (left/right) of each story. Standard
                      dimensions: 140 cm wide × 130 cm tall, allège 95 cm. The
                      cut shows the BUTT of the window so we draw frame + glass
                      tinted. RDC entry replaces the window on the voirie side
                      but in coupe we always show fenêtres for clarity. */}
                  {(() => {
                    const winWpx = Math.max(14, 1.40 * scale);
                    const winHpx = Math.max(14, 1.30 * scale);
                    const allegePx = Math.max(8, 0.95 * scale);
                    const frameThick = Math.max(2, 0.05 * scale);
                    // y from ground for this story
                    const [, yStoryFloor] = worldToPx(0, s.yBase);
                    const winYTop = yStoryFloor - allegePx - winHpx;
                    // Skip if window won't fit in story HSP
                    if (allegePx + winHpx > (yStoryFloor - innerY)) return null;
                    return (
                      <g>
                        {/* Left window — drawn on the inner face of the left
                            outer wall (just inside the wall pattern). */}
                        <rect
                          x={xA + wallW - frameThick / 2}
                          y={winYTop}
                          width={winWpx * 0.18}
                          height={winHpx}
                          fill="#475569"
                          stroke="#0a0a0a"
                          strokeWidth={0.7}
                        />
                        <rect
                          x={xA + wallW + frameThick}
                          y={winYTop + frameThick}
                          width={winWpx * 0.18 - frameThick * 2}
                          height={winHpx - frameThick * 2}
                          fill="#bfe1ee"
                          opacity={0.6}
                        />
                        {/* Allège (parapet bas sous fenêtre) */}
                        <rect
                          x={xA + wallW * 0.9}
                          y={winYTop + winHpx}
                          width={winWpx * 0.22}
                          height={allegePx}
                          fill="#9ca3af"
                          opacity={0.5}
                        />
                        {/* Right window — symmetric on right outer wall */}
                        <rect
                          x={xB - wallW - winWpx * 0.18 + frameThick / 2}
                          y={winYTop}
                          width={winWpx * 0.18}
                          height={winHpx}
                          fill="#475569"
                          stroke="#0a0a0a"
                          strokeWidth={0.7}
                        />
                        <rect
                          x={xB - wallW - winWpx * 0.18 + frameThick}
                          y={winYTop + frameThick}
                          width={winWpx * 0.18 - frameThick * 2}
                          height={winHpx - frameThick * 2}
                          fill="#bfe1ee"
                          opacity={0.6}
                        />
                        <rect
                          x={xB - wallW * 0.9 - winWpx * 0.22}
                          y={winYTop + winHpx}
                          width={winWpx * 0.22}
                          height={allegePx}
                          fill="#9ca3af"
                          opacity={0.5}
                        />
                      </g>
                    );
                  })()}

                  {/* Pass 2 — labels last, on top of refends/windows so that
                      uniqueTicks (drawn after pass 1) cannot clip the start
                      of "Entr."/"Séj." on narrow cells. */}
                  {pieces.map((p, pi) => {
                    const pxA = worldToPx(toSection(p.wA), 0)[0];
                    const pxB = worldToPx(toSection(p.wB), 0)[0];
                    if (pxB - pxA <= 26) return null;
                    return (
                      <text
                        key={`lbl-${pi}`}
                        x={(pxA + pxB) / 2}
                        y={innerY + innerH / 2 + 3.5}
                        textAnchor="middle"
                        fontSize={9}
                        fontWeight={600}
                        fill="#0f172a"
                      >
                        {p.label}
                      </text>
                    );
                  })}
                </g>
              );
            })}

            {/* Building section perimeter — crisp dark outline drawn LAST so
                the envelope reads clearly against the room fills. Goes around
                the full section: top of acrotère caps to ground level. */}
            <rect
              x={xA}
              y={yTopTop - slabH - acrotereHpx - couvertineHpx}
              width={segPx}
              height={by0 - (yTopTop - slabH - acrotereHpx - couvertineHpx)}
              fill="none"
              stroke="#0a0a0a"
              strokeWidth={2.5}
            />
          </g>
        );
      })}

      {/* Personnage échelle 1.75 m au RDC — silhouette pour donner l'échelle.
          Opacity 0.85 (était 0.55) + lit double 200×90 cm posé à côté pour
          ancrer encore l'échelle. */}
      {(() => {
        const rdc = stories[0];
        if (!rdc || footprintIntervals.length === 0) return null;
        // Position à 1/4 du premier segment d'envelope
        const [wA, wB] = footprintIntervals[0];
        const personW = wB - wA;
        const personPosWorld = wA + personW * 0.25;
        const [pxFoot] = worldToPx(toSection(personPosWorld), 0);
        const [, yFoot] = worldToPx(0, 0);
        // Hauteur 1.75 m, largeur ~50 cm
        const personHpx = 1.75 * scale;
        const personWpx = 0.5 * scale;
        const headR = personWpx * 0.32;
        // Pieds reposent au-dessus de la dalle RDC (laisser place à la dalle)
        const footY = yFoot - slabH;
        const headCy = footY - personHpx + headR;
        const cx = pxFoot;
        // Mobilier : lit double 200 × 90 cm (vue en coupe = simple rectangle)
        const bedWpx = 2.0 * scale;
        const bedHpx = 0.55 * scale;  // hauteur tête de lit visible
        const bedX = cx + personWpx * 1.4;
        const bedY = footY - bedHpx;
        const mattressHpx = 0.30 * scale;
        return (
          <g>
            {/* Mobilier — lit double silhouette beige */}
            <g opacity={0.4} stroke="#a78b65" strokeWidth={0.7} fill="#e8d9bd">
              {/* Cadre du lit */}
              <rect x={bedX} y={bedY} width={bedWpx} height={bedHpx} />
              {/* Matelas (partie supérieure) */}
              <rect x={bedX + 1.5} y={bedY + bedHpx - mattressHpx} width={bedWpx - 3} height={mattressHpx} fill="#f0e4ce" />
              {/* Tête de lit (rectangle plus haut à gauche) */}
              <rect x={bedX} y={bedY - bedHpx * 0.5} width={Math.max(3, 0.08 * scale)} height={bedHpx * 0.5} />
              {/* Oreiller */}
              <rect
                x={bedX + Math.max(3, 0.08 * scale) + 2}
                y={bedY + bedHpx - mattressHpx - 1}
                width={bedWpx * 0.20}
                height={mattressHpx * 0.45}
                fill="#faf3e0"
              />
            </g>
            {/* Personnage */}
            <g opacity={0.85} stroke="#1e293b" strokeWidth={1.1} fill="none" strokeLinecap="round">
              {/* Tête */}
              <circle cx={cx} cy={headCy} r={headR} fill="#f8fafc" />
              {/* Corps + jambes */}
              <path
                d={`M ${cx} ${headCy + headR}
                    L ${cx} ${footY - personHpx * 0.40}
                    M ${cx} ${footY - personHpx * 0.40}
                    L ${cx - personWpx * 0.35} ${footY}
                    M ${cx} ${footY - personHpx * 0.40}
                    L ${cx + personWpx * 0.35} ${footY}`}
              />
              {/* Bras */}
              <path
                d={`M ${cx - personWpx * 0.42} ${headCy + headR + personHpx * 0.12}
                    L ${cx + personWpx * 0.42} ${headCy + headR + personHpx * 0.12}`}
              />
            </g>
          </g>
        );
      })()}

      {/* Stair profile — diagonal hatched volée at each story with up-arrow.
          Skipped silently if no core position is provided. */}
      {stairCuts && (() => {
        const [xS0] = worldToPx(stairCuts.xStart, 0);
        const [xS1] = worldToPx(stairCuts.xEnd, 0);
        return (
          <g>
            {stories.slice(0, -1).map((s, i) => {
              const [, yB] = worldToPx(0, s.yBase);
              const [, yT] = worldToPx(0, s.yBase + s.height);
              const flightUpLeft = i % 2 === 1;
              const sx0 = flightUpLeft ? xS1 : xS0;
              const sx1 = flightUpLeft ? xS0 : xS1;
              const steps = 5;
              const dx = sx1 - sx0;
              const dy = yT - yB;
              return (
                <g key={`stair-${i}`}>
                  {/* Diagonal volée — fond clair sous la rampe */}
                  <polygon
                    points={`${sx0},${yB} ${sx1},${yT} ${sx1},${yB} ${sx0},${yB}`}
                    fill="#e2e8f0"
                    opacity={0.55}
                  />
                  {/* Hachures diagonales (parallèles à la pente) */}
                  {Array.from({ length: 6 }).map((_, k) => {
                    const t = (k + 1) / 7;
                    const px0 = sx0 + dx * t;
                    const py0 = yB;
                    const px1 = sx0 + dx * t;
                    const py1 = yB + dy * t;
                    return (
                      <line
                        key={`hatch-${k}`}
                        x1={px0}
                        y1={py0}
                        x2={px1}
                        y2={py1}
                        stroke="#64748b"
                        strokeWidth={0.4}
                        opacity={0.6}
                      />
                    );
                  })}
                  {/* Stringer (limon) */}
                  <line x1={sx0} y1={yB - 1} x2={sx1} y2={yT + 1} stroke="#0f172a" strokeWidth={1.4} />
                  {/* Tread ticks (marches) */}
                  {Array.from({ length: steps - 1 }).map((_, k) => {
                    const t = (k + 1) / steps;
                    const tx = sx0 + dx * t;
                    const ty = yB + dy * t;
                    return (
                      <line key={k} x1={tx - 2.5} y1={ty} x2={tx + 2.5} y2={ty} stroke="#1e293b" strokeWidth={0.8} />
                    );
                  })}
                  {/* Up-arrow ↑ at the top of each flight indicating ascent */}
                  <text
                    x={sx1 + (sx1 > sx0 ? -8 : 8)}
                    y={yT + 4}
                    fontSize={11}
                    fontWeight={700}
                    fill="#0f172a"
                    textAnchor="middle"
                  >
                    ↑
                  </text>
                </g>
              );
            })}
          </g>
        );
      })()}
    </g>
  );
}

/* ─────────── Façade body ─────────── */

/* Contemporary residential palette (2025-2026 architectural trends,
 * cost-aware for 12% margin target):
 *   - ENDUIT: beige sable / blanc cassé (RPE minéral, bas coût)
 *   - BARDAGE: cèdre naturel vertical (accents sélectifs, attique)
 *   - MÉTAL: noir thermolaqué (menuiseries, garde-corps, brise-soleil)
 *   - SOUBASSEMENT: pierre reconstituée anthracite (plinthe)
 *   - ACCENT: terracotta / bleu pétrole (rare, rythme vertical)
 */
const PALETTE = {
  // Palette unifiée tons terre / chaud — cohabitabilité chromatique entre
  // enduit, brique, bois, béton (axe sable + ocre + terre brune désaturée).
  // Évite les contrastes durs noir/blanc/rouge primaires.
  enduitBase: "#ece7db",       // sable doux légèrement réchauffé
  enduitShadow: "#d3cdb8",
  bardageWood: "#a07956",      // cèdre vieilli (un poil rougi pour dialoguer avec brique)
  bardageWoodDark: "#5e4429",
  brique: "#7d3a26",           // brique brûlée mais désaturée
  briqueDark: "#4a1d11",
  briqueJoint: "#241108",
  betonMatrice: "#8b8377",     // béton chaud (vers terre)
  betonMatriceLine: "#3e3830",
  // Soubassement basalte + plinthe — gris très foncé au lieu de noir pur
  soubassement: "#1f1d19",
  soubassementLine: "#0a0907",
  menuiserieBlack: "#161412",  // alu très foncé teinté chaud
  menuiserieNoir: "#0a0907",
  // Vitrage low-e — un peu plus vert/sage pour cohabiter avec verdure
  glass: "#9bcfd9",
  glassLight: "#cce4e6",
  glassReflect: "#ebf3f3",
  gardeCorps: "#161412",
  shadowDeep: "#0a0a0a",
  shadowSoft: "#1f1c18",
  accentPetrole: "#234548",
  vegetation: "#5d7547",       // un poil plus chaud
  vegetationDark: "#3a4d2c",
};

function FacadeBody({
  stories, openingsByStory, worldToPx, spanPx, scale, parapetPx, env, showEntry, isVoirieAny, side,
  silhouette, facadeWorldStart, facadeWorldDir,
}: {
  stories: Array<{ code: string; yBase: number; height: number; usage: string }>;
  openingsByStory: number[];
  worldToPx: (x: number, y: number) => [number, number];
  spanPx: number;
  scale: number;
  parapetPx: number;
  env: BuildingModelPayload["envelope"];
  /** Show main entrance door (only TRUE for the first/principal voirie side). */
  showEntry: boolean;
  /** ANY voirie side (incl. secondary on a corner building) — gets balcons filants. */
  isVoirieAny: boolean;
  side: "nord" | "sud" | "est" | "ouest";
  silhouette: FacadeSegment[];
  facadeWorldStart: number;
  facadeWorldDir: 1 | -1;
}) {
  const topStory = stories[stories.length - 1];
  const [xL, yTop] = worldToPx(0, topStory.yBase + topStory.height);
  const [, yBase] = worldToPx(0, 0);

  const isVoirie = isVoirieAny;
  const isPignon = side === "est" || side === "ouest";
  const isNorth = side === "nord";

  // Map each silhouette segment from world coords → façade pixel coords.
  // facadeWorldDir=+1 means facade_x grows with world coord; -1 means reversed
  // (Nord, Ouest). Then convert to absolute screen X using xL + facadeX*scale.
  type SegPx = { xLpx: number; spanPxSeg: number; isFront: boolean; recessM: number };
  const segments: SegPx[] = silhouette.length === 0
    ? [{ xLpx: xL, spanPxSeg: spanPx, isFront: true, recessM: 0 }]
    : silhouette.map((s) => {
        const a = facadeWorldDir * (s.startCoord - facadeWorldStart);
        const b = facadeWorldDir * (s.endCoord - facadeWorldStart);
        const segStart = Math.min(a, b);
        const segEnd = Math.max(a, b);
        return {
          xLpx: xL + segStart * scale,
          spanPxSeg: (segEnd - segStart) * scale,
          isFront: s.isFront,
          recessM: s.recessM,
        };
      });
  // Sort left-to-right.
  segments.sort((p, q) => p.xLpx - q.xLpx);

  // Common architectural constants shared across silhouette segments.
  const atticHeight = topStory.height;
  const atticSetbackPx = 1.2 * scale;
  const [, yAtticFloor] = worldToPx(0, topStory.yBase);  // floor of attic
  const soubassementHeight = 1.2 * scale;
  const ySoub = yBase - soubassementHeight;
  const targetBayM = 3.8;
  // Recessed segments: visual offset at top + darker enduit conveys depth.
  const recessShadowDy = 4;

  return (
    <g>
      <defs>
        {/* Gradient diagonal NE → SW : haut-droit clair, bas-gauche dans
            l'ombre. Donne du modelé volumétrique aux murs enduit (plus
            convaincant que les rect d'ombre plats). */}
        <linearGradient id="enduit-vshadow" x1="1" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity={0.18} />
          <stop offset="0.45" stopColor={PALETTE.enduitShadow} stopOpacity={0} />
          <stop offset="1" stopColor={PALETTE.shadowSoft} stopOpacity={0.42} />
        </linearGradient>
        {/* Gradient pour les vitrages — ciel clair en haut, plus saturé en bas */}
        <linearGradient id="glass-sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#e8f3f8" stopOpacity={0.85} />
          <stop offset="0.55" stopColor={PALETTE.glassLight} stopOpacity={0.30} />
          <stop offset="1" stopColor={PALETTE.glass} stopOpacity={0.10} />
        </linearGradient>
        {/* Brique terre cuite en appareillage panneresses — chaque assise
            décalée d'1/2 brique. Joints verticaux bien marqués + variation
            ton brique alternée pour réalisme. */}
        <pattern id="pat-brique" patternUnits="userSpaceOnUse" width="20" height="9">
          {/* Course 1 (haut) — briques pleines 20px */}
          <rect x="0" y="0" width="20" height="4.5" fill={PALETTE.brique} />
          <rect x="0" y="0" width="10" height="4.5" fill={PALETTE.briqueDark} opacity="0.18" />
          <line x1="0" y1="4.5" x2="20" y2="4.5" stroke={PALETTE.briqueJoint} strokeWidth="0.6" />
          <line x1="10" y1="0" x2="10" y2="4.5" stroke={PALETTE.briqueJoint} strokeWidth="0.5" />
          {/* Course 2 (bas) — briques décalées 1/2 (panneresses) */}
          <rect x="0" y="4.5" width="20" height="4.5" fill={PALETTE.brique} />
          <rect x="10" y="4.5" width="10" height="4.5" fill={PALETTE.briqueDark} opacity="0.20" />
          <line x1="0" y1="9" x2="20" y2="9" stroke={PALETTE.briqueJoint} strokeWidth="0.6" />
          <line x1="5" y1="4.5" x2="5" y2="9" stroke={PALETTE.briqueJoint} strokeWidth="0.5" />
          <line x1="15" y1="4.5" x2="15" y2="9" stroke={PALETTE.briqueJoint} strokeWidth="0.5" />
          {/* Reflet horizontal léger en haut de chaque assise */}
          <line x1="0" y1="0.5" x2="20" y2="0.5" stroke="#fff" strokeWidth="0.2" opacity="0.18" />
          <line x1="0" y1="5.0" x2="20" y2="5.0" stroke="#fff" strokeWidth="0.2" opacity="0.18" />
        </pattern>
        {/* Béton matricé RDC — bandes verticales 14cm avec joints fins */}
        <pattern id="pat-beton-matrice" patternUnits="userSpaceOnUse" width="14" height="14">
          <rect width="14" height="14" fill={PALETTE.betonMatrice} />
          <rect x="0" y="0" width="6" height="14" fill={PALETTE.betonMatriceLine} opacity="0.15" />
          <line x1="6" y1="0" x2="6" y2="14" stroke={PALETTE.betonMatriceLine} strokeWidth="0.6" opacity="0.85" />
          <line x1="0" y1="13.5" x2="14" y2="13.5" stroke={PALETTE.betonMatriceLine} strokeWidth="0.4" opacity="0.5" />
        </pattern>
        {/* Bardage bois claires-voies horizontales — lames de 18cm avec joint creux */}
        <pattern id="pat-bardage-bois" patternUnits="userSpaceOnUse" width="14" height="6">
          <rect width="14" height="6" fill={PALETTE.bardageWood} />
          {/* Joint creux ombré entre lames */}
          <rect x="0" y="0" width="14" height="0.6" fill={PALETTE.bardageWoodDark} />
          <rect x="0" y="0" width="14" height="0.3" fill={PALETTE.shadowDeep} opacity="0.55" />
          {/* Reflet supérieur sur la lame (bois plutôt mat) */}
          <line x1="0" y1="0.8" x2="14" y2="0.8" stroke="#fff" strokeWidth="0.15" opacity="0.18" />
          {/* Texture grain bois subtile */}
          <line x1="3" y1="2.5" x2="9" y2="2.7" stroke={PALETTE.bardageWoodDark} strokeWidth="0.18" opacity="0.45" />
          <line x1="2" y1="4.0" x2="11" y2="4.1" stroke={PALETTE.bardageWoodDark} strokeWidth="0.18" opacity="0.40" />
        </pattern>
      </defs>

      {/* Per-silhouette-segment rendering. For an L-shape, Nord and Ouest
          give 2 segments (front + recessed); flat sides give 1. Each segment
          renders enduit, attic, soubassement, windows, balcons, parapet at
          its own xL/spanPx so the L silhouette reads correctly. */}
      {segments.map((seg, segIdx) => {
        const segXL = seg.xLpx;
        const segSpan = seg.spanPxSeg;
        const yTopSeg = seg.isFront ? yTop : yTop + recessShadowDy;
        const totalHSeg = yBase - yTopSeg;
        const enduitFill = seg.isFront ? PALETTE.enduitBase : PALETTE.enduitShadow;
        const estimatedBays = Math.max(2, Math.round(segSpan / (targetBayM * scale)));
        const bays = Math.min(8, estimatedBays);
        const bayW = segSpan / bays;
        const atticHPx = atticHeight * scale;

        // Brique tower volume — full-height blind brique cladding on voirie
        // façades. Centered on entrance bay (principale) or shifted (secondaire).
        // Acts as an "entrance volume" with its own integrated porte.
        const hasBriqueTower = seg.isFront && isVoirieAny;
        const briqueTowerWm = 4.2;
        const briqueTowerWpx = briqueTowerWm * scale;
        const briqueCxFrac = showEntry ? 0.5 : 0.32;
        const briqueCx = segXL + segSpan * briqueCxFrac;
        const briqueX0 = briqueCx - briqueTowerWpx / 2;
        const briqueX1 = briqueCx + briqueTowerWpx / 2;

        return (
          <g key={`seg-${segIdx}`}>
            {/* Enduit base + vertical shadow gradient (front only). */}
            <rect x={segXL} y={yTopSeg} width={segSpan} height={totalHSeg} fill={enduitFill} />
            {seg.isFront && (
              <rect x={segXL} y={yTopSeg} width={segSpan} height={totalHSeg} fill="url(#enduit-vshadow)" />
            )}

            {/* RDC zone — béton matricé (commercial / hall ground floor).
                Spans from soubassement top to floor R+1. Stratifies the façade
                into 3 reading layers: béton (RDC) / enduit (étages) / bois (attic). */}
            {(() => {
              const rdcTop = worldToPx(0, env.hauteur_rdc_m)[1];  // top of RDC = floor of R+1
              const rdcHpx = ySoub - rdcTop;
              if (rdcHpx <= 0) return null;
              return (
                <>
                  <rect x={segXL} y={rdcTop} width={segSpan} height={rdcHpx} fill="url(#pat-beton-matrice)" opacity={seg.isFront ? 0.94 : 0.72} />
                  {/* Nez de dalle marqué en haut du RDC — protrusion 6cm noire
                      avec reflet et ombre portée dégradée. Sépare clairement
                      la zone béton (RDC) de l'enduit (étages courants). */}
                  <rect x={segXL - 1.5} y={rdcTop - 4.5} width={segSpan + 3} height={4.5} fill={PALETTE.soubassement} />
                  <rect x={segXL - 1.5} y={rdcTop - 4.5} width={segSpan + 3} height={0.7} fill="#fff" opacity={0.22} />
                  <rect x={segXL} y={rdcTop} width={segSpan} height={4} fill={PALETTE.shadowDeep} opacity={0.30} />
                  <rect x={segXL} y={rdcTop + 4} width={segSpan} height={4} fill={PALETTE.shadowDeep} opacity={0.18} />
                  <rect x={segXL} y={rdcTop + 8} width={segSpan} height={4} fill={PALETTE.shadowDeep} opacity={0.08} />
                </>
              );
            })()}

            {/* Brique tower rendering moved to AFTER per-segment loop so it
                draws on top of windows/balcons (it is a VOLUME, not a stripe). */}

            {/* Cast-shadow band on the side of the recess that touches the
                front segment (simulates the front wall casting shadow on the
                back wall, archi convention for showing depth). */}
            {!seg.isFront && segIdx > 0 && (
              <rect x={segXL} y={yTopSeg} width={Math.min(24, segSpan / 3)} height={totalHSeg} fill="#0f172a" opacity={0.18} />
            )}
            {!seg.isFront && segIdx < segments.length - 1 && (
              <rect x={segXL + segSpan - Math.min(24, segSpan / 3)} y={yTopSeg} width={Math.min(24, segSpan / 3)} height={totalHSeg} fill="#0f172a" opacity={0.18} />
            )}

            {/* Attic bardage bois — front segments only. Pattern claires-voies
                horizontales (18cm lames avec joint creux ombré) au lieu des
                verticales monotones précédentes. */}
            {seg.isFront && (
              <>
                <rect
                  x={segXL + atticSetbackPx}
                  y={yAtticFloor - atticHPx}
                  width={segSpan - 2 * atticSetbackPx}
                  height={atticHPx}
                  fill="url(#pat-bardage-bois)"
                />
                {/* Cast shadow LEFT side of attic (light from NE) */}
                <rect
                  x={segXL + atticSetbackPx}
                  y={yAtticFloor - atticHPx}
                  width={3}
                  height={atticHPx}
                  fill={PALETTE.shadowDeep}
                  opacity={0.20}
                />
                {/* Nez de dalle attic (béton sombre) */}
                <rect x={segXL} y={yAtticFloor - 3} width={segSpan} height={3} fill={PALETTE.menuiserieBlack} />
                {/* Cast shadow horizontal sous la dalle attic (sur l'étage du dessous) */}
                <rect x={segXL} y={yAtticFloor} width={segSpan} height={3} fill={PALETTE.shadowDeep} opacity={0.32} />
                <rect x={segXL} y={yAtticFloor + 3} width={segSpan} height={3} fill={PALETTE.shadowDeep} opacity={0.18} />
              </>
            )}

            {/* Soubassement (recessed = muted) */}
            <rect x={segXL - 1} y={ySoub} width={segSpan + 2} height={soubassementHeight} fill={PALETTE.soubassement} opacity={seg.isFront ? 1 : 0.7} />
            <line x1={segXL - 1} y1={ySoub + soubassementHeight * 0.5} x2={segXL + segSpan + 1} y2={ySoub + soubassementHeight * 0.5} stroke={PALETTE.soubassementLine} strokeWidth={0.4} />
            <line x1={segXL - 1} y1={ySoub} x2={segXL + segSpan + 1} y2={ySoub} stroke={PALETTE.menuiserieBlack} strokeWidth={1.2} />

            {/* Windows per story per bay. Recessed = smaller windows, no
                balcons, no entrance. */}
            {stories.map((s, i) => {
              const isRdc = i === 0;
              const isAttic = i === stories.length - 1;
              const [, yT] = worldToPx(0, s.yBase + s.height);
              const [, yB] = worldToPx(0, s.yBase);
              const storyH = yB - yT;
              const winSizeMult = seg.isFront ? 1.0 : 0.78;
              const winH = (isRdc
                ? storyH * 0.55 - soubassementHeight * 0.5
                : storyH * (isNorth ? 0.52 : 0.70)) * winSizeMult;
              const winW = Math.min(bayW * 0.58, isNorth ? 55 : 78) * winSizeMult;
              const winY = isRdc ? ySoub - winH - 6 : yT + (storyH - winH) / 2;

              return (
                <g key={`fa-${segIdx}-${i}`}>
                  {Array.from({ length: bays }).map((_, c) => {
                    const bayCx = segXL + (c + 0.5) * bayW;
                    // Skip any bay whose centre falls inside the brique tower
                    // x-range — that area is blind brique cladding (with the
                    // entrance integrated separately at RDC).
                    if (hasBriqueTower && bayCx > briqueX0 && bayCx < briqueX1) return null;
                    const isEntryBay = isRdc && seg.isFront && c === Math.floor(bays / 2) && showEntry;
                    if (isEntryBay) {
                      const doorH = storyH * 0.82;
                      const doorW = winW * 1.25;
                      const doorX = bayCx - doorW / 2;
                      const doorY = yB - doorH;
                      return (
                        <g key={c}>
                          <rect x={doorX - 16} y={doorY - 16} width={doorW + 32} height={5} fill={PALETTE.bardageWood} stroke={PALETTE.bardageWoodDark} strokeWidth={0.5} />
                          <rect x={doorX - 16} y={doorY - 21} width={doorW + 32} height={5} fill={PALETTE.bardageWoodDark} opacity={0.9} />
                          <rect x={doorX} y={doorY} width={doorW} height={doorH} fill={PALETTE.glass} stroke={PALETTE.menuiserieNoir} strokeWidth={1.8} />
                          <line x1={doorX + doorW / 2} y1={doorY} x2={doorX + doorW / 2} y2={doorY + doorH} stroke={PALETTE.menuiserieNoir} strokeWidth={1.4} />
                          <line x1={doorX} y1={doorY + doorH * 0.18} x2={doorX + doorW} y2={doorY + doorH * 0.18} stroke={PALETTE.menuiserieNoir} strokeWidth={0.9} />
                          <rect x={doorX + 3} y={doorY + 3} width={doorW / 2 - 5} height={doorH - 6} fill={PALETTE.glassReflect} opacity={0.35} />
                          <rect x={doorX + doorW * 0.40} y={doorY + doorH * 0.55} width={1.8} height={22} fill="#cbd5e1" />
                          <rect x={doorX - 3} y={doorY + doorH} width={doorW + 6} height={2.5} fill={PALETTE.menuiserieNoir} />
                          <text x={bayCx} y={doorY - 26} textAnchor="middle" fontSize={9} fontWeight={700} fill={PALETTE.menuiserieNoir} letterSpacing="0.6">
                            ENTRÉE
                          </text>
                        </g>
                      );
                    }
                    // Rythme par appart — un appart T3+ = 1 séjour porte-fenêtre
                    // + 2 chambres fenêtres hautes. Donc 1 PF tous les 3 bays
                    // (groupement réaliste, pas alternance 1:1).
                    // Skip variation on RDC/attic and recessed segment.
                    const isPorteFen = !isRdc && !isAttic && seg.isFront && c % 3 === 0;
                    // Resolve dims for this bay's window kind.
                    const bayWinW = isPorteFen ? Math.min(bayW * 0.62, isNorth ? 60 : 86) : winW;
                    const bayWinH = isPorteFen ? storyH * 0.86 : winH;
                    const bayWinY = isPorteFen ? yT + storyH * 0.07 : winY;
                    const wx = bayCx - bayWinW / 2;
                    return (
                      <g key={c}>
                        {/* Cadre aluminium noir 4cm — encadre la baie */}
                        <rect x={wx - 1.5} y={bayWinY - 1.5} width={bayWinW + 3} height={bayWinH + 3} fill={PALETTE.menuiserieBlack} />
                        {/* Vitrage low-e — couche de base + ciel dégradé */}
                        <rect x={wx} y={bayWinY} width={bayWinW} height={bayWinH} fill={PALETTE.glass} />
                        <rect x={wx} y={bayWinY} width={bayWinW} height={bayWinH} fill="url(#glass-sky)" />
                        {/* Cumulus reflétés (2 ellipses subtiles dans le tiers haut) */}
                        <ellipse cx={wx + bayWinW * 0.32} cy={bayWinY + bayWinH * 0.18} rx={bayWinW * 0.24} ry={bayWinH * 0.07} fill="#fff" opacity={0.42} />
                        <ellipse cx={wx + bayWinW * 0.68} cy={bayWinY + bayWinH * 0.10} rx={bayWinW * 0.18} ry={bayWinH * 0.05} fill="#fff" opacity={0.32} />
                        {/* Reflet ciel haut épais (frange lumineuse) */}
                        <rect x={wx + 1.5} y={bayWinY + 1.5} width={bayWinW - 3} height={2.0} fill="#fff" opacity={0.38} />
                        {/* Mullion vertical entre vantaux */}
                        <line x1={wx + bayWinW / 2} y1={bayWinY} x2={wx + bayWinW / 2} y2={bayWinY + bayWinH} stroke={PALETTE.menuiserieNoir} strokeWidth={1.2} />
                        {/* Traverse horizontale */}
                        {isPorteFen ? (
                          <line x1={wx} y1={bayWinY + bayWinH * 0.30} x2={wx + bayWinW} y2={bayWinY + bayWinH * 0.30} stroke={PALETTE.menuiserieNoir} strokeWidth={0.9} />
                        ) : (
                          <line x1={wx} y1={bayWinY + bayWinH * 0.5} x2={wx + bayWinW} y2={bayWinY + bayWinH * 0.5} stroke={PALETTE.menuiserieNoir} strokeWidth={0.7} opacity={0.85} />
                        )}
                        {/* Cast shadow cadre alu (light NE) */}
                        <line x1={wx} y1={bayWinY - 0.5} x2={wx + bayWinW} y2={bayWinY - 0.5} stroke="#fff" strokeWidth={0.3} opacity={0.45} />
                        <line x1={wx + bayWinW + 0.5} y1={bayWinY} x2={wx + bayWinW + 0.5} y2={bayWinY + bayWinH} stroke={PALETTE.shadowDeep} strokeWidth={0.4} opacity={0.55} />
                        <line x1={wx} y1={bayWinY + bayWinH + 0.5} x2={wx + bayWinW + 0.5} y2={bayWinY + bayWinH + 0.5} stroke={PALETTE.shadowDeep} strokeWidth={0.4} opacity={0.55} />
                        {/* Allège pierre noire sous fenêtre haute */}
                        {!isPorteFen && (
                          <rect x={wx - 2} y={bayWinY + bayWinH + 0.5} width={bayWinW + 4} height={2.2} fill={PALETTE.soubassement} />
                        )}
                        {/* Garde-corps verre devant porte-fenêtre */}
                        {isPorteFen && (
                          <g>
                            <rect x={wx - 4} y={bayWinY + bayWinH - 18} width={bayWinW + 8} height={14} fill={PALETTE.glassLight} opacity={0.35} />
                            <rect x={wx - 4} y={bayWinY + bayWinH - 18} width={bayWinW + 8} height={14} fill="none" stroke={PALETTE.gardeCorps} strokeWidth={0.7} />
                            <rect x={wx - 4} y={bayWinY + bayWinH - 18} width={bayWinW + 8} height={1.2} fill={PALETTE.gardeCorps} />
                          </g>
                        )}
                        {seg.isFront && !isRdc && !isAttic && renderBalconyOrLoggia({
                          side, isVoirie, isPignon, wx, winY: bayWinY, winW: bayWinW, winH: bayWinH, yT, yB,
                          palette: PALETTE, c, bays,
                        })}
                        {seg.isFront && !isRdc && isPignon && c > 0 && c < bays - 1 && (
                          <g opacity={0.88}>
                            {[-1, 1].map((sgn) => (
                              <rect
                                key={sgn}
                                x={wx + (sgn < 0 ? -4 : bayWinW + 1)}
                                y={bayWinY - 3}
                                width={3}
                                height={bayWinH + 6}
                                fill={PALETTE.menuiserieBlack}
                              />
                            ))}
                          </g>
                        )}
                      </g>
                    );
                  })}
                  {i < stories.length - 1 && (
                    <g>
                      {/* Nez de dalle béton — protrusion 5cm horizontale,
                          dépasse de 1.5px à gauche/droite + ombre portée
                          dégradée 6px en-dessous pour profondeur 3D. */}
                      <rect x={segXL - 1.5} y={yB - 3.5} width={segSpan + 3} height={3.5} fill={PALETTE.soubassement} />
                      {/* Reflet haut nez de dalle */}
                      <rect x={segXL - 1.5} y={yB - 3.5} width={segSpan + 3} height={0.6} fill="#fff" opacity={0.18} />
                      {/* Cast shadow under the slab edge — gradient implied by 3 stacked rects */}
                      <rect x={segXL} y={yB} width={segSpan} height={3} fill={PALETTE.shadowDeep} opacity={0.30} />
                      <rect x={segXL} y={yB + 3} width={segSpan} height={3} fill={PALETTE.shadowDeep} opacity={0.18} />
                      <rect x={segXL} y={yB + 6} width={segSpan} height={3} fill={PALETTE.shadowDeep} opacity={0.08} />
                    </g>
                  )}
                </g>
              );
            })}

            {/* Garde-corps balcons filants — front voirie segment only.
                Architecture moderne: dalle béton 6cm porte-à-faux + cast
                shadow gradué 12px en-dessous + garde-corps verre 1.10m
                avec main courante alu noir 5cm + lisse basse alu 5cm +
                mini-mullions tous les 1.5m. */}
            {seg.isFront && isVoirie && stories.slice(1, -1).map((s, i) => {
              const [, yB] = worldToPx(0, s.yBase);
              return (
                <g key={`balcony-filant-${segIdx}-${i}`}>
                  {/* Cast shadow under the cantilever — 4 strates dégradées */}
                  <rect x={segXL + 6} y={yB} width={segSpan - 12} height={3} fill={PALETTE.shadowDeep} opacity={0.42} />
                  <rect x={segXL + 6} y={yB + 3} width={segSpan - 12} height={3} fill={PALETTE.shadowDeep} opacity={0.26} />
                  <rect x={segXL + 6} y={yB + 6} width={segSpan - 12} height={3} fill={PALETTE.shadowDeep} opacity={0.14} />
                  <rect x={segXL + 6} y={yB + 9} width={segSpan - 12} height={2.5} fill={PALETTE.shadowDeep} opacity={0.07} />
                  {/* Dalle béton porte-à-faux — 5px épais avec léger débord */}
                  <rect x={segXL + 4.5} y={yB - 5} width={segSpan - 9} height={5} fill={PALETTE.soubassement} />
                  <rect x={segXL + 4.5} y={yB - 5} width={segSpan - 9} height={0.8} fill="#fff" opacity={0.18} />
                  {/* Garde-corps verre 16px hauteur */}
                  <rect x={segXL + 6} y={yB - 21} width={segSpan - 12} height={16} fill={PALETTE.glassLight} opacity={0.30} />
                  <rect x={segXL + 6} y={yB - 21} width={segSpan - 12} height={16} fill="none" stroke={PALETTE.gardeCorps} strokeWidth={0.6} />
                  {/* Mini-mullions verticaux toutes les ~1.5m */}
                  {(() => {
                    const segSpanM = segSpan / scale;
                    const nMullions = Math.max(0, Math.floor(segSpanM / 1.5) - 1);
                    return Array.from({ length: nMullions }).map((_, mi) => (
                      <line
                        key={`mm-${mi}`}
                        x1={segXL + 6 + (mi + 1) * (segSpan - 12) / (nMullions + 1)}
                        y1={yB - 20.5}
                        x2={segXL + 6 + (mi + 1) * (segSpan - 12) / (nMullions + 1)}
                        y2={yB - 5.5}
                        stroke={PALETTE.gardeCorps}
                        strokeWidth={0.5}
                        opacity={0.55}
                      />
                    ));
                  })()}
                  {/* Main courante alu noir 5cm — ligne épaisse en haut */}
                  <rect x={segXL + 4} y={yB - 22.5} width={segSpan - 8} height={2.0} fill={PALETTE.gardeCorps} />
                  <rect x={segXL + 4} y={yB - 22.5} width={segSpan - 8} height={0.5} fill="#fff" opacity={0.20} />
                  {/* Lisse basse alu noir */}
                  <rect x={segXL + 4} y={yB - 6.0} width={segSpan - 8} height={1.8} fill={PALETTE.gardeCorps} />
                  {/* Jardinières — bacs alu noir avec arbustes silhouettes
                      feuillues (graminées + petits buissons). 1 sur 2 slots
                      pour ne pas surcharger. */}
                  {(() => {
                    const segSpanM = segSpan / scale;
                    const nMullions = Math.max(0, Math.floor(segSpanM / 1.5) - 1);
                    const slots = nMullions + 1;
                    return Array.from({ length: slots }).map((_, ji) => {
                      const slotW = (segSpan - 12) / slots;
                      const jx0 = segXL + 6 + ji * slotW + 4;
                      const jw = slotW - 8;
                      if (jw < 6 || ji % 2 !== 0) return null;
                      const cy = yB - 24;
                      return (
                        <g key={`jard-${ji}`}>
                          {/* Bac alu noir avec retour bas + reflet */}
                          <rect x={jx0} y={yB - 26} width={jw} height={4} fill={PALETTE.gardeCorps} />
                          <rect x={jx0} y={yB - 26} width={jw} height={0.5} fill="#fff" opacity={0.20} />
                          {/* Arbustes silhouettes — formes irrégulières (path) */}
                          {Array.from({ length: Math.max(2, Math.floor(jw / 6)) }).map((_, b) => {
                            const total = Math.max(2, Math.floor(jw / 6));
                            const bx = jx0 + (b + 0.5) * jw / total;
                            const bushH = 4 + (b % 2 === 0 ? 1.5 : 0);
                            const isDark = b % 2 === 1;
                            const fill = isDark ? PALETTE.vegetationDark : PALETTE.vegetation;
                            return (
                              <g key={`bush-${b}`}>
                                {/* Buisson : cluster de 3 lobes irrégulier */}
                                <path
                                  d={`M ${bx - 2.2} ${cy + 0.5}
                                      Q ${bx - 2.8} ${cy - bushH * 0.7} ${bx - 0.5} ${cy - bushH}
                                      Q ${bx + 0.3} ${cy - bushH * 1.1} ${bx + 1.4} ${cy - bushH * 0.9}
                                      Q ${bx + 2.6} ${cy - bushH * 0.5} ${bx + 2.2} ${cy + 0.5}
                                      Z`}
                                  fill={fill}
                                />
                                {/* Petite graminée vertical fine (1 brin) */}
                                {b % 3 === 0 && (
                                  <line
                                    x1={bx + 0.5}
                                    y1={cy - bushH * 0.9}
                                    x2={bx + 1.2}
                                    y2={cy - bushH * 1.6}
                                    stroke={PALETTE.vegetationDark}
                                    strokeWidth={0.4}
                                  />
                                )}
                                {/* Texture feuillage (ombre interne) */}
                                <ellipse
                                  cx={bx - 0.5}
                                  cy={cy - bushH * 0.45}
                                  rx={0.8}
                                  ry={1.2}
                                  fill={PALETTE.vegetationDark}
                                  opacity={0.55}
                                />
                              </g>
                            );
                          })}
                        </g>
                      );
                    });
                  })()}
                </g>
              );
            })}

            {/* Parapet acrotère (recessed = muted) */}
            <rect x={segXL - 1} y={yTopSeg - parapetPx} width={segSpan + 2} height={parapetPx} fill={PALETTE.enduitShadow} opacity={seg.isFront ? 1 : 0.7} />
            <rect x={segXL - 1} y={yTopSeg - parapetPx} width={segSpan + 2} height={3} fill={PALETTE.menuiserieNoir} />
            <rect x={segXL - 1} y={yTopSeg} width={segSpan + 2} height={2.5} fill={PALETTE.menuiserieBlack} />

            {/* Couvertine zinc protrusive 4cm — déborde de 2px de chaque côté
                avec ombre portée fine en-dessous (lecture du capping métal) */}
            <rect x={segXL - 3} y={yTopSeg - parapetPx - 2.5} width={segSpan + 6} height={2.5} fill={PALETTE.menuiserieNoir} />
            <rect x={segXL - 3} y={yTopSeg - parapetPx - 2.5} width={segSpan + 6} height={0.6} fill="#fff" opacity={0.25} />

            {/* Toiture-terrasse — front segments only. Garde-corps verre +
                main courante alu visible AU-DESSUS de l'acrotère (terrasse
                accessible R+5), jardinière vegetalisée en bandeau. */}
            {seg.isFront && (() => {
              const yAcrotereTop = yTopSeg - parapetPx - 2.5;
              const gcH = 9;  // ~55cm garde-corps visible au-dessus
              const jardH = 4;  // ~25cm jardinière en bandeau
              return (
                <g>
                  {/* Bandeau jardinière végétalisée (tons verts) collé sur la couvertine */}
                  <rect x={segXL + 4} y={yAcrotereTop - jardH} width={segSpan - 8} height={jardH} fill={PALETTE.vegetationDark} />
                  {/* Texture verdure — petits bumps */}
                  {(() => {
                    const nBumps = Math.max(4, Math.floor(segSpan / 16));
                    return Array.from({ length: nBumps }).map((_, b) => (
                      <circle
                        key={`vg-${b}`}
                        cx={segXL + 4 + (b + 0.5) * (segSpan - 8) / nBumps}
                        cy={yAcrotereTop - jardH + 0.5}
                        r={1.6}
                        fill={PALETTE.vegetation}
                        opacity={0.85}
                      />
                    ));
                  })()}
                  {/* Garde-corps verre 110cm au-dessus jardinière */}
                  <rect x={segXL + 8} y={yAcrotereTop - jardH - gcH} width={segSpan - 16} height={gcH} fill={PALETTE.glassLight} opacity={0.30} />
                  <rect x={segXL + 8} y={yAcrotereTop - jardH - gcH} width={segSpan - 16} height={gcH} fill="none" stroke={PALETTE.gardeCorps} strokeWidth={0.5} />
                  {/* Mini-mullions garde-corps toiture */}
                  {(() => {
                    const segSpanM = segSpan / scale;
                    const nMullions = Math.max(0, Math.floor(segSpanM / 1.8));
                    return Array.from({ length: nMullions }).map((_, mi) => (
                      <line
                        key={`mt-${mi}`}
                        x1={segXL + 8 + (mi + 1) * (segSpan - 16) / (nMullions + 1)}
                        y1={yAcrotereTop - jardH - gcH + 0.5}
                        x2={segXL + 8 + (mi + 1) * (segSpan - 16) / (nMullions + 1)}
                        y2={yAcrotereTop - jardH - 0.5}
                        stroke={PALETTE.gardeCorps}
                        strokeWidth={0.4}
                        opacity={0.5}
                      />
                    ));
                  })()}
                  {/* Main courante alu noir 4cm */}
                  <rect x={segXL + 6} y={yAcrotereTop - jardH - gcH - 1.5} width={segSpan - 12} height={1.6} fill={PALETTE.gardeCorps} />

                  {/* Panneaux PV solaires sur toiture (RE2020) — alignés
                      en rangée derrière le garde-corps verre. */}
                  {(() => {
                    const pvW = 9;
                    const pvH = 4;
                    const pvY = yAcrotereTop - jardH - gcH - 1.5 - pvH - 2;
                    const pvN = Math.max(2, Math.floor((segSpan - 28) / (pvW + 2)));
                    const pvStart = segXL + (segSpan - (pvN * (pvW + 2) - 2)) / 2;
                    return Array.from({ length: pvN }).map((_, p) => (
                      <g key={`pv-${p}`}>
                        {/* Cellule PV bleu sombre */}
                        <rect x={pvStart + p * (pvW + 2)} y={pvY} width={pvW} height={pvH} fill="#1a3a5c" />
                        {/* Reflet ciel (gradient simple) */}
                        <rect x={pvStart + p * (pvW + 2)} y={pvY} width={pvW} height={1.2} fill="#5279a8" opacity={0.6} />
                        {/* Quadrillage cellules */}
                        <line x1={pvStart + p * (pvW + 2) + pvW / 2} y1={pvY} x2={pvStart + p * (pvW + 2) + pvW / 2} y2={pvY + pvH} stroke="#0a1f30" strokeWidth={0.3} />
                        <line x1={pvStart + p * (pvW + 2)} y1={pvY + pvH / 2} x2={pvStart + p * (pvW + 2) + pvW} y2={pvY + pvH / 2} stroke="#0a1f30" strokeWidth={0.3} />
                        {/* Cadre alu noir */}
                        <rect x={pvStart + p * (pvW + 2)} y={pvY} width={pvW} height={pvH} fill="none" stroke={PALETTE.menuiserieNoir} strokeWidth={0.4} />
                      </g>
                    ));
                  })()}
                </g>
              );
            })()}

            {/* Building outline per segment */}
            <rect x={segXL} y={yTopSeg} width={segSpan} height={totalHSeg} fill="none" stroke={PALETTE.menuiserieNoir} strokeWidth={seg.isFront ? 1.4 : 1.0} />

            {/* Recessed segment depth label */}
            {!seg.isFront && (
              <text
                x={segXL + segSpan / 2}
                y={yTopSeg + 14}
                fontSize={8.5}
                fontWeight={600}
                fill="#475569"
                textAnchor="middle"
                letterSpacing="0.4"
              >
                ⤓ retrait {seg.recessM.toFixed(1)} m
              </text>
            )}

            {/* ───── Brique tower (volume) ─────
                Drawn LAST in the segment so it overlays everything below.
                Full-height blind brique cladding with couvertine zinc above,
                pierre noire socle below, and (on principale voirie) the
                porte d'entrée punching through at RDC. */}
            {hasBriqueTower && (() => {
              // RDC top in screen coords (= floor of R+1)
              const rdcTopScreen = worldToPx(0, env.hauteur_rdc_m)[1];
              return (
                <g>
                  {/* Cast shadow LEFT of the brique tower — falls on the enduit
                      wall (light from NE = top-right). Convey 3D volume. */}
                  <rect x={briqueX0 - 7} y={yTopSeg + 2} width={7} height={totalHSeg - 2} fill={PALETTE.shadowDeep} opacity={0.28} />
                  <rect x={briqueX0 - 4} y={yTopSeg + 2} width={4} height={totalHSeg - 2} fill={PALETTE.shadowDeep} opacity={0.18} />
                  {/* Brique body — full segment height (between attic top and ground) */}
                  <rect x={briqueX0} y={yTopSeg + 2} width={briqueTowerWpx} height={totalHSeg - 2} fill="url(#pat-brique)" />
                  {/* Subtle vertical shadow gradient on the right edge for relief */}
                  <rect x={briqueX0} y={yTopSeg + 2} width={briqueTowerWpx} height={totalHSeg - 2} fill="url(#enduit-vshadow)" opacity={0.35} />
                  {/* Retours d'angle ombrés (gauche + droite) */}
                  <rect x={briqueX0} y={yTopSeg + 2} width={4} height={totalHSeg - 2} fill={PALETTE.shadowDeep} opacity={0.32} />
                  <rect x={briqueX1 - 4} y={yTopSeg + 2} width={4} height={totalHSeg - 2} fill={PALETTE.shadowDeep} opacity={0.20} />
                  {/* Joints horizontaux marqués (linteaux par étage pour rythme) */}
                  {stories.slice(1).map((s, i) => {
                    const [, yJoint] = worldToPx(0, s.yBase);
                    return (
                      <rect key={`bj-${i}`} x={briqueX0} y={yJoint - 0.5} width={briqueTowerWpx} height={1.0} fill={PALETTE.briqueJoint} opacity={0.85} />
                    );
                  })}
                  {/* Fenêtres palières — 1 par étage R+1 à R+5 (escalier
                      visible derrière la brique). Format vertical étroit
                      ~70cm × 1.50m, centrées sur la tour. */}
                  {stories.slice(1).map((s, i) => {
                    const [, yT] = worldToPx(0, s.yBase + s.height);
                    const [, yB] = worldToPx(0, s.yBase);
                    const storyH = yB - yT;
                    const palWinW = Math.min(briqueTowerWpx * 0.20, 12);
                    const palWinH = storyH * 0.62;
                    const palX = briqueCx - palWinW / 2;
                    const palY = yT + (storyH - palWinH) / 2;
                    return (
                      <g key={`pal-${i}`}>
                        {/* Cadre alu noir */}
                        <rect x={palX - 1.2} y={palY - 1.2} width={palWinW + 2.4} height={palWinH + 2.4} fill={PALETTE.menuiserieBlack} />
                        {/* Vitrage légèrement opacifié (escalier flou derrière) */}
                        <rect x={palX} y={palY} width={palWinW} height={palWinH} fill={PALETTE.glass} opacity={0.85} />
                        {/* Reflet ciel haut */}
                        <rect x={palX + 0.8} y={palY + 0.8} width={palWinW - 1.6} height={palWinH * 0.4} fill={PALETTE.glassReflect} opacity={0.45} />
                        {/* Mullion vertical central */}
                        <line x1={palX + palWinW / 2} y1={palY} x2={palX + palWinW / 2} y2={palY + palWinH} stroke={PALETTE.menuiserieNoir} strokeWidth={0.7} />
                        {/* Suggérer la limon escalier diagonal derrière (juste 1 ligne diagonale subtile) */}
                        <line
                          x1={palX + 1}
                          y1={palY + palWinH * 0.75}
                          x2={palX + palWinW - 1}
                          y2={palY + palWinH * 0.25}
                          stroke={PALETTE.menuiserieNoir}
                          strokeWidth={0.4}
                          opacity={0.45}
                        />
                      </g>
                    );
                  })}
                  {/* Ombre portée DESSOUS la tour (sur la dalle du sol) */}
                  <rect x={briqueX0 - 4} y={yBase} width={briqueTowerWpx + 8} height={5} fill={PALETTE.shadowDeep} opacity={0.32} />
                  <rect x={briqueX0 - 4} y={yBase + 5} width={briqueTowerWpx + 8} height={4} fill={PALETTE.shadowDeep} opacity={0.18} />
                  {/* Couvertine zinc en haut — protrusion 8cm noir mat avec reflet */}
                  <rect x={briqueX0 - 3} y={yTopSeg - 5} width={briqueTowerWpx + 6} height={6} fill={PALETTE.menuiserieNoir} />
                  <rect x={briqueX0 - 3} y={yTopSeg - 5} width={briqueTowerWpx + 6} height={1.5} fill="#fff" opacity={0.28} />
                  {/* Soubassement pierre noire 1.2m épais — devant le RDC béton */}
                  <rect x={briqueX0 - 1} y={ySoub - 1} width={briqueTowerWpx + 2} height={soubassementHeight + 1.5} fill={PALETTE.soubassement} />
                  {/* Reflet haut soubassement */}
                  <rect x={briqueX0 - 1} y={ySoub - 1} width={briqueTowerWpx + 2} height={0.7} fill="#fff" opacity={0.20} />
                  {/* Porte d'entrée intégrée (uniquement sur voirie principale) */}
                  {showEntry && (() => {
                    const yT = rdcTopScreen;
                    const yB = yBase;
                    const storyH = yB - yT;
                    const doorH = storyH * 0.92;
                    const doorW = briqueTowerWpx * 0.55;
                    const doorX = briqueCx - doorW / 2;
                    const doorY = yB - doorH;
                    return (
                      <g>
                        {/* Auvent profond porte-à-faux 1.20m alu noir +
                            ombre portée marquée sur la porte */}
                        <rect x={doorX - 18} y={doorY - 14} width={doorW + 36} height={6} fill={PALETTE.menuiserieNoir} />
                        <rect x={doorX - 18} y={doorY - 14} width={doorW + 36} height={1.5} fill="#fff" opacity={0.30} />
                        {/* Ombre portée auvent sur la brique au-dessus */}
                        <rect x={doorX - 18} y={doorY - 18} width={doorW + 36} height={4} fill={PALETTE.shadowDeep} opacity={0.30} />
                        {/* Ombre portée auvent sur la porte en-dessous */}
                        <rect x={doorX - 4} y={doorY - 8} width={doorW + 8} height={4} fill={PALETTE.shadowDeep} opacity={0.45} />
                        <rect x={doorX - 4} y={doorY - 4} width={doorW + 8} height={3} fill={PALETTE.shadowDeep} opacity={0.25} />
                        {/* Vitrage entrée toute hauteur — plus clair avec
                            reflets élaborés (verre transparent profond) */}
                        <rect x={doorX} y={doorY} width={doorW} height={doorH} fill={PALETTE.glassLight} stroke={PALETTE.menuiserieNoir} strokeWidth={2.2} />
                        {/* Reflets ciel (clair gradient haut) */}
                        <rect x={doorX + 2} y={doorY + 2} width={doorW - 4} height={doorH * 0.30} fill={PALETTE.glassReflect} opacity={0.55} />
                        {/* Reflet diagonal (clarté ciel) */}
                        <polygon
                          points={`${doorX + 4},${doorY + 4} ${doorX + doorW * 0.45},${doorY + 4} ${doorX + doorW * 0.65},${doorY + doorH - 4} ${doorX + 4},${doorY + doorH - 4}`}
                          fill="#fff"
                          opacity={0.18}
                        />
                        {/* 2 vantaux + imposte (alu fin) */}
                        <line x1={doorX + doorW / 2} y1={doorY} x2={doorX + doorW / 2} y2={doorY + doorH} stroke={PALETTE.menuiserieNoir} strokeWidth={1.5} />
                        <line x1={doorX} y1={doorY + doorH * 0.16} x2={doorX + doorW} y2={doorY + doorH * 0.16} stroke={PALETTE.menuiserieNoir} strokeWidth={1.0} />
                        {/* Sub-mullions vantaux (verticaux fins) */}
                        <line x1={doorX + doorW * 0.25} y1={doorY + doorH * 0.16} x2={doorX + doorW * 0.25} y2={doorY + doorH} stroke={PALETTE.menuiserieNoir} strokeWidth={0.5} opacity={0.5} />
                        <line x1={doorX + doorW * 0.75} y1={doorY + doorH * 0.16} x2={doorX + doorW * 0.75} y2={doorY + doorH} stroke={PALETTE.menuiserieNoir} strokeWidth={0.5} opacity={0.5} />
                        {/* Poignées inox verticales (1 par vantail) */}
                        <rect x={doorX + doorW * 0.42} y={doorY + doorH * 0.50} width={2.2} height={28} fill="#cbd5e1" />
                        <rect x={doorX + doorW * 0.42} y={doorY + doorH * 0.50} width={0.8} height={28} fill="#fff" opacity={0.40} />
                        {/* Seuil pierre noire avec petit débord */}
                        <rect x={doorX - 6} y={doorY + doorH} width={doorW + 12} height={3.5} fill={PALETTE.menuiserieNoir} />
                        <rect x={doorX - 6} y={doorY + doorH} width={doorW + 12} height={0.5} fill="#fff" opacity={0.20} />
                        {/* Label ENTRÉE — sur l'auvent métal */}
                        <text x={briqueCx} y={doorY - 17} textAnchor="middle" fontSize={9.5} fontWeight={700} fill="#fff" letterSpacing="0.8">
                          ENTRÉE
                        </text>
                      </g>
                    );
                  })()}
                </g>
              );
            })()}
          </g>
        );
      })}

      {/* Vertical depth-break separator at each segment boundary (dashed). */}
      {segments.length > 1 && segments.slice(1).map((seg, i) => (
        <line
          key={`break-${i}`}
          x1={seg.xLpx}
          y1={yTop - parapetPx - 4}
          x2={seg.xLpx}
          y2={yBase + 2}
          stroke={PALETTE.menuiserieNoir}
          strokeWidth={0.7}
          strokeDasharray="3 2"
          opacity={0.55}
        />
      ))}

      {/* ACROTÈRE label — pushed well above the toiture-terrasse stack
          (jardinière + garde-corps verre + main courante alu) so it
          doesn't collide with any of those elements. */}
      {(() => {
        const fronts = segments.filter((s) => s.isFront);
        if (fronts.length === 0) return null;
        const fxL = Math.min(...fronts.map((s) => s.xLpx));
        const fxR = Math.max(...fronts.map((s) => s.xLpx + s.spanPxSeg));
        // Stack above parapet: 2.5 (couvertine) + 4 (jardinière) + 9 (garde-corps) + 1.5 (main courante) + 6 (gap)
        return (
          <text
            x={(fxL + fxR) / 2}
            y={yTop - parapetPx - 26}
            fontSize={9.5}
            fontWeight={700}
            fill="#0f172a"
            textAnchor="middle"
          >
            ACROTÈRE
          </text>
        );
      })()}

      {/* ───── Contexte rue (trottoir + bordure granit + caniveau + mobilier urbain) ─────
          Présent uniquement sur les façades voirie. Référentiel PC obligatoire. */}
      {isVoirieAny && (() => {
        const trottoirH = 6;
        const trottoirW = 60;
        const tx0 = xL + spanPx + 4;
        const tx1 = tx0 + trottoirW;
        // Renders d'un lampadaire (3.5m de haut, sur le trottoir)
        const renderLampadaire = (lx: number, key: string) => {
          const lampH = 3.5 * scale;
          const lampTop = yBase - trottoirH - lampH;
          return (
            <g key={key}>
              {/* Mât conique alu noir */}
              <polygon
                points={`${lx - 0.5},${yBase - trottoirH} ${lx + 0.5},${yBase - trottoirH} ${lx + 0.3},${lampTop} ${lx - 0.3},${lampTop}`}
                fill={PALETTE.menuiserieNoir}
              />
              {/* Tête lampadaire (LED rectangulaire en porte-à-faux) */}
              <rect x={lx} y={lampTop - 1.5} width={9} height={2.2} fill={PALETTE.menuiserieNoir} />
              <rect x={lx + 0.5} y={lampTop} width={8} height={0.8} fill="#ffd966" opacity={0.85} />
              <rect x={lx + 0.5} y={lampTop} width={8} height={0.4} fill="#fff" opacity={0.6} />
              {/* Halo lumineux subtil */}
              <ellipse cx={lx + 4.5} cy={lampTop + 0.6} rx={6} ry={1.5} fill="#ffd966" opacity={0.15} />
              {/* Petit socle au sol */}
              <rect x={lx - 1.5} y={yBase - trottoirH - 1} width={3} height={1.2} fill={PALETTE.menuiserieNoir} />
            </g>
          );
        };
        return (
          <g>
            {/* Bordure granit + caniveau côté droit */}
            <rect x={tx0 - 1} y={yBase - trottoirH} width={trottoirW + 2} height={trottoirH} fill={PALETTE.soubassement} />
            <rect x={tx0 - 1} y={yBase - trottoirH} width={trottoirW + 2} height={0.8} fill="#fff" opacity={0.20} />
            <line x1={tx0 - 1} y1={yBase - 0.5} x2={tx1 + 1} y2={yBase - 0.5} stroke={PALETTE.menuiserieNoir} strokeWidth={0.7} />
            <rect x={tx0} y={yBase} width={trottoirW} height={3.5} fill="#2a2a2a" />
            <rect x={tx0} y={yBase} width={trottoirW} height={1.2} fill={PALETTE.shadowDeep} opacity={0.45} />
            {Array.from({ length: Math.floor(trottoirW / 12) }).map((_, mi) => (
              <rect key={`mark-${mi}`} x={tx0 + 4 + mi * 12} y={yBase + 1.6} width={6} height={0.6} fill="#e5e5e5" opacity={0.7} />
            ))}
            {/* Bordure granit + caniveau côté gauche */}
            <rect x={xL - trottoirW - 4} y={yBase - trottoirH} width={trottoirW + 2} height={trottoirH} fill={PALETTE.soubassement} />
            <rect x={xL - trottoirW - 4} y={yBase - trottoirH} width={trottoirW + 2} height={0.8} fill="#fff" opacity={0.20} />
            <line x1={xL - trottoirW - 5} y1={yBase - 0.5} x2={xL - 4} y2={yBase - 0.5} stroke={PALETTE.menuiserieNoir} strokeWidth={0.7} />
            <rect x={xL - trottoirW - 4} y={yBase} width={trottoirW} height={3.5} fill="#2a2a2a" />
            <rect x={xL - trottoirW - 4} y={yBase} width={trottoirW} height={1.2} fill={PALETTE.shadowDeep} opacity={0.45} />
            {Array.from({ length: Math.floor(trottoirW / 12) }).map((_, mi) => (
              <rect key={`markl-${mi}`} x={xL - trottoirW - 4 + 4 + mi * 12} y={yBase + 1.6} width={6} height={0.6} fill="#e5e5e5" opacity={0.7} />
            ))}
            {/* Trottoir devant le bâtiment (béton clair) avec joints */}
            <rect x={xL} y={yBase - trottoirH * 0.5} width={spanPx} height={trottoirH * 0.5} fill="#bcb8b0" opacity={0.55} />
            {(() => {
              const nJoints = Math.max(0, Math.floor(spanPx / (1.5 * scale)));
              return Array.from({ length: nJoints }).map((_, j) => (
                <line
                  key={`tj-${j}`}
                  x1={xL + (j + 1) * spanPx / (nJoints + 1)}
                  y1={yBase - trottoirH * 0.5}
                  x2={xL + (j + 1) * spanPx / (nJoints + 1)}
                  y2={yBase}
                  stroke={PALETTE.shadowDeep}
                  strokeWidth={0.3}
                  opacity={0.4}
                />
              ));
            })()}
            {/* Lampadaires LED — 1 sur chaque trottoir + 1 sur le large devant bâtiment */}
            {renderLampadaire(tx0 + trottoirW * 0.4, "lamp-r")}
            {renderLampadaire(xL - trottoirW * 0.5, "lamp-l")}
            {/* Poteau signalétique (petit) côté droit */}
            <g>
              <rect x={tx0 + trottoirW * 0.75 - 0.4} y={yBase - trottoirH - 14} width={0.8} height={14} fill={PALETTE.menuiserieNoir} />
              <rect x={tx0 + trottoirW * 0.75 - 4} y={yBase - trottoirH - 16} width={8} height={3} fill="#3b82f6" />
              <text x={tx0 + trottoirW * 0.75} y={yBase - trottoirH - 13.6} textAnchor="middle" fontSize={2.5} fontWeight={700} fill="#fff">P</text>
            </g>
          </g>
        );
      })()}

      {/* Échelle urbaine — 2 personnages 1.75m sur le trottoir + 1 banc.
          Convention PC : silhouettes pleines (fill gris clair) plutôt que
          stick-figures pour lecture immédiate de l'échelle. */}
      {(() => {
        const front = segments.find((s) => s.isFront);
        if (!front) return null;
        const personHpx = 1.75 * scale;
        const personWpx = 0.55 * scale;
        const headR = personWpx * 0.30;
        // Position 1 : devant le bâtiment, à 22% du front
        // Position 2 : sur le trottoir droit (à droite du bâtiment)
        const positions = [
          { cx: front.xLpx + front.spanPxSeg * 0.22, color: "#3a4754" },
          { cx: xL + spanPx + 32, color: "#5a4f42" },
        ];
        return (
          <g>
            {positions.map((p, i) => {
              const cx = p.cx;
              const footY = yBase;
              const headCy = footY - personHpx + headR;
              const torsoCy = footY - personHpx * 0.62;
              return (
                <g key={i}>
                  {/* Ombre portée au sol (light NE) */}
                  <ellipse cx={cx + personWpx * 0.3} cy={footY + 1.2} rx={personWpx * 0.5} ry={1.2} fill={PALETTE.shadowDeep} opacity={0.32} />
                  {/* Tête remplie */}
                  <circle cx={cx} cy={headCy} r={headR} fill={p.color} />
                  {/* Corps trapézoïdal (épaules + taille) */}
                  <path
                    d={`M ${cx - personWpx * 0.4} ${headCy + headR + 0.5}
                        L ${cx + personWpx * 0.4} ${headCy + headR + 0.5}
                        L ${cx + personWpx * 0.32} ${torsoCy + personHpx * 0.18}
                        L ${cx - personWpx * 0.32} ${torsoCy + personHpx * 0.18}
                        Z`}
                    fill={p.color}
                  />
                  {/* Jambes */}
                  <rect x={cx - personWpx * 0.30} y={torsoCy + personHpx * 0.18} width={personWpx * 0.22} height={footY - (torsoCy + personHpx * 0.18)} fill={p.color} />
                  <rect x={cx + personWpx * 0.08} y={torsoCy + personHpx * 0.18} width={personWpx * 0.22} height={footY - (torsoCy + personHpx * 0.18)} fill={p.color} />
                </g>
              );
            })}
            {/* Banc public — devant le trottoir gauche */}
            {(() => {
              const benchX = xL - 35;
              const benchY = yBase - 4;
              const benchW = 24;
              return (
                <g>
                  <rect x={benchX} y={benchY} width={benchW} height={2.5} fill={PALETTE.bardageWood} />
                  <rect x={benchX} y={benchY} width={benchW} height={0.6} fill="#fff" opacity={0.20} />
                  <rect x={benchX + 1.5} y={benchY + 2.5} width={1.6} height={4} fill={PALETTE.menuiserieBlack} />
                  <rect x={benchX + benchW - 3.1} y={benchY + 2.5} width={1.6} height={4} fill={PALETTE.menuiserieBlack} />
                  {/* Ombre portée du banc */}
                  <rect x={benchX + 1} y={yBase + 0.8} width={benchW} height={1.2} fill={PALETTE.shadowDeep} opacity={0.30} />
                </g>
              );
            })()}
          </g>
        );
      })()}

      {/* Ground line + shadow spanning the entire bbox. */}
      <line x1={xL - 30} y1={yBase} x2={xL + spanPx + 30} y2={yBase} stroke="#0f172a" strokeWidth={1.4} />
      <rect x={xL - 4} y={yBase} width={spanPx + 8} height={3} fill="#0f172a" opacity={0.22} />
    </g>
  );
}

/**
 * Per-side balcony / loggia logic. The SUD façade (voirie) gets a filant
 * balcony drawn separately (see main component); here we draw per-window
 * elements only on non-voirie sides to differentiate.
 */
function renderBalconyOrLoggia({
  side, isVoirie, isPignon, wx, winY, winW, winH, yT, yB, palette, c, bays,
}: {
  side: "nord" | "sud" | "est" | "ouest";
  isVoirie: boolean;
  isPignon: boolean;
  wx: number;
  winY: number;
  winW: number;
  winH: number;
  yT: number;
  yB: number;
  palette: typeof PALETTE;
  c: number;
  bays: number;
}) {
  // NORD: no balcony, just clean windows
  if (side === "nord") return null;

  // Pignons E/W: loggia creuse (recessed balcony) on the 2 central bays.
  // Recess profond avec ombre 3D interne, encadrement linteau béton sombre,
  // garde-corps barreaudage métal noir, plafond sombre suggérant la profondeur.
  if (isPignon) {
    const centralBays = c >= Math.floor(bays / 3) && c < Math.ceil((2 * bays) / 3);
    if (!centralBays) return null;
    const loggiaX = wx - winW * 0.18;
    const loggiaY = winY - 8;
    const loggiaW = winW * 1.36;
    const loggiaH = winH + 14;
    return (
      <g>
        {/* Fond recess très sombre (mur intérieur loggia dans l'ombre) */}
        <rect x={loggiaX} y={loggiaY} width={loggiaW} height={loggiaH} fill={palette.shadowDeep} opacity={0.55} />
        {/* Plafond loggia (gradient sombre vers le haut, suggère la profondeur) */}
        <rect x={loggiaX} y={loggiaY} width={loggiaW} height={loggiaH * 0.18} fill="#000" opacity={0.40} />
        {/* Mur intérieur ouest (côté gauche, en pleine ombre car light NE) */}
        <rect x={loggiaX} y={loggiaY} width={loggiaW * 0.10} height={loggiaH} fill="#000" opacity={0.35} />
        {/* Mur intérieur est (côté droite, partiellement éclairé) */}
        <rect x={loggiaX + loggiaW - loggiaW * 0.10} y={loggiaY} width={loggiaW * 0.10} height={loggiaH} fill="#000" opacity={0.18} />
        {/* Linteau béton sombre en haut (encadre la loggia) */}
        <rect x={loggiaX - 1} y={loggiaY - 2} width={loggiaW + 2} height={3} fill={palette.soubassement} />
        <rect x={loggiaX - 1} y={loggiaY - 2} width={loggiaW + 2} height={0.6} fill="#fff" opacity={0.20} />
        {/* Dalle bas loggia (béton brut) */}
        <rect x={loggiaX - 1} y={loggiaY + loggiaH} width={loggiaW + 2} height={3} fill={palette.soubassement} />
        {/* Cast shadow sous la dalle bas */}
        <rect x={loggiaX} y={loggiaY + loggiaH + 3} width={loggiaW} height={3} fill="#000" opacity={0.35} />
        <rect x={loggiaX} y={loggiaY + loggiaH + 6} width={loggiaW} height={2.5} fill="#000" opacity={0.18} />
        {/* Garde-corps barreaudage métal noir épais (devant la loggia) */}
        <rect x={loggiaX + 2} y={loggiaY + loggiaH - 16} width={loggiaW - 4} height={1.4} fill={palette.gardeCorps} />
        <rect x={loggiaX + 2} y={loggiaY + loggiaH - 4} width={loggiaW - 4} height={1.4} fill={palette.gardeCorps} />
        {Array.from({ length: 9 }).map((_, b) => (
          <line
            key={b}
            x1={loggiaX + 2 + b * (loggiaW - 4) / 8}
            y1={loggiaY + loggiaH - 16}
            x2={loggiaX + 2 + b * (loggiaW - 4) / 8}
            y2={loggiaY + loggiaH - 4}
            stroke={palette.gardeCorps}
            strokeWidth={0.6}
          />
        ))}
      </g>
    );
  }

  // SUD non-voirie impossible, already handled by `isVoirie`. Shouldn't reach.
  return null;
}

/* ─────────── Height dimension ─────────── */

function HeightDim({
  x1, yTop, yBottom, totalHeightM, stories, worldToPx, showTotal = true,
}: {
  x1: number; yTop: number; yBottom: number; totalHeightM: number;
  stories: Array<{ code: string; yBase: number; height: number }>;
  worldToPx: (x: number, y: number) => [number, number];
  showTotal?: boolean;
}) {
  return (
    <g>
      {/* Vertical dim line */}
      <line x1={x1} y1={yTop} x2={x1} y2={yBottom} stroke="#0f172a" strokeWidth={0.6} />
      {/* arrows top/bottom */}
      <polygon points={`${x1},${yTop} ${x1 - 3},${yTop + 6} ${x1 + 3},${yTop + 6}`} fill="#0f172a" />
      <polygon points={`${x1},${yBottom} ${x1 - 3},${yBottom - 6} ${x1 + 3},${yBottom - 6}`} fill="#0f172a" />
      {/* Total (skipped in coupe — NGT scale + header already convey total height) */}
      {showTotal && (
        <text x={x1 + 8} y={(yTop + yBottom) / 2} fontSize={10} fontWeight={700} fill="#0f172a" dominantBaseline="middle">
          {totalHeightM.toFixed(1)} m
        </text>
      )}

      {/* Inter-story ticks */}
      {stories.map((s, i) => {
        const [, yStoryTop] = worldToPx(0, s.yBase + s.height);
        const [, yStoryBot] = worldToPx(0, s.yBase);
        return (
          <g key={i}>
            <line x1={x1 - 5} y1={yStoryTop} x2={x1 + 5} y2={yStoryTop} stroke="#0f172a" strokeWidth={0.6} />
            <text x={x1 - 8} y={(yStoryTop + yStoryBot) / 2 + 3} textAnchor="end" fontSize={9} fill="#475569">
              {s.height.toFixed(2)} m
            </text>
          </g>
        );
      })}
    </g>
  );
}

/* ─────────── Width dimension (façade only) ─────────── */

function WidthDim({
  xLeft, xRight, y, widthM,
}: { xLeft: number; xRight: number; y: number; widthM: number }) {
  return (
    <g>
      <line x1={xLeft} y1={y} x2={xRight} y2={y} stroke="#0f172a" strokeWidth={0.6} />
      <polygon points={`${xLeft},${y} ${xLeft + 6},${y - 3} ${xLeft + 6},${y + 3}`} fill="#0f172a" />
      <polygon points={`${xRight},${y} ${xRight - 6},${y - 3} ${xRight - 6},${y + 3}`} fill="#0f172a" />
      <text x={(xLeft + xRight) / 2} y={y + 11} fontSize={10} fontWeight={700} fill="#0f172a" textAnchor="middle">
        {widthM.toFixed(1)} m
      </text>
    </g>
  );
}

/* ─────────── Orientation badge — which face of the building is shown ─────────── */

function FacadeOrientationBadge({
  x, y, side,
}: { x: number; y: number; side: "nord" | "sud" | "est" | "ouest" }) {
  // Tiny plan-view square with an arrow on the shown side
  const size = 42;
  const cx = x + size / 2, cy = y + size / 2;
  const half = size / 2 - 5;
  // Arrow pointing out of the building on the shown side
  const arrowPos: Record<"nord" | "sud" | "est" | "ouest", [number, number, number, number]> = {
    nord: [cx, cy - half, cx, cy - half - 9],
    sud: [cx, cy + half, cx, cy + half + 9],
    est: [cx + half, cy, cx + half + 9, cy],
    ouest: [cx - half, cy, cx - half - 9, cy],
  };
  const [ax1, ay1, ax2, ay2] = arrowPos[side];
  const perp: Record<"nord" | "sud" | "est" | "ouest", [number, number]> = {
    nord: [-1, 0], sud: [-1, 0], est: [0, -1], ouest: [0, -1],
  };
  const [px, py] = perp[side];
  return (
    <g>
      <rect x={x} y={y} width={size} height={size} fill="white" stroke="#475569" strokeWidth={0.6} rx={3} />
      <rect x={cx - half} y={cy - half} width={half * 2} height={half * 2} fill="#e2e8f0" stroke="#64748b" strokeWidth={0.8} />
      <line x1={ax1} y1={ay1} x2={ax2} y2={ay2} stroke="#0f766e" strokeWidth={1.3} />
      <polygon
        points={`${ax2},${ay2} ${ax2 + px * 3.5 + (ax2 - ax1) * 0.25},${ay2 + py * 3.5 + (ay2 - ay1) * 0.25} ${ax2 - px * 3.5 + (ax2 - ax1) * 0.25},${ay2 - py * 3.5 + (ay2 - ay1) * 0.25}`}
        fill="#0f766e"
      />
      <text x={cx} y={cy + 3} fontSize={9} fontWeight={700} fill="#0f172a" textAnchor="middle">
        {{ nord: "N", sud: "S", est: "E", ouest: "O" }[side]}
      </text>
    </g>
  );
}

/* ─────────── Coupe : profil TN + fondations + semelles ─────────── */

function CoupeGroundProfile({
  x, width, y, depthPx, scale, buildingX0, buildingX1,
}: {
  x: number; width: number; y: number; depthPx: number; scale: number;
  buildingX0: number; buildingX1: number;
}) {
  // TN naturel — légèrement ondulé pour rappeler le terrain
  const points: string[] = [];
  const steps = 14;
  const amp = 1.2; // amplitude TN
  for (let i = 0; i <= steps; i++) {
    const px = x + (i / steps) * width;
    // Ondulation déterministe
    const dy = Math.sin(i * 1.7) * amp + Math.cos(i * 0.9) * amp * 0.5;
    points.push(`${px},${y + dy}`);
  }
  const tnPath = `M ${x},${y + depthPx} L ${points[0]} L ${points.slice(1).join(" L ")} L ${x + width},${y + depthPx} Z`;

  // Semelles filantes : 50 cm × 30 cm sous chaque mur extérieur, à -1.0 m
  const semelleW = 0.50 * scale;
  const semelleH = 0.30 * scale;
  const semelleY = y + 1.0 * scale;

  return (
    <g>
      {/* Zone fondations / terre — pattern stippling */}
      <path d={tnPath} fill="url(#pat-terre)" stroke="none" />
      {/* TN line (slightly wavy) */}
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke="#0f172a"
        strokeWidth={1.3}
      />
      {/* Label "TN" */}
      <text x={x + 4} y={y - 3} fontSize={8} fill="#475569" fontStyle="italic">
        TN ±0.00
      </text>
      {/* Petit décaissement / nez de dalle (ressaut de 5 cm entre TN et dalle RDC) */}
      <line
        x1={buildingX0}
        y1={y - 2}
        x2={buildingX1}
        y2={y - 2}
        stroke="#0f172a"
        strokeWidth={0.4}
        strokeDasharray="2 1"
      />
      {/* Semelle filante gauche */}
      <rect
        x={buildingX0 - semelleW * 0.15}
        y={semelleY}
        width={semelleW}
        height={semelleH}
        fill="url(#pat-beton-arme)"
        stroke="#0f172a"
        strokeWidth={0.6}
      />
      {/* Semelle filante droite */}
      <rect
        x={buildingX1 - semelleW * 0.85}
        y={semelleY}
        width={semelleW}
        height={semelleH}
        fill="url(#pat-beton-arme)"
        stroke="#0f172a"
        strokeWidth={0.6}
      />
      {/* Cote de profondeur fondations */}
      <line
        x1={buildingX0 - semelleW - 6}
        y1={y}
        x2={buildingX0 - semelleW - 6}
        y2={semelleY + semelleH}
        stroke="#475569"
        strokeWidth={0.4}
        strokeDasharray="2 1.5"
      />
      <text
        x={buildingX0 - semelleW - 8}
        y={semelleY + semelleH / 2 + 3}
        fontSize={7.5}
        fill="#475569"
        textAnchor="end"
      >
        −1.30
      </text>
      {/* Bordure inférieure profil */}
      <line
        x1={x}
        y1={y + depthPx}
        x2={x + width}
        y2={y + depthPx}
        stroke="#0f172a"
        strokeWidth={0.5}
      />
    </g>
  );
}

/* ─────────── NGT altimetric scale (right edge, coupe only) ─────────── */

function NGTScale({
  x, yGround, stories, worldToPx, totalHeightM,
}: {
  x: number; yGround: number;
  stories: Array<{ code: string; yBase: number; height: number }>;
  worldToPx: (xM: number, yM: number) => [number, number];
  totalHeightM: number;
}) {
  // Niveaux NGT à afficher : TN (+0.00) puis chaque PHR (plancher haut).
  // Anti-collision: drop any tick whose label would overlap the previous one
  // vertically (< 11px apart in pixel space → label glyphs touch at 7.5pt).
  type Tick = { yPx: number; alt: number; label: string; code: string };
  const rawTicks: Tick[] = [{ yPx: yGround, alt: 0, label: "+0.00 NGT", code: "TN" }];
  for (let i = 0; i < stories.length; i++) {
    const s = stories[i];
    const altTop = s.yBase + s.height;
    const [, yTopPx] = worldToPx(0, altTop);
    const phrCode = i === 0 ? "PHRDC" : `PHR+${i}`;
    rawTicks.push({
      yPx: yTopPx,
      alt: altTop,
      label: `+${altTop.toFixed(2)}`,
      code: phrCode,
    });
  }
  // Sort by yPx ascending (top of building first → smaller y).
  // Then walk bottom-up, keeping TN (+0.00) and dropping any subsequent tick
  // closer than minGap to the LAST KEPT tick.
  const sortedDesc = [...rawTicks].sort((a, b) => b.yPx - a.yPx); // bottom first
  const minGap = 11;
  const keptDesc: Tick[] = [];
  for (const t of sortedDesc) {
    const lastY = keptDesc.length ? keptDesc[keptDesc.length - 1].yPx : Infinity;
    if (Math.abs(lastY - t.yPx) >= minGap || t.code === "TN") {
      keptDesc.push(t);
    }
  }
  // Special case: if TN (+0.00) and PHRDC end up too close, the loop kept TN
  // first (it's at the largest yPx). Now also ensure PHRDC is not within minGap
  // of TN — if so, drop PHRDC (TN is more important visually as the ground ref).
  const ticks = keptDesc;

  // Top tick is total height — ensure consistency
  const topAlt = totalHeightM;
  const [, yTopBld] = worldToPx(0, topAlt);

  return (
    <g style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
      {/* Axe vertical NGT */}
      <line x1={x} y1={yTopBld - 8} x2={x} y2={yGround + 4} stroke="#0f172a" strokeWidth={0.5} />
      {/* Label en-tête */}
      <text x={x} y={yTopBld - 14} fontSize={7.5} fontWeight={700} fill="#0f172a" textAnchor="middle">
        NGT
      </text>
      {ticks.map((t, i) => (
        <g key={i}>
          {/* Tick mark */}
          <line x1={x - 4} y1={t.yPx} x2={x + 4} y2={t.yPx} stroke="#0f172a" strokeWidth={0.6} />
          {/* Altitude on the right of the tick. PHR codes are intentionally
              omitted: floor codes (R+0…R+5) already appear on the LEFT axis,
              so repeating them on the NGT scale would just clutter the sheet. */}
          <text x={x + 6} y={t.yPx + 3} fontSize={7.5} fill="#0f172a">
            {t.label}
          </text>
        </g>
      ))}
    </g>
  );
}

/* ─────────── Légende matériaux (façade) ─────────── */

function LegendeMateriauxFacade({ x, y, maxWidth }: { x: number; y: number; maxWidth: number }) {
  // 3 items compacts pour tenir avant le title block (qui a été rétréci à 180px).
  const items: Array<{ fill: string; label: string }> = [
    { fill: PALETTE.enduitBase, label: "Enduit" },
    { fill: PALETTE.brique, label: "Brique" },
    { fill: PALETTE.bardageWood, label: "Bois" },
  ];
  const h = 30;
  const titleCellW = 60;
  const swatchW = 12;
  const swatchH = 8;
  const swatchToText = 4;
  const itemColW = swatchW + swatchToText + 36;
  const innerPad = 6;
  const required = titleCellW + innerPad + items.length * itemColW;
  const w = Math.max(required, maxWidth);
  const colW = (w - titleCellW - innerPad) / items.length;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill="white" stroke="#0f172a" strokeWidth={0.6} rx={2} />
      <text x={x + 6} y={y + 18} fontSize={8.5} fontWeight={700} fill="#0f172a">
        Matériaux
      </text>
      <line x1={x + titleCellW} y1={y + 4} x2={x + titleCellW} y2={y + h - 4} stroke="#cbd5e1" strokeWidth={0.4} />
      {items.map((it, i) => (
        <g key={i} transform={`translate(${x + titleCellW + innerPad / 2 + i * colW}, ${y + h / 2 - swatchH / 2})`}>
          <rect x={0} y={0} width={swatchW} height={swatchH} fill={it.fill} stroke="#475569" strokeWidth={0.4} />
          <text x={swatchW + swatchToText} y={swatchH - 0.5} fontSize={7.5} fill="#0f172a">
            {it.label}
          </text>
        </g>
      ))}
    </g>
  );
}

/* ─────────── Légende matériaux (coupe only) ─────────── */

function LegendeMateriaux({ x, y, maxWidth }: { x: number; y: number; maxWidth: number }) {
  // Horizontal strip layout: title on the left, swatches flowing to the right.
  // Each column reserves enough width for the longest label so swatch and text
  // never overlap. Strip height fixed at 30 px.
  // "Terre" is dropped: terrain naturel is already obvious from the
  // ground hatching on the section itself.
  const items: Array<{ pattern: string; label: string }> = [
    { pattern: "url(#pat-beton-arme)", label: "Béton armé" },
    { pattern: "url(#pat-isolation)", label: "Isolation" },
    { pattern: "url(#pat-etancheite)", label: "Étanchéité" },
  ];
  const h = 30;
  const titleCellW = 86;
  const swatchW = 14;
  const swatchH = 8;
  const swatchToText = 5;
  // 56 px per label fits "Étanchéité" at 7.5pt with no truncation.
  const itemColW = swatchW + swatchToText + 56;
  const innerPad = 8;
  const required = titleCellW + innerPad + items.length * itemColW;
  const w = Math.max(required, maxWidth);
  // Distribute slack so columns expand evenly when there is extra room.
  const colW = (w - titleCellW - innerPad) / items.length;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill="white" stroke="#0f172a" strokeWidth={0.6} rx={2} />
      <text x={x + 6} y={y + 18} fontSize={8.5} fontWeight={700} fill="#0f172a">
        Légende matériaux
      </text>
      <line x1={x + titleCellW} y1={y + 4} x2={x + titleCellW} y2={y + h - 4} stroke="#cbd5e1" strokeWidth={0.4} />
      {items.map((it, i) => (
        <g key={i} transform={`translate(${x + titleCellW + innerPad / 2 + i * colW}, ${y + h / 2 - swatchH / 2})`}>
          <rect x={0} y={0} width={swatchW} height={swatchH} fill={it.pattern} stroke="#475569" strokeWidth={0.4} />
          <text x={swatchW + swatchToText} y={swatchH - 0.5} fontSize={7.5} fill="#0f172a">
            {it.label}
          </text>
        </g>
      ))}
    </g>
  );
}
