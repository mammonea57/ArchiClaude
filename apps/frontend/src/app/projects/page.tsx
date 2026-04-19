"use client";

import Link from "next/link";
import { useProjects } from "@/lib/hooks/useProjects";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Project } from "@/lib/types";

function statusLabel(status: Project["status"]): string {
  switch (status) {
    case "draft":
      return "Brouillon";
    case "analyzed":
      return "Analysé";
    case "archived":
      return "Archivé";
  }
}

function StatusBadge({ status }: { status: Project["status"] }) {
  if (status === "analyzed") {
    return (
      <Badge
        className="text-xs border-transparent"
        style={{ backgroundColor: "#dcfce7", color: "#15803d" }}
      >
        {statusLabel(status)}
      </Badge>
    );
  }
  if (status === "archived") {
    return (
      <Badge
        className="text-xs border-transparent"
        style={{ backgroundColor: "#f1f5f9", color: "#64748b" }}
      >
        {statusLabel(status)}
      </Badge>
    );
  }
  // draft
  return (
    <Badge
      className="text-xs border-transparent"
      style={{ backgroundColor: "#f1f5f9", color: "#475569" }}
    >
      {statusLabel(status)}
    </Badge>
  );
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

export default function ProjectsPage() {
  const { projects, loading, error } = useProjects();

  return (
    <main className="min-h-screen bg-slate-50">
      {/* Navigation */}
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <Link href="/" className="font-display text-xl font-semibold text-slate-900">
            ArchiClaude
          </Link>
          <Link
            href="/account"
            className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
          >
            Mon compte
          </Link>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-10">
        {/* Page header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="font-display text-3xl font-bold text-slate-900">Mes projets</h1>
          <Link href="/projects/new">
            <Button
              className="text-white font-medium gap-2"
              style={{ backgroundColor: "var(--ac-primary)" }}
            >
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Nouveau projet
            </Button>
          </Link>
        </div>

        {/* States */}
        {loading && (
          <div className="py-20 text-center text-sm text-slate-400">Chargement…</div>
        )}

        {error && (
          <div className="py-20 text-center text-sm text-red-500">
            Erreur : {error}
          </div>
        )}

        {!loading && !error && projects.length === 0 && (
          <div className="py-24 text-center">
            <p className="text-slate-500 text-sm mb-6">
              Aucun projet — créez votre premier projet
            </p>
            <Link href="/projects/new">
              <Button
                className="text-white font-medium"
                style={{ backgroundColor: "var(--ac-primary)" }}
              >
                Nouveau projet
              </Button>
            </Link>
          </div>
        )}

        {!loading && !error && projects.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white shadow-none overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="text-left px-5 py-3 font-medium text-xs uppercase tracking-wider text-slate-400">
                    Projet
                  </th>
                  <th className="text-left px-5 py-3 font-medium text-xs uppercase tracking-wider text-slate-400">
                    Statut
                  </th>
                  <th className="text-left px-5 py-3 font-medium text-xs uppercase tracking-wider text-slate-400">
                    Confiance
                  </th>
                  <th className="text-left px-5 py-3 font-medium text-xs uppercase tracking-wider text-slate-400">
                    Créé le
                  </th>
                </tr>
              </thead>
              <tbody>
                {projects.map((project, idx) => (
                  <tr
                    key={project.id}
                    className={`hover:bg-slate-50 transition-colors ${
                      idx < projects.length - 1 ? "border-b border-slate-100" : ""
                    }`}
                  >
                    <td className="px-5 py-4">
                      <Link
                        href={`/projects/${project.id}`}
                        className="font-medium text-slate-900 hover:underline"
                        style={{ textDecorationColor: "var(--ac-primary)" }}
                      >
                        {project.name}
                      </Link>
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge status={project.status} />
                    </td>
                    <td className="px-5 py-4">
                      {project.status === "analyzed" && project.confidence_score != null ? (
                        <span className="text-slate-700 tabular-nums">
                          {Math.round(project.confidence_score * 100)}&thinsp;%
                        </span>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className="px-5 py-4 text-slate-500">
                      {project.created_at ? formatDate(project.created_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
