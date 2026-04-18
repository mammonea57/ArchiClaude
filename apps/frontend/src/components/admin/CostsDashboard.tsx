"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { apiFetch, ApiError } from "@/lib/api";

interface DayEntry {
  date: string;
  cost_cents: number;
}

interface ExtractionCostsData {
  by_day: DayEntry[];
  total_cents: number;
}

// Placeholder data used when the endpoint isn't wired
const PLACEHOLDER_DATA: ExtractionCostsData = {
  total_cents: 4250,
  by_day: [
    { date: "2026-04-10", cost_cents: 320 },
    { date: "2026-04-11", cost_cents: 480 },
    { date: "2026-04-12", cost_cents: 210 },
    { date: "2026-04-13", cost_cents: 650 },
    { date: "2026-04-14", cost_cents: 890 },
    { date: "2026-04-15", cost_cents: 700 },
    { date: "2026-04-16", cost_cents: 1000 },
  ],
};

export function CostsDashboard() {
  const [data, setData] = useState<ExtractionCostsData>(PLACEHOLDER_DATA);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<ExtractionCostsData>("/admin/extraction-costs")
      .then(setData)
      .catch(() => {
        // Use placeholder on error
      })
      .finally(() => setLoading(false));
  }, []);

  const chartData = data.by_day.map((d) => ({
    date: new Date(d.date).toLocaleDateString("fr-FR", {
      month: "short",
      day: "numeric",
    }),
    cost: d.cost_cents / 100,
  }));

  const totalEur = (data.total_cents / 100).toFixed(2);

  return (
    <div className="space-y-6">
      {/* KPI card */}
      <div className="inline-flex rounded-xl border border-teal-200 bg-teal-50 px-6 py-4 gap-4 items-center">
        <div>
          <p className="text-xs text-teal-600 uppercase tracking-wide font-semibold">
            Coût total extractions
          </p>
          <p className="text-3xl font-bold text-teal-800 mt-0.5">
            {totalEur} €
          </p>
          <p className="text-xs text-teal-500 mt-1">Toutes requêtes LLM confondues</p>
        </div>
      </div>

      {/* Chart */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">
          Coût par jour (€)
        </h3>
        {loading ? (
          <div className="h-52 flex items-center justify-center text-sm text-slate-400">
            Chargement…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: "#94a3b8" }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                tickFormatter={(v: number) => `${v.toFixed(2)} €`}
              />
              <Tooltip
                formatter={(value) => [
                  typeof value === "number" ? `${value.toFixed(2)} €` : value,
                  "Coût",
                ]}
              />
              <Line
                type="monotone"
                dataKey="cost"
                stroke="#0d9488"
                strokeWidth={2}
                dot={{ r: 3, fill: "#0d9488" }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
