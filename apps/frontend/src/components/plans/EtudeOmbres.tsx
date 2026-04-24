"use client";

import { useMemo, useState } from "react";
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
  const footprint = useMemo(() => coordsFromGeoJSON(bm.envelope?.footprint_geojson), [bm]);
  const parcelle = useMemo(() => coordsFromGeoJSON(bm.site?.parcelle_geojson), [bm]);

  const currentSeason = SEASONS.find((s) => s.key === season) ?? SEASONS[1];
  const h = bm.envelope.hauteur_totale_m;

  const shadows = useMemo(() => {
    return HOURS.map((hr) => {
      const { azDeg, elDeg } = solarAzElDeg(latitudeDeg, currentSeason.declinDeg, hr);
      return { hour: hr, azDeg, elDeg, polygon: shadowPolygon(footprint, h, azDeg, elDeg) };
    });
  }, [footprint, h, latitudeDeg, currentSeason.declinDeg]);

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

  // Palette for shadows per hour — thermochromic feel
  const HOUR_PALETTE: Record<number, { fill: string; stroke: string }> = {
    9:  { fill: "#1e3a8a", stroke: "#1e3a8a" },
    11: { fill: "#6b21a8", stroke: "#6b21a8" },
    13: { fill: "#b45309", stroke: "#b45309" },
    15: { fill: "#be185d", stroke: "#be185d" },
    17: { fill: "#4c1d95", stroke: "#4c1d95" },
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between bg-white border border-slate-200 rounded-xl px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Étude d&apos;ombres solaires</h2>
          <p className="text-xs text-slate-400">
            Latitude {latitudeDeg.toFixed(3)}° · bâtiment R+{bm.envelope.niveaux - 1}, {h} m ·{" "}
            heure solaire locale (non DST)
          </p>
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
          </text>
          <text x={30} y={56} fontSize={10.5} fill="#475569">
            Ombres portées au sol chaque 2 h — hauteur bâtiment {h} m
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

        {/* Shadows: painted darker where they overlap */}
        {shadows.map((s) =>
          s.polygon.length >= 3 ? (
            <path
              key={s.hour}
              d={ringPath(s.polygon)}
              fill={HOUR_PALETTE[s.hour].fill}
              opacity={0.14}
              stroke={HOUR_PALETTE[s.hour].stroke}
              strokeWidth={0.7}
              strokeOpacity={0.6}
            />
          ) : null,
        )}

        {/* Building pseudo-3D: bottom layer (footprint) + 4-5 extrusion offsets */}
        {(() => {
          const steps = 5;
          const layers: React.ReactNode[] = [];
          for (let i = steps; i >= 0; i--) {
            const dx = (isoDx * i) / steps;
            const dy = (isoDy * i) / steps;
            const shade = i === steps
              ? "#f5f5f4"  // top light
              : i === 0 ? "#3a3a3a" : `rgba(80, 80, 85, ${0.7 - i * 0.1})`;
            layers.push(
              <path
                key={`layer-${i}`}
                d={ringPath(footprint)}
                fill={i === steps ? "#fafaf9" : i === 0 ? "#2a2a2a" : "#4a4a4c"}
                opacity={i === steps ? 1 : 0.85}
                stroke="#1c1917"
                strokeWidth={i === 0 || i === steps ? 1.2 : 0.4}
                transform={`translate(${dx}, ${dy})`}
              />,
            );
            // Silent unused var
            void shade;
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
          // Tip = farthest point from footprint centroid
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
          const tone = HOUR_PALETTE[s.hour];
          return (
            <g key={`lbl-${s.hour}`}>
              <circle cx={lx} cy={ly} r={11} fill="white" stroke={tone.stroke} strokeWidth={1.3} />
              <text x={lx} y={ly + 3} textAnchor="middle" fontSize={9} fontWeight={800} fill={tone.stroke}>
                {s.hour}h
              </text>
            </g>
          );
        })}

        {/* Legend */}
        <g transform={`translate(${width - 200}, ${110})`}>
          <rect x={0} y={0} width={180} height={shadows.length * 18 + 28} fill="white" stroke="#0f172a" strokeWidth={0.6} rx={3} />
          <text x={12} y={16} fontSize={10} fontWeight={700} fill="#0f172a">Position solaire</text>
          <text x={12} y={28} fontSize={8} fill="#64748b">heure · azimut · élévation</text>
          {shadows.map((s, i) => (
            <g key={s.hour} transform={`translate(12, ${42 + i * 18})`}>
              <circle cx={0} cy={0} r={5.5} fill="white" stroke={HOUR_PALETTE[s.hour].stroke} strokeWidth={1.1} />
              <text x={0} y={2.5} fontSize={7.5} fontWeight={700} fill={HOUR_PALETTE[s.hour].stroke} textAnchor="middle">{s.hour}</text>
              <text x={14} y={2.5} fontSize={8.5} fill="#334155" fontFamily="monospace">
                az {s.azDeg.toFixed(0).padStart(3)}°
              </text>
              <text x={85} y={2.5} fontSize={8.5} fill="#334155" fontFamily="monospace">
                el {s.elDeg.toFixed(0).padStart(2)}°
              </text>
            </g>
          ))}
        </g>

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
