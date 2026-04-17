"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Label } from "recharts";

export interface TypologyChartProps {
  data: Record<string, number>;
}

const TEAL_PALETTE = [
  "#0d9488",
  "#14b8a6",
  "#2dd4bf",
  "#5eead4",
  "#99f6e4",
];

export function TypologyChart({ data }: TypologyChartProps) {
  const entries = Object.entries(data).map(([name, value]) => ({ name, value }));
  const total = entries.reduce((s, e) => s + e.value, 0);

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-slate-400">
        Aucune donnée typologique
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
        Mix typologique
      </h3>
      <div className="flex flex-col sm:flex-row items-center gap-6">
        <ResponsiveContainer width={200} height={200}>
          <PieChart>
            <Pie
              data={entries}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={85}
              paddingAngle={3}
              dataKey="value"
              strokeWidth={0}
            >
              {entries.map((_, idx) => (
                <Cell key={idx} fill={TEAL_PALETTE[idx % TEAL_PALETTE.length]} />
              ))}
              <Label
                value={total}
                position="center"
                className="text-2xl font-bold fill-slate-900"
                fontSize={28}
                fontWeight={700}
                fill="#0f172a"
              />
            </Pie>
            <Tooltip
              formatter={(value, name) => [`${value} logts`, String(name)]}
              contentStyle={{
                borderRadius: "8px",
                border: "1px solid #e2e8f0",
                fontSize: "12px",
              }}
            />
          </PieChart>
        </ResponsiveContainer>

        <div className="flex flex-col gap-2 min-w-0">
          {entries.map((entry, idx) => (
            <div key={entry.name} className="flex items-center gap-2 text-sm">
              <span
                className="w-3 h-3 rounded-sm shrink-0"
                style={{ backgroundColor: TEAL_PALETTE[idx % TEAL_PALETTE.length] }}
              />
              <span className="text-slate-600 font-medium w-8">{entry.name}</span>
              <span className="text-slate-900 tabular-nums font-semibold">{entry.value}</span>
              <span className="text-slate-400 text-xs">
                ({total > 0 ? Math.round((entry.value / total) * 100) : 0}%)
              </span>
            </div>
          ))}
          <div className="pt-2 border-t border-slate-100 flex items-center gap-2 text-sm">
            <span className="text-slate-400 w-3 h-3 shrink-0" />
            <span className="text-slate-500 font-medium w-8">Total</span>
            <span className="text-slate-900 tabular-nums font-bold">{total}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
