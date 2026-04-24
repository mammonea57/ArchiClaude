"use client";

import type { BuildingModelPayload } from "@/lib/types";
import { bboxOf, coordsFromGeoJSON, makeProjector, ringToPath, type Coord } from "./plan-utils";
import { PlanPatterns, NorthArrow, ScaleBar, TitleBlock } from "./plan-patterns";

interface PlanMasseProps {
  bm: BuildingModelPayload;
  width?: number;
  height?: number;
  projectName?: string;
  streetName?: string;
  buildingNumber?: string;
  /** When true, overlay AA' (transversale) and BB' (longitudinale) section markers. */
  showCutLines?: boolean;
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
export function PlanMasse({
  bm, width = 880, height = 620, projectName,
  streetName = "Rue des Héros Nogentais",
  buildingNumber = "80",
  showCutLines = false,
}: PlanMasseProps) {
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

  const voirieSides = (bm.site.voirie_orientations?.length ? bm.site.voirie_orientations : ["sud"]) as string[];
  const voirieSide = voirieSides[0] ?? "sud";
  // Street names per side (fallback to the streetName prop for the primary side)
  const streetNames = ((bm.site as unknown as { street_names?: Record<string, string> }).street_names) ?? {};
  const getStreetName = (side: string): string =>
    streetNames[side] ?? (side === voirieSide ? streetName : `Rue (${side})`);

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

      {/* Road strip on EACH voirie side (L-shape or corner support) */}
      {voirieSides.map((side) => (
        <VoirieStrip
          key={`voirie-${side}`}
          voirieSide={side}
          expanded={expanded}
          project={project}
          thicknessM={6}
          streetName={getStreetName(side)}
        />
      ))}

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

      {/* Parcelle : toute la surface cadastrale doit être visible.
          On dessine (1) le fill pleine terre, (2) un contour CADASTRAL
          bien visible tracé en TRAIT CONTINU noir (comme un PC2
          réglementaire), (3) un halo rouge pointillé qui double le
          contour pour signaler la limite de propriété + (4) des
          marqueurs aux sommets pour que chaque point cadastral soit
          lisible. Le clip du bâtiment + pleine terre utilisent cette
          exacte géométrie, pas un bbox simplifié. */}
      {parcelle.length >= 3 && (
        <g>
          <path d={ringToPath(parcelle, project)} fill="url(#pat-lawn)" />
          {/* Contour cadastral opaque (trait fort PC2) */}
          <path
            d={ringToPath(parcelle, project)}
            fill="none"
            stroke="#0f172a"
            strokeWidth={2.2}
            strokeLinejoin="miter"
          />
          {/* Halo rouge pointillé = limite de propriété */}
          <path
            d={ringToPath(parcelle, project)}
            fill="none"
            stroke="#dc2626"
            strokeWidth={1.2}
            strokeDasharray="10 4 3 4"
            strokeOpacity={0.85}
          />
          {/* Marqueurs aux sommets du cadastre pour lisibilité */}
          {parcelle.map((pt, i) => {
            const [x, y] = project(pt);
            return (
              <circle
                key={`v-${i}`}
                cx={x}
                cy={y}
                r={1.8}
                fill="#dc2626"
                stroke="white"
                strokeWidth={0.6}
              />
            );
          })}
        </g>
      )}

      {/* Building footprint with shadow + roof + level count + number.
          The visual footprint is CLIPPED to the real parcelle polygon (not
          just bbox) — the BM solver currently builds axis-aligned rects
          sized to terrain bbox, which on non-rectangular parcels can poke
          outside the cadastre boundary. Clipping here keeps the plan
          faithful to the real constructible envelope while the solver
          catches up. */}
      {footprint.length >= 3 && (
        <g>
          {/* Clip-path: only show building INSIDE the parcelle */}
          {parcelle.length >= 3 && (
            <defs>
              <clipPath id="pc-clip-parcelle">
                <path d={ringToPath(parcelle, project)} />
              </clipPath>
            </defs>
          )}
          <g clipPath={parcelle.length >= 3 ? "url(#pc-clip-parcelle)" : undefined}>
            {/* Shadow — projected per floor to show volume */}
            {Array.from({ length: Math.min(bm.envelope.niveaux, 6) }).map((_, i) => (
              <path
                key={i}
                d={ringToPath(footprint, project)}
                fill="#0f172a"
                opacity={0.055}
                transform={`translate(${1.3 * (i + 1)}, ${2.2 * (i + 1)})`}
              />
            ))}
            {/* Footprint base */}
            <path
              d={ringToPath(footprint, project)}
              fill="#f5f5f4"
              stroke="#1c1917"
              strokeWidth={2.2}
              strokeLinejoin="miter"
              filter="url(#fx-shadow)"
            />
            {/* Roof indication — cross pattern */}
            <RoofDiagonals footprint={footprint} project={project} />
          </g>
          {/* Core marker, badge, entrance — drawn AFTER clip so they stay
              visible even if their position is near the parcel boundary */}
          <CoreMarker core={bm.core} project={project} scale={scale} />
          <LevelBadge footprint={footprint} project={project} niveaux={bm.envelope.niveaux} />
          <EntranceNumber
            footprint={footprint}
            voirieSide={voirieSide}
            voirieSides={voirieSides}
            project={project}
            number={buildingNumber}
            corePosition={bm.core.position_xy}
          />
        </g>
      )}

      {/* ── PC2 enrichissement ── Cotes de retrait, accès, stationnement */}
      {footprint.length >= 3 && parcelle.length >= 3 && (
        <RetraitCotes
          footprint={footprint}
          parcelle={parcelle}
          project={project}
          scale={scale}
        />
      )}
      {footprint.length >= 3 && (
        <AccesMarkers
          footprint={footprint}
          voirieSides={voirieSides}
          project={project}
          scale={scale}
          expanded={expanded}
        />
      )}
      {footprint.length >= 3 && parcelle.length >= 3 && (
        <Stationnement
          footprint={footprint}
          parcelle={parcelle}
          project={project}
          scale={scale}
          nbLogements={bm.envelope.niveaux > 0 ? (bm.niveaux?.reduce((acc, n) => acc + (n.cellules?.length ?? 0), 0) ?? 0) : 0}
        />
      )}
      {parcelle.length >= 3 && footprint.length >= 3 && (
        <PleineTerreLabel
          parcelle={parcelle}
          footprint={footprint}
          project={project}
        />
      )}

      {/* Section markers AA' / BB' — overlaid on top of footprint */}
      {showCutLines && footprint.length >= 3 && (
        <>
          <SectionMarker footprint={footprint} axis="y" label="A" color="#0f766e" project={project} />
          <SectionMarker footprint={footprint} axis="x" label="B" color="#be185d" project={project} />
        </>
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
  voirieSide, expanded, project, thicknessM, streetName,
}: {
  voirieSide: string;
  expanded: { minx: number; miny: number; maxx: number; maxy: number };
  project: (c: Coord) => Coord;
  thicknessM: number;
  streetName: string;
}) {
  const e = expanded;
  let band: Coord[];
  let labelPos: Coord;
  let labelRotation = 0;
  if (voirieSide === "sud") {
    band = [[e.minx, e.miny], [e.maxx, e.miny], [e.maxx, e.miny + thicknessM], [e.minx, e.miny + thicknessM]];
    labelPos = [(e.minx + e.maxx) / 2, e.miny + thicknessM / 2];
  } else if (voirieSide === "nord") {
    band = [[e.minx, e.maxy - thicknessM], [e.maxx, e.maxy - thicknessM], [e.maxx, e.maxy], [e.minx, e.maxy]];
    labelPos = [(e.minx + e.maxx) / 2, e.maxy - thicknessM / 2];
  } else if (voirieSide === "est") {
    band = [[e.maxx - thicknessM, e.miny], [e.maxx, e.miny], [e.maxx, e.maxy], [e.maxx - thicknessM, e.maxy]];
    labelPos = [e.maxx - thicknessM / 2, (e.miny + e.maxy) / 2];
    labelRotation = -90;
  } else {
    band = [[e.minx, e.miny], [e.minx + thicknessM, e.miny], [e.minx + thicknessM, e.maxy], [e.minx, e.maxy]];
    labelPos = [e.minx + thicknessM / 2, (e.miny + e.maxy) / 2];
    labelRotation = -90;
  }
  const d = ringToPath(band, project);
  const [lx, ly] = project(labelPos);
  return (
    <g>
      <path d={d} fill="url(#pat-road)" />
      {/* Center line stripes */}
      <path d={d} fill="none" stroke="white" strokeWidth={1.2} strokeDasharray="14 10" strokeOpacity={0.75} />
      {/* Sidewalk line on building side */}
      <SidewalkLine voirieSide={voirieSide} expanded={expanded} project={project} thicknessM={thicknessM} />
      {/* Street name label in CAPS */}
      <g transform={`translate(${lx}, ${ly}) rotate(${labelRotation})`}>
        <rect x={-70} y={-8} width={140} height={14} fill="#1c1917" opacity={0.6} rx={2} />
        <text y={3} textAnchor="middle" fontSize={10} fontWeight={700} fill="white" letterSpacing="1.2">
          {streetName.toUpperCase()}
        </text>
      </g>
    </g>
  );
}

function SidewalkLine({
  voirieSide, expanded, project, thicknessM,
}: {
  voirieSide: string;
  expanded: { minx: number; miny: number; maxx: number; maxy: number };
  project: (c: Coord) => Coord;
  thicknessM: number;
}) {
  const e = expanded;
  let p0: Coord, p1: Coord;
  if (voirieSide === "sud") {
    p0 = [e.minx, e.miny + thicknessM]; p1 = [e.maxx, e.miny + thicknessM];
  } else if (voirieSide === "nord") {
    p0 = [e.minx, e.maxy - thicknessM]; p1 = [e.maxx, e.maxy - thicknessM];
  } else if (voirieSide === "est") {
    p0 = [e.maxx - thicknessM, e.miny]; p1 = [e.maxx - thicknessM, e.maxy];
  } else {
    p0 = [e.minx + thicknessM, e.miny]; p1 = [e.minx + thicknessM, e.maxy];
  }
  const [x0, y0] = project(p0);
  const [x1, y1] = project(p1);
  return <line x1={x0} y1={y0} x2={x1} y2={y1} stroke="#1c1917" strokeWidth={1.2} />;
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

function LevelBadge({
  footprint, project, niveaux,
}: { footprint: Coord[]; project: (c: Coord) => Coord; niveaux: number }) {
  const bb = bboxOf(footprint);
  if (!bb) return null;
  const [tx, ty] = project([bb.maxx, bb.maxy]);
  return (
    <g transform={`translate(${tx - 8}, ${ty + 8})`}>
      <rect x={-28} y={-10} width={28} height={18} rx={2} fill="#dc2626" stroke="#7f1d1d" strokeWidth={0.6} />
      <text x={-14} y={3} textAnchor="middle" fontSize={10} fontWeight={700} fill="white">
        R+{niveaux - 1}
      </text>
    </g>
  );
}

function EntranceNumber({
  footprint, voirieSide, voirieSides, project, number, corePosition,
}: {
  footprint: Coord[];
  voirieSide: string;
  voirieSides?: string[];
  project: (c: Coord) => Coord;
  number: string;
  corePosition: [number, number];
}) {
  const bb = bboxOf(footprint);
  if (!bb) return null;
  // With 2 voiries, place entrance on the PRIMARY side but offset toward
  // the corner shared with the secondary side. This matches "à l'angle
  // des 2 rues" (intersection of both streets).
  const sides = voirieSides ?? [voirieSide];
  const primary = sides[0] ?? voirieSide;
  const secondary = sides.length > 1 ? sides[1] : null;

  const coordOnPrimary = (u: number): Coord => {
    if (primary === "sud") return [u, bb.miny];
    if (primary === "nord") return [u, bb.maxy];
    if (primary === "est") return [bb.maxx, u];
    return [bb.minx, u];
  };
  // Determine the U coordinate (position along the primary wall).
  // - If secondary street exists: put entrée close to the corner shared
  //   with secondary, slightly back from it so the door isn't ON the
  //   intersection (user asked "pas exactement à l'angle mais proche").
  // - Otherwise: align with core.
  let u: number;
  const [cxM, cyM] = corePosition;
  if (secondary) {
    if (primary === "est" || primary === "ouest") {
      // U axis is Y
      if (secondary === "nord") u = bb.maxy - (bb.maxy - bb.miny) * 0.12;
      else if (secondary === "sud") u = bb.miny + (bb.maxy - bb.miny) * 0.12;
      else u = cyM;
    } else {
      // primary is nord/sud → U axis is X
      if (secondary === "est") u = bb.maxx - (bb.maxx - bb.minx) * 0.12;
      else if (secondary === "ouest") u = bb.minx + (bb.maxx - bb.minx) * 0.12;
      else u = cxM;
    }
  } else {
    u = (primary === "est" || primary === "ouest") ? cyM : cxM;
  }
  const entryM = coordOnPrimary(u);
  const [ex, ey] = project(entryM);
  const isHoriz = primary === "sud" || primary === "nord";
  return (
    <g>
      {/* Entrance gap on the primary wall */}
      {isHoriz ? (
        <rect x={ex - 6} y={ey - 3} width={12} height={6} fill="white" stroke="#b45309" strokeWidth={1} />
      ) : (
        <rect x={ex - 3} y={ey - 6} width={6} height={12} fill="white" stroke="#b45309" strokeWidth={1} />
      )}
      {/* Number plate — push outward from building */}
      {(() => {
        let nx = ex, ny = ey;
        if (primary === "sud") { ny = ey + 14; }
        else if (primary === "nord") { ny = ey - 14; }
        else if (primary === "est") { nx = ex + 14; }
        else { nx = ex - 14; }
        return (
          <>
            <circle cx={nx} cy={ny} r={8} fill="white" stroke="#0f172a" strokeWidth={1} />
            <text x={nx} y={ny + 3} textAnchor="middle" fontSize={10} fontWeight={700} fill="#0f172a">
              {number}
            </text>
          </>
        );
      })()}
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

// ─────────────────────────────────────────────────────────────────────────
// PC2 enrichissement — cotes retrait, accès, stationnement, pleine terre
// ─────────────────────────────────────────────────────────────────────────

/** Cote segment with arrow heads + dimension text — classic archi notation. */
function Cote({
  x1, y1, x2, y2, label, offset = 14,
}: { x1: number; y1: number; x2: number; y2: number; label: string; offset?: number }) {
  // Compute perpendicular offset so the dimension sits outside the segment
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const ox1 = x1 + nx * offset;
  const oy1 = y1 + ny * offset;
  const ox2 = x2 + nx * offset;
  const oy2 = y2 + ny * offset;
  const midx = (ox1 + ox2) / 2;
  const midy = (oy1 + oy2) / 2;
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  const textAngle = angle > 90 || angle < -90 ? angle + 180 : angle;
  return (
    <g stroke="#1e293b" strokeWidth={0.6} fontFamily="system-ui">
      {/* Extension lines from endpoints */}
      <line x1={x1} y1={y1} x2={ox1} y2={oy1} strokeDasharray="2 2" />
      <line x1={x2} y1={y2} x2={ox2} y2={oy2} strokeDasharray="2 2" />
      {/* Dimension line */}
      <line x1={ox1} y1={oy1} x2={ox2} y2={oy2} />
      {/* Arrow heads */}
      <polygon points={`${ox1},${oy1} ${ox1 + nx * -3 + (dx / len) * 6},${oy1 + ny * -3 + (dy / len) * 6} ${ox1 + nx * 3 + (dx / len) * 6},${oy1 + ny * 3 + (dy / len) * 6}`} fill="#1e293b" stroke="none" />
      <polygon points={`${ox2},${oy2} ${ox2 + nx * -3 + (dx / len) * -6},${oy2 + ny * -3 + (dy / len) * -6} ${ox2 + nx * 3 + (dx / len) * -6},${oy2 + ny * 3 + (dy / len) * -6}`} fill="#1e293b" stroke="none" />
      {/* Label */}
      <g transform={`translate(${midx}, ${midy}) rotate(${textAngle})`}>
        <rect x={-18} y={-8} width={36} height={11} fill="white" stroke="none" />
        <text y={1} textAnchor="middle" fontSize={9} fontWeight={600} fill="#0f172a" stroke="none">{label}</text>
      </g>
    </g>
  );
}

function RetraitCotes({
  footprint, parcelle, project, scale,
}: {
  footprint: Coord[]; parcelle: Coord[]; project: (c: Coord) => Coord; scale: number;
}) {
  const fBB = bboxOf(footprint);
  const pBB = bboxOf(parcelle);
  if (!fBB || !pBB) return null;
  // Retraits en mètres (world units)
  const rSud   = fBB.miny - pBB.miny;
  const rNord  = pBB.maxy - fBB.maxy;
  const rOuest = fBB.minx - pBB.minx;
  const rEst   = pBB.maxx - fBB.maxx;
  const fmt = (m: number) => (m < 0 ? "" : `${m.toFixed(2)} m`);
  const midFx = (fBB.minx + fBB.maxx) / 2;
  const midFy = (fBB.miny + fBB.maxy) / 2;
  const _ = scale;
  const items: { side: string; a: Coord; b: Coord; label: string }[] = [];
  if (rSud > 0.3)   items.push({ side: "sud",   a: [midFx, pBB.miny], b: [midFx, fBB.miny], label: fmt(rSud) });
  if (rNord > 0.3)  items.push({ side: "nord",  a: [midFx, fBB.maxy], b: [midFx, pBB.maxy], label: fmt(rNord) });
  if (rOuest > 0.3) items.push({ side: "ouest", a: [pBB.minx, midFy], b: [fBB.minx, midFy], label: fmt(rOuest) });
  if (rEst > 0.3)   items.push({ side: "est",   a: [fBB.maxx, midFy], b: [pBB.maxx, midFy], label: fmt(rEst) });
  return (
    <g>
      {items.map((it, i) => {
        const [x1, y1] = project(it.a);
        const [x2, y2] = project(it.b);
        return <Cote key={i} x1={x1} y1={y1} x2={x2} y2={y2} label={it.label} offset={0} />;
      })}
    </g>
  );
}

function AccesMarkers({
  footprint, voirieSides, project, scale, expanded,
}: {
  footprint: Coord[]; voirieSides: string[]; project: (c: Coord) => Coord; scale: number;
  expanded: { minx: number; miny: number; maxx: number; maxy: number };
}) {
  const bb = bboxOf(footprint);
  if (!bb) return null;
  const _ = scale;
  const arrows: { from: Coord; to: Coord; label: string; color: string }[] = [];
  const primary = voirieSides[0] ?? "sud";
  // Piéton : arrive depuis la voirie primaire vers l'entrée bâtiment
  const fromP: Coord = primary === "est" ? [expanded.maxx - 2, bb.maxy - 1.5]
    : primary === "nord" ? [bb.maxx - 1.5, expanded.maxy - 2]
    : primary === "ouest" ? [expanded.minx + 2, (bb.miny + bb.maxy) / 2]
    : [(bb.minx + bb.maxx) / 2, expanded.miny + 2];
  const toP: Coord = primary === "est" ? [bb.maxx + 0.3, bb.maxy - 1.5]
    : primary === "nord" ? [bb.maxx - 1.5, bb.maxy + 0.3]
    : primary === "ouest" ? [bb.minx - 0.3, (bb.miny + bb.maxy) / 2]
    : [(bb.minx + bb.maxx) / 2, bb.miny - 0.3];
  arrows.push({ from: fromP, to: toP, label: "Piéton", color: "#2563eb" });
  // Véhicule (si parking existe — on met flèche depuis la voirie vers le fond de parcelle)
  const fromV: Coord = primary === "est" ? [expanded.maxx - 2, bb.miny + 2]
    : primary === "nord" ? [bb.minx + 2, expanded.maxy - 2]
    : primary === "ouest" ? [expanded.minx + 2, bb.miny + 2]
    : [bb.minx + 2, expanded.miny + 2];
  const toV: Coord = primary === "est" ? [bb.maxx + 0.3, bb.miny + 2]
    : primary === "nord" ? [bb.minx + 2, bb.maxy + 0.3]
    : primary === "ouest" ? [bb.minx - 0.3, bb.miny + 2]
    : [bb.minx + 2, bb.miny - 0.3];
  arrows.push({ from: fromV, to: toV, label: "Véhicule", color: "#b45309" });

  return (
    <g>
      {arrows.map((a, i) => {
        const [x1, y1] = project(a.from);
        const [x2, y2] = project(a.to);
        const dx = x2 - x1, dy = y2 - y1;
        const len = Math.hypot(dx, dy) || 1;
        const ux = dx / len, uy = dy / len;
        const ah = 7;
        return (
          <g key={i} stroke={a.color} strokeWidth={1.6} fill="none">
            <line x1={x1} y1={y1} x2={x2 - ux * ah} y2={y2 - uy * ah} />
            <polygon
              points={`${x2},${y2} ${x2 - ux * ah - (-uy) * ah * 0.5},${y2 - uy * ah - ux * ah * 0.5} ${x2 - ux * ah - uy * ah * 0.5},${y2 - uy * ah - (-ux) * ah * 0.5}`}
              fill={a.color} stroke="none"
            />
            <text x={(x1 + x2) / 2 + 4} y={(y1 + y2) / 2 - 4} fontSize={9} fontWeight={600} fill={a.color} stroke="white" strokeWidth={2} paintOrder="stroke">
              {a.label}
            </text>
          </g>
        );
      })}
    </g>
  );
}

function Stationnement({
  footprint, parcelle, project, scale, nbLogements,
}: {
  footprint: Coord[]; parcelle: Coord[]; project: (c: Coord) => Coord; scale: number; nbLogements: number;
}) {
  const fBB = bboxOf(footprint);
  const pBB = bboxOf(parcelle);
  if (!fBB || !pBB) return null;
  // Place une rangée de stationnement surface dans l'espace disponible côté sud/ouest
  // 1 place PMR + 1 place visiteur + 2 vélos (surface uniquement ; principal en sous-sol)
  const stripY = (pBB.miny + fBB.miny) / 2;
  const stripH = Math.min(5.0, (fBB.miny - pBB.miny) - 1.5);
  if (stripH < 2.5) return null;
  const slotW = 2.5, slotD = 5.0; // 5 x 2.5 m VL
  const startX = fBB.minx + 0.5;
  const slots = [
    { label: "PMR",     w: 3.3, color: "#1d4ed8" },
    { label: "Visit.",  w: slotW, color: "#334155" },
    { label: "Visit.",  w: slotW, color: "#334155" },
    { label: "Vélos",   w: 2.0, color: "#047857" },
  ];
  let x = startX;
  const _ = scale;
  return (
    <g>
      {slots.map((s, i) => {
        const [px0, py0] = project([x, stripY - slotD / 2]);
        const [px1, py1] = project([x + s.w, stripY + slotD / 2]);
        const w = Math.abs(px1 - px0);
        const h = Math.abs(py1 - py0);
        const rx = Math.min(px0, px1);
        const ry = Math.min(py0, py1);
        x += s.w + 0.15;
        return (
          <g key={i}>
            <rect x={rx} y={ry} width={w} height={h} fill="white" stroke={s.color} strokeWidth={1} strokeDasharray={s.label === "Vélos" ? "3 2" : undefined} />
            <text x={rx + w / 2} y={ry + h / 2 + 3} fontSize={8} fontWeight={600} fill={s.color} textAnchor="middle">
              {s.label}
            </text>
          </g>
        );
      })}
      {/* Small count annotation */}
      {(() => {
        const [lx, ly] = project([startX, stripY + slotD / 2 + 1.2]);
        return (
          <text x={lx} y={ly} fontSize={8.5} fill="#475569" fontWeight={500}>
            Stationnement surface · {nbLogements} logts → parking sous-sol
          </text>
        );
      })()}
    </g>
  );
}

function polygonArea(pts: Coord[]): number {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % pts.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

function PleineTerreLabel({
  parcelle, footprint, project,
}: { parcelle: Coord[]; footprint: Coord[]; project: (c: Coord) => Coord }) {
  const pA = polygonArea(parcelle);
  const fA = polygonArea(footprint);
  const pt = Math.max(0, pA - fA);
  const pct = pA > 0 ? Math.round((pt / pA) * 100) : 0;
  const pBB = bboxOf(parcelle);
  const fBB = bboxOf(footprint);
  if (!pBB || !fBB) return null;
  // Place label in a green zone (between footprint and parcel, south side)
  const lx = (pBB.minx + fBB.minx) / 2;
  const ly = (pBB.miny + fBB.maxy) / 2;
  const [tx, ty] = project([lx, ly]);
  return (
    <g>
      <rect x={tx - 58} y={ty - 10} width={116} height={22} fill="white" stroke="#15803d" strokeWidth={0.8} rx={2} />
      <text x={tx} y={ty - 1} fontSize={9.5} fontWeight={700} fill="#15803d" textAnchor="middle">
        Pleine terre
      </text>
      <text x={tx} y={ty + 9} fontSize={9} fill="#166534" textAnchor="middle">
        {Math.round(pt)} m² · {pct}%
      </text>
    </g>
  );
}

/* ─── Section marker (AA' or BB') — shows a dashed cut line across the
 *     footprint with an A/A' (or B/B') medallion at each end and view
 *     arrows indicating section direction. Convention used:
 *       axis="y" → line runs along the y-axis (vertical in plan), at mid-x.
 *                  Section spans y-extent. → AA' transversale.
 *       axis="x" → line runs along the x-axis (horizontal in plan), at mid-y.
 *                  Section spans x-extent. → BB' longitudinale.
 */
function SectionMarker({
  footprint, axis, label, color, project,
}: {
  footprint: Coord[];
  axis: "x" | "y";
  label: string;
  color: string;
  project: (c: Coord) => Coord;
}) {
  const bb = bboxOf(footprint);
  if (!bb) return null;
  const cx = (bb.minx + bb.maxx) / 2;
  const cy = (bb.miny + bb.maxy) / 2;
  // Extend 7m outside the footprint so medallions clear perimeter labels
  // (Piéton / Véhicule / Pleine terre).
  const extM = 7;
  const a: Coord = axis === "y" ? [cx, bb.miny - extM] : [bb.minx - extM, cy];
  const b: Coord = axis === "y" ? [cx, bb.maxy + extM] : [bb.maxx + extM, cy];
  const [ax, ay] = project(a);
  const [bx, by] = project(b);
  const dx = bx - ax, dy = by - ay;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const px = -uy, py = ux;
  const medR = 7;
  const renderMedallion = (x: number, y: number, txt: string, arrowOut: 1 | -1) => {
    const tipX = x + arrowOut * ux * (medR + 10) + px * 8;
    const tipY = y + arrowOut * uy * (medR + 10) + py * 8;
    const baseX = x + arrowOut * ux * (medR + 10);
    const baseY = y + arrowOut * uy * (medR + 10);
    return (
      <g key={txt}>
        <line x1={baseX} y1={baseY} x2={tipX} y2={tipY} stroke={color} strokeWidth={1.1} />
        <polygon
          points={`${tipX},${tipY} ${tipX - px * 4 - arrowOut * ux * 4},${tipY - py * 4 - arrowOut * uy * 4} ${tipX - px * 4 + arrowOut * ux * 4},${tipY - py * 4 + arrowOut * uy * 4}`}
          fill={color}
        />
        {/* Opaque white disc to block any underlying label */}
        <circle cx={x} cy={y} r={medR + 1.2} fill="white" />
        <circle cx={x} cy={y} r={medR} fill="white" stroke={color} strokeWidth={1.3} />
        <text x={x} y={y + 3} fontSize={9} fontWeight={800} fill={color} textAnchor="middle">
          {txt}
        </text>
      </g>
    );
  };
  return (
    <g>
      <line
        x1={ax} y1={ay} x2={bx} y2={by}
        stroke={color}
        strokeWidth={1.1}
        strokeDasharray="9 3 2 3"
        opacity={0.85}
      />
      {renderMedallion(ax, ay, label, -1)}
      {renderMedallion(bx, by, `${label}'`, 1)}
    </g>
  );
}
