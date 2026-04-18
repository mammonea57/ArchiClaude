"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export interface ScenarioData {
  nom: string;
  sdp_m2: number;
  nb_logements: number;
  nb_niveaux: number;
  mix_utilise: Record<string, number>;
  mix_ajustements: string[];
  marge_pct: number;
  variante_acces_separes: boolean;
}

interface ScenarioComparatorProps {
  scenarios: ScenarioData[];
  scenario_recommande: string;
  onSelect?: (nom: string) => void;
}

function formatPct(value: number): string {
  return `${value.toFixed(1)} %`;
}

function formatMix(mix: Record<string, number>): string {
  return Object.entries(mix)
    .map(([k, v]) => `${k} ${(v * 100).toFixed(0)} %`)
    .join(" · ");
}

export function ScenarioComparator({
  scenarios,
  scenario_recommande,
  onSelect,
}: ScenarioComparatorProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {scenarios.map((sc) => {
        const isRecommended = sc.nom === scenario_recommande;
        return (
          <Card
            key={sc.nom}
            className={[
              "p-5 flex flex-col gap-3 border",
              isRecommended
                ? "border-teal-500 ring-2 ring-teal-500/30 bg-teal-50"
                : "border-slate-200",
            ].join(" ")}
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-800 capitalize">{sc.nom}</span>
              {isRecommended && (
                <Badge className="bg-teal-500 text-white text-xs">Recommandé</Badge>
              )}
            </div>

            <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-sm">
              <dt className="text-slate-500">SDP</dt>
              <dd className="text-right font-medium tabular-nums">
                {sc.sdp_m2.toLocaleString("fr-FR")} m²
              </dd>

              <dt className="text-slate-500">Logements</dt>
              <dd className="text-right font-medium tabular-nums">{sc.nb_logements}</dd>

              <dt className="text-slate-500">Niveaux</dt>
              <dd className="text-right font-medium tabular-nums">{sc.nb_niveaux}</dd>

              <dt className="text-slate-500">Marge</dt>
              <dd
                className={[
                  "text-right font-medium tabular-nums",
                  sc.marge_pct >= 15 ? "text-teal-600" : "text-amber-600",
                ].join(" ")}
              >
                {formatPct(sc.marge_pct)}
              </dd>
            </dl>

            {Object.keys(sc.mix_utilise).length > 0 && (
              <p className="text-xs text-slate-500 leading-snug">
                Mix&nbsp;: {formatMix(sc.mix_utilise)}
              </p>
            )}

            {sc.mix_ajustements.length > 0 && (
              <ul className="text-xs text-slate-500 list-disc pl-4 space-y-0.5">
                {sc.mix_ajustements.map((adj, i) => (
                  <li key={i}>{adj}</li>
                ))}
              </ul>
            )}

            {sc.variante_acces_separes && (
              <Badge variant="outline" className="w-fit text-xs text-slate-600">
                Accès séparés LLS
              </Badge>
            )}

            <Button
              size="sm"
              className={isRecommended ? "bg-teal-600 hover:bg-teal-700 text-white" : ""}
              variant={isRecommended ? "default" : "outline"}
              onClick={() => onSelect?.(sc.nom)}
            >
              Sélectionner
            </Button>
          </Card>
        );
      })}
    </div>
  );
}
