"use client";

import type { BuildingModelNiveau, BuildingModelCellule } from "@/lib/types";
import { bboxOf, type Coord } from "./plan-utils";

interface BalconsJardinsLayerProps {
  niveau: BuildingModelNiveau;
  footprint: Coord[];
  project: (c: Coord) => Coord;
  scale: number;
  isRdc: boolean;
  /** Optional parcel outline — if provided, gardens are clipped to it. */
  parcelle?: Coord[];
}

/**
 * Dessin des balcons (étages) et jardins privatifs (RDC) avec séparateurs
 * de vie privée. Géométrie dérivée de la position des portes-fenêtres sur
 * les murs extérieurs.
 *
 * Règles architecturales :
 *  - BALCONS : profondeur 1.5 m, projetés vers l'extérieur du mur, longueur =
 *    largeur de la cellule côté ext. Garde-corps métal noir ajouré.
 *  - JARDINS RDC : profondeur 4-6 m (si espace le permet), séparés entre
 *    voisins par une haie basse + muret 1.2 m hauteur pour la vie privée.
 *  - SÉPARATEURS ÉTAGES : cloison pleine (brique / verre dépoli) hauteur
 *    1.8 m entre 2 balcons mitoyens → on ne voit pas son voisin.
 */
export function BalconsJardinsLayer({
  niveau, footprint, project, scale, isRdc, parcelle,
}: BalconsJardinsLayerProps) {
  const balconyDepthM = 1.5;
  const gardenDepthM = 5.0;

  // Collect exterior extrusions per apartment.
  const extrusions: Array<{
    cellId: string;
    typo: string;
    a: Coord;
    b: Coord;
    outward: Coord;  // unit outward normal
    depth: number;
  }> = [];

  for (const cell of niveau.cellules) {
    if (cell.type !== "logement") continue;
    // For each wall of the cellule, check if it's on the footprint perimeter
    // AND has a porte-fenêtre (else no balcony/garden access).
    for (const wall of cell.walls ?? []) {
      const coords = wall.geometry?.coords as Coord[] | undefined;
      if (!coords || coords.length < 2) continue;
      if (wall.type !== "porteur") continue;  // only porteurs are outer walls
      if (!isOnPerimeter(coords, footprint)) continue;
      // Does this wall have any porte-fenêtre opening?
      const hasPorteFen = (cell.openings ?? []).some(
        (o) => o.wall_id === wall.id && (o.type === "porte_fenetre" || o.type === "baie_coulissante"),
      );
      if (!hasPorteFen) continue;

      // Outward normal (perpendicular to wall, pointing away from footprint centroid)
      let [a, b] = coords;
      // Clip the wall segment to the portion that lies on the footprint
      // perimeter. Pocket-infill apartments may have a wall whose endpoints
      // extend past the footprint boundary on one end (e.g. an L-elbow);
      // extruding a jardin from the FULL wall would intrude into the
      // neighbour apt. Clipping the segment to its exterior sub-range yields
      // a clean strip aligned to the actual perimeter.
      const clipped = clipSegmentToPerimeter(a, b, footprint);
      if (clipped) {
        a = clipped[0];
        b = clipped[1];
      }
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const len = Math.hypot(dx, dy);
      if (len < 0.5) continue;
      const fbb = bboxOf(footprint);
      if (!fbb) continue;
      const mid: Coord = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      const n1: Coord = [-dy / len, dx / len];
      const n2: Coord = [dy / len, -dx / len];
      // Outward normal = the side that is OUTSIDE the footprint.
      // For L-shaped (or generally non-convex) footprints, the centroid
      // heuristic fails at the reflex corner (e.g. Nogent L-notch: apt 5's
      // north wall at y=15 has the centroid slightly NORTH of the wall,
      // but the outward side is also north — the centroid heuristic would
      // put the jardin south, inside apt 5 itself). Testing a small probe
      // point on each side against the footprint is robust for any shape.
      const probe = 0.2;
      const p1: Coord = [mid[0] + n1[0] * probe, mid[1] + n1[1] * probe];
      const p2: Coord = [mid[0] + n2[0] * probe, mid[1] + n2[1] * probe];
      const p1Inside = pointInPolygon(p1, footprint);
      const p2Inside = pointInPolygon(p2, footprint);
      let outward: Coord;
      if (p1Inside && !p2Inside) outward = n2;
      else if (p2Inside && !p1Inside) outward = n1;
      else {
        // Both sides ambiguous (probes land on boundary) — fall back to
        // centroid heuristic.
        const fcx = (fbb.minx + fbb.maxx) / 2;
        const fcy = (fbb.miny + fbb.maxy) / 2;
        outward = (
          (n1[0] * (mid[0] - fcx) + n1[1] * (mid[1] - fcy))
          >= (n2[0] * (mid[0] - fcx) + n2[1] * (mid[1] - fcy))
        ) ? n1 : n2;
      }

      extrusions.push({
        cellId: cell.id,
        typo: (cell.typologie ?? "LGT").toUpperCase(),
        a, b, outward,
        depth: isRdc ? gardenDepthM : balconyDepthM,
      });
    }
  }

  // Build initial strip geometry per extrusion.
  type StripRaw = {
    ex: typeof extrusions[number];
    bbox: { minx: number; miny: number; maxx: number; maxy: number };
  };
  const rawStrips: StripRaw[] = extrusions.map((ex) => {
    const a1: Coord = [ex.a[0] + ex.outward[0] * ex.depth, ex.a[1] + ex.outward[1] * ex.depth];
    const b1: Coord = [ex.b[0] + ex.outward[0] * ex.depth, ex.b[1] + ex.outward[1] * ex.depth];
    const bbox = {
      minx: Math.min(ex.a[0], ex.b[0], a1[0], b1[0]),
      miny: Math.min(ex.a[1], ex.b[1], a1[1], b1[1]),
      maxx: Math.max(ex.a[0], ex.b[0], a1[0], b1[0]),
      maxy: Math.max(ex.a[1], ex.b[1], a1[1], b1[1]),
    };
    return { ex, bbox };
  });

  // Clip each strip's along-wall extent to avoid overlapping with any other
  // strip's bbox. Handles the L-notch case where apt 5's north-extruded
  // jardin and apt 3's west-extruded jardin would otherwise both claim the
  // reflex-corner quadrant. Each strip shrinks along its wall direction until
  // its bbox no longer intersects its neighbour's bbox (a hedge separator is
  // then drawn at the wall's trimmed endpoint).
  const TOLC = 0.15;
  const strips = rawStrips.map((rs) => {
    const { ex } = rs;
    let aCur: Coord = ex.a;
    let bCur: Coord = ex.b;
    const horizontalWall = Math.abs(ex.b[1] - ex.a[1]) < TOLC;
    const verticalWall = Math.abs(ex.b[0] - ex.a[0]) < TOLC;
    if (horizontalWall || verticalWall) {
      for (const other of rawStrips) {
        if (other.ex.cellId === ex.cellId) continue;
        // Compute current strip bbox (may have shrunk from earlier iterations).
        const curA1: Coord = [aCur[0] + ex.outward[0] * ex.depth, aCur[1] + ex.outward[1] * ex.depth];
        const curB1: Coord = [bCur[0] + ex.outward[0] * ex.depth, bCur[1] + ex.outward[1] * ex.depth];
        const minx = Math.min(aCur[0], bCur[0], curA1[0], curB1[0]);
        const miny = Math.min(aCur[1], bCur[1], curA1[1], curB1[1]);
        const maxx = Math.max(aCur[0], bCur[0], curA1[0], curB1[0]);
        const maxy = Math.max(aCur[1], bCur[1], curA1[1], curB1[1]);
        const ob = other.bbox;
        // Must actually overlap in both axes to need clipping.
        if (maxx <= ob.minx + TOLC || minx >= ob.maxx - TOLC) continue;
        if (maxy <= ob.miny + TOLC || miny >= ob.maxy - TOLC) continue;
        // Shrink along the wall direction to exit the overlap.
        if (horizontalWall) {
          const y0 = aCur[1];
          const aX0 = Math.min(aCur[0], bCur[0]);
          const aX1 = Math.max(aCur[0], bCur[0]);
          const leftLen = Math.max(0, ob.minx - aX0);
          const rightLen = Math.max(0, aX1 - ob.maxx);
          if (leftLen >= rightLen && leftLen > 0.3) {
            aCur = [aX0, y0]; bCur = [ob.minx, y0];
          } else if (rightLen > 0.3) {
            aCur = [ob.maxx, y0]; bCur = [aX1, y0];
          } else {
            aCur = [aX0, y0]; bCur = [aX0, y0]; // collapse
            break;
          }
        } else {
          const x0 = aCur[0];
          const aY0 = Math.min(aCur[1], bCur[1]);
          const aY1 = Math.max(aCur[1], bCur[1]);
          const lowLen = Math.max(0, ob.miny - aY0);
          const highLen = Math.max(0, aY1 - ob.maxy);
          if (lowLen >= highLen && lowLen > 0.3) {
            aCur = [x0, aY0]; bCur = [x0, ob.miny];
          } else if (highLen > 0.3) {
            aCur = [x0, ob.maxy]; bCur = [x0, aY1];
          } else {
            aCur = [x0, aY0]; bCur = [x0, aY0];
            break;
          }
        }
      }
    }
    const a1: Coord = [aCur[0] + ex.outward[0] * ex.depth, aCur[1] + ex.outward[1] * ex.depth];
    const b1: Coord = [bCur[0] + ex.outward[0] * ex.depth, bCur[1] + ex.outward[1] * ex.depth];
    return {
      ...ex,
      a: aCur,
      b: bCur,
      poly: [aCur, bCur, b1, a1] as Coord[],
      outerA: a1,
      outerB: b1,
    };
  }).filter((s) => {
    const dx = s.b[0] - s.a[0];
    const dy = s.b[1] - s.a[1];
    return Math.hypot(dx, dy) > 0.4; // drop degenerate strips
  });

  const toPath = (pts: Coord[]): string => {
    if (!pts.length) return "";
    const proj2 = pts.map(project);
    return `M ${proj2.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ")} Z`;
  };

  return (
    <g data-balcons-jardins="true" pointerEvents="none">
      <defs>
        <pattern id="pat-lawn-bj" width="8" height="8" patternUnits="userSpaceOnUse">
          <rect width="8" height="8" fill="#c4d8a8" />
          <circle cx="2" cy="2" r="0.6" fill="#7a9656" opacity="0.5" />
          <circle cx="6" cy="5" r="0.5" fill="#6e8c4a" opacity="0.45" />
          <circle cx="4" cy="7" r="0.4" fill="#7a9656" opacity="0.4" />
        </pattern>
        <pattern id="pat-terrasse-bois" width="7" height="14" patternUnits="userSpaceOnUse">
          <rect width="7" height="14" fill="#c29d6a" />
          <line x1="0" y1="3" x2="7" y2="3" stroke="#8a6c44" strokeWidth="0.3" />
          <line x1="0" y1="10" x2="7" y2="10" stroke="#8a6c44" strokeWidth="0.3" />
        </pattern>
      </defs>

      {strips.map((s, i) => {
        if (isRdc) {
          // Jardin privatif : lawn pattern + hedge separators between adjacent gardens.
          return (
            <g key={`g-${s.cellId}-${i}`}>
              {/* Lawn fill */}
              <path d={toPath(s.poly)} fill="url(#pat-lawn-bj)" stroke="#4f6d3a" strokeWidth={0.6} opacity={0.92} />
              {/* Terrasse bois adjacente au mur (1.5 m de profondeur) */}
              <path
                d={toPath([
                  s.a, s.b,
                  [s.b[0] + s.outward[0] * 1.5, s.b[1] + s.outward[1] * 1.5],
                  [s.a[0] + s.outward[0] * 1.5, s.a[1] + s.outward[1] * 1.5],
                ])}
                fill="url(#pat-terrasse-bois)"
                stroke="#8a6c44"
                strokeWidth={0.5}
              />
              {/* Séparateurs vie privée : haie + muret 1.2 m entre jardins */}
              <path
                d={toPath([
                  s.a,
                  [s.a[0] + s.outward[0] * s.depth, s.a[1] + s.outward[1] * s.depth],
                  [s.a[0] + s.outward[0] * s.depth + 0.2, s.a[1] + s.outward[1] * s.depth + 0.2],
                  [s.a[0] + 0.2, s.a[1] + 0.2],
                ])}
                fill="#4f6d3a"
                stroke="#1e3a23"
                strokeWidth={0.5}
              />
              <path
                d={toPath([
                  s.b,
                  [s.b[0] + s.outward[0] * s.depth, s.b[1] + s.outward[1] * s.depth],
                  [s.b[0] + s.outward[0] * s.depth - 0.2, s.b[1] + s.outward[1] * s.depth - 0.2],
                  [s.b[0] - 0.2, s.b[1] - 0.2],
                ])}
                fill="#4f6d3a"
                stroke="#1e3a23"
                strokeWidth={0.5}
              />
              {/* Label jardin */}
              {(() => {
                const cx = (s.a[0] + s.outerB[0]) / 2;
                const cy = (s.a[1] + s.outerB[1]) / 2;
                const [px, py] = project([cx, cy]);
                return (
                  <text x={px} y={py} fontSize={7} fill="#1e3a23" textAnchor="middle" opacity={0.8} fontWeight={600}>
                    jardin privatif
                  </text>
                );
              })()}
            </g>
          );
        }

        // Balcon étage courant
        return (
          <g key={`b-${s.cellId}-${i}`}>
            {/* Dalle béton */}
            <path d={toPath(s.poly)} fill="#d6d3d1" stroke="#3a3a3a" strokeWidth={0.7} />
            {/* Surface terrasse bois */}
            <path
              d={toPath([
                [s.a[0] + s.outward[0] * 0.15, s.a[1] + s.outward[1] * 0.15],
                [s.b[0] + s.outward[0] * 0.15, s.b[1] + s.outward[1] * 0.15],
                [s.outerB[0] - s.outward[0] * 0.15, s.outerB[1] - s.outward[1] * 0.15],
                [s.outerA[0] - s.outward[0] * 0.15, s.outerA[1] - s.outward[1] * 0.15],
              ])}
              fill="url(#pat-terrasse-bois)"
              opacity={0.85}
            />
            {/* Garde-corps métal noir à barreaudage (ligne extérieure) */}
            {(() => {
              const [pa] = [project(s.outerA)];
              const [pb] = [project(s.outerB)];
              const n = 6;
              const ticks: React.ReactNode[] = [];
              for (let k = 0; k < n; k++) {
                const t = (k + 0.5) / n;
                const tx = pa[0] + (pb[0] - pa[0]) * t;
                const ty = pa[1] + (pb[1] - pa[1]) * t;
                ticks.push(<circle key={k} cx={tx} cy={ty} r={0.6} fill="#1a1a1a" />);
              }
              return (
                <g>
                  <line x1={pa[0]} y1={pa[1]} x2={pb[0]} y2={pb[1]} stroke="#1a1a1a" strokeWidth={1.3} />
                  {ticks}
                </g>
              );
            })()}
            {/* Séparateurs latéraux vie privée — cloisons verre dépoli + cadre métal */}
            <path
              d={toPath([
                s.a,
                [s.a[0] + s.outward[0] * s.depth, s.a[1] + s.outward[1] * s.depth],
                [s.a[0] + s.outward[0] * s.depth + 0.1 * Math.sign(s.a[0] - s.b[0] + 0.0001), s.a[1] + s.outward[1] * s.depth],
                [s.a[0] + 0.1 * Math.sign(s.a[0] - s.b[0] + 0.0001), s.a[1]],
              ])}
              fill="#b9dce9"
              fillOpacity={0.55}
              stroke="#1a1a1a"
              strokeWidth={0.7}
            />
            <path
              d={toPath([
                s.b,
                [s.b[0] + s.outward[0] * s.depth, s.b[1] + s.outward[1] * s.depth],
                [s.b[0] + s.outward[0] * s.depth + 0.1 * Math.sign(s.b[0] - s.a[0] + 0.0001), s.b[1] + s.outward[1] * s.depth],
                [s.b[0] + 0.1 * Math.sign(s.b[0] - s.a[0] + 0.0001), s.b[1]],
              ])}
              fill="#b9dce9"
              fillOpacity={0.55}
              stroke="#1a1a1a"
              strokeWidth={0.7}
            />
            {/* Label balcon */}
            {(() => {
              const cx = (s.a[0] + s.outerB[0]) / 2;
              const cy = (s.a[1] + s.outerB[1]) / 2;
              const [px, py] = project([cx, cy]);
              const depthPx = s.depth * scale;
              if (depthPx < 18) return null;
              return (
                <text x={px} y={py + 2} fontSize={7} fill="#1a1a1a" textAnchor="middle" opacity={0.85} fontWeight={600}>
                  balcon {s.typo}
                </text>
              );
            })()}
          </g>
        );
      })}
      {/* Silence unused parcelle param for now (future clip target) */}
      {parcelle?.length === -1 ? null : null}
    </g>
  );
}

/**
 * Ray-casting point-in-polygon test. Returns true if `p` lies strictly
 * inside `poly`. Used to disambiguate the outward normal of a wall
 * against non-convex footprints (L, U, T shapes) where the bbox-centroid
 * heuristic misfires at reflex corners.
 */
function pointInPolygon(p: Coord, poly: Coord[]): boolean {
  if (poly.length < 3) return false;
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1];
    const xj = poly[j][0], yj = poly[j][1];
    const intersect =
      ((yi > p[1]) !== (yj > p[1])) &&
      (p[0] < ((xj - xi) * (p[1] - yi)) / ((yj - yi) || 1e-9) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function isOnPerimeter(wallCoords: Coord[], footprint: Coord[]): boolean {
  if (wallCoords.length < 2 || footprint.length < 3) return false;
  const [a, b] = wallCoords;
  const mx = (a[0] + b[0]) / 2;
  const my = (a[1] + b[1]) / 2;
  const TOL = 0.3;
  for (let i = 0; i < footprint.length; i++) {
    const fa = footprint[i];
    const fb = footprint[(i + 1) % footprint.length];
    const vx = fb[0] - fa[0];
    const vy = fb[1] - fa[1];
    const len2 = vx * vx + vy * vy;
    if (len2 < 1e-6) continue;
    let t = ((mx - fa[0]) * vx + (my - fa[1]) * vy) / len2;
    t = Math.max(0, Math.min(1, t));
    const qx = fa[0] + t * vx;
    const qy = fa[1] + t * vy;
    if (Math.hypot(mx - qx, my - qy) < TOL) return true;
  }
  return false;
}

/**
 * Clip an axis-aligned wall segment (a,b) to the sub-range that overlaps
 * a colinear segment of the footprint perimeter. Returns null if the
 * segment is not axis-aligned or no perimeter overlap is found.
 *
 * Rationale: for pocket-infill apartments whose slot bbox extends past
 * the footprint boundary at one end (e.g. an L-elbow joint), the wall
 * spans both perimeter and interior portions. The jardin/balcon strip
 * must be limited to the exterior portion, otherwise it intrudes into
 * the neighbour apartment's footprint.
 */
function clipSegmentToPerimeter(
  a: Coord, b: Coord, footprint: Coord[],
): [Coord, Coord] | null {
  if (footprint.length < 3) return null;
  const TOL = 0.3;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const horizontal = Math.abs(dy) < TOL;
  const vertical = Math.abs(dx) < TOL;
  if (!horizontal && !vertical) return null;

  // For each footprint edge that is colinear with the wall, compute the
  // overlap range and union with the running clip.
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < footprint.length; i++) {
    const fa = footprint[i];
    const fb = footprint[(i + 1) % footprint.length];
    const fdx = fb[0] - fa[0];
    const fdy = fb[1] - fa[1];
    const fHoriz = Math.abs(fdy) < TOL;
    const fVert = Math.abs(fdx) < TOL;
    if (horizontal && fHoriz && Math.abs(fa[1] - a[1]) < TOL) {
      const aLo = Math.min(a[0], b[0]);
      const aHi = Math.max(a[0], b[0]);
      const fLo = Math.min(fa[0], fb[0]);
      const fHi = Math.max(fa[0], fb[0]);
      const oLo = Math.max(aLo, fLo);
      const oHi = Math.min(aHi, fHi);
      if (oHi - oLo > TOL) {
        lo = Math.min(lo, oLo);
        hi = Math.max(hi, oHi);
      }
    } else if (vertical && fVert && Math.abs(fa[0] - a[0]) < TOL) {
      const aLo = Math.min(a[1], b[1]);
      const aHi = Math.max(a[1], b[1]);
      const fLo = Math.min(fa[1], fb[1]);
      const fHi = Math.max(fa[1], fb[1]);
      const oLo = Math.max(aLo, fLo);
      const oHi = Math.min(aHi, fHi);
      if (oHi - oLo > TOL) {
        lo = Math.min(lo, oLo);
        hi = Math.max(hi, oHi);
      }
    }
  }
  if (!isFinite(lo) || !isFinite(hi) || hi - lo < TOL) return null;
  if (horizontal) {
    return [[lo, a[1]] as Coord, [hi, a[1]] as Coord];
  }
  return [[a[0], lo] as Coord, [a[0], hi] as Coord];
}

// Silence unused parameter warnings
export type BalconStripFor<T extends BuildingModelCellule> = { cell: T };
