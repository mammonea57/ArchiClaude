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

  // Compute screen bbox including shadow + attic + urban context buffer (5m
  // around the building for trottoir + chaussée + trees + lampadaires).
  const urbanBufferM = 5.5;
  const zs = [0, totalH + parapetH];
  const buildingPts: [number, number][] = [];
  for (const [x, y] of footprint) for (const z of zs) buildingPts.push(iso(x, y, z));
  const shadowPts: [number, number][] = footprint.map(([x, y]) => iso(x + shadowDx, y + shadowDy, 0));
  // Urban context corners (approx — bbox + buffer). Reuse `bb` (non-null after early return).
  const urbanCorners: [number, number][] = [];
  for (const dxOff of [-urbanBufferM, urbanBufferM]) {
    for (const dyOff of [-urbanBufferM, urbanBufferM]) {
      urbanCorners.push(iso(bb.minx + dxOff, bb.miny + dyOff, 0));
      urbanCorners.push(iso(bb.maxx + dxOff, bb.maxy + dyOff, 0));
    }
  }
  // Trees can be ~5m tall above the ground
  for (const [x, y] of footprint) urbanCorners.push(iso(x, y, 5));
  const allPts = [...buildingPts, ...shadowPts, ...urbanCorners];
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
  const soubassementZ1 = 1.2;
  const rdcZ1 = rdcH;  // top of RDC = floor R+1 (béton matricé band)

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

  // Stratification 5 bandes : soubassement noir + RDC béton matricé + étages
  // enduit + attic bardage bois + parapet acrotère. Plus brique tower
  // (voirie principale) qui split l'edge concernée en 3 segments.
  const voirieAll = (bm.site?.voirie_orientations ?? ["sud"]) as Array<"nord" | "sud" | "est" | "ouest">;
  const towerWidthM = 4.2;
  // Find the longest voirie edge to host the brique tower (entrance hall).
  // A voirie edge has its outward normal pointing toward the voirie cardinal.
  const isEdgeOnVoirie = (a: Coord, b: Coord): boolean => {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len;  // CW polygon outward normal
    // Check each voirie cardinal direction
    return voirieAll.some((v) => {
      if (v === "nord") return ny > 0.7;
      if (v === "sud") return ny < -0.7;
      if (v === "est") return nx > 0.7;
      if (v === "ouest") return nx < -0.7;
      return false;
    });
  };
  // Pick the longest voirie edge for the principale tower
  let towerEdgeIdx = -1;
  let towerEdgeLen = 0;
  for (let i = 0; i < footprint.length; i++) {
    const a = footprint[i];
    const b = footprint[(i + 1) % footprint.length];
    if (!isEdgeOnVoirie(a, b)) continue;
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (len > towerEdgeLen) {
      towerEdgeLen = len;
      towerEdgeIdx = i;
    }
  }

  const pushBands = (a: Coord, b: Coord, edgeIdx: number) => {
    pushFace(a, b, 0, soubassementZ1, "soubassement", edgeIdx);
    pushFace(a, b, soubassementZ1, rdcZ1, "rdc", edgeIdx);
    pushFace(a, b, rdcZ1, atticZ0, "wall", edgeIdx);
    pushFace(a, b, atticZ0, atticZ1, "attic", edgeIdx);
    pushFace(a, b, atticZ1, atticZ1 + parapetH, "parapet", edgeIdx);
  };

  // Brique tower : protruding volume 1m hors façade. Génère 3 faces 3D
  // (face devant + 2 cotés) au lieu d'une face flush.
  const towerProtrusionM = 2.5;
  let towerProtrudeFaces: Array<{ a: Coord; b: Coord; z0: number; z1: number; tone: string; nx: number; ny: number; isTop?: boolean }> = [];
  for (let i = 0; i < footprint.length; i++) {
    const a = footprint[i];
    const b = footprint[(i + 1) % footprint.length];
    if (i === towerEdgeIdx && towerEdgeLen >= towerWidthM + 1.5) {
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const len = Math.hypot(dx, dy);
      const ux = dx / len, uy = dy / len;
      // Outward normal CW polygon = (-dy, dx)/len
      const nox = -dy / len, noy = dx / len;
      const t1 = (len - towerWidthM) / 2 / len;
      const t2 = 1 - t1;
      const towerA: Coord = [a[0] + dx * t1, a[1] + dy * t1];
      const towerB: Coord = [a[0] + dx * t2, a[1] + dy * t2];
      // Protruded corners (1m vers l'extérieur)
      const towerAOut: Coord = [towerA[0] + nox * towerProtrusionM, towerA[1] + noy * towerProtrusionM];
      const towerBOut: Coord = [towerB[0] + nox * towerProtrusionM, towerB[1] + noy * towerProtrusionM];
      // Bandes plein-hauteur SUR le mur de chaque côté de la tour
      pushBands(a, towerA, i);
      pushBands(towerB, b, i);
      // Tour : rendu en 3D protruding
      const towerTopZ = atticZ1 + parapetH + 0.5;
      // Stash the 3 visible faces (front + 2 sides) + top cap for painter's sort
      // Front face (towerAOut → towerBOut) — facing outward
      towerProtrudeFaces.push({ a: towerAOut, b: towerBOut, z0: 0, z1: towerTopZ, tone: "brique", nx: nox, ny: noy });
      // Right side face (towerB → towerBOut) — perpendicular to wall
      towerProtrudeFaces.push({ a: towerB, b: towerBOut, z0: 0, z1: towerTopZ, tone: "brique", nx: ux, ny: uy });
      // Left side face (towerAOut → towerA) — perpendicular to wall, other side
      towerProtrudeFaces.push({ a: towerAOut, b: towerA, z0: 0, z1: towerTopZ, tone: "brique", nx: -ux, ny: -uy });
      // Top cap (couvertine zinc, drawn as flat polygon)
      // Will be rendered separately as a polygon
      towerProtrudeFaces.push({ a: towerA, b: towerB, z0: towerTopZ, z1: towerTopZ, tone: "couvertine", nx: 0, ny: 0, isTop: true });
    } else {
      pushBands(a, b, i);
    }
  }
  // Tower : SKIP les push dans `faces` — on le rendra séparément après les walls
  // pour garantir qu'il est en front (et avoir contrôle sur l'ordre des 3 faces visibles).

  faces.sort((x, y) => x.depth - y.depth);

  // Palette unifiée avec FacadeBody (axe terre/sable + ocre + brique brûlée).
  const TONES = {
    enduit: "#ece7db",
    enduitDark: "#cfc8b3",
    enduitDarker: "#9e937a",
    soubassement: "#1f1d19",
    soubassementShade: "#0a0907",
    attic: "#a07956",
    atticShade: "#5e4429",
    parapet: "#cfc8b3",
    parapetShade: "#7a7264",
    rdc: "#8b8377",        // béton matricé RDC
    rdcShade: "#56524a",
    brique: "#7d3a26",
    briqueShade: "#4a1d11",
    roof: "#3f3a32",       // membrane étanchéité gris foncé
    roofShade: "#1f1c18",
    vegetation: "#5d7547",
    vegetationDark: "#3a4d2c",
    pv: "#1a3a5c",
    pvLight: "#5279a8",
    glass: "#9bcfd9",
    glassShade: "#5a8794",
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
    if (tone === "wall") return mix(TONES.enduitDarker, TONES.enduit, shade);
    if (tone === "rdc") return mix(TONES.rdcShade, TONES.rdc, shade);
    if (tone === "attic") return mix(TONES.atticShade, TONES.attic, shade);
    if (tone === "soubassement") return mix(TONES.soubassementShade, TONES.soubassement, shade);
    if (tone === "parapet") return mix(TONES.parapetShade, TONES.parapet, shade);
    if (tone === "brique") return mix(TONES.briqueShade, TONES.brique, shade);
    return "#cccccc";
  };

  // Windows per face — draw small dark rectangles on wall + RDC faces.
  function renderWindowsForFace(face: Face): React.ReactNode {
    if (face.tone !== "wall" && face.tone !== "rdc") return null;
    const edgeLenM = Math.hypot(face.b[0] - face.a[0], face.b[1] - face.a[1]);
    if (edgeLenM < 3) return null;
    const bays = Math.max(2, Math.min(9, Math.round(edgeLenM / 3.8)));
    const windows: React.ReactNode[] = [];
    if (face.tone === "rdc") {
      // RDC commercial : larger horizontal vitrines per bay
      const winHM = 2.0;
      const winMargin = 0.4;
      for (let c = 0; c < bays; c++) {
        const t0 = (c + 0.15) / bays;
        const t1 = (c + 0.85) / bays;
        const xA = face.a[0] + (face.b[0] - face.a[0]) * t0;
        const yA = face.a[1] + (face.b[1] - face.a[1]) * t0;
        const xB = face.a[0] + (face.b[0] - face.a[0]) * t1;
        const yB = face.a[1] + (face.b[1] - face.a[1]) * t1;
        const wz0 = face.z0 + winMargin;
        const wz1 = Math.min(face.z1 - winMargin, wz0 + winHM);
        const p1 = proj(xA, yA, wz0), p2 = proj(xB, yB, wz0), p3 = proj(xB, yB, wz1), p4 = proj(xA, yA, wz1);
        const path = `M ${p1[0].toFixed(1)},${p1[1].toFixed(1)} L ${p2[0].toFixed(1)},${p2[1].toFixed(1)} L ${p3[0].toFixed(1)},${p3[1].toFixed(1)} L ${p4[0].toFixed(1)},${p4[1].toFixed(1)} Z`;
        const winColor = face.shade > 0.65 ? TONES.glass : TONES.glassShade;
        windows.push(<path key={`rw-${face.edgeIndex}-${c}`} d={path} fill={winColor} stroke="#0a0a0a" strokeWidth={0.4} />);
      }
      return <g>{windows}</g>;
    }
    // wall : R+1 → R+(N-1) (étages courants)
    const floors = niveaux - 2;  // exclude RDC (its own band) + attic (its own band)
    for (let f = 0; f < floors; f++) {
      const fz0 = rdcH + f * etageCH;
      const fz1 = rdcH + (f + 1) * etageCH;
      const winHM = 1.9;
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
        const p1 = proj(xA, yA, wz0), p2 = proj(xB, yB, wz0), p3 = proj(xB, yB, wz1), p4 = proj(xA, yA, wz1);
        const path = `M ${p1[0].toFixed(1)},${p1[1].toFixed(1)} L ${p2[0].toFixed(1)},${p2[1].toFixed(1)} L ${p3[0].toFixed(1)},${p3[1].toFixed(1)} L ${p4[0].toFixed(1)},${p4[1].toFixed(1)} Z`;
        const winColor = face.shade > 0.65 ? TONES.glass : TONES.glassShade;
        windows.push(<path key={`w-${face.edgeIndex}-${f}-${c}`} d={path} fill={winColor} stroke="#0a0a0a" strokeWidth={0.35} />);
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

  // Strong contour lines around attic + parapet to delineate bands clearly
  // (corrige le bug visuel "transparent" entre dernier étage et toit).
  const atticBottomRing = ringPath(footprint, atticZ0);
  const atticTopRing = ringPath(footprint, atticZ1);
  const parapetTopRing = ringPath(footprint, atticZ1 + parapetH);

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

      {/* Contexte urbain au sol — trottoir béton autour du bâtiment + bordure
          granit + chaussée asphalte + arbres + voitures. Rendu APRÈS le sol
          (donc visible) mais AVANT les walls (donc le bâtiment l'occlut où il faut). */}
      {(() => {
        const elements: React.ReactNode[] = [];
        const trottoirOffsetM = 1.8;
        const chausseeOffsetM = 4.5;
        // Trottoir + chaussée — rectangle bbox-based pour éviter les slivers
        // triangulaires aux coins re-entrants du L (le rendu per-edge créait
        // des artefacts visibles). Approche : 3 anneaux concentriques autour
        // de la bbox du footprint.
        const tBb = bb;
        const buildBbox = (insetMin: number, insetMax: number): Coord[] => [
          [tBb.minx - insetMax, tBb.miny - insetMax],
          [tBb.maxx + insetMax, tBb.miny - insetMax],
          [tBb.maxx + insetMax, tBb.maxy + insetMax],
          [tBb.minx - insetMax, tBb.maxy + insetMax],
          [tBb.minx - insetMax, tBb.miny - insetMax],
          // inner ring (reverse order for SVG even-odd fill)
          [tBb.minx - insetMin, tBb.miny - insetMin],
          [tBb.minx - insetMin, tBb.maxy + insetMin],
          [tBb.maxx + insetMin, tBb.maxy + insetMin],
          [tBb.maxx + insetMin, tBb.miny - insetMin],
          [tBb.minx - insetMin, tBb.miny - insetMin],
        ];
        // Trottoir (anneau de 0 à trottoirOffsetM autour bbox)
        const trotRing = buildBbox(0, trottoirOffsetM);
        const trotPath = trotRing.map((c) => proj(c[0], c[1], 0));
        elements.push(
          <path
            key="trot-ring"
            d={`M ${trotPath.slice(0, 5).map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z M ${trotPath.slice(5).map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z`}
            fill="#bcb8b0"
            stroke="none"
            opacity={0.92}
            fillRule="evenodd"
          />,
        );
        // Chaussée asphalte (anneau de trottoirOffsetM à chausseeOffsetM)
        const chausRing = buildBbox(trottoirOffsetM, chausseeOffsetM);
        const chausPath = chausRing.map((c) => proj(c[0], c[1], 0));
        elements.push(
          <path
            key="chaus-ring"
            d={`M ${chausPath.slice(0, 5).map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z M ${chausPath.slice(5).map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z`}
            fill="#3a3833"
            stroke="none"
            fillRule="evenodd"
          />,
        );
        // Bordure granit (rectangle ouvert à trottoirOffsetM)
        const borderInner: Coord[] = [
          [tBb.minx - trottoirOffsetM, tBb.miny - trottoirOffsetM],
          [tBb.maxx + trottoirOffsetM, tBb.miny - trottoirOffsetM],
          [tBb.maxx + trottoirOffsetM, tBb.maxy + trottoirOffsetM],
          [tBb.minx - trottoirOffsetM, tBb.maxy + trottoirOffsetM],
          [tBb.minx - trottoirOffsetM, tBb.miny - trottoirOffsetM],
        ];
        const borderPath = borderInner.map((c) => proj(c[0], c[1], 0));
        elements.push(
          <path
            key="bord-ring"
            d={`M ${borderPath.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")}`}
            fill="none"
            stroke="#1f1d19"
            strokeWidth={1.4}
          />,
        );
        // Marquage axe chaussée (pointillés au milieu)
        const midOffsetM = (trottoirOffsetM + chausseeOffsetM) / 2;
        for (const side of ["s", "n", "e", "w"] as const) {
          let a: Coord, b: Coord;
          if (side === "s") {
            a = [tBb.minx, tBb.miny - midOffsetM];
            b = [tBb.maxx, tBb.miny - midOffsetM];
          } else if (side === "n") {
            a = [tBb.minx, tBb.maxy + midOffsetM];
            b = [tBb.maxx, tBb.maxy + midOffsetM];
          } else if (side === "e") {
            a = [tBb.maxx + midOffsetM, tBb.miny];
            b = [tBb.maxx + midOffsetM, tBb.maxy];
          } else {
            a = [tBb.minx - midOffsetM, tBb.miny];
            b = [tBb.minx - midOffsetM, tBb.maxy];
          }
          const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
          const nDashes = Math.max(2, Math.floor(len / 4));
          for (let k = 0; k < nDashes; k++) {
            const t0 = (k + 0.3) / nDashes;
            const t1 = (k + 0.7) / nDashes;
            const a0: Coord = [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0];
            const a1: Coord = [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1];
            const [p0x, p0y] = proj(a0[0], a0[1], 0);
            const [p1x, p1y] = proj(a1[0], a1[1], 0);
            elements.push(
              <line
                key={`ax-${side}-${k}`}
                x1={p0x}
                y1={p0y}
                x2={p1x}
                y2={p1y}
                stroke="#e5e5e5"
                strokeWidth={0.8}
                opacity={0.7}
              />,
            );
          }
        }

        // 2. Arbres — placés sur le trottoir face Sud (low y) et face Est (max x)
        // Vue iso: cercle + triangle pour le tronc
        const renderTree = (wx: number, wy: number, key: string) => {
          const treeH = 4.5;
          const trunkH = 1.6;
          const [tx, ty0] = proj(wx, wy, 0);
          const [, ty1] = proj(wx, wy, trunkH);
          const [, ty2] = proj(wx, wy, treeH);
          return (
            <g key={key}>
              {/* Tronc */}
              <line x1={tx} y1={ty0} x2={tx} y2={ty1} stroke="#5e4429" strokeWidth={1.6} />
              {/* Houppier (3 cercles superposés pour profondeur) */}
              <circle cx={tx} cy={ty1 - 6} r={9} fill="#3a4d2c" opacity={0.92} />
              <circle cx={tx - 3} cy={ty1 - 9} r={6.5} fill="#5d7547" opacity={0.95} />
              <circle cx={tx + 3} cy={ty1 - 4} r={5} fill="#5d7547" opacity={0.85} />
              {/* Ombre portée */}
              <ellipse cx={tx + 6} cy={ty0 + 1.5} rx={9} ry={2.5} fill="#000" opacity={0.30} />
            </g>
          );
        };
        // Place 3 arbres devant la voirie est (high x)
        const [eastA, eastB] = (() => {
          const idx = towerEdgeIdx >= 0 ? towerEdgeIdx : 0;
          return [footprint[idx], footprint[(idx + 1) % footprint.length]];
        })();
        for (let k = 0; k < 3; k++) {
          const t = (k + 0.5) / 3;
          // Skip the middle (where the tower is)
          if (t > 0.4 && t < 0.6) continue;
          const wx = eastA[0] + (eastB[0] - eastA[0]) * t;
          const wy = eastA[1] + (eastB[1] - eastA[1]) * t;
          // Push to trottoir
          const dx = eastB[0] - eastA[0], dy = eastB[1] - eastA[1];
          const len = Math.hypot(dx, dy) || 1;
          const nx = -dy / len, ny = dx / len;
          elements.push(renderTree(wx + nx * (trottoirOffsetM * 0.55), wy + ny * (trottoirOffsetM * 0.55), `tree-e-${k}`));
        }

        // 3. Lampadaires — 1 sur le trottoir EST, 1 NORD
        const renderLamp = (wx: number, wy: number, key: string) => {
          const lampH = 4.5;
          const [lx, ly0] = proj(wx, wy, 0);
          const [, ly1] = proj(wx, wy, lampH);
          return (
            <g key={key}>
              <line x1={lx} y1={ly0} x2={lx} y2={ly1} stroke="#0a0907" strokeWidth={1.2} />
              <rect x={lx - 1} y={ly1 - 2} width={6} height={2.5} fill="#0a0907" />
              <rect x={lx - 0.5} y={ly1 - 1.2} width={5} height={1.2} fill="#ffd966" opacity={0.85} />
              {/* Halo lumineux */}
              <ellipse cx={lx + 2.5} cy={ly1 - 0.5} rx={5} ry={1.5} fill="#ffd966" opacity={0.18} />
              {/* Ombre du mât au sol */}
              <ellipse cx={lx + 4} cy={ly0 + 1} rx={4.5} ry={1.5} fill="#000" opacity={0.3} />
            </g>
          );
        };
        if (eastA && eastB) {
          const wx0 = eastA[0] + (eastB[0] - eastA[0]) * 0.15;
          const wy0 = eastA[1] + (eastB[1] - eastA[1]) * 0.15;
          const wx1 = eastA[0] + (eastB[0] - eastA[0]) * 0.85;
          const wy1 = eastA[1] + (eastB[1] - eastA[1]) * 0.85;
          const dx = eastB[0] - eastA[0], dy = eastB[1] - eastA[1];
          const len = Math.hypot(dx, dy) || 1;
          const nx = -dy / len, ny = dx / len;
          elements.push(renderLamp(wx0 + nx * trottoirOffsetM * 0.85, wy0 + ny * trottoirOffsetM * 0.85, "lamp-e-0"));
          elements.push(renderLamp(wx1 + nx * trottoirOffsetM * 0.85, wy1 + ny * trottoirOffsetM * 0.85, "lamp-e-1"));
        }

        // 4. Voiture (vue de dessus iso) sur la chaussée
        const renderCar = (wx: number, wy: number, color: string, key: string) => {
          const carL = 4.5;
          const carW = 1.8;
          // Aligned along the road direction (parallel to building edge)
          // Approx: get east edge direction
          const dx = eastB[0] - eastA[0], dy = eastB[1] - eastA[1];
          const len = Math.hypot(dx, dy) || 1;
          const ux = dx / len, uy = dy / len;       // unit along edge
          const vx = uy, vy = -ux;                  // perpendicular (toward outside)
          const corners: Coord[] = [
            [wx - ux * carL/2 - vx * carW/2, wy - uy * carL/2 - vy * carW/2],
            [wx + ux * carL/2 - vx * carW/2, wy + uy * carL/2 - vy * carW/2],
            [wx + ux * carL/2 + vx * carW/2, wy + uy * carL/2 + vy * carW/2],
            [wx - ux * carL/2 + vx * carW/2, wy - uy * carL/2 + vy * carW/2],
          ];
          const carH = 1.3;
          const tops = corners.map(([x, y]) => proj(x, y, carH));
          const bots = corners.map(([x, y]) => proj(x, y, 0));
          // Body top
          elements.push(
            <path key={`${key}-top`}
              d={`M ${tops.map((p) => `${p[0]},${p[1]}`).join(" L ")} Z`}
              fill={color} stroke="#0a0907" strokeWidth={0.5} />,
          );
          // Side faces (only 2 visible)
          for (let s = 0; s < 4; s++) {
            const t0 = tops[s], t1 = tops[(s + 1) % 4];
            const b0 = bots[s], b1 = bots[(s + 1) % 4];
            elements.push(
              <path key={`${key}-side-${s}`}
                d={`M ${b0[0]},${b0[1]} L ${b1[0]},${b1[1]} L ${t1[0]},${t1[1]} L ${t0[0]},${t0[1]} Z`}
                fill={color} stroke="#0a0907" strokeWidth={0.4} opacity={0.85} />,
            );
          }
          // Reflet pare-brise
          const [glx, gly] = proj(wx, wy, carH);
          elements.push(
            <ellipse key={`${key}-glass`} cx={glx} cy={gly + 1.5} rx={6} ry={2} fill="#9bcfd9" opacity={0.55} />,
          );
        };
        if (eastA && eastB) {
          const dx = eastB[0] - eastA[0], dy = eastB[1] - eastA[1];
          const len = Math.hypot(dx, dy) || 1;
          const nx = -dy / len, ny = dx / len;
          // 1 voiture devant l'entrée
          const cwx = eastA[0] + (eastB[0] - eastA[0]) * 0.35;
          const cwy = eastA[1] + (eastB[1] - eastA[1]) * 0.35;
          renderCar(cwx + nx * (chausseeOffsetM * 0.7), cwy + ny * (chausseeOffsetM * 0.7), "#7a3120", "car-1");
        }

        return elements;
      })()}

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

      {/* Lignes fortes de séparation wall/attic/parapet pour corriger le bug
          "transparent" — délimitent clairement les 3 bandes en haut. */}
      <path d={atticBottomRing} fill="none" stroke="#1c1917" strokeWidth={1.3} />
      <path d={atticTopRing} fill="none" stroke="#1c1917" strokeWidth={1.3} />
      <path d={parapetTopRing} fill="none" stroke="#1c1917" strokeWidth={1.5} />

      {/* Brique tower — rendu APRÈS les walls pour être garanti devant.
          Ordre: side back → top cap → side front → front face (painter's manuel). */}
      {towerProtrudeFaces.length > 0 && (() => {
        const els: React.ReactNode[] = [];
        // Compute shaded path for each face, sort visible faces back-to-front
        const items = towerProtrudeFaces.map((tf) => {
          const sunFactor = Math.max(0, tf.nx * lightDirX + tf.ny * lightDirY);
          const shade = 0.35 + 0.65 * sunFactor;
          let quad: [number, number][];
          if (tf.isTop) {
            // Top cap is a polygon between towerA, towerB, towerBOut, towerAOut at z=tf.z0
            // We don't have towerAOut/BOut here; rebuild from a, b + outward normal magnitude
            // Actually for top cap, a→b is towerA→towerB on inner edge. We need towerAOut/BOut too.
            // Stored differently — skip top cap here; render separately.
            quad = [
              proj(tf.a[0], tf.a[1], tf.z0), proj(tf.b[0], tf.b[1], tf.z0),
              proj(tf.b[0], tf.b[1], tf.z0), proj(tf.a[0], tf.a[1], tf.z0),
            ];
          } else {
            quad = [
              proj(tf.a[0], tf.a[1], tf.z0), proj(tf.b[0], tf.b[1], tf.z0),
              proj(tf.b[0], tf.b[1], tf.z1), proj(tf.a[0], tf.a[1], tf.z1),
            ];
          }
          const path = `M ${quad.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z`;
          const [, midSy] = iso((tf.a[0] + tf.b[0]) / 2, (tf.a[1] + tf.b[1]) / 2, (tf.z0 + tf.z1) / 2);
          return { path, midSy, shade, isTop: tf.isTop, tf };
        });
        // Sort sides back-to-front
        items.sort((p, q) => p.midSy - q.midSy);
        // Render sides
        for (const it of items) {
          if (it.isTop) continue;
          // Mix brique color with shade
          const briqueLight = "#a05036";
          const briqueDark = "#4a1d11";
          const mixHex = (a: string, b: string, t: number) => {
            const ah = a.replace("#", ""), bh = b.replace("#", "");
            const ar = parseInt(ah.slice(0, 2), 16), ag = parseInt(ah.slice(2, 4), 16), ab = parseInt(ah.slice(4, 6), 16);
            const br = parseInt(bh.slice(0, 2), 16), bg = parseInt(bh.slice(2, 4), 16), bb2 = parseInt(bh.slice(4, 6), 16);
            return `rgb(${Math.round(ar+(br-ar)*t)},${Math.round(ag+(bg-ag)*t)},${Math.round(ab+(bb2-ab)*t)})`;
          };
          const fill = mixHex(briqueDark, briqueLight, it.shade);
          els.push(<path key={`tower-${it.midSy.toFixed(1)}`} d={it.path} fill={fill} stroke="#1c1917" strokeWidth={0.9} />);
        }
        // Render top cap as a quad polygon (inner a → b → outer b → outer a)
        // Find the inner a/b and outer a/b from stored items
        const sideFront = items.find((it) => !it.isTop && Math.abs(it.tf.a[0] - it.tf.b[0]) < 0.1 ? it.tf.a[1] === it.tf.b[1] : false);
        // Easier: reconstruct from the original towerA, towerB, towerAOut, towerBOut
        // We don't have direct access, so compute from the stored faces.
        // Front face is: a=towerAOut, b=towerBOut. So towerAOut=front.a, towerBOut=front.b
        // Side back face is: a=towerAOut, b=towerA. So towerA=back.b
        // From those we can build the cap.
        const front = towerProtrudeFaces.find((tf) => !tf.isTop && tf.nx !== 0 && tf.ny === 0 && tf.nx > 0)
                  ?? towerProtrudeFaces.find((tf) => !tf.isTop);  // fallback
        const top = towerProtrudeFaces.find((tf) => tf.isTop);
        if (front && top) {
          const towerTopZ = top.z0;
          // top.a = towerA (inner), top.b = towerB (inner)
          // front.a = towerAOut (outer), front.b = towerBOut (outer)
          const capCorners = [
            proj(top.a[0], top.a[1], towerTopZ),
            proj(front.a[0], front.a[1], towerTopZ),
            proj(front.b[0], front.b[1], towerTopZ),
            proj(top.b[0], top.b[1], towerTopZ),
          ];
          const capPath = `M ${capCorners.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L ")} Z`;
          els.push(
            <path key="tower-cap" d={capPath} fill="#3a3833" stroke="#1c1917" strokeWidth={0.8} />,
          );
          // Couvertine zinc reflective edge
          els.push(
            <path key="tower-cap-reflect" d={capPath} fill="none" stroke="#fff" strokeWidth={0.6} opacity={0.40} />,
          );
        }
        return els;
      })()}

      {/* Roof (toit-terrasse) — membrane étanchéité */}
      <path d={topPath} fill={TONES.roof} stroke="#1c1917" strokeWidth={1.0} />
      {/* Toiture-terrasse — bandeau jardinière végétalisée le long du périmètre
          intérieur + panneaux solaires PV en damier sur la zone centrale. */}
      {(() => {
        const elements: React.ReactNode[] = [];
        const roofZ = atticZ1 + parapetH;
        // Veg strip — petite bordure verte le long de chaque edge du footprint
        // (1m de large vers l'intérieur). Pour simplicité on rend juste des
        // segments verts épais le long de chaque edge, à l'intérieur du parapet.
        for (let i = 0; i < footprint.length; i++) {
          const a = footprint[i];
          const b = footprint[(i + 1) % footprint.length];
          // Inset edge 0.5m vers l'intérieur (perpendiculaire à l'edge)
          const dx = b[0] - a[0], dy = b[1] - a[1];
          const len = Math.hypot(dx, dy) || 1;
          const inX = -dy / len * 0.6, inY = dx / len * 0.6;
          // Si c'est CW polygon, in normal points -90° (vers l'extérieur).
          // Pour l'intérieur on inverse.
          const ax = a[0] - inX, ay = a[1] - inY;
          const bx = b[0] - inX, by = b[1] - inY;
          const [p0x, p0y] = proj(ax, ay, roofZ);
          const [p1x, p1y] = proj(bx, by, roofZ);
          elements.push(
            <line key={`vg-${i}`} x1={p0x} y1={p0y} x2={p1x} y2={p1y}
              stroke={TONES.vegetation} strokeWidth={3.5} strokeLinecap="round" opacity={0.95} />,
          );
          // Petits buissons cluster
          const nBumps = Math.max(2, Math.floor(len / 4));
          for (let k = 0; k < nBumps; k++) {
            const t = (k + 0.5) / nBumps;
            const cx0 = ax + (bx - ax) * t;
            const cy0 = ay + (by - ay) * t;
            const [cx1, cy1] = proj(cx0, cy0, roofZ);
            elements.push(
              <circle key={`vb-${i}-${k}`} cx={cx1} cy={cy1 - 1.0} r={1.6} fill={TONES.vegetationDark} opacity={0.85} />,
            );
          }
        }
        // PV panels — grille en damier sur la zone centrale du toit
        const margin = 2.5;
        const pvX0 = bb.minx + margin;
        const pvX1 = bb.maxx - margin;
        const pvY0 = bb.miny + margin;
        const pvY1 = bb.maxy - margin;
        const pvCols = 7;
        const pvRows = 4;
        const pvW = (pvX1 - pvX0) / pvCols * 0.85;
        const pvH = (pvY1 - pvY0) / pvRows * 0.85;
        // Use point-in-polygon to skip cells outside L footprint
        const inside = (px: number, py: number): boolean => {
          let n = 0;
          for (let i = 0; i < footprint.length; i++) {
            const [x1, y1] = footprint[i];
            const [x2, y2] = footprint[(i + 1) % footprint.length];
            if ((y1 > py) !== (y2 > py)) {
              const xCross = x1 + (py - y1) / (y2 - y1) * (x2 - x1);
              if (xCross > px) n++;
            }
          }
          return n % 2 === 1;
        };
        for (let i = 0; i < pvCols; i++) {
          for (let j = 0; j < pvRows; j++) {
            const cx = pvX0 + (i + 0.5) * (pvX1 - pvX0) / pvCols;
            const cy = pvY0 + (j + 0.5) * (pvY1 - pvY0) / pvRows;
            if (!inside(cx, cy)) continue;
            // Skip cells too close to edge (where vegetation is)
            const minD = Math.min(
              cx - bb.minx, bb.maxx - cx, cy - bb.miny, bb.maxy - cy,
            );
            if (minD < margin + 1) continue;
            const xPv0 = cx - pvW / 2, yPv0 = cy - pvH / 2;
            const xPv1 = cx + pvW / 2, yPv1 = cy + pvH / 2;
            // Skip if any corner outside the L footprint
            if (!inside(xPv0, yPv0) || !inside(xPv1, yPv0) || !inside(xPv1, yPv1) || !inside(xPv0, yPv1)) continue;
            const [a0x, a0y] = proj(xPv0, yPv0, roofZ);
            const [a1x, a1y] = proj(xPv1, yPv0, roofZ);
            const [a2x, a2y] = proj(xPv1, yPv1, roofZ);
            const [a3x, a3y] = proj(xPv0, yPv1, roofZ);
            const path = `M ${a0x},${a0y} L ${a1x},${a1y} L ${a2x},${a2y} L ${a3x},${a3y} Z`;
            elements.push(
              <path key={`pv-${i}-${j}`} d={path} fill={TONES.pv} stroke={TONES.pvLight} strokeWidth={0.4} />,
            );
            // Reflet ciel sur PV
            const [r0x, r0y] = proj(xPv0 + 0.2, yPv0 + 0.2, roofZ);
            const [r1x, r1y] = proj(xPv0 + 0.2 + pvW * 0.4, yPv0 + 0.2, roofZ);
            const [r2x, r2y] = proj(xPv0 + 0.2 + pvW * 0.4, yPv0 + 0.2 + pvH * 0.5, roofZ);
            const [r3x, r3y] = proj(xPv0 + 0.2, yPv0 + 0.2 + pvH * 0.5, roofZ);
            const refl = `M ${r0x},${r0y} L ${r1x},${r1y} L ${r2x},${r2y} L ${r3x},${r3y} Z`;
            elements.push(
              <path key={`pvr-${i}-${j}`} d={refl} fill="#fff" opacity={0.18} />,
            );
          }
        }
        return elements;
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
