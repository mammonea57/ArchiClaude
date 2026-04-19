"use client";

import Link from "next/link";
import { use } from "react";
import { useFeasibility } from "@/lib/hooks/useFeasibility";
import { useBuildingModel } from "@/lib/hooks/useBuildingModel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FeasibilityDashboard, type KPI } from "@/components/panels/FeasibilityDashboard";
import { ComplianceSummary } from "@/components/panels/ComplianceSummary";
import { ServitudesList, type Alert } from "@/components/panels/ServitudesList";
import { TypologyChart } from "@/components/report/TypologyChart";
import { ArchitectureNoteRenderer } from "@/components/report/ArchitectureNoteRenderer";
import { ReportExportButton } from "@/components/report/ReportExportButton";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ArrowLeft, Building2, MapPin } from "lucide-react";
import type { Project, BuildingModelRow, BuildingModelPayload } from "@/lib/types";

function statusLabel(status: Project["status"]): string {
  switch (status) {
    case "draft":     return "Brouillon";
    case "analyzed":  return "Analysé";
    case "archived":  return "Archivé";
  }
}

function countLogements(bm: BuildingModelPayload): number {
  return bm.niveaux.reduce(
    (acc, n) => acc + n.cellules.filter((c) => c.type === "logement").length,
    0,
  );
}

function countTypology(bm: BuildingModelPayload): Record<string, number> {
  const out: Record<string, number> = {};
  for (const n of bm.niveaux) {
    for (const c of n.cellules) {
      if (c.type === "logement" && c.typologie) {
        out[c.typologie] = (out[c.typologie] ?? 0) + 1;
      }
    }
  }
  return out;
}

function sumSdp(bm: BuildingModelPayload): number {
  return bm.niveaux.reduce((acc, n) => acc + n.surface_plancher_m2, 0);
}

function empriseMetric(bm: BuildingModelPayload): number | null {
  const parcelle = bm.site.parcelle_surface_m2 ?? 0;
  if (!parcelle) return null;
  return Math.round((bm.envelope.emprise_m2 / parcelle) * 100);
}

function buildKPIs(project: Project, bm: BuildingModelRow | null): KPI[] {
  const b = project.brief;

  if (bm) {
    const m = bm.model_json;
    return [
      { label: "SDP", value: Math.round(sumSdp(m)), unit: "m²" },
      { label: "Niveaux", value: m.envelope.niveaux },
      { label: "Logements", value: countLogements(m) },
      { label: "Hauteur", value: m.envelope.hauteur_totale_m, unit: "m" },
      { label: "Emprise", value: empriseMetric(m) != null ? `${empriseMetric(m)}%` : "—" },
      { label: "Emprise", value: Math.round(m.envelope.emprise_m2), unit: "m²" },
    ];
  }

  return [
    { label: "SDP cible", value: b?.cible_sdp_m2 ?? "—", unit: b?.cible_sdp_m2 != null ? "m²" : undefined },
    { label: "Niveaux cible", value: b?.hauteur_cible_niveaux ?? "—" },
    { label: "Logements cible", value: b?.cible_nb_logements ?? "—" },
    { label: "Emprise cible", value: b?.emprise_cible_pct != null ? `${b.emprise_cible_pct}%` : "—" },
    { label: "Stationnement cible", value: b?.stationnement_cible_par_logement ?? "—" },
    {
      label: "Pleine terre cible",
      value: b?.espaces_verts_pleine_terre_cible_pct != null
        ? `${b.espaces_verts_pleine_terre_cible_pct}%`
        : "—",
    },
  ];
}

function buildAlerts(bm: BuildingModelRow | null): Alert[] {
  if (!bm?.conformite_check?.alerts) return [];
  const LEVEL_MAP: Record<"info" | "warning" | "error", Alert["level"]> = {
    info: "info", warning: "warning", error: "critical",
  };
  return bm.conformite_check.alerts.slice(0, 20).map((a) => ({
    level: LEVEL_MAP[a.level],
    type: a.category,
    message: a.message,
  }));
}

function formatTypologyMix(mix: Record<string, number>): Record<string, number> {
  // If input values are ratios (≤ 1), keep them; otherwise treat as counts.
  // TypologyChart accepts either.
  return mix;
}

function buildingSummary(bm: BuildingModelPayload, logementCount: number): string {
  const sdp = Math.round(sumSdp(bm));
  const emp = empriseMetric(bm);
  const parts = [
    `Opération ${bm.envelope.niveaux} niveau${bm.envelope.niveaux > 1 ? "x" : ""}`,
    `${logementCount} logement${logementCount > 1 ? "s" : ""}`,
    `SDP ${sdp} m²`,
  ];
  if (emp != null) parts.push(`emprise ${emp}%`);
  return `${parts.join(" · ")} — hauteur totale ${bm.envelope.hauteur_totale_m} m.`;
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { project, loading, error } = useFeasibility(id);
  const { buildingModel, notFound: bmNotFound } = useBuildingModel(id);

  const kpis = project ? buildKPIs(project, buildingModel) : [];
  const alerts = buildAlerts(buildingModel);
  const mix = buildingModel
    ? countTypology(buildingModel.model_json)
    : formatTypologyMix(project?.brief?.mix_typologique ?? {});

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
              <span className="text-sm text-slate-500 truncate max-w-xs">{project.name}</span>
            )}
            {project && (
              <Badge
                className="text-xs border-transparent shrink-0"
                style={{ backgroundColor: "#dcfce7", color: "#15803d" }}
              >
                {statusLabel(project.status)}
              </Badge>
            )}
            {buildingModel && (
              <Badge
                className="text-xs border-transparent shrink-0"
                style={{ backgroundColor: "#e0f2fe", color: "#075985" }}
              >
                BM v{buildingModel.version}
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
            {buildingModel && <ReportExportButton resultId={buildingModel.id} />}
          </div>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-8">
        {loading && <div className="py-20 text-center text-sm text-slate-400">Chargement…</div>}
        {error && <div className="py-20 text-center text-sm text-red-500">Erreur : {error}</div>}

        {!loading && !error && project && (
          <>
            {alerts.length > 0 && (
              <div className="mb-6">
                <ServitudesList alerts={alerts} />
              </div>
            )}

            {bmNotFound && (
              <div className="mb-6 rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                Aucun modèle bâtiment généré pour ce projet — le rapport affiche les objectifs du brief uniquement.
              </div>
            )}

            <Tabs defaultValue="synthese" className="space-y-6">
              <TabsList className="bg-white border border-slate-100 rounded-xl p-1 h-auto flex-wrap gap-1">
                <TabsTrigger value="synthese" className="rounded-lg text-sm">Synthèse</TabsTrigger>
                <TabsTrigger value="capacite" className="rounded-lg text-sm">Capacité</TabsTrigger>
                <TabsTrigger value="compliance" className="rounded-lg text-sm">Conformité</TabsTrigger>
                <TabsTrigger value="site" className="rounded-lg text-sm">Site</TabsTrigger>
                <TabsTrigger value="analyse" className="rounded-lg text-sm">Analyse</TabsTrigger>
              </TabsList>

              {/* Synthèse */}
              <TabsContent value="synthese" className="space-y-6">
                <FeasibilityDashboard kpis={kpis} />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <Card className="p-6 border-slate-100 shadow-none">
                    <TypologyChart data={mix} />
                  </Card>
                  <Card className="p-6 border-slate-100 shadow-none space-y-4">
                    <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                      Résumé
                    </h3>
                    {buildingModel ? (
                      <p className="text-sm text-slate-700 leading-relaxed">
                        {buildingSummary(buildingModel.model_json, countLogements(buildingModel.model_json))}
                      </p>
                    ) : (
                      <p className="text-sm text-slate-500 leading-relaxed">
                        Objectifs (brief) : {project.brief?.cible_sdp_m2 ?? "—"} m² SDP cible,{" "}
                        {project.brief?.cible_nb_logements ?? "—"} logements cible.
                      </p>
                    )}
                  </Card>
                </div>
              </TabsContent>

              {/* Capacité */}
              <TabsContent value="capacite" className="space-y-6">
                <FeasibilityDashboard kpis={kpis} />
                {buildingModel && (
                  <Card className="p-6 border-slate-100 shadow-none space-y-4">
                    <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                      Détail par niveau
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {buildingModel.model_json.niveaux.map((n) => {
                        const logs = n.cellules.filter((c) => c.type === "logement");
                        const typos = logs.map((c) => c.typologie).filter(Boolean).join(" · ");
                        return (
                          <div key={n.code} className="rounded-lg border border-slate-100 p-4 space-y-1">
                            <div className="flex items-baseline justify-between">
                              <span className="text-sm font-semibold text-slate-900">{n.code}</span>
                              <span className="text-xs text-slate-400">{n.usage_principal}</span>
                            </div>
                            <div className="text-xs text-slate-500">
                              {logs.length} logement{logs.length > 1 ? "s" : ""} — {Math.round(n.surface_plancher_m2)} m²
                              {typos && <span className="ml-1">· {typos}</span>}
                            </div>
                            <div className="text-xs text-slate-400">
                              HSP {n.hauteur_sous_plafond_m} m
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </Card>
                )}
                <Card className="p-6 border-slate-100 shadow-none">
                  <TypologyChart data={mix} />
                </Card>
              </TabsContent>

              {/* Conformité */}
              <TabsContent value="compliance" className="space-y-6">
                {buildingModel?.conformite_check ? (
                  <Card className="p-6 border-slate-100 shadow-none">
                    <ComplianceSummary
                      incendie={buildingModel.conformite_check.incendie_distance_sorties_ok ? "Distance sorties OK" : "Distance sorties à revoir"}
                      pmr_ascenseur={buildingModel.conformite_check.pmr_ascenseur_ok}
                      re2020_seuil="—"
                      lls_statut="—"
                      rsdu_obligations={[]}
                    />
                  </Card>
                ) : (
                  <Card className="p-6 border-slate-100 shadow-none text-sm text-slate-400">
                    Conformité non disponible — aucun modèle bâtiment généré.
                  </Card>
                )}
                {buildingModel?.conformite_check?.alerts && buildingModel.conformite_check.alerts.length > 0 && (
                  <Card className="p-6 border-slate-100 shadow-none space-y-3">
                    <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                      Alertes détaillées ({buildingModel.conformite_check.alerts.length})
                    </h3>
                    <div className="max-h-80 overflow-y-auto divide-y divide-slate-100">
                      {buildingModel.conformite_check.alerts.map((a, i) => (
                        <div key={i} className="py-2 text-xs">
                          <span
                            className="inline-block uppercase tracking-wider font-semibold mr-2"
                            style={{
                              color: a.level === "error" ? "var(--ac-red)" : a.level === "warning" ? "var(--ac-amber)" : "var(--ac-blue)",
                            }}
                          >
                            {a.level}
                          </span>
                          <span className="text-slate-700">{a.message}</span>
                          <span className="ml-2 text-slate-400">[{a.category}]</span>
                        </div>
                      ))}
                    </div>
                  </Card>
                )}
              </TabsContent>

              {/* Site */}
              <TabsContent value="site" className="space-y-6">
                <Card className="p-6 border-slate-100 shadow-none space-y-4">
                  <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider flex items-center gap-2">
                    <MapPin className="h-4 w-4" /> Parcelle & site
                  </h3>
                  {buildingModel ? (
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Adresse</div>
                        <div className="font-semibold text-slate-900 mt-0.5">{buildingModel.model_json.metadata.address}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Zone PLU</div>
                        <div className="font-semibold text-slate-900 mt-0.5">{buildingModel.model_json.metadata.zone_plu}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Surface parcelle</div>
                        <div className="font-semibold text-slate-900 mt-0.5">
                          {Math.round(buildingModel.model_json.site.parcelle_surface_m2)} m²
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Voirie</div>
                        <div className="font-semibold text-slate-900 mt-0.5">
                          {buildingModel.model_json.site.voirie_orientations.join(", ")}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Projet</div>
                        <div className="font-semibold text-slate-900 mt-0.5">{project.name}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Destination</div>
                        <div className="font-semibold text-slate-900 mt-0.5">{project.brief?.destination ?? "—"}</div>
                      </div>
                    </div>
                  )}
                </Card>

                <Card className="p-6 border-slate-100 shadow-none space-y-3">
                  <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider flex items-center gap-2">
                    <Building2 className="h-4 w-4" /> Programme cible (brief)
                  </h3>
                  {project.brief ? (
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Destination</div>
                        <div className="font-semibold text-slate-900 mt-0.5">{project.brief.destination}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">SDP cible</div>
                        <div className="font-semibold text-slate-900 mt-0.5">
                          {project.brief.cible_sdp_m2 ?? "—"} {project.brief.cible_sdp_m2 != null && "m²"}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-400 uppercase tracking-wider">Logements cible</div>
                        <div className="font-semibold text-slate-900 mt-0.5">{project.brief.cible_nb_logements ?? "—"}</div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-400">Pas de brief renseigné.</p>
                  )}
                </Card>
              </TabsContent>

              {/* Analyse */}
              <TabsContent value="analyse">
                <Card className="p-6 border-slate-100 shadow-none">
                  <ArchitectureNoteRenderer
                    markdown={buildingModel
                      ? [
                          `## Synthèse — ${project.name}`,
                          "",
                          buildingSummary(buildingModel.model_json, countLogements(buildingModel.model_json)),
                          "",
                          "## Programme (brief)",
                          "",
                          `- Destination : ${project.brief?.destination ?? "—"}`,
                          `- Cible SDP : ${project.brief?.cible_sdp_m2 ?? "—"} m²`,
                          `- Cible logements : ${project.brief?.cible_nb_logements ?? "—"}`,
                          "",
                          "## Conformité",
                          "",
                          `- ${buildingModel.conformite_check?.alerts.length ?? 0} alertes détectées par \`validate_all\``,
                          `- PMR ascenseur : ${buildingModel.conformite_check?.pmr_ascenseur_ok ? "OK" : "À revoir"}`,
                          `- PLU emprise : ${buildingModel.conformite_check?.plu_emprise_ok ? "OK" : "À revoir"}`,
                        ].join("\n")
                      : `## ${project.name}\n\nModèle bâtiment pas encore généré.`}
                  />
                </Card>
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>
    </main>
  );
}
