"use client";

import { Card } from "@/components/ui/card";

export interface KPI {
  label: string;
  value: string | number;
  unit?: string;
  color?: string;
}

interface FeasibilityDashboardProps {
  kpis: KPI[];
}

export function FeasibilityDashboard({ kpis }: FeasibilityDashboardProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {kpis.map((kpi, idx) => (
        <Card key={idx} className="p-5 flex flex-col gap-1 border-slate-100 shadow-none">
          <span
            className="text-3xl font-bold tabular-nums leading-none"
            style={{ color: kpi.color ?? "var(--ac-primary)" }}
          >
            {kpi.value}
            {kpi.unit && (
              <span className="text-base font-normal ml-1 text-slate-400">{kpi.unit}</span>
            )}
          </span>
          <span className="text-xs text-slate-400 font-medium uppercase tracking-wider mt-1">
            {kpi.label}
          </span>
        </Card>
      ))}
    </div>
  );
}
