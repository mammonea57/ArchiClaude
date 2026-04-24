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
    // Explicit tiled jardin polygon (RDC notch tiling) — skip extrusion
    // for this cellule; it will be rendered directly below from its
    // `jardin_polygon_xy` field.
    if (isRdc && cell.jardin_polygon_xy && cell.jardin_polygon_xy.length >= 3) {
      continue;
    }
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

  // No clipping between jardins — each extrudes fully perpendicular to its
  // wall. In L-notch configs jardins may overlap at the reflex corner;
  // that's intentional. The per-jardin hedge/haie is drawn at strip
  // endpoints so the visual separation reads clearly even through the
  // overlap.
  const strips = rawStrips.map((rs) => {
    const { ex } = rs;
    const a1: Coord = [ex.a[0] + ex.outward[0] * ex.depth, ex.a[1] + ex.outward[1] * ex.depth];
    const b1: Coord = [ex.b[0] + ex.outward[0] * ex.depth, ex.b[1] + ex.outward[1] * ex.depth];
    return {
      ...ex,
      poly: [ex.a, ex.b, b1, a1] as Coord[],
      outerA: a1,
      outerB: b1,
    };
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

      {/* Explicit tiled jardins for RDC apts whose backend provided a
          jardin_polygon_xy (e.g. L-notch tiling). Renders the polygon
          directly, plus a terrasse strip along the apt's adjacent wall
          and hedges on the non-apt-wall sides to signal privacy
          between neighbouring jardins. */}
      {isRdc && niveau.cellules.map((cell) => {
        if (cell.type !== "logement") return null;
        const poly = cell.jardin_polygon_xy;
        if (!poly || poly.length < 3) return null;
        const jBbox = bboxOf(poly as Coord[]);
        if (!jBbox) return null;
        // Apt bbox, used to find which edge of the jardin rect touches
        // the apt wall. That edge hosts the terrasse; the remaining
        // three edges host hedges.
        const aBbox = bboxOf(cell.polygon_xy as Coord[]);
        if (!aBbox) return null;
        const TOL = 0.3;
        type Side = "south" | "north" | "west" | "east";
        let aptSide: Side | null = null;
        if (Math.abs(jBbox.miny - aBbox.maxy) < TOL) aptSide = "south";
        else if (Math.abs(jBbox.maxy - aBbox.miny) < TOL) aptSide = "north";
        else if (Math.abs(jBbox.minx - aBbox.maxx) < TOL) aptSide = "west";
        else if (Math.abs(jBbox.maxx - aBbox.minx) < TOL) aptSide = "east";

        // Terrasse strip 1.5 m deep along the apt-facing edge.
        const terrasseDepth = 1.5;
        let terrasse: Coord[] | null = null;
        if (aptSide === "south") {
          terrasse = [
            [jBbox.minx, jBbox.miny],
            [jBbox.maxx, jBbox.miny],
            [jBbox.maxx, jBbox.miny + terrasseDepth],
            [jBbox.minx, jBbox.miny + terrasseDepth],
          ];
        } else if (aptSide === "north") {
          terrasse = [
            [jBbox.minx, jBbox.maxy - terrasseDepth],
            [jBbox.maxx, jBbox.maxy - terrasseDepth],
            [jBbox.maxx, jBbox.maxy],
            [jBbox.minx, jBbox.maxy],
          ];
        } else if (aptSide === "west") {
          terrasse = [
            [jBbox.minx, jBbox.miny],
            [jBbox.minx + terrasseDepth, jBbox.miny],
            [jBbox.minx + terrasseDepth, jBbox.maxy],
            [jBbox.minx, jBbox.maxy],
          ];
        } else if (aptSide === "east") {
          terrasse = [
            [jBbox.maxx - terrasseDepth, jBbox.miny],
            [jBbox.maxx, jBbox.miny],
            [jBbox.maxx, jBbox.maxy],
            [jBbox.maxx - terrasseDepth, jBbox.maxy],
          ];
        }

        // Hedges on every side EXCEPT the apt-facing side.
        const hedgeThickness = 0.25;
        const hedges: Coord[][] = [];
        const addHedge = (side: Side) => {
          if (side === aptSide) return;
          if (side === "south") {
            hedges.push([
              [jBbox.minx, jBbox.miny],
              [jBbox.maxx, jBbox.miny],
              [jBbox.maxx, jBbox.miny + hedgeThickness],
              [jBbox.minx, jBbox.miny + hedgeThickness],
            ]);
          } else if (side === "north") {
            hedges.push([
              [jBbox.minx, jBbox.maxy - hedgeThickness],
              [jBbox.maxx, jBbox.maxy - hedgeThickness],
              [jBbox.maxx, jBbox.maxy],
              [jBbox.minx, jBbox.maxy],
            ]);
          } else if (side === "west") {
            hedges.push([
              [jBbox.minx, jBbox.miny],
              [jBbox.minx + hedgeThickness, jBbox.miny],
              [jBbox.minx + hedgeThickness, jBbox.maxy],
              [jBbox.minx, jBbox.maxy],
            ]);
          } else {
            hedges.push([
              [jBbox.maxx - hedgeThickness, jBbox.miny],
              [jBbox.maxx, jBbox.miny],
              [jBbox.maxx, jBbox.maxy],
              [jBbox.maxx - hedgeThickness, jBbox.maxy],
            ]);
          }
        };
        (["south", "north", "west", "east"] as Side[]).forEach(addHedge);

        const cx = (jBbox.minx + jBbox.maxx) / 2;
        const cy = (jBbox.miny + jBbox.maxy) / 2;
        const [lx, ly] = project([cx, cy]);
        return (
          <g key={`tiled-jardin-${cell.id}`}>
            {/* Lawn fill on the full jardin polygon */}
            <path
              d={toPath(poly as Coord[])}
              fill="url(#pat-lawn-bj)"
              stroke="#4f6d3a"
              strokeWidth={0.6}
              opacity={0.92}
            />
            {/* Terrasse bois along the apt wall */}
            {terrasse && (
              <path
                d={toPath(terrasse)}
                fill="url(#pat-terrasse-bois)"
                stroke="#8a6c44"
                strokeWidth={0.5}
              />
            )}
            {/* Hedges on the 3 non-apt-wall sides */}
            {hedges.map((h, hi) => (
              <path
                key={`hedge-${cell.id}-${hi}`}
                d={toPath(h)}
                fill="#4f6d3a"
                stroke="#1e3a23"
                strokeWidth={0.5}
              />
            ))}
            <text
              x={lx}
              y={ly}
              fontSize={7}
              fill="#1e3a23"
              textAnchor="middle"
              opacity={0.85}
              fontWeight={600}
            >
              jardin privatif
            </text>
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
