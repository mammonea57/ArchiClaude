"use client";

import { Shield, Droplets, Trees, AlertTriangle, Info, Zap } from "lucide-react";

export interface Alert {
  level: "info" | "warning" | "critical";
  type: string;
  message: string;
}

const LEVEL_ORDER: Record<Alert["level"], number> = {
  critical: 0,
  warning: 1,
  info: 2,
};

const LEVEL_STYLES: Record<
  Alert["level"],
  { border: string; bg: string; text: string; icon: string }
> = {
  critical: {
    border: "border-l-4 border-red-500",
    bg: "bg-red-50",
    text: "text-red-700",
    icon: "text-red-500",
  },
  warning: {
    border: "border-l-4 border-amber-400",
    bg: "bg-amber-50",
    text: "text-amber-800",
    icon: "text-amber-500",
  },
  info: {
    border: "border-l-4 border-blue-400",
    bg: "bg-blue-50",
    text: "text-blue-800",
    icon: "text-blue-500",
  },
};

function AlertIcon({ type, className }: { type: string; className?: string }) {
  const t = type.toLowerCase();
  if (t.includes("abf") || t.includes("monument") || t.includes("patrimoine"))
    return <Shield className={className} />;
  if (t.includes("ppri") || t.includes("inondation") || t.includes("eau"))
    return <Droplets className={className} />;
  if (t.includes("ebc") || t.includes("arbre") || t.includes("espace"))
    return <Trees className={className} />;
  if (t.includes("electr") || t.includes("rte") || t.includes("haute tension"))
    return <Zap className={className} />;
  if (t.includes("critique") || t.includes("critical"))
    return <AlertTriangle className={className} />;
  return <Info className={className} />;
}

interface ServitudesListProps {
  alerts: Alert[];
}

export function ServitudesList({ alerts }: ServitudesListProps) {
  if (alerts.length === 0) return null;

  const sorted = [...alerts].sort(
    (a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level],
  );

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
        Servitudes &amp; Alertes
      </h3>
      <div className="space-y-2">
        {sorted.map((alert, idx) => {
          const styles = LEVEL_STYLES[alert.level];
          return (
            <div
              key={idx}
              className={`flex gap-3 rounded-r-lg px-4 py-3 ${styles.border} ${styles.bg}`}
            >
              <AlertIcon
                type={alert.type}
                className={`h-4 w-4 shrink-0 mt-0.5 ${styles.icon}`}
              />
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className={`text-xs font-semibold uppercase tracking-wider ${styles.text}`}>
                  {alert.type}
                </span>
                <span className={`text-sm leading-relaxed ${styles.text}`}>{alert.message}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
