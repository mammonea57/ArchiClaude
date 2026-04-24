"use client";

import { useEffect, useMemo, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

interface Parcelle {
  geometry: GeoJSON.Geometry;
  numero?: string;
  section?: string;
  contenance_m2?: number;
}

interface PlanSituationMapProps {
  parcelles: Parcelle[];
  center: [number, number]; // [lng, lat]
  zoom: number;
  tilesLayer: "ortho" | "plan";
  /** Label shown in the cartouche (PC1 sheet reference). */
  sheetCode: string;
  /** Scale text (e.g., "1:5 000"). */
  scaleLabel: string;
  /** Render a line-scale bar for this many meters. */
  scaleBarM?: number;
  height?: number;
  title: string;
  subtitle?: string;
}

const IGN_ORTHO =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg";

const IGN_PLAN =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png";

/**
 * Non-interactive PC1-style situation map. Renders IGN ortho OR plan tiles
 * at a fixed zoom, with the project's parcelles highlighted and a cartouche
 * overlay conforming to PC1 conventions (sheet code, scale, north arrow).
 */
function PlanSituationMap({
  parcelles, center, zoom, tilesLayer,
  sheetCode, scaleLabel, scaleBarM = 100,
  height = 340, title, subtitle,
}: PlanSituationMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const tileUrl = tilesLayer === "ortho" ? IGN_ORTHO : IGN_PLAN;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          ign: { type: "raster", tiles: [tileUrl], tileSize: 256, attribution: "© IGN" },
        },
        layers: [{ id: "ign-layer", type: "raster", source: "ign" }],
      },
      center,
      zoom,
      interactive: false,
      attributionControl: false,
    });

    map.on("load", () => {
      if (parcelles.length === 0) return;
      map.addSource("parcelles", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: parcelles.map((p) => ({
            type: "Feature",
            geometry: p.geometry,
            properties: {
              label: p.numero ?? "",
            },
          })),
        },
      });
      map.addLayer({
        id: "parcelles-fill",
        type: "fill",
        source: "parcelles",
        paint: { "fill-color": "#dc2626", "fill-opacity": 0.18 },
      });
      map.addLayer({
        id: "parcelles-stroke",
        type: "line",
        source: "parcelles",
        paint: {
          "line-color": "#dc2626",
          "line-width": 2,
          "line-dasharray": [3, 2],
        },
      });
    });

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Meters per pixel at target lat & zoom, to size the scale bar accurately.
  const scaleBarPx = useMemo(() => {
    const latRad = (center[1] * Math.PI) / 180;
    const metersPerPx = (156543.03 * Math.cos(latRad)) / 2 ** zoom;
    return scaleBarM / metersPerPx;
  }, [center, zoom, scaleBarM]);

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
          {subtitle && <p className="text-xs text-slate-400">{subtitle}</p>}
        </div>
        <span className="text-xs font-mono text-slate-500">{scaleLabel}</span>
      </div>
      <div className="relative">
        <div ref={containerRef} style={{ width: "100%", height }} />

        {/* Crosshair marker at project center */}
        <div
          className="absolute pointer-events-none"
          style={{
            left: "50%",
            top: "50%",
            transform: "translate(-50%, -50%)",
          }}
        >
          <svg width={36} height={36} viewBox="0 0 36 36">
            <circle cx={18} cy={18} r={12} fill="none" stroke="#dc2626" strokeWidth={1.8} />
            <line x1={18} y1={4} x2={18} y2={14} stroke="#dc2626" strokeWidth={1.8} />
            <line x1={18} y1={22} x2={18} y2={32} stroke="#dc2626" strokeWidth={1.8} />
            <line x1={4} y1={18} x2={14} y2={18} stroke="#dc2626" strokeWidth={1.8} />
            <line x1={22} y1={18} x2={32} y2={18} stroke="#dc2626" strokeWidth={1.8} />
            <circle cx={18} cy={18} r={2} fill="#dc2626" />
          </svg>
        </div>

        {/* North arrow — top-right overlay */}
        <div className="absolute top-3 right-3 bg-white/95 rounded-md border border-slate-200 p-1.5 shadow-sm">
          <svg width={32} height={32} viewBox="0 0 32 32">
            <circle cx={16} cy={16} r={14} fill="white" stroke="#334155" strokeWidth={0.6} />
            <polygon points="16,3 20,16 16,14 12,16" fill="#0f172a" />
            <polygon points="16,29 20,16 16,18 12,16" fill="#e5e7eb" stroke="#334155" strokeWidth={0.4} />
            <text x={16} y={10.5} fontSize={8} fontWeight={800} fill="#0f172a" textAnchor="middle">N</text>
          </svg>
        </div>

        {/* Scale bar — bottom-left overlay */}
        <div className="absolute bottom-3 left-3 bg-white/95 rounded-md border border-slate-200 px-2 py-1 shadow-sm">
          <div className="flex items-center gap-1">
            <div style={{ width: scaleBarPx, height: 4, background: "linear-gradient(to right, #0f172a 50%, white 50%)", border: "1px solid #0f172a" }} />
            <span className="text-[10px] font-mono text-slate-700">{scaleBarM} m</span>
          </div>
        </div>

        {/* Cartouche PC — bottom-right */}
        <div className="absolute bottom-3 right-3 bg-white/95 rounded-md border border-slate-300 px-3 py-1.5 shadow-sm">
          <div className="flex items-center gap-3">
            <div>
              <p className="text-[10px] font-semibold text-slate-900 leading-tight">{title}</p>
              <p className="text-[9px] font-mono text-slate-500 leading-tight">{scaleLabel} · {sheetCode}</p>
            </div>
            <span className="text-[10px] font-mono font-bold text-slate-900 bg-slate-100 px-1.5 py-0.5 rounded">{sheetCode}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────── Public entry — PlanSituation tab body ─────────── */

interface PlanSituationProps {
  parcelles: Parcelle[];
  address?: string;
  communeName?: string;
  codePostal?: string;
}

/** Compute the centroid of a GeoJSON Polygon / MultiPolygon ring union. */
function centroidOfParcelles(parcelles: Parcelle[]): [number, number] {
  if (!parcelles.length) return [2.35, 48.85]; // Paris fallback
  let sx = 0, sy = 0, n = 0;
  for (const p of parcelles) {
    const g = p.geometry;
    if (!g) continue;
    const rings =
      g.type === "Polygon" ? [g.coordinates[0]]
      : g.type === "MultiPolygon" ? g.coordinates.map((poly) => poly[0])
      : [];
    for (const ring of rings) {
      for (const c of ring as number[][]) {
        sx += c[0];
        sy += c[1];
        n += 1;
      }
    }
  }
  return n ? [sx / n, sy / n] : [2.35, 48.85];
}

export function PlanSituation({
  parcelles, address, communeName, codePostal,
}: PlanSituationProps) {
  const center = centroidOfParcelles(parcelles);
  return (
    <div className="space-y-4">
      <div className="bg-white border border-slate-200 rounded-xl px-5 py-3">
        <p className="text-xs font-medium text-slate-500">Adresse du terrain</p>
        <p className="font-semibold text-slate-900">{address ?? "—"}</p>
        {(communeName || codePostal) && (
          <p className="text-xs text-slate-500 mt-0.5">
            {codePostal ? `${codePostal} ` : ""}{communeName ?? ""} · Coordonnées WGS84 : {center[1].toFixed(5)}, {center[0].toFixed(5)}
          </p>
        )}
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <PlanSituationMap
          parcelles={parcelles}
          center={center}
          zoom={17}
          tilesLayer="plan"
          sheetCode="PC1-1"
          scaleLabel="≈ 1:5 000"
          scaleBarM={200}
          title="Plan de situation"
          subtitle="Situation communale — Plan IGN"
        />
        <PlanSituationMap
          parcelles={parcelles}
          center={center}
          zoom={19}
          tilesLayer="ortho"
          sheetCode="PC1-2"
          scaleLabel="≈ 1:1 000"
          scaleBarM={50}
          title="Contexte immédiat"
          subtitle="Vue aérienne — IGN Ortho"
        />
      </div>
    </div>
  );
}
