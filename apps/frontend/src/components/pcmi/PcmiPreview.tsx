"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const PIECES = [
  { code: "PCMI1", titre: "Plan de situation" },
  { code: "PCMI2a", titre: "Plan de masse" },
  { code: "PCMI2b", titre: "Plans de niveaux" },
  { code: "PCMI3", titre: "Coupe" },
  { code: "PCMI4", titre: "Notice architecturale" },
  { code: "PCMI5", titre: "Façades" },
  { code: "PCMI7", titre: "Photo env. proche" },
  { code: "PCMI8", titre: "Photo env. lointain" },
] as const;

type PieceCode = (typeof PIECES)[number]["code"];

interface Props {
  projectId: string;
}

export function PcmiPreview({ projectId }: Props) {
  const [activeCode, setActiveCode] = useState<PieceCode>("PCMI1");

  const iframeSrc = `${API_BASE}/api/v1/projects/${projectId}/pcmi/${activeCode}`;

  return (
    <div className="space-y-4">
      {/* Tab row */}
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Pièces PCMI">
        {PIECES.map((piece) => {
          const isActive = activeCode === piece.code;
          return (
            <button
              key={piece.code}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${piece.code}`}
              onClick={() => setActiveCode(piece.code)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors border ${
                isActive
                  ? "text-white border-transparent"
                  : "bg-white text-slate-600 border-slate-200 hover:border-slate-300 hover:bg-slate-50"
              }`}
              style={isActive ? { backgroundColor: "var(--ac-primary)", borderColor: "var(--ac-primary)" } : undefined}
              title={piece.titre}
            >
              {piece.code}
            </button>
          );
        })}
      </div>

      {/* Active piece label */}
      <p className="text-sm text-slate-500">
        <span className="font-semibold" style={{ color: "var(--ac-primary)" }}>
          {activeCode}
        </span>
        {" — "}
        {PIECES.find((p) => p.code === activeCode)?.titre}
      </p>

      {/* Preview iframe */}
      <div
        id={`panel-${activeCode}`}
        role="tabpanel"
        className="rounded-lg border border-slate-100 overflow-hidden bg-slate-50"
      >
        <iframe
          key={iframeSrc}
          src={iframeSrc}
          title={`Aperçu ${activeCode}`}
          className="w-full h-[600px]"
          loading="lazy"
        />
      </div>
    </div>
  );
}
