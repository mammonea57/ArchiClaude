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
  const voirieFirst = (bm.site.voirie_orientations?.[0] ?? "sud") as FacadeSide;
  const side: FacadeSide = facadeSide ?? voirieFirst;
  const isVoirieSide = mode === "facade" && side === voirieFirst;

  // Horizontal span from footprint bbox (mode-dependent)
  let spanM = Math.sqrt(env.emprise_m2);
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
    } else {
      spanM = cutAxis === "BB" ? w : h;
    }
  }

  // Total height + 1m for parapet + below-ground
  const totalHeightM = env.hauteur_totale_m + 1.2;
  const groundDepthM = 1.5;

  const padLeft = 80;
  const padRight = 60;
  const padTop = 70;
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
          showEntry={isVoirieSide}
          side={side}
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

      {/* NGT altimetric scale (right edge — coupe mode only) */}
      {mode === "coupe" && (
        <NGTScale
          x={width - padRight + 8}
          yGround={by0}
          stories={stories}
          worldToPx={worldToPx}
          totalHeightM={env.hauteur_totale_m}
        />
      )}

      {/* Légende matériaux (coupe mode only) — placed in the bottom strip
          BETWEEN the scale bar (left) and the title block (right). This is
          OUTSIDE the building drawing zone (below by0 + groundDepth) so it
          never overlaps the section. Horizontal layout, compact height. */}
      {mode === "coupe" && (
        <LegendeMateriaux
          x={padLeft + 100}
          y={height - 60}
          maxWidth={width - padLeft - 100 - 240}
        />
      )}

      {/* Story codes on the left */}
      {stories.map((s, i) => {
        const [, yTop] = worldToPx(0, s.yBase + s.height);
        const [, yMid] = worldToPx(0, s.yBase + s.height / 2);
        return (
          <g key={i}>
            <line x1={padLeft - 30} y1={yTop} x2={padLeft - 4} y2={yTop} stroke="#475569" strokeWidth={0.5} strokeDasharray="3 2" />
            <text x={padLeft - 36} y={yTop + 4} textAnchor="end" fontSize={10} fontWeight={700} fill="#0f172a">
              {s.code}
            </text>
            <text x={padLeft - 36} y={yMid + 4} textAnchor="end" fontSize={9.5} fontWeight={500} fill="#475569">
              HSP {s.hsp.toFixed(2)}
            </text>
          </g>
        );
      })}

      {/* Header — title text shifts right in coupe mode to leave room for the
          compass at TOP-LEFT (inside the cartouche) */}
      <g>
        <rect x={20} y={20} width={width - 40} height={38} fill="white" />
        <line x1={20} y1={58} x2={width - 20} y2={58} stroke="#0f172a" strokeWidth={0.5} />
        <text x={mode === "coupe" ? 64 : 30} y={40} fontSize={15} fontWeight={700} fill="#0f172a">
          {mode === "coupe"
            ? (cutAxis === "BB" ? "Coupe B-B' — longitudinale" : "Coupe A-A' — transversale")
            : `Façade ${SIDE_LABEL[side]}${isVoirieSide ? " — principale (voirie)" : ""}`}
        </text>
        <text x={mode === "coupe" ? 64 : 30} y={54} fontSize={10.5} fill="#475569">
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
        x={width - 232}
        y={height - 68}
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
              {/* Label "ACROTÈRE" — small annotation outside the right acrotère
                  pointing inward with a thin leader. Helps the reader. */}
              <line
                x1={xB + 2}
                y1={yTopTop - slabH - acrotereHpx / 2}
                x2={xB + 18}
                y2={yTopTop - slabH - acrotereHpx / 2}
                stroke="#475569"
                strokeWidth={0.5}
              />
              <text
                x={xB + 20}
                y={yTopTop - slabH - acrotereHpx / 2 + 3}
                fontSize={8}
                fontWeight={700}
                fill="#0f172a"
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
                  {pieces.map((p, pi) => {
                    const pxA = worldToPx(toSection(p.wA), 0)[0];
                    const pxB = worldToPx(toSection(p.wB), 0)[0];
                    return (
                      <g key={pi}>
                        <rect x={pxA + 0.4} y={innerY} width={pxB - pxA - 0.8} height={innerH} fill={p.tone} opacity={0.95} />
                        {pxB - pxA > 26 && (
                          <text
                            x={(pxA + pxB) / 2}
                            y={innerY + innerH / 2 + 3.5}
                            textAnchor="middle"
                            fontSize={9}
                            fontWeight={600}
                            fill="#0f172a"
                          >
                            {p.label}
                          </text>
                        )}
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
  enduitBase: "#e8e1d0",     // beige sable
  enduitShadow: "#d9d0b8",   // ombre enduit
  bardageWood: "#9c7d57",    // cèdre naturel
  bardageWoodDark: "#6f5636",
  soubassement: "#4a4542",   // pierre anthracite
  soubassementLine: "#2a2725",
  menuiserieBlack: "#1a1a1a",
  menuiserieNoir: "#0a0a0a",
  glass: "#8fc7e0",
  glassLight: "#b9dce9",
  glassReflect: "#dceef5",
  gardeCorps: "#111111",
  accentPetrole: "#25525c",
};

function FacadeBody({
  stories, openingsByStory, worldToPx, spanPx, scale, parapetPx, env, showEntry, side,
}: {
  stories: Array<{ code: string; yBase: number; height: number; usage: string }>;
  openingsByStory: number[];
  worldToPx: (x: number, y: number) => [number, number];
  spanPx: number;
  scale: number;
  parapetPx: number;
  env: BuildingModelPayload["envelope"];
  showEntry: boolean;
  side: "nord" | "sud" | "est" | "ouest";
}) {
  const topStory = stories[stories.length - 1];
  const [xL, yTop] = worldToPx(0, topStory.yBase + topStory.height);
  const [, yBase] = worldToPx(0, 0);
  const totalH = yBase - yTop;

  const isVoirie = showEntry;
  const isPignon = side === "est" || side === "ouest";
  const isNorth = side === "nord";

  // Attic setback (last floor): 1.2 m from the façade plane, rendered as a
  // wood-clad attic at the top of the sheet.
  const [, yAtticTop] = worldToPx(0, topStory.yBase);  // bottom of attic
  const atticHeight = topStory.height;
  const atticSetbackPx = 1.2 * scale;  // visual inset for attic
  const [, yAtticFloor] = worldToPx(0, topStory.yBase);  // floor of attic = top of R+N-1

  // Soubassement (pierre anthracite), 0.9 m
  const soubassementHeight = 0.9 * scale;
  const [, ySoubassementTop] = worldToPx(0, 0);  // ground
  const ySoub = yBase - soubassementHeight;

  // Number of vertical bays (rhythm): 5-7 depending on span (contemporary
  // wide openings, not cram).
  const targetBayM = 3.8;  // bay spacing in meters — one window + wall
  const estimatedBays = Math.max(4, Math.round(spanPx / (targetBayM * scale)));
  const bays = Math.min(8, estimatedBays);
  const bayW = spanPx / bays;

  return (
    <g>
      {/* ───── Main wall — enduit ───── */}
      <defs>
        <linearGradient id="enduit-vshadow" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor={PALETTE.enduitShadow} stopOpacity={0.45} />
          <stop offset="0.25" stopColor={PALETTE.enduitShadow} stopOpacity={0} />
          <stop offset="0.75" stopColor={PALETTE.enduitShadow} stopOpacity={0} />
          <stop offset="1" stopColor={PALETTE.enduitShadow} stopOpacity={0.6} />
        </linearGradient>
      </defs>
      <rect x={xL} y={yTop} width={spanPx} height={totalH} fill={PALETTE.enduitBase} />
      <rect x={xL} y={yTop} width={spanPx} height={totalH} fill="url(#enduit-vshadow)" />

      {/* ───── Attic (dernier étage) — bardage bois vertical ───── */}
      <rect
        x={xL + atticSetbackPx}
        y={yAtticFloor - atticHeight * scale / env.hauteur_etage_courant_m}
        width={spanPx - 2 * atticSetbackPx}
        height={yAtticFloor - (yAtticFloor - atticHeight * scale / env.hauteur_etage_courant_m)}
        fill={PALETTE.bardageWood}
      />
      {/* Wood cladding vertical boards (one line every ~15 cm) */}
      {(() => {
        const atticHPx = topStory.height * scale;
        const boardSpacingPx = 6;  // ~15-20 cm boards
        const atticTop = yAtticFloor - atticHPx;
        const atticW = spanPx - 2 * atticSetbackPx;
        const n = Math.floor(atticW / boardSpacingPx);
        return Array.from({ length: n }).map((_, i) => (
          <line
            key={`b-${i}`}
            x1={xL + atticSetbackPx + i * boardSpacingPx}
            y1={atticTop}
            x2={xL + atticSetbackPx + i * boardSpacingPx}
            y2={yAtticFloor}
            stroke={PALETTE.bardageWoodDark}
            strokeWidth={0.25}
            opacity={0.65}
          />
        ));
      })()}
      {/* Nez de dalle dark line separating attic from floor below */}
      <rect
        x={xL}
        y={yAtticFloor - 3}
        width={spanPx}
        height={3}
        fill={PALETTE.menuiserieBlack}
      />

      {/* ───── Soubassement (pierre anthracite) ───── */}
      <rect
        x={xL - 1}
        y={ySoub}
        width={spanPx + 2}
        height={soubassementHeight}
        fill={PALETTE.soubassement}
      />
      {/* Joints horizontaux */}
      <line x1={xL - 1} y1={ySoub + soubassementHeight * 0.5} x2={xL + spanPx + 1} y2={ySoub + soubassementHeight * 0.5} stroke={PALETTE.soubassementLine} strokeWidth={0.4} />
      <line x1={xL - 1} y1={ySoub} x2={xL + spanPx + 1} y2={ySoub} stroke={PALETTE.menuiserieBlack} strokeWidth={1.2} />

      {/* ───── Windows per story ───── */}
      {stories.map((s, i) => {
        const isRdc = i === 0;
        const isAttic = i === stories.length - 1;
        const [, yT] = worldToPx(0, s.yBase + s.height);
        const [, yB] = worldToPx(0, s.yBase);
        const storyH = yB - yT;

        // Window proportions — contemporary tall vertical windows on upper
        // floors, more compact on RDC (because of soubassement), smaller on
        // NORD (energy-conscious).
        const winH = isRdc
          ? storyH * 0.55 - soubassementHeight * 0.5
          : storyH * (isNorth ? 0.52 : 0.70);
        const winW = Math.min(bayW * 0.58, isNorth ? 55 : 78);
        const winY = isRdc
          ? ySoub - winH - 6
          : yT + (storyH - winH) / 2;

        return (
          <g key={`fa-${i}`}>
            {Array.from({ length: bays }).map((_, c) => {
              const bayCx = xL + (c + 0.5) * bayW;
              const wx = bayCx - winW / 2;

              // Entry on RDC + center bay only on voirie façade
              const isEntryBay = isRdc && c === Math.floor(bays / 2) && showEntry;
              if (isEntryBay) {
                const doorH = storyH * 0.82;
                const doorW = winW * 1.25;
                const doorX = bayCx - doorW / 2;
                const doorY = yB - doorH;
                return (
                  <g key={c}>
                    {/* Auvent / casquette bois en porte-à-faux */}
                    <rect x={doorX - 16} y={doorY - 16} width={doorW + 32} height={5} fill={PALETTE.bardageWood} stroke={PALETTE.bardageWoodDark} strokeWidth={0.5} />
                    <rect x={doorX - 16} y={doorY - 21} width={doorW + 32} height={5} fill={PALETTE.bardageWoodDark} opacity={0.9} />
                    {/* Vitrage entrée toute hauteur */}
                    <rect x={doorX} y={doorY} width={doorW} height={doorH} fill={PALETTE.glass} stroke={PALETTE.menuiserieNoir} strokeWidth={1.8} />
                    {/* Porte + vantaux + imposte */}
                    <line x1={doorX + doorW / 2} y1={doorY} x2={doorX + doorW / 2} y2={doorY + doorH} stroke={PALETTE.menuiserieNoir} strokeWidth={1.4} />
                    <line x1={doorX} y1={doorY + doorH * 0.18} x2={doorX + doorW} y2={doorY + doorH * 0.18} stroke={PALETTE.menuiserieNoir} strokeWidth={0.9} />
                    {/* Reflets vitrage */}
                    <rect x={doorX + 3} y={doorY + 3} width={doorW / 2 - 5} height={doorH - 6} fill={PALETTE.glassReflect} opacity={0.35} />
                    {/* Poignée inox linéaire */}
                    <rect x={doorX + doorW * 0.40} y={doorY + doorH * 0.55} width={1.8} height={22} fill="#cbd5e1" />
                    {/* Seuil */}
                    <rect x={doorX - 3} y={doorY + doorH} width={doorW + 6} height={2.5} fill={PALETTE.menuiserieNoir} />
                    {/* Label */}
                    <text x={bayCx} y={doorY - 26} textAnchor="middle" fontSize={9} fontWeight={700} fill={PALETTE.menuiserieNoir} letterSpacing="0.6">
                      ENTRÉE
                    </text>
                  </g>
                );
              }

              return (
                <g key={c}>
                  {/* ── Window frame ── */}
                  <rect x={wx - 1} y={winY - 1} width={winW + 2} height={winH + 2} fill={PALETTE.menuiserieBlack} />
                  <rect x={wx} y={winY} width={winW} height={winH} fill={PALETTE.glass} />
                  {/* Glass reflections — graded */}
                  <rect x={wx + 1.5} y={winY + 1.5} width={winW * 0.45} height={winH * 0.6} fill={PALETTE.glassReflect} opacity={0.42} />
                  <rect x={wx + winW * 0.55} y={winY + winH * 0.55} width={winW * 0.4} height={winH * 0.4} fill={PALETTE.glassLight} opacity={0.35} />
                  {/* Central mullion */}
                  <line x1={wx + winW / 2} y1={winY} x2={wx + winW / 2} y2={winY + winH} stroke={PALETTE.menuiserieNoir} strokeWidth={1.0} />
                  {/* Allège sous la fenêtre (bandeau moderne étroit) */}
                  <rect x={wx - 2} y={winY + winH + 0.5} width={winW + 4} height={2.2} fill={PALETTE.soubassement} />

                  {/* ── Balcony / loggia per side ── */}
                  {!isRdc && !isAttic && renderBalconyOrLoggia({
                    side, isVoirie, isPignon, wx, winY, winW, winH, yT, yB,
                    palette: PALETTE, c, bays,
                  })}

                  {/* ── Brise-soleil vertical (pignons E/W only) ── */}
                  {!isRdc && isPignon && c > 0 && c < bays - 1 && (
                    <g opacity={0.88}>
                      {[-1, 1].map((sgn) => (
                        <rect
                          key={sgn}
                          x={wx + (sgn < 0 ? -4 : winW + 1)}
                          y={winY - 3}
                          width={3}
                          height={winH + 6}
                          fill={PALETTE.menuiserieBlack}
                        />
                      ))}
                    </g>
                  )}
                </g>
              );
            })}

            {/* Nez de dalle horizontal entre les étages */}
            {i < stories.length - 1 && (
              <rect x={xL} y={yB - 3} width={spanPx} height={3} fill={PALETTE.soubassement} opacity={0.85} />
            )}
          </g>
        );
      })}

      {/* ───── Garde-corps balcons filants (sud voirie seulement) ───── */}
      {isVoirie && stories.slice(1, -1).map((s, i) => {
        const [, yB] = worldToPx(0, s.yBase);
        return (
          <g key={`balcony-filant-${i}`}>
            {/* Dalle de balcon */}
            <rect x={xL + 6} y={yB - 4} width={spanPx - 12} height={4} fill={PALETTE.soubassement} opacity={0.9} />
            {/* Garde-corps verre + cadre métal noir */}
            <rect x={xL + 6} y={yB - 18} width={spanPx - 12} height={14} fill={PALETTE.glassLight} opacity={0.38} />
            <rect x={xL + 6} y={yB - 18} width={spanPx - 12} height={14} fill="none" stroke={PALETTE.gardeCorps} strokeWidth={0.9} />
            <rect x={xL + 6} y={yB - 18} width={spanPx - 12} height={1.4} fill={PALETTE.gardeCorps} />
            <rect x={xL + 6} y={yB - 5.5} width={spanPx - 12} height={1.4} fill={PALETTE.gardeCorps} />
          </g>
        );
      })}

      {/* ───── Parapet & attique terminale ───── */}
      <rect x={xL - 1} y={yTop - parapetPx} width={spanPx + 2} height={parapetPx} fill={PALETTE.enduitShadow} />
      <rect x={xL - 1} y={yTop - parapetPx} width={spanPx + 2} height={3} fill={PALETTE.menuiserieNoir} />
      <rect x={xL - 1} y={yTop} width={spanPx + 2} height={2.5} fill={PALETTE.menuiserieBlack} />

      {/* Building outline (crisp contour) */}
      <rect x={xL} y={yTop} width={spanPx} height={totalH} fill="none" stroke={PALETTE.menuiserieNoir} strokeWidth={1.4} />

      {/* Ground line */}
      <line x1={xL - 30} y1={yBase} x2={xL + spanPx + 30} y2={yBase} stroke="#0f172a" strokeWidth={1.4} />
      {/* Light ground shadow under building */}
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

  // Pignons E/W: loggia creuse (recessed balcony) on the 2 central bays
  if (isPignon) {
    const centralBays = c >= Math.floor(bays / 3) && c < Math.ceil((2 * bays) / 3);
    if (!centralBays) return null;
    // Draw a darker recess pattern indicating a loggia
    const loggiaX = wx - winW * 0.15;
    const loggiaY = winY - 6;
    const loggiaW = winW * 1.3;
    const loggiaH = winH + 12;
    return (
      <g>
        <rect x={loggiaX} y={loggiaY} width={loggiaW} height={loggiaH} fill={palette.soubassement} opacity={0.22} />
        <rect x={loggiaX} y={loggiaY + loggiaH - 2} width={loggiaW} height={2} fill={palette.menuiserieBlack} opacity={0.4} />
        {/* Garde-corps loggia — métal noir barreaudage */}
        <rect x={loggiaX + 2} y={loggiaY + loggiaH - 14} width={loggiaW - 4} height={12} fill="none" stroke={palette.gardeCorps} strokeWidth={0.8} />
        {Array.from({ length: 8 }).map((_, b) => (
          <line
            key={b}
            x1={loggiaX + 2 + b * (loggiaW - 4) / 7}
            y1={loggiaY + loggiaH - 14}
            x2={loggiaX + 2 + b * (loggiaW - 4) / 7}
            y2={loggiaY + loggiaH - 2}
            stroke={palette.gardeCorps}
            strokeWidth={0.5}
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
  // Niveaux NGT à afficher : TN (+0.00) puis chaque PHR (plancher haut)
  type Tick = { yPx: number; alt: number; label: string; code: string };
  const ticks: Tick[] = [{ yPx: yGround, alt: 0, label: "+0.00 NGT", code: "TN" }];
  for (let i = 0; i < stories.length; i++) {
    const s = stories[i];
    const altTop = s.yBase + s.height;
    const [, yTopPx] = worldToPx(0, altTop);
    const phrCode = i === 0 ? "PHRDC" : `PHR+${i}`;
    ticks.push({
      yPx: yTopPx,
      alt: altTop,
      label: `+${altTop.toFixed(2)}`,
      code: phrCode,
    });
  }

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
          {/* Label altitude */}
          <text x={x + 6} y={t.yPx + 2.6} fontSize={7.5} fill="#0f172a">
            {t.label}
          </text>
          {/* Code PHR/TN au-dessus de la cote */}
          <text x={x + 6} y={t.yPx - 3} fontSize={6.5} fill="#64748b">
            {t.code}
          </text>
        </g>
      ))}
    </g>
  );
}

/* ─────────── Légende matériaux (coupe only) ─────────── */

function LegendeMateriaux({ x, y, maxWidth }: { x: number; y: number; maxWidth: number }) {
  // Horizontal strip layout: title on the left, swatches flowing to the right.
  // Sized to fit BETWEEN the scale bar and the title block, OUTSIDE the
  // building drawing zone. Strip height fixed at 28 px.
  const h = 30;
  const w = Math.max(280, maxWidth);
  const items: Array<{ pattern: string; label: string }> = [
    { pattern: "url(#pat-beton-arme)", label: "Béton armé" },
    { pattern: "url(#pat-isolation)", label: "Isolation" },
    { pattern: "url(#pat-etancheite)", label: "Étanchéité" },
    { pattern: "url(#pat-terre)", label: "Terre" },
  ];
  // Estimate column width based on available width minus the title cell.
  const titleCellW = 78;
  const colW = (w - titleCellW - 8) / items.length;
  const swatchW = 16;
  const swatchH = 8;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill="white" stroke="#0f172a" strokeWidth={0.6} rx={2} />
      {/* Title cell */}
      <text x={x + 6} y={y + 18} fontSize={8.5} fontWeight={700} fill="#0f172a">
        Légende matériaux
      </text>
      <line x1={x + titleCellW} y1={y + 4} x2={x + titleCellW} y2={y + h - 4} stroke="#cbd5e1" strokeWidth={0.4} />
      {items.map((it, i) => (
        <g key={i} transform={`translate(${x + titleCellW + 6 + i * colW}, ${y + h / 2 - swatchH / 2})`}>
          <rect x={0} y={0} width={swatchW} height={swatchH} fill={it.pattern} stroke="#475569" strokeWidth={0.4} />
          <text x={swatchW + 5} y={swatchH - 0.5} fontSize={7.8} fill="#0f172a">
            {it.label}
          </text>
        </g>
      ))}
    </g>
  );
}
