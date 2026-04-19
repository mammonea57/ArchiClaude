"use client";

import type { BuildingModelPayload } from "@/lib/types";
import { PlanPatterns, NorthArrow, ScaleBar, TitleBlock } from "./plan-patterns";

interface CoupeElevationProps {
  bm: BuildingModelPayload;
  mode: "coupe" | "facade";
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
  bm, mode, width = 900, height = 620, projectName,
}: CoupeElevationProps) {
  const env = bm.envelope;
  const niveaux = [...bm.niveaux].sort((a, b) => a.index - b.index);

  // Horizontal span from footprint bbox (mode-dependent)
  let spanM = Math.sqrt(env.emprise_m2);
  const footprint = env.footprint_geojson as { coordinates?: number[][][] } | undefined;
  if (footprint?.coordinates?.[0]) {
    const coords = footprint.coordinates[0];
    const xs = coords.map((c) => c[0]);
    const ys = coords.map((c) => c[1]);
    const w = Math.max(...xs) - Math.min(...xs);
    const h = Math.max(...ys) - Math.min(...ys);
    spanM = mode === "facade" ? w : h;
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
      <rect
        x={padLeft - 30}
        y={by0}
        width={innerW + 60}
        height={groundDepthM * scale}
        fill="url(#pat-ground)"
        stroke="#0f172a"
        strokeWidth={0.7}
      />
      {/* Ground surface line */}
      <line
        x1={padLeft - 30}
        y1={by0}
        x2={padLeft + innerW + 30}
        y2={by0}
        stroke="#0f172a"
        strokeWidth={1.3}
      />

      {/* Sky fade above */}
      <rect x={padLeft - 30} y={padTop - 10} width={innerW + 60} height={by0 - padTop + 10} fill="#f8fafc" />

      {/* Building volume */}
      {mode === "coupe" ? (
        <CoupeBody stories={stories} worldToPx={worldToPx} spanPx={spanPx} scale={scale} parapetPx={parapetPx} />
      ) : (
        <FacadeBody stories={stories} openingsByStory={openingsByStory} worldToPx={worldToPx} spanPx={spanPx} scale={scale} parapetPx={parapetPx} env={env} />
      )}

      {/* Height dimension on the right */}
      <HeightDim
        x1={bx0 + spanPx + 18}
        yTop={by0 - totalHPx - parapetPx}
        yBottom={by0}
        totalHeightM={env.hauteur_totale_m}
        stories={stories}
        worldToPx={worldToPx}
      />

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
            <text x={padLeft - 36} y={yMid + 4} textAnchor="end" fontSize={8.5} fill="#64748b">
              HSP {s.hsp.toFixed(2)}
            </text>
          </g>
        );
      })}

      {/* Header */}
      <g>
        <rect x={20} y={20} width={width - 40} height={38} fill="white" />
        <line x1={20} y1={58} x2={width - 20} y2={58} stroke="#0f172a" strokeWidth={0.5} />
        <text x={30} y={40} fontSize={15} fontWeight={700} fill="#0f172a">
          {mode === "coupe" ? "Coupe longitudinale A-A" : `Façade principale (${bm.site.voirie_orientations[0] ?? "sud"})`}
        </text>
        <text x={30} y={54} fontSize={10.5} fill="#475569">
          R+{env.niveaux - 1} · hauteur {env.hauteur_totale_m} m · RDC {env.hauteur_rdc_m} m · étages courants {env.hauteur_etage_courant_m} m
          {projectName ? ` · ${projectName}` : ""}
        </text>
      </g>

      {/* Compass + scale */}
      <NorthArrow x={width - 56} y={98} size={46} rotationDeg={bm.site.north_angle_deg ?? 0} />
      <ScaleBar x={padLeft} y={height - 32} scalePxPerM={scale} meters={5} />

      <TitleBlock
        x={width - 232}
        y={height - 68}
        title={mode === "coupe" ? "Coupe A-A" : "Façade"}
        subtitle={`1:100 · ${mode === "coupe" ? "DP-CO-01" : "DP-FA-01"}`}
        sheetCode={mode === "coupe" ? "PC3" : "PC5"}
      />
    </svg>
  );
}

/* ─────────── Coupe body ─────────── */

function CoupeBody({
  stories, worldToPx, spanPx, scale, parapetPx,
}: {
  stories: Array<{ code: string; yBase: number; height: number; usage: string }>;
  worldToPx: (x: number, y: number) => [number, number];
  spanPx: number;
  scale: number;
  parapetPx: number;
}) {
  return (
    <g>
      {/* Outer walls (filled concrete) - left + right */}
      {stories.map((s, i) => {
        const [xL, yB] = worldToPx(0, s.yBase);
        const [, yT] = worldToPx(0, s.yBase + s.height);
        const wallW = Math.max(4, 0.25 * scale);
        return (
          <g key={i}>
            <rect x={xL} y={yT} width={wallW} height={yB - yT} fill="url(#pat-concrete)" stroke="#0f172a" strokeWidth={0.7} />
            <rect x={xL + spanPx - wallW} y={yT} width={wallW} height={yB - yT} fill="url(#pat-concrete)" stroke="#0f172a" strokeWidth={0.7} />
          </g>
        );
      })}

      {/* Slabs between stories */}
      {stories.map((s, i) => {
        const [xL, yB] = worldToPx(0, s.yBase);
        const slabH = 0.25 * scale;
        return (
          <rect
            key={`slab-${i}`}
            x={xL - 2}
            y={yB - slabH}
            width={spanPx + 4}
            height={slabH}
            fill="url(#pat-concrete)"
            stroke="#0f172a"
            strokeWidth={0.6}
          />
        );
      })}

      {/* Top slab + parapet */}
      {(() => {
        const top = stories[stories.length - 1];
        const [xL, yT] = worldToPx(0, top.yBase + top.height);
        const slabH = 0.3 * scale;
        return (
          <g>
            <rect x={xL - 2} y={yT - slabH} width={spanPx + 4} height={slabH} fill="url(#pat-concrete)" stroke="#0f172a" strokeWidth={0.6} />
            {/* Parapet */}
            <rect x={xL - 2} y={yT - slabH - parapetPx} width={spanPx + 4} height={parapetPx} fill="#e7e5e4" stroke="#0f172a" strokeWidth={0.6} />
            <rect x={xL - 2} y={yT - slabH - parapetPx} width={spanPx + 4} height={2} fill="#78716c" />
          </g>
        );
      })()}

      {/* Room interior per story */}
      {stories.map((s, i) => {
        const [xL, yB] = worldToPx(0, s.yBase);
        const [, yT] = worldToPx(0, s.yBase + s.height);
        const wallW = Math.max(4, 0.25 * scale);
        const innerX = xL + wallW + 2;
        const innerY = yT + 0.25 * scale;
        const innerW = spanPx - 2 * (wallW + 2);
        const innerH = (yB - yT) - 0.5 * scale;
        return (
          <g key={`room-${i}`}>
            <rect x={innerX} y={innerY} width={innerW} height={innerH} fill="#fafaf9" />
            <rect x={innerX} y={innerY + innerH * 0.85} width={innerW} height={innerH * 0.15} fill="url(#pat-parquet)" />
            <text x={innerX + innerW / 2} y={innerY + innerH / 2 + 4} textAnchor="middle" fontSize={10} fill="#64748b">
              {s.usage}
            </text>
          </g>
        );
      })}

      {/* Stairs marker in middle */}
      {(() => {
        const mid = stories[Math.floor(stories.length / 2)];
        const [, yB] = worldToPx(0, mid.yBase);
        const [xL, yT] = worldToPx(0, mid.yBase + mid.height);
        const sx = xL + spanPx / 2 - 18;
        return (
          <g>
            {Array.from({ length: 8 }).map((_, i) => (
              <line
                key={i}
                x1={sx + i * 4.5}
                y1={yB - 2}
                x2={sx + i * 4.5}
                y2={yT + 2}
                stroke="#475569"
                strokeWidth={0.4}
              />
            ))}
            <path
              d={`M ${sx} ${yB - 2} L ${sx + 36} ${yT + 2}`}
              stroke="#0f172a"
              strokeWidth={0.8}
            />
          </g>
        );
      })()}
    </g>
  );
}

/* ─────────── Façade body ─────────── */

function FacadeBody({
  stories, openingsByStory, worldToPx, spanPx, scale, parapetPx, env,
}: {
  stories: Array<{ code: string; yBase: number; height: number; usage: string }>;
  openingsByStory: number[];
  worldToPx: (x: number, y: number) => [number, number];
  spanPx: number;
  scale: number;
  parapetPx: number;
  env: BuildingModelPayload["envelope"];
}) {
  // Enduit background
  const topStory = stories[stories.length - 1];
  const [xL, yTop] = worldToPx(0, topStory.yBase + topStory.height);
  const [, yBase] = worldToPx(0, 0);
  return (
    <g>
      {/* Enduit wall */}
      <rect x={xL} y={yTop} width={spanPx} height={yBase - yTop} fill="#eeece1" stroke="#1c1917" strokeWidth={1.4} />
      {/* enduit horizontal joints */}
      {Array.from({ length: Math.floor((yBase - yTop) / 26) }).map((_, i) => (
        <line key={i} x1={xL} y1={yTop + (i + 1) * 26} x2={xL + spanPx} y2={yTop + (i + 1) * 26} stroke="#d6d3d1" strokeWidth={0.3} />
      ))}

      {/* Windows grid per story */}
      {stories.map((s, i) => {
        const nOp = Math.max(3, openingsByStory[i] || 3);
        const cols = Math.min(nOp, Math.max(3, Math.floor(spanPx / 80)));
        const [, yT] = worldToPx(0, s.yBase + s.height);
        const [, yB] = worldToPx(0, s.yBase);
        const storyH = yB - yT;
        const winH = Math.min(storyH * 0.55, env.hauteur_etage_courant_m * 0.55 * scale);
        const winW = Math.min((spanPx * 0.7) / cols, 90);
        const winY = yT + (storyH - winH) / 2;
        const gap = (spanPx - cols * winW) / (cols + 1);
        return (
          <g key={`fa-${i}`}>
            {Array.from({ length: cols }).map((_, c) => {
              const wx = xL + gap + c * (winW + gap);
              return (
                <g key={c}>
                  {/* Sill */}
                  <rect x={wx - 2} y={winY + winH} width={winW + 4} height={2} fill="#78716c" />
                  {/* Frame */}
                  <rect x={wx} y={winY} width={winW} height={winH} fill="#bae6fd" stroke="#0c4a6e" strokeWidth={1} />
                  {/* Glass mullions — 2x2 */}
                  <line x1={wx + winW / 2} y1={winY} x2={wx + winW / 2} y2={winY + winH} stroke="#0c4a6e" strokeWidth={0.7} />
                  <line x1={wx} y1={winY + winH / 2} x2={wx + winW} y2={winY + winH / 2} stroke="#0c4a6e" strokeWidth={0.7} />
                  {/* Shadow on inside */}
                  <rect x={wx + 2} y={winY + 2} width={winW / 2 - 2} height={winH / 2 - 2} fill="#7dd3fc" opacity={0.6} />
                  <rect x={wx + winW / 2 + 2} y={winY + winH / 2 + 2} width={winW / 2 - 4} height={winH / 2 - 4} fill="#7dd3fc" opacity={0.6} />
                  {/* Lintel */}
                  <rect x={wx - 2} y={winY - 2} width={winW + 4} height={2} fill="#a8a29e" />
                </g>
              );
            })}
            {/* Story band horizontal line */}
            <line x1={xL} y1={yB - 0.25 * scale} x2={xL + spanPx} y2={yB - 0.25 * scale} stroke="#a8a29e" strokeWidth={0.5} strokeDasharray="2 2" />
          </g>
        );
      })}

      {/* Parapet */}
      <rect x={xL} y={yTop - parapetPx} width={spanPx} height={parapetPx} fill="#d6d3d1" stroke="#0f172a" strokeWidth={0.6} />
      <line x1={xL} y1={yTop - parapetPx + 3} x2={xL + spanPx} y2={yTop - parapetPx + 3} stroke="#0f172a" strokeWidth={0.5} />

      {/* Ground line continuation */}
      <line x1={xL - 20} y1={yBase} x2={xL + spanPx + 20} y2={yBase} stroke="#0f172a" strokeWidth={1.4} />
    </g>
  );
}

/* ─────────── Height dimension ─────────── */

function HeightDim({
  x1, yTop, yBottom, totalHeightM, stories, worldToPx,
}: {
  x1: number; yTop: number; yBottom: number; totalHeightM: number;
  stories: Array<{ code: string; yBase: number; height: number }>;
  worldToPx: (x: number, y: number) => [number, number];
}) {
  return (
    <g>
      {/* Vertical dim line */}
      <line x1={x1} y1={yTop} x2={x1} y2={yBottom} stroke="#0f172a" strokeWidth={0.6} />
      {/* arrows top/bottom */}
      <polygon points={`${x1},${yTop} ${x1 - 3},${yTop + 6} ${x1 + 3},${yTop + 6}`} fill="#0f172a" />
      <polygon points={`${x1},${yBottom} ${x1 - 3},${yBottom - 6} ${x1 + 3},${yBottom - 6}`} fill="#0f172a" />
      {/* Total */}
      <text x={x1 + 8} y={(yTop + yBottom) / 2} fontSize={10} fontWeight={700} fill="#0f172a" dominantBaseline="middle">
        {totalHeightM.toFixed(1)} m
      </text>

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
