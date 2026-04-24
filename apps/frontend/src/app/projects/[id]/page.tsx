"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useFeasibility } from "@/lib/hooks/useFeasibility";
import { useBuildingModel } from "@/lib/hooks/useBuildingModel";
import { apiFetch } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FeasibilityDashboard, type KPI } from "@/components/panels/FeasibilityDashboard";
import { ServitudesList, type Alert } from "@/components/panels/ServitudesList";
import { useRouter } from "next/navigation";
import { ArrowLeft, Calculator, Copy, FileText, LayoutGrid, Play, Loader2, Trash2 } from "lucide-react";
import type { Project, BuildingModelRow, BuildingModelPayload } from "@/lib/types";

function statusLabel(status: Project["status"]): string {
  switch (status) {
    case "draft":     return "Brouillon";
    case "analyzed":  return "Analysé";
    case "archived":  return "Archivé";
  }
}

function StatusBadge({ status }: { status: Project["status"] }) {
  const styles: Record<Project["status"], { bg: string; color: string }> = {
    analyzed: { bg: "#dcfce7", color: "#15803d" },
    draft:    { bg: "#f1f5f9", color: "#475569" },
    archived: { bg: "#f1f5f9", color: "#64748b" },
  };
  const s = styles[status];
  return (
    <Badge className="text-xs border-transparent" style={{ backgroundColor: s.bg, color: s.color }}>
      {statusLabel(status)}
    </Badge>
  );
}

function countLogements(bm: BuildingModelPayload): number {
  return bm.niveaux.reduce(
    (acc, n) => acc + n.cellules.filter((c) => c.type === "logement").length,
    0,
  );
}

function sumSdp(bm: BuildingModelPayload): number {
  return bm.niveaux.reduce((acc, n) => acc + n.surface_plancher_m2, 0);
}

function empriseMetric(bm: BuildingModelPayload): string {
  const parcelle = bm.site.parcelle_surface_m2 ?? 0;
  if (!parcelle) return "—";
  return `${Math.round((bm.envelope.emprise_m2 / parcelle) * 100)}%`;
}

function buildKPIs(project: Project, bm: BuildingModelRow | null): KPI[] {
  const b = project.brief;
  const mix = b?.mix_typologique ?? {};
  const typoCount = Object.values(mix).filter((v) => Number(v) > 0).length;

  if (bm) {
    const m = bm.model_json;
    const sdp = Math.round(sumSdp(m));
    return [
      { label: "SDP", value: sdp, unit: "m²" },
      { label: "Niveaux", value: m.envelope.niveaux },
      { label: "Logements", value: countLogements(m) },
      { label: "Typologies", value: typoCount > 0 ? typoCount : "—" },
      { label: "Emprise", value: empriseMetric(m) },
      { label: "Hauteur", value: m.envelope.hauteur_totale_m, unit: "m" },
    ];
  }

  // Fallback: brief targets only (no building model generated yet)
  return [
    {
      label: "SDP cible",
      value: b?.cible_sdp_m2 ?? "—",
      unit: b?.cible_sdp_m2 != null ? "m²" : undefined,
    },
    { label: "Niveaux cible", value: b?.hauteur_cible_niveaux ?? "—" },
    { label: "Logements cible", value: b?.cible_nb_logements ?? "—" },
    { label: "Typologies", value: typoCount > 0 ? typoCount : "—" },
    {
      label: "Emprise cible",
      value: b?.emprise_cible_pct != null ? `${b.emprise_cible_pct}%` : "—",
    },
    {
      label: "Pleine terre cible",
      value:
        b?.espaces_verts_pleine_terre_cible_pct != null
          ? `${b.espaces_verts_pleine_terre_cible_pct}%`
          : "—",
    },
  ];
}

function buildAlerts(bm: BuildingModelRow | null): Alert[] {
  if (!bm?.conformite_check?.alerts) return [];
  const ALERT_LEVEL: Record<"info" | "warning" | "error", Alert["level"]> = {
    info: "info",
    warning: "warning",
    error: "critical",
  };
  return bm.conformite_check.alerts.slice(0, 10).map((a) => ({
    level: ALERT_LEVEL[a.level],
    type: a.category,
    message: a.message,
  }));
}

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { project, loading, error } = useFeasibility(id);
  const { buildingModel, notFound: bmNotFound } = useBuildingModel(id);
  const [analyzing, setAnalyzing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleAnalyze() {
    setAnalyzing(true);
    setActionError(null);
    try {
      await apiFetch(`/projects/${id}/analyze`, { method: "POST" });
      // Reload to show the freshly-generated BM + analyzed status.
      window.location.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Erreur lors de l'analyse");
      setAnalyzing(false);
    }
  }

  async function handleDuplicate() {
    setDuplicating(true);
    setActionError(null);
    try {
      const resp = await apiFetch<{ id: string }>(`/projects/${id}/duplicate`, { method: "POST" });
      router.push(`/projects/${resp.id}`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Erreur lors de la duplication");
      setDuplicating(false);
    }
  }

  async function handleDelete() {
    if (!confirm("Supprimer ce projet ? Cette action est irréversible et effacera tous les plans et bilans associés.")) {
      return;
    }
    setDeleting(true);
    setActionError(null);
    try {
      await apiFetch(`/projects/${id}`, { method: "DELETE" });
      router.push("/projects");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Erreur lors de la suppression");
      setDeleting(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <Link href="/" className="font-display text-xl font-semibold text-slate-900">
            ArchiClaude
          </Link>
          <Link href="/account" className="text-sm text-slate-500 hover:text-slate-700 transition-colors">
            Mon compte
          </Link>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-10 space-y-8">
        <Link
          href="/projects"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-700 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Mes projets
        </Link>

        {loading && (
          <div className="py-20 text-center text-sm text-slate-400">Chargement…</div>
        )}

        {error && (
          <div className="py-20 text-center text-sm text-red-500">Erreur : {error}</div>
        )}

        {!loading && !error && project && (
          <>
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-3 flex-wrap">
                  <h1 className="font-display text-3xl font-bold text-slate-900">{project.name}</h1>
                  <StatusBadge status={project.status} />
                  {buildingModel && (
                    <Badge
                      className="text-xs border-transparent"
                      style={{ backgroundColor: "#e0f2fe", color: "#075985" }}
                    >
                      BM v{buildingModel.version}
                    </Badge>
                  )}
                </div>
                {project.confidence_score != null && (
                  <p className="text-sm text-slate-400">
                    Confiance d&apos;analyse&thinsp;:{" "}
                    <span className="font-semibold text-slate-700">
                      {Math.round(project.confidence_score * 100)}&thinsp;%
                    </span>
                  </p>
                )}
              </div>

              <div className="flex gap-2 flex-wrap">
                {project.status !== "analyzed" && (
                  <Button
                    className="gap-2 text-white font-medium"
                    onClick={handleAnalyze}
                    disabled={analyzing}
                    style={{ backgroundColor: "var(--ac-primary)" }}
                  >
                    {analyzing ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Analyse en cours…
                      </>
                    ) : (
                      <>
                        <Play className="h-4 w-4" />
                        Lancer l&apos;analyse
                      </>
                    )}
                  </Button>
                )}
                {project.status === "analyzed" && (
                  <>
                    <Link href={`/projects/${id}/plans`}>
                      <Button variant="outline" className="gap-2 font-medium">
                        <LayoutGrid className="h-4 w-4" />
                        Plans
                      </Button>
                    </Link>
                    <Link href={`/projects/${id}/bilan`}>
                      <Button variant="outline" className="gap-2 font-medium">
                        <Calculator className="h-4 w-4" />
                        Bilan
                      </Button>
                    </Link>
                    <Link href={`/projects/${id}/report`}>
                      <Button
                        className="gap-2 text-white font-medium"
                        style={{ backgroundColor: "var(--ac-primary)" }}
                      >
                        <FileText className="h-4 w-4" />
                        Voir le rapport
                      </Button>
                    </Link>
                  </>
                )}
                <Button
                  variant="outline"
                  className="gap-2 font-medium"
                  onClick={handleDuplicate}
                  disabled={duplicating}
                >
                  {duplicating ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                  Dupliquer
                </Button>
                <Button
                  variant="outline"
                  className="gap-2 font-medium"
                  onClick={handleDelete}
                  disabled={deleting}
                  style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                >
                  {deleting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Supprimer
                </Button>
              </div>
            </div>
            {actionError && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {actionError}
              </div>
            )}

            {/* KPI Dashboard */}
            {project.status === "analyzed" ? (
              <section className="space-y-4">
                <div className="flex items-baseline justify-between flex-wrap gap-2">
                  <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                    {buildingModel ? "Indicateurs modèle bâtiment" : "Objectifs (brief)"}
                  </h2>
                  {bmNotFound && (
                    <p className="text-xs text-slate-400">
                      Modèle bâtiment pas encore généré — affichage des objectifs du brief.
                    </p>
                  )}
                </div>
                <FeasibilityDashboard kpis={buildKPIs(project, buildingModel)} />
              </section>
            ) : (
              <div className="rounded-xl border border-slate-100 bg-white p-10 text-center space-y-3">
                <p className="text-slate-400 text-sm">
                  L&apos;analyse de faisabilité n&apos;a pas encore été lancée pour ce projet.
                </p>
                <p className="text-slate-300 text-xs">
                  Les indicateurs apparaîtront ici une fois l&apos;analyse complète.
                </p>
              </div>
            )}

            {/* Conformité alerts */}
            <ServitudesList alerts={buildAlerts(buildingModel)} />

            {/* Quick links */}
            {project.status === "analyzed" && (
              <div className="flex justify-end">
                <Link href={`/projects/${id}/report`}>
                  <Button variant="outline" className="gap-2 text-sm">
                    <FileText className="h-4 w-4" />
                    Rapport complet interactif
                  </Button>
                </Link>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
