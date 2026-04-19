"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";

const PLAN_TYPES: { key: string; label: string }[] = [
  { key: "masse", label: "Plan de masse" },
  { key: "niveau_0", label: "Niveau 0 (RDC)" },
  { key: "niveau_1", label: "Niveau 1" },
  { key: "coupe", label: "Coupe" },
  { key: "facade_rue", label: "Façade rue" },
  { key: "facade_arriere", label: "Façade arrière" },
];

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function PlansPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <Link href="/" className="font-display text-xl font-semibold text-slate-900">
            ArchiClaude
          </Link>
          <Link href="/projects" className="text-sm text-slate-500 hover:text-slate-700">
            Mes projets
          </Link>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-10 space-y-6">
        <Link
          href={`/projects/${id}`}
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-700"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour au projet
        </Link>

        <h1 className="font-display text-3xl font-bold text-slate-900">Plans</h1>
        <p className="text-sm text-slate-500">
          Plans générés par le moteur de programmation (v1 : géométrie placeholder). Export DXF disponible pour chaque plan.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {PLAN_TYPES.map((p) => (
            <div
              key={p.key}
              className="bg-white border border-slate-200 rounded-xl overflow-hidden"
            >
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                <h2 className="text-sm font-semibold text-slate-700">{p.label}</h2>
                <a
                  href={`${API_BASE}/api/v1/projects/${id}/plans/${p.key}/dxf`}
                  download
                  className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                >
                  <Download className="h-3.5 w-3.5" />
                  DXF
                </a>
              </div>
              <div className="bg-slate-50 p-4 flex items-center justify-center min-h-[280px]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`${API_BASE}/api/v1/projects/${id}/plans/${p.key}`}
                  alt={p.label}
                  className="max-w-full max-h-[400px]"
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
