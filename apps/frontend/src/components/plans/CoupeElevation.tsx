"use client";

import type { BuildingModelPayload } from "@/lib/types";

interface CoupeElevationProps {
  bm: BuildingModelPayload;
  mode: "coupe" | "facade";
  width?: number;
  height?: number;
}

/**
 * Schematic section (coupe) or elevation (façade) view derived from the BM
 * envelope. Stories, heights, HSP, parapet are drawn to scale.
 */
export function CoupeElevation({ bm, mode, width = 600, height = 400 }: CoupeElevationProps) {
  const env = bm.envelope;
  const niveaux = [...bm.niveaux].sort((a, b) => a.index - b.index);

  // Horizontal span = footprint width along voirie axis. Fall back to sqrt(area)
  let spanM = Math.sqrt(env.emprise_m2);
  const footprint = env.footprint_geojson;
  if (footprint && typeof footprint === "object" && "coordinates" in footprint) {
    const coords = (footprint as { coordinates: number[][][] }).coordinates?.[0];
    if (coords && coords.length > 0) {
      const xs = coords.map((c) => c[0]);
      const ys = coords.map((c) => c[1]);
      const w = Math.max(...xs) - Math.min(...xs);
      const h = Math.max(...ys) - Math.min(...ys);
      spanM = mode === "facade" ? w : h;
    }
  }

  const padding = { top: 40, right: 30, bottom: 50, left: 50 };
  const availW = width - padding.left - padding.right;
  const availH = height - padding.top - padding.bottom;

  const scale = Math.min(availW / spanM, availH / (env.hauteur_totale_m + 1.5));

  const baseX = padding.left;
  const baseY = height - padding.bottom;

  const spanPx = spanM * scale;
  const totalHPx = env.hauteur_totale_m * scale;

  let yCursor = baseY;
  const levelLines: Array<{ y: number; label: string; hsp: number; usage: string }> = [];
  // Ground line at baseY
  for (let i = 0; i < env.niveaux; i++) {
    const niv = niveaux[i];
    const hsp = niv?.hauteur_sous_plafond_m ?? (i === 0 ? env.hauteur_rdc_m : env.hauteur_etage_courant_m);
    const storyH = i === 0 ? env.hauteur_rdc_m : env.hauteur_etage_courant_m;
    yCursor -= storyH * scale;
    levelLines.push({
      y: yCursor,
      label: niv?.code ?? `R+${i}`,
      hsp,
      usage: niv?.usage_principal ?? "—",
    });
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="bg-white border border-slate-100 rounded-lg"
    >
      {/* Ground line */}
      <line x1={padding.left - 10} y1={baseY} x2={width - padding.right + 10} y2={baseY} stroke="#0f172a" strokeWidth={1.5} />
      {/* Ground hatch */}
      {Array.from({ length: 20 }).map((_, i) => (
        <line
          key={i}
          x1={padding.left - 10 + i * ((width - padding.left - padding.right + 20) / 20)}
          y1={baseY}
          x2={padding.left - 10 + i * ((width - padding.left - padding.right + 20) / 20) - 6}
          y2={baseY + 8}
          stroke="#64748b"
          strokeWidth={0.8}
        />
      ))}

      {/* Building envelope */}
      <rect
        x={baseX}
        y={baseY - totalHPx}
        width={spanPx}
        height={totalHPx}
        fill={mode === "facade" ? "#f1f5f9" : "#e2e8f0"}
        stroke="#334155"
        strokeWidth={1.5}
      />

      {/* Story lines */}
      {levelLines.map((lvl, i) => (
        <g key={i}>
          <line x1={baseX} y1={lvl.y} x2={baseX + spanPx} y2={lvl.y} stroke="#64748b" strokeWidth={0.8} strokeDasharray="3 2" />
          <text x={baseX - 8} y={lvl.y + 4} textAnchor="end" fontSize={10} fill="#334155" fontWeight={600}>
            {lvl.label}
          </text>
        </g>
      ))}

      {/* Facade-specific: window openings */}
      {mode === "facade" && niveaux.map((niv, ni) => {
        const openings = niv.cellules
          .flatMap((c) => c.openings ?? [])
          .filter((o) => o.type === "fenetre" || o.type === "porte_fenetre" || o.type === "baie_coulissante")
          .slice(0, 6);
        if (openings.length === 0) return null;
        const y0 = levelLines[ni]?.y ?? baseY;
        const storyH = (ni === 0 ? env.hauteur_rdc_m : env.hauteur_etage_courant_m) * scale;
        return (
          <g key={ni}>
            {openings.map((op, i) => {
              const w = Math.min(spanPx * 0.12, (op.width_cm / 100) * scale);
              const h = Math.min(storyH * 0.6, (op.height_cm / 100) * scale);
              const xgap = spanPx / (openings.length + 1);
              const x = baseX + xgap * (i + 1) - w / 2;
              const y = y0 + (storyH - h) / 2;
              return (
                <rect
                  key={op.id ?? i}
                  x={x}
                  y={y}
                  width={w}
                  height={h}
                  fill="#bae6fd"
                  stroke="#0369a1"
                  strokeWidth={0.8}
                />
              );
            })}
          </g>
        );
      })}

      {/* Height annotations (coupe mode) */}
      {mode === "coupe" && (
        <g>
          <line x1={baseX + spanPx + 16} y1={baseY} x2={baseX + spanPx + 16} y2={baseY - totalHPx} stroke="#334155" strokeWidth={1} />
          <polygon points={`${baseX + spanPx + 16},${baseY} ${baseX + spanPx + 12},${baseY - 6} ${baseX + spanPx + 20},${baseY - 6}`} fill="#334155" />
          <polygon points={`${baseX + spanPx + 16},${baseY - totalHPx} ${baseX + spanPx + 12},${baseY - totalHPx + 6} ${baseX + spanPx + 20},${baseY - totalHPx + 6}`} fill="#334155" />
          <text x={baseX + spanPx + 24} y={baseY - totalHPx / 2} fontSize={11} fill="#334155" fontWeight={600}>
            {env.hauteur_totale_m} m
          </text>
        </g>
      )}

      {/* Title */}
      <text x={padding.left} y={20} fontSize={11} fontWeight={600} fill="#334155">
        {mode === "coupe" ? "Coupe longitudinale" : "Façade principale"}
      </text>
      <text x={padding.left} y={height - 14} fontSize={10} fill="#64748b">
        {env.niveaux} niveaux · R+{env.niveaux - 1} · hauteur {env.hauteur_totale_m} m
      </text>
    </svg>
  );
}
