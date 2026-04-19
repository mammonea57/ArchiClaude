"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, FolderOpen } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { PcmiGenerator } from "@/components/pcmi/PcmiGenerator";
import { SituationMapSelector } from "@/components/pcmi/SituationMapSelector";
import { PcmiPreview } from "@/components/pcmi/PcmiPreview";
import { PcmiDownloadButtons } from "@/components/pcmi/PcmiDownloadButtons";
import { RevisionHistory } from "@/components/pcmi/RevisionHistory";

export default function PcmiPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  return (
    <main className="min-h-screen bg-slate-50">
      {/* Navigation */}
      <nav className="border-b border-slate-100 bg-white px-6 py-4 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link
              href="/"
              className="font-display text-xl font-semibold text-slate-900 shrink-0"
            >
              ArchiClaude
            </Link>
            <Separator orientation="vertical" className="h-5" />
            <Link
              href="/projects"
              className="text-sm text-slate-500 hover:text-slate-700 transition-colors shrink-0"
            >
              Projets
            </Link>
            <Separator orientation="vertical" className="h-5" />
            <Link
              href={`/projects/${id}`}
              className="text-sm text-slate-500 hover:text-slate-700 transition-colors truncate max-w-[160px]"
            >
              Projet
            </Link>
          </div>
          <Link
            href={`/projects/${id}`}
            className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-700 transition-colors shrink-0"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Tableau de bord
          </Link>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        {/* Breadcrumb */}
        <nav aria-label="Fil d'Ariane" className="flex items-center gap-2 text-sm text-slate-400">
          <Link href={`/projects/${id}`} className="hover:text-slate-700 transition-colors">
            Projet
          </Link>
          <span>/</span>
          <span className="text-slate-700 font-medium">Dossier PC</span>
        </nav>

        {/* Page header */}
        <div className="flex items-start gap-3">
          <div
            className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
            style={{ backgroundColor: "var(--ac-primary)" }}
          >
            <FolderOpen className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold text-slate-900">
              Dossier PC complet
            </h1>
            <p className="mt-0.5 text-sm text-slate-500">
              Générez et téléchargez l&apos;ensemble des pièces graphiques du permis de construire.
            </p>
          </div>
        </div>

        {/* Card: Generator + Map selector + Downloads */}
        <Card className="p-6 border-slate-100 shadow-none space-y-5">
          <div className="flex flex-wrap items-end gap-6">
            <SituationMapSelector projectId={id} defaultValue="scan25" />
            <PcmiGenerator projectId={id} />
          </div>
          <Separator />
          <PcmiDownloadButtons projectId={id} />
        </Card>

        {/* Card: Preview */}
        <Card className="p-6 border-slate-100 shadow-none space-y-4">
          <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
            Aperçu des pièces
          </h2>
          <PcmiPreview projectId={id} />
        </Card>

        {/* Card: Revision history */}
        <Card className="p-6 border-slate-100 shadow-none space-y-4">
          <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
            Historique des révisions
          </h2>
          <RevisionHistory revisions={[]} />
        </Card>

        {/* Card: PCMI6 insertion paysagère */}
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-4">
            PCMI6 — Insertion paysagère
          </h2>
          <p className="text-sm text-slate-500 mb-3">
            Photomontage du projet intégré dans son environnement.
          </p>
          <Link
            href={`/projects/${id}/pcmi6`}
            className="inline-flex items-center gap-2 text-sm text-teal-600 hover:underline"
          >
            Créer / modifier le PCMI6 →
          </Link>
        </div>
      </div>
    </main>
  );
}
