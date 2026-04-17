"use client";

import Link from "next/link";
import { use } from "react";
import { useFeasibility } from "@/lib/hooks/useFeasibility";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FeasibilityDashboard, type KPI } from "@/components/panels/FeasibilityDashboard";
import { ServitudesList } from "@/components/panels/ServitudesList";
import { ArrowLeft, FileText } from "lucide-react";
import type { Project, FeasibilityResult } from "@/lib/types";

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

function buildKPIs(result: FeasibilityResult): KPI[] {
  return [
    { label: "SDP", value: result.sdp_m2 ?? "—", unit: result.sdp_m2 != null ? "m²" : undefined },
    { label: "Niveaux", value: result.niveaux ?? "—" },
    { label: "Logements", value: result.nb_logements ?? "—" },
    { label: "Stationnement", value: result.stationnement ?? "—", unit: result.stationnement != null ? "pl." : undefined },
    { label: "Emprise", value: result.emprise_pct != null ? `${result.emprise_pct}%` : "—" },
    { label: "Pleine terre", value: result.pleine_terre_pct != null ? `${result.pleine_terre_pct}%` : "—" },
  ];
}

// Placeholder result for when backend returns no feasibility yet
const PLACEHOLDER_RESULT: FeasibilityResult = {
  id: "placeholder",
  project_id: "",
  status: "pending",
};

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { project, loading, error } = useFeasibility(id);

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

              {project.status === "analyzed" && (
                <Link href={`/projects/${id}/report`}>
                  <Button
                    className="gap-2 text-white font-medium"
                    style={{ backgroundColor: "var(--ac-primary)" }}
                  >
                    <FileText className="h-4 w-4" />
                    Voir le rapport
                  </Button>
                </Link>
              )}
            </div>

            {/* KPI Dashboard */}
            {project.status === "analyzed" ? (
              <section className="space-y-4">
                <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                  Indicateurs clés
                </h2>
                <FeasibilityDashboard kpis={buildKPIs(PLACEHOLDER_RESULT)} />
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

            {/* Alerts preview */}
            <ServitudesList alerts={[]} />

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
