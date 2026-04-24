"use client";

import type { BuildingModelPayload } from "@/lib/types";
import { bboxOf, coordsFromGeoJSON, type Coord } from "./plan-utils";

interface PhotomontageRenderProps {
  bm: BuildingModelPayload;
  /** Shot type: PC6 insertion paysagère (close), PC7 contexte proche, PC8 lointain */
  shot: "pc6" | "pc7" | "pc8";
  width?: number;
  height?: number;
  communeName?: string;
  address?: string;
}

/**
 * Photomontage généré sans photo réelle — composition SVG d'une scène urbaine
 * avec mise en insertion du projet. Sert de rendu avant photoshoot officiel :
 * montre l'intention volumétrique + traitement matériaux dans un contexte
 * crédible (voirie, trottoir, bâti voisin, ciel, végétation).
 *
 * Les trois variantes PC6/PC7/PC8 diffèrent par :
 *   - Distance caméra / champ de vue
 *   - Densité de contexte (voisins + mobilier urbain)
 *   - Proportion ciel / bâti
 */
export function PhotomontageRender({
  bm, shot, width = 880, height = 500, communeName, address,
}: PhotomontageRenderProps) {
  const footprint = coordsFromGeoJSON(bm.envelope?.footprint_geojson);
  const bb = bboxOf(footprint);
  const H = bm.envelope?.hauteur_totale_m ?? 16;
  const niveaux = bm.envelope?.niveaux ?? 6;
  const atticSetback = 1.2;

  // Shot parameters
  const params = shot === "pc6"
    ? { camDistance: 22, elevAngle: 5, fov: 55, skyRatio: 0.45, neighborDensity: 0.6, title: "PC6 — Insertion paysagère", subtitle: "Vue depuis la voirie, contexte proche" }
    : shot === "pc7"
    ? { camDistance: 40, elevAngle: 8, fov: 45, skyRatio: 0.5, neighborDensity: 0.9, title: "PC7 — Contexte proche", subtitle: "Vue trottoir d'en face, état projeté" }
    : { camDistance: 85, elevAngle: 12, fov: 35, skyRatio: 0.55, neighborDensity: 1.2, title: "PC8 — Contexte lointain", subtitle: "Insertion dans le paysage urbain élargi" };

  if (!bb) {
    return (
      <div className="flex items-center justify-center bg-slate-50 rounded-lg p-10 text-sm text-slate-400 border border-slate-100 h-[300px]">
        Footprint indisponible.
      </div>
    );
  }

  const bldW = bb.maxx - bb.minx;
  const bldD = bb.maxy - bb.miny;
  const groundY = height * params.skyRatio;
  const cx = width / 2;

  // Perspective: the building's base width on screen depends on camDistance
  const pxPerM = (width * 0.4) / Math.max(bldW, bldD) * (20 / params.camDistance);
  const bldWpx = bldW * pxPerM;
  const bldHpx = H * pxPerM;
  const bldDpx = bldD * pxPerM * 0.55;  // 3D foreshortening

  // Building position on ground line
  const bldBaseCx = cx;
  const bldBaseY = groundY + (height - groundY) * 0.45;

  // Window grid on front façade
  const bays = Math.max(4, Math.min(8, Math.round(bldW / 3.8)));

  // Neighbor buildings (stylized)
  const neighbors = [
    { x: cx - bldWpx * 1.3, w: bldWpx * 0.7, h: bldHpx * 0.82, tone: "#e7e0d0" },
    { x: cx - bldWpx * 1.85, w: bldWpx * 0.55, h: bldHpx * 0.68, tone: "#d4ccb9" },
    { x: cx + bldWpx * 0.9, w: bldWpx * 0.65, h: bldHpx * 0.9, tone: "#ede5d0" },
    { x: cx + bldWpx * 1.45, w: bldWpx * 0.8, h: bldHpx * 0.75, tone: "#c9bfa6" },
  ];

  const roadY = bldBaseY + bldDpx + 6;

  return (
    <figure className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-100">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">{params.title}</h3>
          <p className="text-xs text-slate-400">{params.subtitle}</p>
        </div>
        <span className="text-xs font-mono font-bold text-slate-900 bg-slate-100 px-2 py-0.5 rounded">
          {shot.toUpperCase()}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="100%"
        style={{ display: "block", fontFamily: "system-ui, -apple-system, sans-serif" }}
      >
        <defs>
          <linearGradient id={`sky-${shot}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#93c5fd" />
            <stop offset="0.6" stopColor="#cee5f5" />
            <stop offset="1" stopColor="#f0e9d2" />
          </linearGradient>
          <linearGradient id={`sidewalk-${shot}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#c4bdac" />
            <stop offset="1" stopColor="#a69b82" />
          </linearGradient>
          <linearGradient id={`road-${shot}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#3e3e42" />
            <stop offset="1" stopColor="#1a1a1c" />
          </linearGradient>
          <linearGradient id={`wall-sunlit-${shot}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#f3ead6" />
            <stop offset="1" stopColor="#dcd3ba" />
          </linearGradient>
          <linearGradient id={`wall-shade-${shot}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#968b6d" />
            <stop offset="1" stopColor="#6e664d" />
          </linearGradient>
          <linearGradient id={`attic-sunlit-${shot}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#b08d60" />
            <stop offset="1" stopColor="#8a6c44" />
          </linearGradient>
          <radialGradient id={`sun-${shot}`} cx="0.82" cy="0.22" r="0.25">
            <stop offset="0" stopColor="#fef9c3" stopOpacity="0.9" />
            <stop offset="1" stopColor="#fef9c3" stopOpacity="0" />
          </radialGradient>
          <filter id={`grain-${shot}`}>
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="3" />
            <feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.06 0" />
            <feComposite in2="SourceGraphic" operator="in" />
          </filter>
          <pattern id={`clouds-${shot}`} width="200" height="40" patternUnits="userSpaceOnUse">
            <ellipse cx="30" cy="20" rx="24" ry="5" fill="white" opacity="0.6" />
            <ellipse cx="120" cy="12" rx="30" ry="5" fill="white" opacity="0.4" />
          </pattern>
        </defs>

        {/* Sky */}
        <rect x={0} y={0} width={width} height={groundY} fill={`url(#sky-${shot})`} />
        <rect x={0} y={0} width={width} height={groundY * 0.4} fill={`url(#clouds-${shot})`} opacity={0.7} />
        <rect x={0} y={0} width={width} height={height} fill={`url(#sun-${shot})`} />

        {/* Distant tree line on horizon */}
        {shot !== "pc6" && (
          <g opacity={0.6}>
            {Array.from({ length: 18 }).map((_, i) => {
              const tx = (i / 18) * width;
              const th = 8 + Math.sin(i * 1.7) * 4 + 6;
              return (
                <ellipse
                  key={i}
                  cx={tx}
                  cy={groundY - th * 0.3}
                  rx={14}
                  ry={th}
                  fill="#6b7c5f"
                />
              );
            })}
          </g>
        )}

        {/* Neighbor buildings (behind) */}
        {neighbors
          .filter((n) => shot !== "pc6" || Math.abs(n.x - cx) < bldWpx * 1.5)
          .map((n, i) => (
            <g key={i}>
              <rect
                x={n.x - n.w / 2}
                y={groundY + (height - groundY) * 0.5 - n.h}
                width={n.w}
                height={n.h}
                fill={n.tone}
                stroke="#1f1c19"
                strokeWidth={0.6}
              />
              {/* Windows on neighbors (simple dots) */}
              {Array.from({ length: Math.floor(n.h / 20) }).map((_, row) => (
                <g key={row}>
                  {Array.from({ length: Math.floor(n.w / 18) }).map((_, col) => (
                    <rect
                      key={col}
                      x={n.x - n.w / 2 + 6 + col * 18}
                      y={groundY + (height - groundY) * 0.5 - n.h + 8 + row * 20}
                      width={8}
                      height={10}
                      fill="#4a6677"
                      opacity={0.7}
                    />
                  ))}
                </g>
              ))}
              {/* Roof line */}
              <rect
                x={n.x - n.w / 2 - 2}
                y={groundY + (height - groundY) * 0.5 - n.h - 4}
                width={n.w + 4}
                height={4}
                fill="#2d2a27"
              />
            </g>
          ))}

        {/* Road */}
        <rect x={0} y={roadY} width={width} height={height - roadY} fill={`url(#road-${shot})`} />
        {/* Sidewalk strip between ground & road */}
        <rect x={0} y={roadY - 10} width={width} height={10} fill={`url(#sidewalk-${shot})`} />
        {/* Road lane markings */}
        {Array.from({ length: 8 }).map((_, i) => (
          <rect
            key={i}
            x={(i * width) / 8 + 10}
            y={roadY + (height - roadY) * 0.55}
            width={28}
            height={3}
            fill="#f5f5f4"
            opacity={0.85}
          />
        ))}

        {/* ═══ Project building ═══ */}
        {(() => {
          const bx = bldBaseCx - bldWpx / 2;
          const by = bldBaseY - bldHpx;

          // Soubassement
          const soubH = bldHpx * (0.9 / H);
          const atticH = bldHpx * (2.7 / H);
          const atticY = by;
          const mainY = by + atticH;
          const mainH = bldHpx - atticH - soubH;
          const atticSetbackPx = bldWpx * (atticSetback / bldW) * 0.5;

          const winWpx = (bldWpx * 0.9) / bays * 0.55;
          const floors = niveaux - 1;
          const winHpx = (mainH / floors) * 0.7;

          return (
            <g>
              {/* Cast shadow on ground */}
              <ellipse
                cx={bldBaseCx + 30}
                cy={bldBaseY + 5}
                rx={bldWpx / 2 + bldDpx * 0.8}
                ry={bldDpx * 0.35}
                fill="#0f172a"
                opacity={0.35}
              />

              {/* Right side face (shade) — 3D perspective */}
              <polygon
                points={`${bx + bldWpx},${by} ${bx + bldWpx + bldDpx * 0.4},${by - bldDpx * 0.15} ${bx + bldWpx + bldDpx * 0.4},${bldBaseY - bldDpx * 0.15} ${bx + bldWpx},${bldBaseY}`}
                fill={`url(#wall-shade-${shot})`}
                stroke="#1c1917"
                strokeWidth={0.8}
              />
              {/* Top face roof */}
              <polygon
                points={`${bx + atticSetbackPx},${atticY} ${bx + bldWpx - atticSetbackPx},${atticY} ${bx + bldWpx - atticSetbackPx + bldDpx * 0.4},${atticY - bldDpx * 0.15} ${bx + atticSetbackPx + bldDpx * 0.4},${atticY - bldDpx * 0.15}`}
                fill="#d0c8b5"
                stroke="#1c1917"
                strokeWidth={0.8}
              />

              {/* Main wall (front) */}
              <rect x={bx} y={mainY} width={bldWpx} height={mainH} fill={`url(#wall-sunlit-${shot})`} stroke="#1c1917" strokeWidth={0.8} />

              {/* Soubassement */}
              <rect x={bx - 1} y={bldBaseY - soubH} width={bldWpx + 2} height={soubH} fill="#3b3633" stroke="#1c1917" strokeWidth={0.8} />

              {/* Attique bardage bois */}
              <rect x={bx + atticSetbackPx} y={atticY} width={bldWpx - 2 * atticSetbackPx} height={atticH} fill={`url(#attic-sunlit-${shot})`} stroke="#1c1917" strokeWidth={0.6} />
              {/* Wood vertical boards */}
              {Array.from({ length: Math.floor((bldWpx - 2 * atticSetbackPx) / 5) }).map((_, i) => (
                <line
                  key={i}
                  x1={bx + atticSetbackPx + i * 5}
                  y1={atticY}
                  x2={bx + atticSetbackPx + i * 5}
                  y2={atticY + atticH}
                  stroke="#6f5636"
                  strokeWidth={0.3}
                  opacity={0.6}
                />
              ))}

              {/* Windows grid on main wall */}
              {Array.from({ length: floors }).map((_, f) => {
                const fy = mainY + (f / floors) * mainH + (mainH / floors - winHpx) / 2;
                return (
                  <g key={f}>
                    {Array.from({ length: bays }).map((_, c) => {
                      const wx = bx + ((c + 0.5) / bays) * bldWpx - winWpx / 2;
                      const entryBay = c === Math.floor(bays / 2) && f === 0;
                      if (entryBay) {
                        const doorH = mainH / floors * 0.85;
                        const doorW = winWpx * 1.3;
                        const dx = bx + ((c + 0.5) / bays) * bldWpx - doorW / 2;
                        const dy = mainY + mainH - doorH;
                        return (
                          <g key={c}>
                            {/* Auvent bois */}
                            <rect x={dx - 10} y={dy - 8} width={doorW + 20} height={4} fill="#9c7d57" stroke="#6f5636" strokeWidth={0.4} />
                            {/* Porte vitrée */}
                            <rect x={dx} y={dy} width={doorW} height={doorH} fill="#6fa0b5" stroke="#0a0a0a" strokeWidth={1.1} />
                            <line x1={dx + doorW / 2} y1={dy} x2={dx + doorW / 2} y2={dy + doorH} stroke="#0a0a0a" strokeWidth={0.9} />
                          </g>
                        );
                      }
                      return (
                        <g key={c}>
                          <rect x={wx - 0.6} y={fy - 0.6} width={winWpx + 1.2} height={winHpx + 1.2} fill="#0a0a0a" />
                          <rect x={wx} y={fy} width={winWpx} height={winHpx} fill="#82b0c5" />
                          <rect x={wx + 1} y={fy + 1} width={winWpx * 0.45} height={winHpx * 0.6} fill="#dceef5" opacity={0.6} />
                          <line x1={wx + winWpx / 2} y1={fy} x2={wx + winWpx / 2} y2={fy + winHpx} stroke="#0a0a0a" strokeWidth={0.6} />
                        </g>
                      );
                    })}
                    {/* Balcony filant at upper floors */}
                    {f > 0 && (
                      <g>
                        <rect x={bx + 4} y={fy + winHpx + 2} width={bldWpx - 8} height={2.5} fill="#3b3633" />
                        <rect x={bx + 4} y={fy + winHpx + 4.5} width={bldWpx - 8} height={6} fill="#b9dce9" opacity={0.35} />
                        <rect x={bx + 4} y={fy + winHpx + 4.5} width={bldWpx - 8} height={6} fill="none" stroke="#111" strokeWidth={0.5} />
                      </g>
                    )}
                  </g>
                );
              })}

              {/* Parapet */}
              <rect x={bx + atticSetbackPx - 2} y={atticY - 3} width={bldWpx - 2 * atticSetbackPx + 4} height={3} fill="#d0c8b5" stroke="#0a0a0a" strokeWidth={0.5} />
            </g>
          );
        })()}

        {/* Foreground elements — tree + lamppost + person/car for scale */}
        {shot !== "pc8" && (
          <g>
            {/* Lamppost left */}
            <line x1={cx - bldWpx * 0.85} y1={roadY - 10} x2={cx - bldWpx * 0.85} y2={roadY - 60} stroke="#1a1a1a" strokeWidth={1.8} />
            <rect x={cx - bldWpx * 0.85 - 6} y={roadY - 68} width={12} height={10} fill="#1a1a1a" />
            {/* Car in foreground right */}
            <g transform={`translate(${cx + bldWpx * 0.7}, ${height - 40})`}>
              <rect x={-28} y={-10} width={56} height={16} rx={3} fill="#4a6b82" stroke="#1a1a1a" strokeWidth={0.6} />
              <rect x={-18} y={-18} width={36} height={10} rx={2} fill="#4a6b82" stroke="#1a1a1a" strokeWidth={0.6} />
              <circle cx={-16} cy={8} r={4} fill="#1a1a1a" />
              <circle cx={16} cy={8} r={4} fill="#1a1a1a" />
              <rect x={-14} y={-16} width={13} height={7} fill="#cee5f5" opacity={0.8} />
              <rect x={1} y={-16} width={13} height={7} fill="#cee5f5" opacity={0.8} />
            </g>
            {/* Person silhouette for scale */}
            <g transform={`translate(${cx - bldWpx * 0.35}, ${height - 48})`}>
              <circle cx={0} cy={-26} r={3.5} fill="#4a4542" />
              <rect x={-3} y={-22} width={6} height={14} fill="#4a4542" />
              <rect x={-4} y={-8} width={8} height={12} fill="#2e2a28" />
            </g>
          </g>
        )}

        {/* Foreground tree (left) */}
        <g transform={`translate(${30}, ${height - 80})`}>
          <line x1={0} y1={0} x2={0} y2={60} stroke="#3e2d1a" strokeWidth={4} />
          <ellipse cx={0} cy={-5} rx={30} ry={35} fill="#5c7a4e" />
          <ellipse cx={-12} cy={-18} rx={18} ry={22} fill="#6e8f5d" />
          <ellipse cx={10} cy={-25} rx={14} ry={18} fill="#6e8f5d" />
        </g>

        {/* Grain overlay */}
        <rect x={0} y={0} width={width} height={height} filter={`url(#grain-${shot})`} />

        {/* Vignette */}
        <radialGradient id={`vignette-${shot}`} cx="0.5" cy="0.5" r="0.7">
          <stop offset="0.6" stopColor="#000" stopOpacity={0} />
          <stop offset="1" stopColor="#000" stopOpacity={0.4} />
        </radialGradient>
        <rect x={0} y={0} width={width} height={height} fill={`url(#vignette-${shot})`} />

        {/* Cartouche PC6/7/8 bottom-right */}
        <g transform={`translate(${width - 170}, ${height - 48})`}>
          <rect x={0} y={0} width={150} height={38} fill="white" opacity={0.92} stroke="#0f172a" strokeWidth={0.6} rx={2} />
          <text x={10} y={14} fontSize={9.5} fontWeight={700} fill="#0f172a">
            {params.title}
          </text>
          <text x={10} y={26} fontSize={8} fill="#64748b">
            {communeName ?? "Commune"} · {address?.slice(0, 24) ?? "—"}
          </text>
          <rect x={110} y={8} width={32} height={22} fill="#0f172a" rx={2} />
          <text x={126} y={23} fontSize={10} fontWeight={800} fill="white" textAnchor="middle">
            {shot.toUpperCase()}
          </text>
        </g>
      </svg>
    </figure>
  );
}
