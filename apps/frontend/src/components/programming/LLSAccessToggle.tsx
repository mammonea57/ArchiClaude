"use client";

import { useState } from "react";

interface LLSAccessToggleProps {
  /** SDP loss in m² when separate LLS access is enabled */
  perteSdpM2?: number;
  /** When false the toggle is disabled (not applicable for this scenario) */
  applicable?: boolean;
  /** Called when toggle state changes */
  onChange?: (enabled: boolean) => void;
}

export function LLSAccessToggle({
  perteSdpM2 = 0,
  applicable = true,
  onChange,
}: LLSAccessToggleProps) {
  const [enabled, setEnabled] = useState(false);

  function toggle() {
    if (!applicable) return;
    const next = !enabled;
    setEnabled(next);
    onChange?.(next);
  }

  return (
    <div
      className={[
        "flex items-center gap-3 rounded-lg border px-4 py-3",
        applicable ? "border-slate-200 bg-white" : "border-slate-100 bg-slate-50 opacity-60",
      ].join(" ")}
    >
      {/* Toggle switch */}
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        disabled={!applicable}
        onClick={toggle}
        className={[
          "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2",
          enabled ? "bg-teal-500" : "bg-slate-300",
          !applicable ? "cursor-not-allowed" : "",
        ].join(" ")}
      >
        <span
          className={[
            "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition-transform",
            enabled ? "translate-x-4" : "translate-x-0",
          ].join(" ")}
        />
      </button>

      {/* Label */}
      <div className="flex flex-col">
        <span className="text-sm font-medium text-slate-800">
          Accès séparés LLS / Accession
        </span>
        {!applicable ? (
          <span className="text-xs text-slate-400">Non applicable pour ce scénario</span>
        ) : enabled && perteSdpM2 > 0 ? (
          <span className="text-xs text-amber-600">
            Perte SDP&nbsp;: −{perteSdpM2.toLocaleString("fr-FR")} m²
          </span>
        ) : (
          <span className="text-xs text-slate-400">
            Activer pour avoir des circulations séparées
          </span>
        )}
      </div>
    </div>
  );
}
