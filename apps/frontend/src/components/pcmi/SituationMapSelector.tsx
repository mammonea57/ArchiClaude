"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";

interface Props {
  projectId: string;
  defaultValue?: "scan25" | "planv2";
}

const OPTIONS: { value: "scan25" | "planv2"; label: string }[] = [
  { value: "scan25", label: "Scan 25" },
  { value: "planv2", label: "Plan IGN v2" },
];

export function SituationMapSelector({ projectId, defaultValue = "scan25" }: Props) {
  const [selected, setSelected] = useState<"scan25" | "planv2">(defaultValue);
  const [saving, setSaving] = useState(false);

  async function handleChange(value: "scan25" | "planv2") {
    if (value === selected) return;
    setSaving(true);
    try {
      await apiFetch<{ map_base: string }>(`/projects/${projectId}/pcmi/settings`, {
        method: "PATCH",
        body: JSON.stringify({ map_base: value }),
      });
      setSelected(value);
    } catch {
      // silently revert on error
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs text-slate-400 uppercase tracking-wider font-medium">
        Fond de carte
      </span>
      <div
        className="inline-flex rounded-lg border border-slate-200 overflow-hidden"
        role="group"
        aria-label="Sélection du fond de carte"
      >
        {OPTIONS.map((opt) => {
          const isActive = selected === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              disabled={saving}
              onClick={() => handleChange(opt.value)}
              className={`px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 disabled:opacity-60 ${
                isActive
                  ? "text-white"
                  : "bg-white text-slate-600 hover:bg-slate-50"
              }`}
              style={isActive ? { backgroundColor: "var(--ac-primary)" } : undefined}
              aria-pressed={isActive}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
