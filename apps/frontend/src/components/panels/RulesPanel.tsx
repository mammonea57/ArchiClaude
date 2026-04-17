"use client";

import { Badge } from "@/components/ui/badge";

export interface RulesPanelProps {
  parsedRules: Record<string, string | null>;
  numericRules?: Record<string, unknown>;
  validated: boolean;
  confidence?: number;
}

const RULE_LABELS: Record<string, string> = {
  zone: "Zone PLU",
  destination: "Destination",
  us_max: "Usage du sol max",
  hauteur_max: "Hauteur maximale",
  emp_max: "Emprise au sol max",
  cos: "COS",
  iar: "Indice d'occupation",
  retrait_voirie: "Retrait voirie",
  retrait_limite: "Retrait limites",
  stationnement: "Stationnement",
  espaces_verts: "Espaces verts",
  pleine_terre: "Pleine terre",
  facades: "Traitement façades",
  toiture: "Toiture",
  materiaux: "Matériaux",
};

function formatLabel(key: string): string {
  return RULE_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function RulesPanel({ parsedRules, numericRules, validated, confidence }: RulesPanelProps) {
  const entries = Object.entries(parsedRules);
  const isLowConfidence = (key: string): boolean => {
    if (confidence === undefined) return false;
    if (numericRules && key in numericRules) return false;
    return confidence < 0.85;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
          Règles PLU extraites
        </h3>
        <div className="flex items-center gap-2">
          {confidence !== undefined && (
            <span className="text-xs text-slate-400">
              Confiance&thinsp;: {Math.round(confidence * 100)}&thinsp;%
            </span>
          )}
          {validated ? (
            <Badge className="text-xs border-transparent" style={{ backgroundColor: "#dcfce7", color: "#15803d" }}>
              Validé
            </Badge>
          ) : (
            <Badge className="text-xs border-transparent" style={{ backgroundColor: "#fef3c7", color: "#92400e" }}>
              À valider
            </Badge>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-100 overflow-hidden bg-white">
        {entries.map(([key, value], idx) => {
          const lowConf = isLowConfidence(key);
          return (
            <div
              key={key}
              className={`flex items-center justify-between px-5 py-3 text-sm ${
                idx < entries.length - 1 ? "border-b border-slate-50" : ""
              } ${lowConf ? "bg-amber-50" : ""}`}
            >
              <span className="text-slate-600 font-medium">{formatLabel(key)}</span>
              {value === null ? (
                <span className="text-slate-300 italic text-xs">Non précisé</span>
              ) : (
                <span className={`font-semibold tabular-nums ${lowConf ? "text-amber-700" : "text-slate-900"}`}>
                  {value}
                </span>
              )}
            </div>
          );
        })}
        {entries.length === 0 && (
          <div className="px-5 py-8 text-center text-sm text-slate-400">
            Aucune règle extraite
          </div>
        )}
      </div>
    </div>
  );
}
