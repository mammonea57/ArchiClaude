"use client";

import Link from "next/link";
import { use } from "react";
import { useFeasibility } from "@/lib/hooks/useFeasibility";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FeasibilityDashboard, type KPI } from "@/components/panels/FeasibilityDashboard";
import { RulesPanel } from "@/components/panels/RulesPanel";
import { ComplianceSummary } from "@/components/panels/ComplianceSummary";
import { ServitudesList } from "@/components/panels/ServitudesList";
import { TypologyChart } from "@/components/report/TypologyChart";
import { ArchitectureNoteRenderer } from "@/components/report/ArchitectureNoteRenderer";
import { ReportExportButton } from "@/components/report/ReportExportButton";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ArrowLeft } from "lucide-react";
import type { Project, FeasibilityResult } from "@/lib/types";

// Demo/placeholder data until real backend result is wired in
const DEMO_RESULT: FeasibilityResult = {
  id: "demo",
  project_id: "",
  status: "complete",
  sdp_m2: 2_400,
  niveaux: 6,
  nb_logements: 28,
  stationnement: 28,
  emprise_pct: 40,
  pleine_terre_pct: 30,
  parsed_rules: {
    zone: "UA",
    hauteur_max: "R+6",
    emp_max: "40%",
    pleine_terre: "30% min",
    stationnement: "1 pl./logement",
    retrait_voirie: "0 m (alignement)",
    retrait_limite: "4 m ou H/2",
    facades: null,
  },
  plu_validated: false,
  plu_confidence: 0.82,
  mix_typologique: { T2: 8, T3: 12, T4: 6, T5: 2 },
  incendie: "Habitation R+5",
  pmr_ascenseur: true,
  re2020_seuil: "Seuil 2025",
  lls_statut: "25% LLS",
  rsdu_obligations: [],
  alerts: [
    {
      level: "warning",
      type: "ABF",
      message: "Périmètre de 500 m autour d'un monument historique — avis ABF requis.",
    },
  ],
  architecture_note_md: `## Synthèse architecturale

Le terrain permet une opération de logements collectifs en zone UA, avec un programme de **28 logements** sur **6 niveaux** et une SDP totale de **2 400 m²**.

## Implantation

L'implantation à l'alignement sur voirie est imposée par le PLU. Les retraits en limite séparative seront de **4 m minimum** ou **H/2** selon la hauteur effective.

## Programme logements

| Typologie | Nombre | % |
|-----------|--------|---|
| T2 | 8 | 29% |
| T3 | 12 | 43% |
| T4 | 6 | 21% |
| T5 | 2 | 7% |

## Points d'attention

- Présence d'un périmètre ABF à vérifier lors du dépôt PC
- Quota LLS de 25% à négocier avec la commune
- RE2020 seuil 2025 — conception bioclimatique recommandée dès l'esquisse
`,
  feasibility_summary:
    "Programme faisable sous réserve de validation PLU et accord ABF. Mix logements équilibré T2/T3 dominant.",
};

function statusLabel(status: Project["status"]): string {
  switch (status) {
    case "draft":     return "Brouillon";
    case "analyzed":  return "Analysé";
    case "archived":  return "Archivé";
  }
}

function buildKPIs(result: FeasibilityResult): KPI[] {
  return [
    { label: "SDP", value: result.sdp_m2 ?? "—", unit: result.sdp_m2 != null ? "m²" : undefined },
    { label: "Niveaux", value: result.niveaux ?? "—" },
    { label: "Logements", value: result.nb_logements ?? "—" },
    { label: "Stationnement", value: result.stationnement ?? "—", unit: result.stationnement != null ? "pl." : undefined },
    { label: "Emprise sol", value: result.emprise_pct != null ? `${result.emprise_pct}%` : "—" },
    { label: "Pleine terre", value: result.pleine_terre_pct != null ? `${result.pleine_terre_pct}%` : "—" },
  ];
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { project, loading, error } = useFeasibility(id);

  // Use demo result until real endpoint is wired
  const result = DEMO_RESULT;

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link href="/" className="font-display text-xl font-semibold text-slate-900 shrink-0">
              ArchiClaude
            </Link>
            <Separator orientation="vertical" className="h-5" />
            {project && (
              <span className="text-sm text-slate-500 truncate max-w-xs">
                {project.name}
              </span>
            )}
            {project && (
              <Badge
                className="text-xs border-transparent shrink-0"
                style={{ backgroundColor: "#dcfce7", color: "#15803d" }}
              >
                {statusLabel(project.status)}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <Link
              href={`/projects/${id}`}
              className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-700 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Tableau de bord
            </Link>
            <ReportExportButton resultId={result.id} />
          </div>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-8">
        {loading && (
          <div className="py-20 text-center text-sm text-slate-400">Chargement…</div>
        )}
        {error && (
          <div className="py-20 text-center text-sm text-red-500">Erreur : {error}</div>
        )}

        {/* Alerts banner */}
        {result.alerts && result.alerts.length > 0 && (
          <div className="mb-6">
            <ServitudesList alerts={result.alerts} />
          </div>
        )}

        <Tabs defaultValue="synthese" className="space-y-6">
          <TabsList className="bg-white border border-slate-100 rounded-xl p-1 h-auto flex-wrap gap-1">
            <TabsTrigger value="synthese" className="rounded-lg text-sm data-[state=active]:text-white" style={{ "--tw-shadow": "none" } as React.CSSProperties}>
              Synthèse
            </TabsTrigger>
            <TabsTrigger value="regles" className="rounded-lg text-sm">
              Règles
            </TabsTrigger>
            <TabsTrigger value="capacite" className="rounded-lg text-sm">
              Capacité
            </TabsTrigger>
            <TabsTrigger value="compliance" className="rounded-lg text-sm">
              Compliance
            </TabsTrigger>
            <TabsTrigger value="site" className="rounded-lg text-sm">
              Site
            </TabsTrigger>
            <TabsTrigger value="analyse" className="rounded-lg text-sm">
              Analyse
            </TabsTrigger>
          </TabsList>

          {/* ── Synthèse ── */}
          <TabsContent value="synthese" className="space-y-6">
            <FeasibilityDashboard kpis={buildKPIs(result)} />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Card className="p-6 border-slate-100 shadow-none">
                <TypologyChart data={result.mix_typologique ?? {}} />
              </Card>

              <Card className="p-6 border-slate-100 shadow-none space-y-4">
                <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                  Résumé de faisabilité
                </h3>
                {result.feasibility_summary ? (
                  <p className="text-sm text-slate-700 leading-relaxed">
                    {result.feasibility_summary}
                  </p>
                ) : (
                  <p className="text-sm text-slate-400 italic">Résumé non disponible</p>
                )}
                {result.plu_confidence != null && (
                  <div className="pt-3 border-t border-slate-100">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-400">Confiance PLU</span>
                      <span
                        className="font-semibold"
                        style={{
                          color:
                            result.plu_confidence >= 0.85
                              ? "var(--ac-green)"
                              : "var(--ac-amber)",
                        }}
                      >
                        {Math.round(result.plu_confidence * 100)}%
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${Math.round(result.plu_confidence * 100)}%`,
                          backgroundColor:
                            result.plu_confidence >= 0.85
                              ? "var(--ac-green)"
                              : "var(--ac-amber)",
                        }}
                      />
                    </div>
                  </div>
                )}
              </Card>
            </div>
          </TabsContent>

          {/* ── Règles ── */}
          <TabsContent value="regles">
            <Card className="p-6 border-slate-100 shadow-none">
              <RulesPanel
                parsedRules={result.parsed_rules ?? {}}
                numericRules={result.numeric_rules}
                validated={result.plu_validated ?? false}
                confidence={result.plu_confidence}
              />
            </Card>
          </TabsContent>

          {/* ── Capacité ── */}
          <TabsContent value="capacite" className="space-y-6">
            <FeasibilityDashboard kpis={buildKPIs(result)} />
            <Card className="p-6 border-slate-100 shadow-none space-y-4">
              <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                Détail du programme
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                {[
                  { label: "Surface plancher", value: result.sdp_m2, unit: "m²" },
                  { label: "Nombre de niveaux", value: result.niveaux },
                  { label: "Nombre de logements", value: result.nb_logements },
                  { label: "Places de stationnement", value: result.stationnement },
                  { label: "Emprise au sol", value: result.emprise_pct, unit: "%" },
                  { label: "Pleine terre", value: result.pleine_terre_pct, unit: "%" },
                ].map((item) => (
                  <div key={item.label} className="flex flex-col gap-1">
                    <span className="text-xs text-slate-400 uppercase tracking-wider">
                      {item.label}
                    </span>
                    <span className="text-xl font-bold tabular-nums" style={{ color: "var(--ac-primary)" }}>
                      {item.value ?? "—"}
                      {item.unit && item.value != null && (
                        <span className="text-sm font-normal text-slate-400 ml-0.5">{item.unit}</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </Card>

            {Object.keys(result.mix_typologique ?? {}).length > 0 && (
              <Card className="p-6 border-slate-100 shadow-none">
                <TypologyChart data={result.mix_typologique ?? {}} />
              </Card>
            )}
          </TabsContent>

          {/* ── Compliance ── */}
          <TabsContent value="compliance">
            <Card className="p-6 border-slate-100 shadow-none">
              <ComplianceSummary
                incendie={result.incendie ?? ""}
                pmr_ascenseur={result.pmr_ascenseur ?? false}
                re2020_seuil={result.re2020_seuil ?? ""}
                lls_statut={result.lls_statut ?? ""}
                rsdu_obligations={result.rsdu_obligations ?? []}
              />
            </Card>
          </TabsContent>

          {/* ── Site ── */}
          <TabsContent value="site">
            <Card className="p-10 border-slate-100 shadow-none text-center space-y-3">
              <p className="text-slate-400 text-sm">
                Les photos de rue (Mapillary) et les données DVF seront affichées ici.
              </p>
              <p className="text-slate-300 text-xs">
                Composants SitePhotosGallery et DvfChart disponibles — en attente de données géolocalisées.
              </p>
            </Card>
          </TabsContent>

          {/* ── Analyse ── */}
          <TabsContent value="analyse">
            <Card className="p-6 border-slate-100 shadow-none">
              <ArchitectureNoteRenderer markdown={result.architecture_note_md ?? ""} />
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </main>
  );
}
