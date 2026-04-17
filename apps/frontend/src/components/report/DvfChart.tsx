"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LabelList,
} from "recharts";

export interface DvfData {
  prix_moyen_m2_appartement?: number;
  prix_moyen_m2_maison?: number;
  nb_transactions: number;
}

interface DvfChartProps {
  data: DvfData;
}

function formatEur(value: number): string {
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function DvfChart({ data }: DvfChartProps) {
  const entries: { name: string; value: number; color: string }[] = [];

  if (data.prix_moyen_m2_appartement != null) {
    entries.push({
      name: "Appartements",
      value: data.prix_moyen_m2_appartement,
      color: "#0d9488",
    });
  }
  if (data.prix_moyen_m2_maison != null) {
    entries.push({
      name: "Maisons",
      value: data.prix_moyen_m2_maison,
      color: "#14b8a6",
    });
  }

  if (entries.length === 0) {
    return (
      <div className="rounded-xl border border-slate-100 bg-white p-10 text-center text-sm text-slate-400">
        Aucune donnée DVF disponible pour ce secteur
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
          Prix de marché DVF
        </h3>
        <span className="text-xs text-slate-400">
          {data.nb_transactions} transaction{data.nb_transactions !== 1 ? "s" : ""}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <BarChart
          data={entries}
          margin={{ top: 24, right: 16, bottom: 8, left: 16 }}
          barCategoryGap="40%"
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fontSize: 12, fill: "#94a3b8" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k€`}
          />
          <Tooltip
            formatter={(value) => [formatEur(Number(value)), "Prix moyen/m²"]}
            contentStyle={{
              borderRadius: "8px",
              border: "1px solid #e2e8f0",
              fontSize: "12px",
            }}
            cursor={{ fill: "#f8fafc" }}
          />
          <Bar dataKey="value" radius={[6, 6, 0, 0]}>
            {entries.map((entry, idx) => (
              <Cell key={idx} fill={entry.color} />
            ))}
            <LabelList
              dataKey="value"
              position="top"
              formatter={(value) => formatEur(Number(value))}
              style={{ fontSize: "11px", fill: "#64748b", fontWeight: 600 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <p className="text-xs text-slate-400 text-center">
        Source : Demandes de Valeurs Foncières (DVF) — données publiques
      </p>
    </div>
  );
}
