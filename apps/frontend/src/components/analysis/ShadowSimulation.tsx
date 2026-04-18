"use client";

import { useState } from "react";

interface ShadowEntry {
  time: string;
  shadow_length_m: number;
  shadow_area_m2: number;
}

interface ShadowSimulationProps {
  modeA?: {
    critical_shadows: ShadowEntry[];
    max_shadow_length_m: number;
  };
  modeB?: {
    pct_aggravation: number;
    ombre_ajoutee_m2: number;
  };
}

type ActiveMode = "a" | "b";

function getAggravationColor(pct: number): { bar: string; text: string; label: string } {
  if (pct < 10) return { bar: "bg-green-400", text: "text-green-700", label: "Faible" };
  if (pct < 25) return { bar: "bg-yellow-400", text: "text-yellow-700", label: "Modérée" };
  if (pct < 50) return { bar: "bg-orange-400", text: "text-orange-700", label: "Significative" };
  return { bar: "bg-red-500", text: "text-red-700", label: "Importante" };
}

function ShadowLengthBar({ lengthM, maxM }: { lengthM: number; maxM: number }) {
  const pct = maxM > 0 ? Math.min(100, (lengthM / maxM) * 100) : 0;
  return (
    <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
      <div
        className="h-full bg-gray-500 rounded-full"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function ShadowSimulation({ modeA, modeB }: ShadowSimulationProps) {
  const [activeMode, setActiveMode] = useState<ActiveMode>(modeA ? "a" : "b");

  const hasA = Boolean(modeA);
  const hasB = Boolean(modeB);

  if (!hasA && !hasB) {
    return (
      <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 text-sm text-gray-500 text-center">
        Aucune donnée d&apos;ombre disponible
      </div>
    );
  }

  const maxShadow = modeA?.max_shadow_length_m ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* Toggle buttons */}
      {hasA && hasB && (
        <div className="flex gap-1 p-1 bg-gray-100 rounded-lg w-fit">
          <button
            type="button"
            onClick={() => setActiveMode("a")}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              activeMode === "a"
                ? "bg-white text-gray-800 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Diagramme solaire
          </button>
          <button
            type="button"
            onClick={() => setActiveMode("b")}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              activeMode === "b"
                ? "bg-white text-gray-800 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Avec voisins
          </button>
        </div>
      )}

      {/* Mode A: critical shadows */}
      {(activeMode === "a" || !hasB) && modeA && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-gray-500 flex-shrink-0" />
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
              Ombres critiques — 21 décembre
            </p>
          </div>

          <div className="flex flex-col gap-3">
            {modeA.critical_shadows.map((shadow, idx) => (
              <div key={idx} className="flex flex-col gap-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-gray-700">{shadow.time}</span>
                  <div className="flex gap-3 text-gray-500">
                    <span>
                      <span className="font-semibold text-gray-700">
                        {shadow.shadow_length_m.toFixed(1)} m
                      </span>{" "}
                      longueur
                    </span>
                    <span>
                      <span className="font-semibold text-gray-700">
                        {shadow.shadow_area_m2.toFixed(0)} m²
                      </span>{" "}
                      surface
                    </span>
                  </div>
                </div>
                <ShadowLengthBar lengthM={shadow.shadow_length_m} maxM={maxShadow} />
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between p-2 bg-gray-50 rounded border border-gray-200">
            <span className="text-xs text-gray-500">Ombre max (midi)</span>
            <span className="text-sm font-bold text-gray-700">
              {modeA.max_shadow_length_m.toFixed(1)} m
            </span>
          </div>
        </div>
      )}

      {/* Mode B: aggravation vs neighbours */}
      {(activeMode === "b" || !hasA) && modeB && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-gray-700 flex-shrink-0" />
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
              Aggravation vs voisinage — 21 décembre 12h
            </p>
          </div>

          {(() => {
            const colors = getAggravationColor(modeB.pct_aggravation);
            return (
              <div className="flex flex-col gap-3">
                {/* Percentage bar */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs text-gray-500">Aggravation</span>
                    <span className={`text-sm font-bold ${colors.text}`}>
                      +{modeB.pct_aggravation.toFixed(1)}%
                    </span>
                  </div>
                  <div className="w-full h-3 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${colors.bar}`}
                      style={{ width: `${Math.min(100, modeB.pct_aggravation)}%` }}
                    />
                  </div>
                </div>

                {/* Stats row */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="p-2 bg-gray-50 rounded border border-gray-200 text-center">
                    <p className="text-xs text-gray-400">Ombre ajoutée</p>
                    <p className="text-sm font-bold text-gray-700 mt-0.5">
                      {modeB.ombre_ajoutee_m2.toFixed(0)} m²
                    </p>
                  </div>
                  <div className="p-2 bg-gray-50 rounded border border-gray-200 text-center">
                    <p className="text-xs text-gray-400">Sévérité</p>
                    <p className={`text-sm font-bold mt-0.5 ${colors.text}`}>
                      {colors.label}
                    </p>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
