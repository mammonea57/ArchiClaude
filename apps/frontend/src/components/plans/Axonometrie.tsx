"use client";

import type { BuildingModelPayload } from "@/lib/types";
import { bboxOf, coordsFromGeoJSON, type Coord } from "./plan-utils";
import { PlanPatterns, NorthArrow, TitleBlock } from "./plan-patterns";

interface AxonometrieProps {
  bm: BuildingModelPayload;
  width?: number;
  height?: number;
  /** Storey height in meters (default 2.8). */
  etageM?: number;
  /** Sun azimuth in degrees (from north, clockwise). Default SE. */
  sunAzDeg?: number;
  /** Sun elevation in degrees. Default 38° (typical studio sun). */
  sunElDeg?: number;
}

/**
 * Axonométrie 3D — projection isométrique photoréaliste avec matériaux,
 * ouvertures, ombres portées et bardage d'attique. Rendu orienté présentation
 * client : on doit lire les matériaux, les rythmes d'ouvertures et comprendre
 * la volumétrie d'un coup d'œil.
 */
export function Axonometrie({
  bm, width = 900, height = 620, etageM = 2.8,
  sunAzDeg = 135, sunElDeg = 38,
}: AxonometrieProps) {
  const footprint = coordsFromGeoJSON(bm.envelope?.footprint_geojson);
  if (footprint.length < 3) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg p-10 text-sm text-slate-400 border border-slate-100 w-full h-[360px]">
        Footprint indisponible pour l&apos;axonométrie.
      </div>
    );
  }
  const niveaux = Math.max(1, bm.envelope?.niveaux ?? 1);
  const rdcH = bm.envelope?.hauteur_rdc_m ?? etageM;
  const etageCH = bm.envelope?.hauteur_etage_courant_m ?? etageM;
  const totalH = rdcH + (niveaux - 1) * etageCH;
  const parapetH = 1.0;
  const atticSetbackM = 1.2;  // visual setback for attic

  const bb = bboxOf(footprint);
  if (!bb) return null;
  const cx = (bb.minx + bb.maxx) / 2;
  const cy = (bb.miny + bb.maxy) / 2;

  // ── Isometric projection ──
  // Classical 30°/30°: world x tilts right+down, y tilts left+down, z goes up.
  const a = Math.PI / 6;
  const ca = Math.cos(a), sa = Math.sin(a);
  const iso = (x: number, y: number, z: number): [number, number] => {
    const dx = x - cx, dy = y - cy;
    const sx = dx * ca - dy * ca;
    const sy = dx * sa + dy * sa - z;
    return [sx, sy];
  };

  // Ground shadow = footprint projected by sun vector
  const sunAz = (sunAzDeg * Math.PI) / 180;
  const sunEl = (sunElDeg * Math.PI) / 180;
  const shadowLen = totalH / Math.tan(sunEl);
  const shadowDx = Math.sin(sunAz + Math.PI) * shadowLen;
  const shadowDy = Math.cos(sunAz + Math.PI) * shadowLen;

  // Compute screen bbox including shadow + attic
  const zs = [0, totalH + parapetH];
  const buildingPts: [number, number][] = [];
  for (const [x, y] of footprint) for (const z of zs) buildingPts.push(iso(x, y, z));
  const shadowPts: [number, number][] = footprint.map(([x, y]) => iso(x + shadowDx, y + shadowDy, 0));
  const allPts = [...buildingPts, ...shadowPts];
  const sxs = allPts.map((p) => p[0]);
  const sys = allPts.map((p) => p[1]);
  const minSx = Math.min(...sxs), maxSx = Math.max(...sxs);
  const minSy = Math.min(...sys), maxSy = Math.max(...sys);
  const pad = 70;
  const scale = Math.min((width - 2 * pad) / (maxSx - minSx), (height - 2 * pad - 80) / (maxSy - minSy));
  const proj = (x: number, y: number, z: number): [number, number] => {
    const [sx, sy] = iso(x, y, z);
    return [(sx - minSx) * scale + pad, (sy - minSy) * scale + pad + 40];
  };

  const ringPath = (coords: Coord[], z: number): string => {
    if (!coords.length) return "";
    const pts = coords.map((c) => proj(c[0], c[1], z));
    return `M ${pts.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z`;
  };

  // Faces: one per footprint edge, extruded from z=0 to totalH (main) + attic
  // band + parapet band. Back-to-front sort for painter's algorithm.
  type Face = {
    path: string;
    depth: number;
    shade: number;        // 0..1 (1=brightest)
    tone: string;         // "wall" | "attic" | "parapet" | "soubassement"
    edgeIndex: number;
    isOuter: boolean;
    // For window grid rendering
    a: Coord; b: Coord; z0: number; z1: number;
    nx: number; ny: number;  // outward normal (xy plane)
  };
  const faces: Face[] = [];

  const atticZ0 = totalH - etageCH;  // bottom of attic = top of R+N-1
  const atticZ1 = totalH;
  const soubassementZ1 = 0.9;

  // Light direction in world XY for face shading: sun comes from SE by default
  // (azimuth 135°). Convert to an XY vector the face normal can dot with.
  const lightDirX = Math.sin(sunAz);
  const lightDirY = Math.cos(sunAz);

  const pushFace = (a: Coord, b: Coord, z0: number, z1: number, tone: string, edgeIndex: number) => {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    // outward normal (CCW polygon assumption): rotate edge -90° in world
    const nx = dy / len;
    const ny = -dx / len;
    // Sunlit factor: 1 when face points exactly toward sun
    const sunFactor = Math.max(0, nx * lightDirX + ny * lightDirY);
    const shade = 0.35 + 0.65 * sunFactor;  // 0.35 to 1.0
    const quad = [
      proj(a[0], a[1], z0), proj(b[0], b[1], z0),
      proj(b[0], b[1], z1), proj(a[0], a[1], z1),
    ];
    const path = `M ${quad.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z`;
    // Depth for sort = midpoint's projected sy (back-to-front)
    const [, midSy] = iso((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (z0 + z1) / 2);
    faces.push({ path, depth: midSy, shade, tone, edgeIndex, isOuter: true, a, b, z0, z1, nx, ny });
  };

  // Main walls: soubassement band + wall (up to atticZ0) + attic band + parapet.
  // Attic uses SAME footprint as walls (no geometric setback) — the setback
  // would distort L-shapes. Visual distinction is made with wood cladding.
  for (let i = 0; i < footprint.length; i++) {
    const a = footprint[i];
    const b = footprint[(i + 1) % footprint.length];
    pushFace(a, b, 0, soubassementZ1, "soubassement", i);
    pushFace(a, b, soubassementZ1, atticZ0, "wall", i);
    pushFace(a, b, atticZ0, atticZ1, "attic", i);
    pushFace(a, b, atticZ1, atticZ1 + parapetH, "parapet", i);
  }

  faces.sort((x, y) => x.depth - y.depth);

  // Palette (must match FacadeBody)
  const TONES = {
    enduit: "#e8e1d0",
    enduitDark: "#c9bfa6",
    enduitDarker: "#a89c7f",
    soubassement: "#4a4542",
    soubassementShade: "#2e2a28",
    attic: "#9c7d57",
    atticShade: "#6f5636",
    parapet: "#d9d0b8",
    parapetShade: "#9a8f74",
    roof: "#d6cfbd",
    roofShade: "#a89c7f",
    glass: "#4a7285",      // small dark window (iso distance)
    glassShade: "#2c4655",
  };

  const toneColor = (tone: string, shade: number): string => {
    const mix = (a: string, b: string, t: number) => {
      const ah = a.replace("#", ""), bh = b.replace("#", "");
      const ar = parseInt(ah.slice(0, 2), 16), ag = parseInt(ah.slice(2, 4), 16), ab = parseInt(ah.slice(4, 6), 16);
      const br = parseInt(bh.slice(0, 2), 16), bg = parseInt(bh.slice(2, 4), 16), bb2 = parseInt(bh.slice(4, 6), 16);
      const r = Math.round(ar + (br - ar) * t);
      const g = Math.round(ag + (bg - ag) * t);
      const b2 = Math.round(ab + (bb2 - ab) * t);
      return `rgb(${r},${g},${b2})`;
    };
    // shade 0 (shadow side) → dark; shade 1 (sunny side) → light
    if (tone === "wall") return mix(TONES.enduitDarker, TONES.enduit, shade);
    if (tone === "attic") return mix(TONES.atticShade, TONES.attic, shade);
    if (tone === "soubassement") return mix(TONES.soubassementShade, TONES.soubassement, shade);
    if (tone === "parapet") return mix(TONES.parapetShade, TONES.parapet, shade);
    return "#cccccc";
  };

  // Windows per face — draw small dark rectangles on wall faces only.
  // Use same bay logic as FacadeBody: ~4-8 bays per face.
  function renderWindowsForFace(face: Face): React.ReactNode {
    if (face.tone !== "wall") return null;
    const edgeLenM = Math.hypot(face.b[0] - face.a[0], face.b[1] - face.a[1]);
    if (edgeLenM < 3) return null;
    const bays = Math.max(2, Math.min(8, Math.round(edgeLenM / 3.8)));
    const floors = niveaux - 1;  // no windows on attic (separate band, own logic)
    const windows: React.ReactNode[] = [];
    for (let f = 0; f < floors; f++) {
      const isRdc = f === 0;
      const fz0 = f === 0 ? 0 + 0.9 : rdcH + (f - 1) * etageCH;  // above soubassement for RDC
      const fz1 = f === 0 ? rdcH : rdcH + f * etageCH;
      const winHM = isRdc ? 1.6 : 1.9;
      const winMargin = 0.35;
      for (let c = 0; c < bays; c++) {
        const t0 = (c + 0.2) / bays;
        const t1 = (c + 0.8) / bays;
        const xA = face.a[0] + (face.b[0] - face.a[0]) * t0;
        const yA = face.a[1] + (face.b[1] - face.a[1]) * t0;
        const xB = face.a[0] + (face.b[0] - face.a[0]) * t1;
        const yB = face.a[1] + (face.b[1] - face.a[1]) * t1;
        const wz0 = fz0 + winMargin;
        const wz1 = Math.min(fz1 - winMargin, wz0 + winHM);
        // Project 4 corners
        const p1 = proj(xA, yA, wz0);
        const p2 = proj(xB, yB, wz0);
        const p3 = proj(xB, yB, wz1);
        const p4 = proj(xA, yA, wz1);
        const path = `M ${p1[0].toFixed(1)},${p1[1].toFixed(1)} L ${p2[0].toFixed(1)},${p2[1].toFixed(1)} L ${p3[0].toFixed(1)},${p3[1].toFixed(1)} L ${p4[0].toFixed(1)},${p4[1].toFixed(1)} Z`;
        // Window tone depends on face shade (sunny = more reflective)
        const winColor = face.shade > 0.65 ? TONES.glass : TONES.glassShade;
        windows.push(
          <path
            key={`w-${face.edgeIndex}-${f}-${c}`}
            d={path}
            fill={winColor}
            stroke="#0a0a0a"
            strokeWidth={0.35}
          />,
        );
      }
    }
    return <g>{windows}</g>;
  }

  // Floor dividers (nez de dalle): horizontal lines on each wall face
  const floorLines: string[] = [];
  for (let k = 1; k < niveaux; k++) {
    const z = rdcH + (k - 1) * etageCH;
    if (z < atticZ0 - 0.1) floorLines.push(ringPath(footprint, z));
  }

  // Roof cap = flat top at atticZ1 + parapetH, same footprint as walls.
  const topPath = ringPath(footprint, atticZ1 + parapetH);
  // Silence unused var (atticSetbackM kept for future re-enabling)
  void atticSetbackM;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="bg-white border border-slate-200 rounded-lg"
      style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
    >
      <PlanPatterns />
      <defs>
        <linearGradient id="ax-sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#dbeafe" />
          <stop offset="1" stopColor="#f8fafc" />
        </linearGradient>
        <linearGradient id="ax-ground" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#e7e5e4" />
          <stop offset="1" stopColor="#d6d3d1" />
        </linearGradient>
        <radialGradient id="ax-shadow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#0f172a" stopOpacity={0.55} />
          <stop offset="0.7" stopColor="#0f172a" stopOpacity={0.2} />
          <stop offset="1" stopColor="#0f172a" stopOpacity={0} />
        </radialGradient>
      </defs>

      {/* Sky */}
      <rect x={0} y={0} width={width} height={height} fill="url(#ax-sky)" />

      {/* Ground */}
      <rect x={0} y={height * 0.55} width={width} height={height * 0.45} fill="url(#ax-ground)" />

      {/* Header */}
      <g>
        <rect x={20} y={20} width={width - 40} height={44} fill="white" stroke="#0f172a" strokeWidth={0.6} />
        <text x={30} y={40} fontSize={15} fontWeight={700} fill="#0f172a">
          Volumétrie — Axonométrie
        </text>
        <text x={30} y={56} fontSize={10.5} fill="#475569">
          R+{niveaux - 1} · {totalH.toFixed(1)} m · {Math.round(bm.envelope?.emprise_m2 ?? 0)} m² emprise · enduit clair + bardage bois attique + menuiseries noires
        </text>
      </g>

      {/* Cast shadow on ground (before building) */}
      <path
        d={(() => {
          const shadowCoords = footprint.map(([x, y]) => [x + shadowDx, y + shadowDy] as Coord);
          // Shadow = convex hull of footprint + translated footprint
          const union = [...footprint, ...shadowCoords];
          return ringPath(convexHull(union), 0);
        })()}
        fill="#0f172a"
        opacity={0.22}
      />

      {/* Walls (painter's sort) */}
      {faces.map((f, i) => (
        <g key={i}>
          <path
            d={f.path}
            fill={toneColor(f.tone, f.shade)}
            stroke="#1c1917"
            strokeWidth={0.55}
            strokeLinejoin="miter"
          />
          {/* Windows only on wall faces */}
          {renderWindowsForFace(f)}
          {/* Wood cladding vertical lines on attic faces */}
          {f.tone === "attic" && (() => {
            const boardN = Math.max(4, Math.round(Math.hypot(f.b[0] - f.a[0], f.b[1] - f.a[1]) / 0.18));
            return Array.from({ length: boardN }).map((_, k) => {
              const t = (k + 0.5) / boardN;
              const xA = f.a[0] + (f.b[0] - f.a[0]) * t;
              const yA = f.a[1] + (f.b[1] - f.a[1]) * t;
              const p0 = proj(xA, yA, f.z0);
              const p1 = proj(xA, yA, f.z1);
              return <line key={k} x1={p0[0]} y1={p0[1]} x2={p1[0]} y2={p1[1]} stroke={TONES.atticShade} strokeWidth={0.3} opacity={0.7} />;
            });
          })()}
          {/* Soubassement horizontal joint line */}
          {f.tone === "soubassement" && (() => {
            const p0 = proj(f.a[0], f.a[1], (f.z0 + f.z1) / 2);
            const p1 = proj(f.b[0], f.b[1], (f.z0 + f.z1) / 2);
            return <line x1={p0[0]} y1={p0[1]} x2={p1[0]} y2={p1[1]} stroke="#2a2725" strokeWidth={0.4} opacity={0.7} />;
          })()}
        </g>
      ))}

      {/* Floor dividers on visible walls (subtle) */}
      {floorLines.map((d, i) => (
        <path key={`fl-${i}`} d={d} fill="none" stroke="#5a5450" strokeWidth={0.45} opacity={0.38} strokeDasharray="3 2" />
      ))}

      {/* Roof (attique flat top) */}
      <path d={topPath} fill={TONES.roof} stroke="#1c1917" strokeWidth={1.0} />
      {/* Roof pattern (gravier/membrane) — faint dots across the full footprint */}
      {(() => {
        const dots: React.ReactNode[] = [];
        for (let i = 1; i < 7; i++) {
          for (let j = 1; j < 5; j++) {
            const tx = bb.minx + (i / 7) * (bb.maxx - bb.minx);
            const ty = bb.miny + (j / 5) * (bb.maxy - bb.miny);
            const [px, py] = proj(tx, ty, atticZ1 + parapetH);
            dots.push(<circle key={`dot-${i}-${j}`} cx={px} cy={py} r={0.8} fill="#78716c" opacity={0.5} />);
          }
        }
        return dots;
      })()}

      {/* Height label on right side */}
      {(() => {
        const [lx, ly] = proj(bb.maxx, bb.miny, totalH / 2);
        return (
          <g>
            <line x1={lx + 14} y1={ly - 6} x2={lx + 14} y2={ly + 10} stroke="#0f172a" strokeWidth={0.8} />
            <rect x={lx + 18} y={ly - 8} width={60} height={16} rx={2} fill="white" stroke="#0f172a" strokeWidth={0.5} />
            <text x={lx + 48} y={ly + 3.5} fontSize={10} fontWeight={700} fill="#0f172a" textAnchor="middle">
              {totalH.toFixed(1)} m
            </text>
          </g>
        );
      })()}

      <NorthArrow x={width - 60} y={98} size={46} rotationDeg={bm.site?.north_angle_deg ?? 0} />
      <TitleBlock
        x={width - 232}
        y={height - 60}
        title="Volumétrie 3D"
        subtitle="Axonométrie iso · DP-VL-01"
        sheetCode="PC6-1"
      />
    </svg>
  );
}

function convexHull(points: Coord[]): Coord[] {
  if (points.length < 3) return points.slice();
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o: Coord, a: Coord, b: Coord) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Coord[] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Coord[] = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}
