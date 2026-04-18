"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// Placeholder data for v1
const MOST_CORRECTED_FIELDS = [
  { field: "Hauteur max", corrections: 38 },
  { field: "Emprise sol", corrections: 29 },
  { field: "Stationnement", corrections: 24 },
  { field: "Pleine terre", corrections: 18 },
  { field: "Retrait front", corrections: 15 },
  { field: "COS", corrections: 12 },
  { field: "Retrait latéral", corrections: 9 },
];

const WORST_ZONES = [
  { zone: "UG3 — Paris", correction_rate: 0.72, total: 32 },
  { zone: "UP — Vincennes", correction_rate: 0.65, total: 17 },
  { zone: "UA — Montreuil", correction_rate: 0.61, total: 23 },
  { zone: "N — Marne-la-Vallée", correction_rate: 0.58, total: 12 },
  { zone: "UCa — Nanterre", correction_rate: 0.54, total: 28 },
];

export function TelemetryPanel() {
  return (
    <div className="space-y-8">
      {/* Bar chart: most corrected fields */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">
          Champs les plus corrigés
        </h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={MOST_CORRECTED_FIELDS} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
            <XAxis
              type="number"
              tick={{ fontSize: 11, fill: "#94a3b8" }}
            />
            <YAxis
              dataKey="field"
              type="category"
              tick={{ fontSize: 11, fill: "#64748b" }}
              width={90}
            />
            <Tooltip formatter={(v) => [v, "Corrections"]} />
            <Bar dataKey="corrections" fill="#0d9488" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <p className="text-xs text-slate-400 mt-2">
          Données v1 — placeholder en attendant les vraies corrections utilisateur.
        </p>
      </div>

      {/* Worst zones table */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">
          Zones avec le taux de correction le plus élevé
        </h3>
        <table className="w-full text-left text-sm">
          <thead className="border-b text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-2 pr-4">Zone</th>
              <th className="py-2 pr-4">Taux de correction</th>
              <th className="py-2">Nb validations</th>
            </tr>
          </thead>
          <tbody>
            {WORST_ZONES.map((z, i) => (
              <tr key={z.zone} className="border-b last:border-0">
                <td className="py-2 pr-4 font-medium text-slate-800">{z.zone}</td>
                <td className="py-2 pr-4">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-24 rounded-full bg-slate-100">
                      <div
                        className="h-2 rounded-full bg-amber-500"
                        style={{ width: `${z.correction_rate * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-600 font-mono">
                      {Math.round(z.correction_rate * 100)}%
                    </span>
                  </div>
                </td>
                <td className="py-2 text-slate-600">{z.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
