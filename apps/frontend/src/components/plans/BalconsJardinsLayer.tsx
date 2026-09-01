"use client";

import type { BuildingModelNiveau } from "@/lib/types";
import { bboxOf, type Coord } from "./plan-utils";

interface BalconsJardinsLayerProps {
  niveau: BuildingModelNiveau;
  footprint: Coord[];
  project: (c: Coord) => Coord;
  scale: number;
  isRdc: boolean;
  /** Optional parcel outline — if provided, gardens are clipped to it. */
  parcelle?: Coord[];
  /** "base" (défaut) = dessiné SOUS les cellules : balcons SAILLANTS (hors
   *  footprint, non recouverts) + jardins RDC. "overlay" = dessiné PAR-DESSUS les
   *  cellules : LOGGIAS en retrait (dans le footprint, sinon recouvertes par l'apt). */
  layer?: "base" | "overlay";
}

/**
 * Dessin des extérieurs privatifs de chaque logement :
 *  - BALCON (saillie, côté cour/jardin) et LOGGIA (retrait, côté rue) rendus
 *    DIRECTEMENT depuis `cell.loggia` calculé par le backend (source de vérité
 *    unique → le plan 2D correspond EXACTEMENT au modèle 3D). On ne ré-extrude
 *    plus les balcons depuis les murs (ça labellait tout « balcon », RDC compris,
 *    et posait des saillies au-dessus du trottoir = non-conforme UA.6).
 *  - JARDINS RDC : rendus depuis `jardin_polygon_xy` (pelouse + terrasse + haies).
 *
 * Règle : `kind="balcon"` = dalle saillante (autorisée seulement sur privé,
 * cour/jardin) ; `kind="loggia"` = creusée en retrait (obligatoire côté rue, et
 * seul extérieur possible au RDC sur alignement — jamais de balcon au sol).
 */
export function BalconsJardinsLayer({
  niveau, footprint, project, scale, isRdc, parcelle, layer = "base",
}: BalconsJardinsLayerProps) {
  void footprint;
  void parcelle;

  const toPath = (pts: Coord[]): string => {
    if (!pts.length) return "";
    const proj2 = pts.map(project);
    return `M ${proj2.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ")} Z`;
  };

  // Extérieurs = balcons/loggias portés par `cell.loggia`. Un logt RDC AVEC
  // jardin privatif est exclu (son extérieur est au sol ; pas de loggia en plus).
  // Seuls les BALCONS (saillie) sont dessinés ici. Les LOGGIAS (retrait) sont
  // émises par le backend comme de vraies PIÈCES (type loggia) et rendues par
  // <RoomFloor> comme n'importe quelle pièce → séparation nette, zéro chevauchement.
  const exteriors = niveau.cellules.filter(
    (c) => c.type === "logement"
      && c.loggia != null
      && (c.loggia.kind ?? "balcon") === "balcon"
      && Array.isArray(c.loggia.polygon_xy)
      && (c.loggia.polygon_xy as Coord[]).length >= 3
      && !(isRdc && c.jardin_polygon_xy != null && (c.jardin_polygon_xy as Coord[]).length >= 3),
  );

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
        <pattern id="pat-lawn-commun" width="10" height="10" patternUnits="userSpaceOnUse">
          <rect width="10" height="10" fill="#8fb26b" />
          <path d="M0,10 L10,0 M-2,2 L2,-2 M8,12 L12,8" stroke="#4f6d3a" strokeWidth="0.6" opacity="0.6" />
          <path d="M0,0 L10,10 M-2,8 L2,12 M8,-2 L12,2" stroke="#4f6d3a" strokeWidth="0.6" opacity="0.6" />
        </pattern>
      </defs>

      {/* BALCONS (saillie, cour) + LOGGIAS (retrait, rue) — depuis cell.loggia. */}
      {exteriors.map((cell) => {
        const lg = cell.loggia!;
        const poly = lg.polygon_xy as Coord[];
        const kind = lg.kind ?? "balcon";
        // Loggias (retrait) PAR-DESSUS les cellules ; balcons (saillie) EN DESSOUS.
        if (kind === "loggia" && layer !== "overlay") return null;
        if (kind === "balcon" && layer !== "base") return null;
        const typo = (cell.typologie ?? "LGT").toUpperCase();
        // Le polygone backend = [p1, p2, p2o, p1o] : p1-p2 = arête FAÇADE (sur le
        // mur), p2o-p1o = arête EXTÉRIEURE (bord opposé). Garde-corps sur le bord
        // extérieur pour un balcon, ligne de façade vitrée pour une loggia.
        const facadeA = poly[0], facadeB = poly[1];
        const outerA = poly[poly.length - 1], outerB = poly[poly.length - 2];
        const bb = bboxOf(poly);
        const [lx, ly] = bb
          ? project([(bb.minx + bb.maxx) / 2, (bb.miny + bb.maxy) / 2])
          : project(poly[0]);
        const showLabel = scale * 1.2 >= 14;

        if (kind === "loggia") {
          const pa = project(facadeA);
          const pb = project(facadeB);
          return (
            <g key={`lg-${cell.id}`}>
              {/* Sol de la loggia (retrait, dans le volume) — semi-transparent pour
                  laisser lire le badge d'apt / la pièce en dessous. */}
              <path d={toPath(poly)} fill="url(#pat-terrasse-bois)" stroke="#8a6c44" strokeWidth={0.6} opacity={0.5} />
              {/* Ligne de façade (baie vitrée donnant sur la loggia) */}
              <line x1={pa[0]} y1={pa[1]} x2={pb[0]} y2={pb[1]} stroke="#1a1a1a" strokeWidth={1.1} />
              {showLabel && (
                <text x={lx} y={ly + 2} fontSize={7} fill="#4a3d2a" textAnchor="middle" opacity={0.9} fontWeight={600}>
                  loggia {typo}
                </text>
              )}
            </g>
          );
        }

        // BALCON (saillie côté cour/jardin) : dalle + terrasse + garde-corps.
        const goA = project(outerA);
        const goB = project(outerB);
        const ticks: React.ReactNode[] = [];
        const n = 6;
        for (let k = 0; k < n; k++) {
          const t = (k + 0.5) / n;
          ticks.push(
            <circle key={k} cx={goA[0] + (goB[0] - goA[0]) * t} cy={goA[1] + (goB[1] - goA[1]) * t} r={0.6} fill="#1a1a1a" />,
          );
        }
        return (
          <g key={`b-${cell.id}`}>
            <path d={toPath(poly)} fill="#d6d3d1" stroke="#3a3a3a" strokeWidth={0.7} />
            <path d={toPath(poly)} fill="url(#pat-terrasse-bois)" opacity={0.6} />
            <line x1={goA[0]} y1={goA[1]} x2={goB[0]} y2={goB[1]} stroke="#1a1a1a" strokeWidth={1.3} />
            {ticks}
            {showLabel && (
              <text x={lx} y={ly + 2} fontSize={7} fill="#1a1a1a" textAnchor="middle" opacity={0.85} fontWeight={600}>
                balcon {typo}
              </text>
            )}
          </g>
        );
      })}

      {/* Jardins privatifs RDC (depuis jardin_polygon_xy) : pelouse + terrasse
          bois le long du mur de l'apt + haies sur les 3 autres côtés. */}
      {layer === "base" && isRdc && niveau.cellules.map((cell) => {
        if (cell.type !== "logement") return null;
        const poly = cell.jardin_polygon_xy;
        if (!poly || poly.length < 3) return null;
        const jBbox = bboxOf(poly as Coord[]);
        if (!jBbox) return null;
        const aBbox = bboxOf(cell.polygon_xy as Coord[]);
        if (!aBbox) return null;
        const TOL = 0.3;
        type Side = "south" | "north" | "west" | "east";
        let aptSide: Side | null = null;
        if (Math.abs(jBbox.miny - aBbox.maxy) < TOL) aptSide = "south";
        else if (Math.abs(jBbox.maxy - aBbox.miny) < TOL) aptSide = "north";
        else if (Math.abs(jBbox.minx - aBbox.maxx) < TOL) aptSide = "west";
        else if (Math.abs(jBbox.maxx - aBbox.minx) < TOL) aptSide = "east";

        const terrasseDepth = 1.5;
        let terrasse: Coord[] | null = null;
        if (aptSide === "south") {
          terrasse = [
            [jBbox.minx, jBbox.miny], [jBbox.maxx, jBbox.miny],
            [jBbox.maxx, jBbox.miny + terrasseDepth], [jBbox.minx, jBbox.miny + terrasseDepth],
          ];
        } else if (aptSide === "north") {
          terrasse = [
            [jBbox.minx, jBbox.maxy - terrasseDepth], [jBbox.maxx, jBbox.maxy - terrasseDepth],
            [jBbox.maxx, jBbox.maxy], [jBbox.minx, jBbox.maxy],
          ];
        } else if (aptSide === "west") {
          terrasse = [
            [jBbox.minx, jBbox.miny], [jBbox.minx + terrasseDepth, jBbox.miny],
            [jBbox.minx + terrasseDepth, jBbox.maxy], [jBbox.minx, jBbox.maxy],
          ];
        } else if (aptSide === "east") {
          terrasse = [
            [jBbox.maxx - terrasseDepth, jBbox.miny], [jBbox.maxx, jBbox.miny],
            [jBbox.maxx, jBbox.maxy], [jBbox.maxx - terrasseDepth, jBbox.maxy],
          ];
        }

        const hedgeThickness = 0.25;
        const hedges: Coord[][] = [];
        const addHedge = (side: Side) => {
          if (side === aptSide) return;
          if (side === "south") {
            hedges.push([
              [jBbox.minx, jBbox.miny], [jBbox.maxx, jBbox.miny],
              [jBbox.maxx, jBbox.miny + hedgeThickness], [jBbox.minx, jBbox.miny + hedgeThickness],
            ]);
          } else if (side === "north") {
            hedges.push([
              [jBbox.minx, jBbox.maxy - hedgeThickness], [jBbox.maxx, jBbox.maxy - hedgeThickness],
              [jBbox.maxx, jBbox.maxy], [jBbox.minx, jBbox.maxy],
            ]);
          } else if (side === "west") {
            hedges.push([
              [jBbox.minx, jBbox.miny], [jBbox.minx + hedgeThickness, jBbox.miny],
              [jBbox.minx + hedgeThickness, jBbox.maxy], [jBbox.minx, jBbox.maxy],
            ]);
          } else {
            hedges.push([
              [jBbox.maxx - hedgeThickness, jBbox.miny], [jBbox.maxx, jBbox.miny],
              [jBbox.maxx, jBbox.maxy], [jBbox.maxx - hedgeThickness, jBbox.maxy],
            ]);
          }
        };
        (["south", "north", "west", "east"] as Side[]).forEach(addHedge);

        const cx = (jBbox.minx + jBbox.maxx) / 2;
        const cy = (jBbox.miny + jBbox.maxy) / 2;
        const [jlx, jly] = project([cx, cy]);
        return (
          <g key={`tiled-jardin-${cell.id}`}>
            <path d={toPath(poly as Coord[])} fill="url(#pat-lawn-bj)" stroke="#4f6d3a" strokeWidth={0.6} opacity={0.92} />
            {terrasse && (
              <path d={toPath(terrasse)} fill="url(#pat-terrasse-bois)" stroke="#8a6c44" strokeWidth={0.5} />
            )}
            {hedges.map((h, hi) => (
              <path key={`hedge-${cell.id}-${hi}`} d={toPath(h)} fill="#4f6d3a" stroke="#1e3a23" strokeWidth={0.5} />
            ))}
            <text x={jlx} y={jly} fontSize={7} fill="#1e3a23" textAnchor="middle" opacity={0.85} fontWeight={600}>
              jardin privatif
            </text>
          </g>
        );
      })}

      {/* Espace vert COMMUN (RDC) : résidu de cour partagé, planté. */}
      {layer === "base" && isRdc && niveau.jardin_commun_polygon_xy
        && (niveau.jardin_commun_polygon_xy as Coord[]).length >= 3 && (() => {
        const poly = niveau.jardin_commun_polygon_xy as Coord[];
        const cBbox = bboxOf(poly);
        if (!cBbox) return null;
        const cx = (cBbox.minx + cBbox.maxx) / 2;
        const cy = (cBbox.miny + cBbox.maxy) / 2;
        const [lx, ly] = project([cx, cy]);
        return (
          <g key="jardin-commun" data-jardin-commun="true">
            <path d={toPath(poly)} fill="url(#pat-lawn-commun)" stroke="#3d5a2c" strokeWidth={0.8} strokeDasharray="2 1.5" opacity={0.95} />
            <text x={lx} y={ly} fontSize={7} fill="#243b18" textAnchor="middle" opacity={0.9} fontWeight={700}>
              jardin commun
            </text>
          </g>
        );
      })()}
    </g>
  );
}
