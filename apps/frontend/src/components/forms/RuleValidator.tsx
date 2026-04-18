"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiFetch, ApiError } from "@/lib/api";

interface RuleValidatorProps {
  zoneId: string;
  extractedRules: Record<string, string | null>;
  confidence: number;
  onValidate: (edits: Record<string, string>) => void;
}

const FIELD_LABELS: Record<string, string> = {
  hauteur_max_m: "Hauteur max (m)",
  emprise_sol_max_pct: "Emprise sol max (%)",
  cos: "COS",
  stationnement_par_logement: "Stationnement / logement",
  pleine_terre_min_pct: "Pleine terre min (%)",
  retrait_front: "Retrait front (m)",
  retrait_lateral: "Retrait latéral (m)",
  retrait_fond: "Retrait fond (m)",
  destination_principale: "Destination principale",
  zone_code: "Code de zone",
};

export function RuleValidator({
  zoneId,
  extractedRules,
  confidence,
  onValidate,
}: RuleValidatorProps) {
  const [edits, setEdits] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const [key, val] of Object.entries(extractedRules)) {
      initial[key] = val ?? "";
    }
    return initial;
  });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const isLowConfidence = confidence < 0.85;

  function handleChange(key: string, value: string) {
    setEdits((prev) => ({ ...prev, [key]: value }));
  }

  async function handleValidate() {
    setLoading(true);
    setErrorMsg(null);
    try {
      // Find changed fields
      const changed: Record<string, string> = {};
      for (const [key, val] of Object.entries(edits)) {
        if (val !== (extractedRules[key] ?? "")) {
          changed[key] = val;
        }
      }

      // Post feedback if any fields changed
      if (Object.keys(changed).length > 0) {
        try {
          await apiFetch(`/rules/${zoneId}/feedback`, {
            method: "POST",
            body: JSON.stringify({ corrections: changed }),
          });
        } catch {
          // Non-blocking — feedback failure shouldn't block validation
        }
      }

      // Validate the zone
      await apiFetch(`/plu/zone/${zoneId}/validate`, {
        method: "POST",
        body: JSON.stringify({ validated_rules: edits }),
      });

      onValidate(edits);
    } catch (e) {
      setErrorMsg(
        e instanceof ApiError
          ? `Erreur ${e.status}: ${JSON.stringify(e.body)}`
          : "Erreur réseau",
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleReport() {
    setLoading(true);
    setErrorMsg(null);
    try {
      await apiFetch(`/rules/${zoneId}/feedback`, {
        method: "POST",
        body: JSON.stringify({ type: "error_report", corrections: edits }),
      });
      setErrorMsg(null);
    } catch (e) {
      setErrorMsg(
        e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau",
      );
    } finally {
      setLoading(false);
    }
  }

  const fields = Object.keys(extractedRules);

  return (
    <div className="space-y-4">
      {isLowConfidence && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <strong>Confiance faible ({Math.round(confidence * 100)}%)</strong> — Vérifiez
          les valeurs surlignées avant de valider.
        </div>
      )}

      {errorMsg && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-8 gap-y-1">
        {/* Column headers */}
        <div className="col-span-2 grid grid-cols-2 gap-x-8 border-b pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <span>Valeur extraite (lecture seule)</span>
          <span>Valeur éditable</span>
        </div>

        {fields.map((key) => {
          const extracted = extractedRules[key];
          const isAmber = isLowConfidence;

          return (
            <div key={key} className="col-span-2 grid grid-cols-2 gap-x-8 items-center py-2 border-b border-slate-100 last:border-0">
              {/* Left: extracted value */}
              <div className="flex items-center gap-2">
                <span className="min-w-[160px] text-sm font-medium text-slate-700">
                  {FIELD_LABELS[key] ?? key}
                </span>
                <span
                  className={`rounded px-2 py-0.5 text-sm font-mono ${
                    isAmber
                      ? "bg-amber-100 text-amber-800 border border-amber-300"
                      : "bg-slate-100 text-slate-700"
                  }`}
                >
                  {extracted ?? <span className="text-slate-400 italic">—</span>}
                </span>
                {isAmber && (
                  <Badge
                    variant="outline"
                    className="border-amber-400 text-amber-700 text-xs"
                  >
                    À vérifier
                  </Badge>
                )}
              </div>

              {/* Right: editable field */}
              <Input
                value={edits[key] ?? ""}
                onChange={(e) => handleChange(key, e.target.value)}
                placeholder={extracted ?? "—"}
                className="h-8 text-sm font-mono"
              />
            </div>
          );
        })}
      </div>

      <div className="flex gap-3 pt-2">
        <Button
          onClick={handleValidate}
          disabled={loading}
          className="bg-teal-600 hover:bg-teal-700 text-white"
        >
          {loading ? "Validation…" : "Valider"}
        </Button>
        <Button
          variant="outline"
          onClick={handleReport}
          disabled={loading}
          className="border-red-300 text-red-600 hover:bg-red-50"
        >
          Signaler une erreur
        </Button>
      </div>
    </div>
  );
}
