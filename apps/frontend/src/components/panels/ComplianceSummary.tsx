"use client";

import { Card } from "@/components/ui/card";
import { CheckCircle, AlertTriangle } from "lucide-react";

export interface ComplianceSummaryProps {
  incendie: string;
  pmr_ascenseur: boolean;
  re2020_seuil: string;
  lls_statut: string;
  rsdu_obligations: string[];
}

function StatusIcon({ ok }: { ok: boolean }) {
  return ok ? (
    <CheckCircle className="h-5 w-5 shrink-0" style={{ color: "var(--ac-green)" }} />
  ) : (
    <AlertTriangle className="h-5 w-5 shrink-0" style={{ color: "var(--ac-amber)" }} />
  );
}

function ComplianceCard({
  title,
  ok,
  value,
  detail,
}: {
  title: string;
  ok: boolean;
  value: string;
  detail: string;
}) {
  return (
    <Card className="p-5 flex gap-4 border-slate-100 shadow-none">
      <StatusIcon ok={ok} />
      <div className="flex flex-col gap-1 min-w-0">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          {title}
        </span>
        <span className="text-sm font-semibold text-slate-900">{value}</span>
        <span className="text-xs text-slate-500 leading-relaxed">{detail}</span>
      </div>
    </Card>
  );
}

function incendieOk(classement: string): boolean {
  return !classement.toLowerCase().includes("non conforme") && classement !== "";
}

function incendieDetail(classement: string): string {
  if (!classement) return "Classement non renseigné — à vérifier avec le SDIS.";
  if (classement.toLowerCase().includes("erp")) {
    return "Établissement recevant du public : règles ERP applicables. Vérifier le type et la catégorie.";
  }
  return "Habitation collective — règles de résistance au feu R+1 à R+8 selon le code de la construction.";
}

function re2020Ok(seuil: string): boolean {
  return seuil.toLowerCase() !== "non conforme" && seuil !== "";
}

function re2020Detail(seuil: string): string {
  if (!seuil) return "Seuil RE2020 non renseigné — requis pour tout permis de construire depuis 2022.";
  if (seuil.toLowerCase().includes("2025"))
    return "Seuil RE2020 2025 — exigences renforcées sur le carbone et l'énergie.";
  if (seuil.toLowerCase().includes("2028"))
    return "Seuil RE2020 2028 — palier final de la réglementation, très contraignant.";
  return "Conformité RE2020 attendue — à dimensionner dès l'esquisse.";
}

function llsDetail(statut: string): string {
  if (!statut || statut.toLowerCase() === "non concerné")
    return "Programme non soumis à l'article 55 SRU (commune non déficitaire ou programme exempt).";
  if (statut.toLowerCase().includes("25%"))
    return "25% de logements sociaux obligatoires (commune avec taux SRU < 25%). À négocier avec la commune.";
  return `Quota LLS applicable : ${statut}. Vérifier avec le service urbanisme.`;
}

export function ComplianceSummary({
  incendie,
  pmr_ascenseur,
  re2020_seuil,
  lls_statut,
  rsdu_obligations,
}: ComplianceSummaryProps) {
  const llsOk =
    !lls_statut || lls_statut.toLowerCase() === "non concerné" || lls_statut.toLowerCase() === "conforme";

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
        Conformités réglementaires
      </h3>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <ComplianceCard
          title="Sécurité incendie"
          ok={incendieOk(incendie)}
          value={incendie || "Non renseigné"}
          detail={incendieDetail(incendie)}
        />
        <ComplianceCard
          title="PMR / Ascenseur"
          ok={pmr_ascenseur}
          value={pmr_ascenseur ? "Ascenseur requis" : "Non requis"}
          detail={
            pmr_ascenseur
              ? "Bâtiment de plus de R+2 : ascenseur obligatoire (Art. R.111-19-1). 100% des logements accessibles."
              : "Moins de 3 niveaux — ascenseur non obligatoire, mais accessibilité RDC et parties communes requise."
          }
        />
        <ComplianceCard
          title="RE 2020"
          ok={re2020Ok(re2020_seuil)}
          value={re2020_seuil || "Non renseigné"}
          detail={re2020Detail(re2020_seuil)}
        />
        <ComplianceCard
          title="LLS / SRU"
          ok={llsOk}
          value={lls_statut || "Non concerné"}
          detail={llsDetail(lls_statut)}
        />
      </div>

      {rsdu_obligations.length > 0 && (
        <Card className="p-5 border-slate-100 shadow-none">
          <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" style={{ color: "var(--ac-amber)" }} />
            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">
                Obligations RSDU / ZAC
              </span>
              <ul className="space-y-1">
                {rsdu_obligations.map((o, i) => (
                  <li key={i} className="text-sm text-slate-700 flex gap-2">
                    <span className="text-slate-300 shrink-0">—</span>
                    {o}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
