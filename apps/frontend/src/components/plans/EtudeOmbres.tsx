"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { BuildingModelPayload } from "@/lib/types";
import { bboxOf, coordsFromGeoJSON, type Coord } from "./plan-utils";
import { PlanPatterns, NorthArrow, TitleBlock } from "./plan-patterns";

interface EtudeOmbresProps {
  bm: BuildingModelPayload;
  latitudeDeg?: number;
  width?: number;
  height?: number;
}

type Season = "hiver" | "equinoxe" | "ete";
const SEASONS: Array<{ key: Season; label: string; date: string; declinDeg: number }> = [
  { key: "hiver", label: "Solstice d'hiver — 21 déc.", date: "12-21", declinDeg: -23.44 },
  { key: "equinoxe", label: "Équinoxe — 21 mars", date: "03-21", declinDeg: 0 },
  { key: "ete", label: "Solstice d'été — 21 juin", date: "06-21", declinDeg: 23.44 },
];

const HOURS = [9, 11, 13, 15, 17] as const;

function solarAzElDeg(latDeg: number, declDeg: number, hourLocal: number) {
  const lat = (latDeg * Math.PI) / 180;
  const decl = (declDeg * Math.PI) / 180;
  const H = ((hourLocal - 12) * 15 * Math.PI) / 180;
  const sinEl = Math.sin(lat) * Math.sin(decl) + Math.cos(lat) * Math.cos(decl) * Math.cos(H);
  const el = Math.asin(Math.max(-1, Math.min(1, sinEl)));
  const cosEl = Math.cos(el);
  let az = 0;
  if (cosEl > 1e-6) {
    const sinAz = (-Math.cos(decl) * Math.sin(H)) / cosEl;
    const cosAz = (Math.sin(decl) - Math.sin(lat) * sinEl) / (Math.cos(lat) * cosEl);
    az = Math.atan2(sinAz, cosAz);
  }
  if (az < 0) az += 2 * Math.PI;
  return { azDeg: (az * 180) / Math.PI, elDeg: (el * 180) / Math.PI };
}

function cross(o: Coord, a: Coord, b: Coord) {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}
function convexHull(points: Coord[]): Coord[] {
  if (points.length < 3) return points.slice();
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
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

function shadowPolygon(footprint: Coord[], h: number, azDeg: number, elDeg: number): Coord[] {
  if (elDeg <= 3) return [];
  const az = (azDeg * Math.PI) / 180;
  const el = (elDeg * Math.PI) / 180;
  const L = Math.min(h / Math.tan(el), h * 4);
  const dx = Math.sin(az + Math.PI) * L;
  const dy = Math.cos(az + Math.PI) * L;
  const translated: Coord[] = footprint.map((c) => [c[0] + dx, c[1] + dy]);
  return convexHull([...footprint, ...translated]);
}

/**
 * Étude d'ombres — vue plan avec bâtiment en 3D iso + ombres portées
 * chromatiques par heure. Palette saisonnière + légende solaire complète.
 * Rendu plus proche d'une carte d'étude solaire architecturale réelle.
 */
export function EtudeOmbres({
  bm, latitudeDeg = 48.85, width = 900, height = 620,
}: EtudeOmbresProps) {
  const [season, setSeason] = useState<Season>("equinoxe");
  // Mode "static" = 5 ombres fixes (vue d'ensemble par défaut)
  // Mode "interactive" = 1 ombre dynamique au curseur (simulation heure par heure)
  const [mode, setMode] = useState<"static" | "interactive">("static");
  const [currentHour, setCurrentHour] = useState(13);
  const [playing, setPlaying] = useState(false);
  const playRef = useRef<number | null>(null);

  const footprint = useMemo(() => coordsFromGeoJSON(bm.envelope?.footprint_geojson), [bm]);
  const parcelle = useMemo(() => coordsFromGeoJSON(bm.site?.parcelle_geojson), [bm]);

  const currentSeason = SEASONS.find((s) => s.key === season) ?? SEASONS[1];
  const h = bm.envelope.hauteur_totale_m;

  // Animation : avance currentHour de 0.25h (15min) toutes les 80ms.
  useEffect(() => {
    if (!playing || mode !== "interactive") return;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = now - last;
      if (dt > 80) {
        last = now;
        setCurrentHour((h) => {
          const next = h + 0.25;
          return next > 21 ? 5 : next;
        });
      }
      playRef.current = requestAnimationFrame(tick);
    };
    playRef.current = requestAnimationFrame(tick);
    return () => {
      if (playRef.current !== null) cancelAnimationFrame(playRef.current);
    };
  }, [playing, mode]);

  const shadows = useMemo(() => {
    if (mode === "interactive") {
      const { azDeg, elDeg } = solarAzElDeg(latitudeDeg, currentSeason.declinDeg, currentHour);
      return [{ hour: currentHour, azDeg, elDeg, polygon: shadowPolygon(footprint, h, azDeg, elDeg) }];
    }
    return HOURS.map((hr) => {
      const { azDeg, elDeg } = solarAzElDeg(latitudeDeg, currentSeason.declinDeg, hr);
      return { hour: hr, azDeg, elDeg, polygon: shadowPolygon(footprint, h, azDeg, elDeg) };
    });
  }, [footprint, h, latitudeDeg, currentSeason.declinDeg, mode, currentHour]);

  // Live solar position (toujours calculé pour l'affichage, même en mode static)
  const liveSolar = useMemo(() => {
    return solarAzElDeg(latitudeDeg, currentSeason.declinDeg, currentHour);
  }, [latitudeDeg, currentSeason.declinDeg, currentHour]);
  const fmtHour = (h: number) => {
    const hh = Math.floor(h);
    const mm = Math.round((h - hh) * 60);
    return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  };

  if (footprint.length < 3 || !bm.envelope) {
    return (
      <div className="rounded-lg bg-slate-50 p-8 text-sm text-slate-400 text-center">
        Footprint bâtiment indisponible.
      </div>
    );
  }

  const bb = bboxOf([
    ...footprint, ...parcelle,
    ...shadows.flatMap((s) => s.polygon),
  ])!;
  const expand = 0.08;
  const box = {
    minx: bb.minx - (bb.maxx - bb.minx) * expand,
    miny: bb.miny - (bb.maxy - bb.miny) * expand,
    maxx: bb.maxx + (bb.maxx - bb.minx) * expand,
    maxy: bb.maxy + (bb.maxy - bb.miny) * expand,
  };
  const innerW = width - 80;
  const innerH = height - 150;
  const scale = Math.min(innerW / (box.maxx - box.minx), innerH / (box.maxy - box.miny));
  // SVG y-axis is flipped (world y → south = high SVG y)
  const proj = (c: Coord): [number, number] => [
    (c[0] - box.minx) * scale + 40,
    height - ((c[1] - box.miny) * scale + 60),
  ];
  const ringPath = (coords: Coord[]): string => {
    if (!coords.length) return "";
    const pts = coords.map(proj);
    return `M ${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ")} Z`;
  };

  // Isometric-ish building projected at its footprint location — we draw a
  // "faux 3D" silhouette by adding a small up-right offset per floor.
  const isoDx = -Math.min(16, scale * 0.4);
  const isoDy = -Math.min(16, scale * 0.4);

  // Palette for shadows per hour — thermochromic feel.
  // Pour le mode interactive, on calcule la couleur dynamiquement via interpolation HSL.
  const HOUR_PALETTE: Record<number, { fill: string; stroke: string }> = {
    9:  { fill: "#1e3a8a", stroke: "#1e3a8a" },
    11: { fill: "#6b21a8", stroke: "#6b21a8" },
    13: { fill: "#b45309", stroke: "#b45309" },
    15: { fill: "#be185d", stroke: "#be185d" },
    17: { fill: "#4c1d95", stroke: "#4c1d95" },
  };
  /** Couleur ombre dynamique : conserve l'aspect "ombre" (dark + cool) tout
      en variant légèrement selon l'heure (bleu froid matin → violet soir). */
  const colorForHour = (hr: number): string => {
    // Hue subtil : matin 220° (bleu froid) → midi 260° (violet) → soir 285°
    const t = Math.max(0, Math.min(1, (hr - 5) / 16));  // 0 at 5h, 1 at 21h
    const hue = 220 + t * 65;
    return `hsl(${hue.toFixed(0)}, 55%, 22%)`;
  };
  const interactiveColor = mode === "interactive" ? colorForHour(currentHour) : "";

  return (
    <div className="space-y-3">
      <div className="bg-white border border-slate-200 rounded-xl px-5 py-3 space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Étude d&apos;ombres solaires</h2>
            <p className="text-xs text-slate-400">
              Latitude {latitudeDeg.toFixed(3)}° · bâtiment R+{bm.envelope.niveaux - 1}, {h} m ·{" "}
              heure solaire locale (non DST)
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Mode toggle : Statique (5 ombres) vs Interactive (slider) */}
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
              <button
                type="button"
                onClick={() => { setMode("static"); setPlaying(false); }}
                className={`text-xs px-3 py-1.5 rounded-md font-medium transition-colors ${
                  mode === "static" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                5 ombres
              </button>
              <button
                type="button"
                onClick={() => setMode("interactive")}
                className={`text-xs px-3 py-1.5 rounded-md font-medium transition-colors ${
                  mode === "interactive" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Simulateur
              </button>
            </div>
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
              {SEASONS.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setSeason(s.key)}
                  className={`text-xs px-3 py-1.5 rounded-md font-medium transition-colors ${
                    s.key === season ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Slider luminosité — visible uniquement en mode interactive */}
        {mode === "interactive" && (
          <div className="flex items-center gap-4 pt-1">
            {/* Bouton play/pause */}
            <button
              type="button"
              onClick={() => setPlaying((p) => !p)}
              className="flex-shrink-0 w-9 h-9 rounded-full bg-slate-900 text-white text-base flex items-center justify-center hover:bg-slate-700 transition-colors shadow-sm"
              title={playing ? "Pause" : "Animer la journée"}
            >
              {playing ? "⏸" : "▶"}
            </button>
            {/* Slider 5h → 21h, step 0.25 (15 min) */}
            <div className="flex-1 flex items-center gap-3">
              <span className="text-xs font-mono text-slate-500 w-10">05:00</span>
              <input
                type="range"
                min={5}
                max={21}
                step={0.25}
                value={currentHour}
                onChange={(e) => setCurrentHour(parseFloat(e.target.value))}
                className="flex-1 h-2 bg-gradient-to-r from-indigo-900 via-amber-300 to-purple-900 rounded-full appearance-none cursor-pointer accent-slate-900"
                style={{
                  background: `linear-gradient(to right, hsl(240,65%,35%) 0%, hsl(45,80%,55%) 44%, hsl(290,65%,35%) 100%)`,
                }}
              />
              <span className="text-xs font-mono text-slate-500 w-10">21:00</span>
            </div>
            {/* Indicateur live */}
            <div className="flex-shrink-0 inline-flex items-center gap-3 bg-slate-900 text-white px-3 py-1.5 rounded-lg">
              <span className="text-base font-mono font-semibold">{fmtHour(currentHour)}</span>
              <span className="text-xs font-mono text-slate-300">
                Az <span className="text-white font-semibold">{liveSolar.azDeg.toFixed(0)}°</span>
                {" · "}
                El <span className="text-white font-semibold">{liveSolar.elDeg.toFixed(0)}°</span>
              </span>
              {liveSolar.elDeg <= 0 && (
                <span className="text-xs bg-slate-700 px-1.5 py-0.5 rounded">🌙 Nuit</span>
              )}
            </div>
          </div>
        )}
      </div>

      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="bg-white border border-slate-200 rounded-xl"
        style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
      >
        <PlanPatterns />
        <defs>
          <linearGradient id="om-ground" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#f0f4f8" />
            <stop offset="1" stopColor="#e0e6ee" />
          </linearGradient>
          <radialGradient id="om-sunlight" cx="0.5" cy="0.5" r="0.7">
            <stop offset="0" stopColor="#fef9c3" stopOpacity={0.5} />
            <stop offset="1" stopColor="#fef9c3" stopOpacity={0} />
          </radialGradient>
        </defs>

        {/* Ground */}
        <rect x={0} y={0} width={width} height={height} fill="url(#om-ground)" />
        {/* Sunlight ambient glow */}
        <rect x={0} y={0} width={width} height={height} fill="url(#om-sunlight)" />

        {/* Header */}
        <g>
          <rect x={20} y={20} width={width - 40} height={44} fill="white" stroke="#0f172a" strokeWidth={0.6} />
          <text x={30} y={40} fontSize={15} fontWeight={700} fill="#0f172a">
            Étude d&apos;ombres — {currentSeason.label}
            {mode === "interactive" && ` · ${fmtHour(currentHour)}`}
          </text>
          <text x={30} y={56} fontSize={10.5} fill="#475569">
            {mode === "interactive"
              ? `Position solaire : Az ${liveSolar.azDeg.toFixed(0)}° / El ${liveSolar.elDeg.toFixed(0)}° · hauteur bâtiment ${h} m`
              : `Ombres portées au sol chaque 2 h — hauteur bâtiment ${h} m`}
          </text>
        </g>

        {/* Parcelle outline (dashed) */}
        {parcelle.length >= 3 && (
          <path
            d={ringPath(parcelle)}
            fill="white"
            fillOpacity={0.35}
            stroke="#94a3b8"
            strokeWidth={0.9}
            strokeDasharray="5 3"
          />
        )}

        {/* Shadows : 5 strates avec opacité 0.14 en mode static, 1 ombre
            forte en mode interactive (opacité 0.35 + stroke épais). */}
        {shadows.map((s) => {
          if (s.polygon.length < 3) return null;
          const color = mode === "interactive" ? interactiveColor : (HOUR_PALETTE[s.hour]?.fill ?? "#475569");
          return (
            <path
              key={s.hour}
              d={ringPath(s.polygon)}
              fill={color}
              opacity={mode === "interactive" ? 0.40 : 0.14}
              stroke={color}
              strokeWidth={mode === "interactive" ? 1.4 : 0.7}
              strokeOpacity={mode === "interactive" ? 0.85 : 0.6}
            />
          );
        })}

        {/* Building pseudo-3D — empilage par tranche avec teintes matériaux
            cohérentes avec les façades (étages enduit clair / attic bardage
            bois / parapet acrotère sombre). Donne le rappel visuel du vrai
            bâtiment dans l'étude d'ombres. */}
        {(() => {
          const steps = 8;
          const layers: React.ReactNode[] = [];
          // Index z-band per layer step
          // i=0 = ground line (darkest)
          // i=1..3 = étages courants enduit clair
          // i=4..5 = attic bardage bois
          // i=6..steps = parapet acrotère sombre + couvertine
          const fillFor = (i: number): string => {
            if (i === 0) return "#2a2a2a";        // ground line
            if (i <= 3) return "#ece7db";         // enduit clair
            if (i <= 5) return "#a07956";         // bardage bois attic
            if (i === steps) return "#1f1d19";    // couvertine
            return "#5e4429";                     // parapet ombre
          };
          for (let i = steps; i >= 0; i--) {
            const dx = (isoDx * i) / steps;
            const dy = (isoDy * i) / steps;
            layers.push(
              <path
                key={`layer-${i}`}
                d={ringPath(footprint)}
                fill={fillFor(i)}
                opacity={i === 0 ? 0.95 : 0.92}
                stroke="#1c1917"
                strokeWidth={i === 0 || i === steps || i === 3 || i === 5 ? 1.2 : 0.4}
                transform={`translate(${dx}, ${dy})`}
              />,
            );
          }
          return layers;
        })()}

        {/* Top roof flat with a subtle grid overlay */}
        <path
          d={ringPath(footprint)}
          fill="url(#pat-lawn)"
          opacity={0}
          transform={`translate(${isoDx}, ${isoDy})`}
        />

        {/* Hour labels on shadow tips (outside footprint) */}
        {shadows.map((s) => {
          if (s.polygon.length < 3 || s.elDeg <= 0) return null;
          const fBB = bboxOf(footprint)!;
          const fcx = (fBB.minx + fBB.maxx) / 2;
          const fcy = (fBB.miny + fBB.maxy) / 2;
          let best = s.polygon[0];
          let bestDist = 0;
          for (const p of s.polygon) {
            const d = (p[0] - fcx) ** 2 + (p[1] - fcy) ** 2;
            if (d > bestDist) { bestDist = d; best = p; }
          }
          const [lx, ly] = proj(best);
          const tone = mode === "interactive"
            ? { stroke: interactiveColor }
            : (HOUR_PALETTE[s.hour] ?? { stroke: "#475569" });
          const label = mode === "interactive" ? fmtHour(s.hour) : `${s.hour}h`;
          return (
            <g key={`lbl-${s.hour}`}>
              <circle cx={lx} cy={ly} r={mode === "interactive" ? 16 : 11} fill="white" stroke={tone.stroke} strokeWidth={1.5} />
              <text x={lx} y={ly + 3} textAnchor="middle" fontSize={mode === "interactive" ? 8.5 : 9} fontWeight={800} fill={tone.stroke}>
                {label}
              </text>
            </g>
          );
        })}

        {/* Legend — masquée en mode interactive (info déjà dans le pill HUD) */}
        {mode === "static" && (
          <g transform={`translate(${width - 200}, ${110})`}>
            <rect x={0} y={0} width={180} height={shadows.length * 18 + 28} fill="white" stroke="#0f172a" strokeWidth={0.6} rx={3} />
            <text x={12} y={16} fontSize={10} fontWeight={700} fill="#0f172a">Position solaire</text>
            <text x={12} y={28} fontSize={8} fill="#64748b">heure · azimut · élévation</text>
            {shadows.map((s, i) => (
              <g key={s.hour} transform={`translate(12, ${42 + i * 18})`}>
                <circle cx={0} cy={0} r={5.5} fill="white" stroke={HOUR_PALETTE[s.hour]?.stroke ?? "#475569"} strokeWidth={1.1} />
                <text x={0} y={2.5} fontSize={7.5} fontWeight={700} fill={HOUR_PALETTE[s.hour]?.stroke ?? "#475569"} textAnchor="middle">{s.hour}</text>
                <text x={14} y={2.5} fontSize={8.5} fill="#334155" fontFamily="monospace">
                  az {s.azDeg.toFixed(0).padStart(3)}°
                </text>
                <text x={85} y={2.5} fontSize={8.5} fill="#334155" fontFamily="monospace">
                  el {s.elDeg.toFixed(0).padStart(2)}°
                </text>
              </g>
            ))}
          </g>
        )}

        <NorthArrow x={width - 50} y={height - 52} size={34} rotationDeg={bm.site.north_angle_deg ?? 0} />
        <TitleBlock
          x={40}
          y={height - 62}
          title="Étude d'ombres"
          subtitle={`${currentSeason.date} · DP-OM-01`}
          sheetCode="PC-OM"
        />
      </svg>
    </div>
  );
}
