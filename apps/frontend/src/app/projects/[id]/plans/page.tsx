"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";
import { useBuildingModel } from "@/lib/hooks/useBuildingModel";
import { NiveauPlan } from "@/components/plans/NiveauPlan";
import { PlanMasse } from "@/components/plans/PlanMasse";
import { CoupeElevation } from "@/components/plans/CoupeElevation";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function PlansPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { buildingModel, loading, error, notFound } = useBuildingModel(id);

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

        <div className="space-y-1">
          <h1 className="font-display text-3xl font-bold text-slate-900">Plans</h1>
          <p className="text-sm text-slate-500">
            Plans générés depuis le modèle bâtiment (SP2-v2a) : masse, niveaux, coupe et façade.
          </p>
        </div>

        {loading && <div className="py-20 text-center text-sm text-slate-400">Chargement…</div>}
        {error && <div className="py-20 text-center text-sm text-red-500">Erreur : {error}</div>}

        {notFound && !loading && (
          <div className="rounded-xl border border-slate-100 bg-white p-10 text-center space-y-3">
            <p className="text-slate-500 text-sm">
              Aucun modèle bâtiment n&apos;a encore été généré pour ce projet.
            </p>
          </div>
        )}

        {buildingModel && (
          <>
            {/* Summary row */}
            <section className="rounded-xl border border-slate-100 bg-white px-5 py-4 text-sm flex items-center justify-between flex-wrap gap-3">
              <div className="flex flex-wrap gap-6 text-slate-600">
                <span>
                  Version <span className="font-semibold text-slate-900">v{buildingModel.version}</span>
                </span>
                <span>
                  Niveaux <span className="font-semibold text-slate-900">{buildingModel.model_json.envelope.niveaux}</span>
                </span>
                <span>
                  Hauteur <span className="font-semibold text-slate-900">{buildingModel.model_json.envelope.hauteur_totale_m} m</span>
                </span>
                <span>
                  Emprise <span className="font-semibold text-slate-900">{Math.round(buildingModel.model_json.envelope.emprise_m2)} m²</span>
                </span>
              </div>
              <span className="text-xs text-slate-400">
                {new Date(buildingModel.generated_at).toLocaleString("fr-FR")}
              </span>
            </section>

            <Tabs defaultValue="masse" className="space-y-4">
              <TabsList className="bg-white border border-slate-100 rounded-xl p-1 h-auto flex-wrap gap-1">
                <TabsTrigger value="masse" className="rounded-lg text-sm">Plan de masse</TabsTrigger>
                <TabsTrigger value="niveaux" className="rounded-lg text-sm">Plans de niveau</TabsTrigger>
                <TabsTrigger value="coupe" className="rounded-lg text-sm">Coupe</TabsTrigger>
                <TabsTrigger value="facade" className="rounded-lg text-sm">Façade</TabsTrigger>
              </TabsList>

              <TabsContent value="masse">
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                    <h2 className="text-sm font-semibold text-slate-700">Plan de masse</h2>
                    <a
                      href={`${API_BASE}/api/v1/projects/${id}/plans/masse/dxf`}
                      download
                      className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                    >
                      <Download className="h-3.5 w-3.5" /> DXF
                    </a>
                  </div>
                  <div className="p-4 flex justify-center bg-slate-50">
                    <PlanMasse bm={buildingModel.model_json} width={760} height={480} />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="niveaux">
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                  {buildingModel.model_json.niveaux.map((niv) => {
                    const logementCount = niv.cellules.filter((c) => c.type === "logement").length;
                    return (
                      <div key={niv.code} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                          <div>
                            <h2 className="text-sm font-semibold text-slate-700">
                              {niv.code}
                              <span className="ml-2 text-xs font-normal text-slate-400">
                                {niv.usage_principal} — {logementCount} logement{logementCount > 1 ? "s" : ""}
                              </span>
                            </h2>
                          </div>
                          <a
                            href={`${API_BASE}/api/v1/projects/${id}/plans/niveau_${niv.index}/dxf`}
                            download
                            className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                          >
                            <Download className="h-3.5 w-3.5" /> DXF
                          </a>
                        </div>
                        <div className="p-3 flex justify-center bg-slate-50">
                          <NiveauPlan niveau={niv} width={580} height={360} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </TabsContent>

              <TabsContent value="coupe">
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                    <h2 className="text-sm font-semibold text-slate-700">Coupe longitudinale</h2>
                    <a
                      href={`${API_BASE}/api/v1/projects/${id}/plans/coupe/dxf`}
                      download
                      className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                    >
                      <Download className="h-3.5 w-3.5" /> DXF
                    </a>
                  </div>
                  <div className="p-4 flex justify-center bg-slate-50">
                    <CoupeElevation bm={buildingModel.model_json} mode="coupe" width={760} height={440} />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="facade">
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                    <h2 className="text-sm font-semibold text-slate-700">Façade principale ({buildingModel.model_json.site.voirie_orientations[0] ?? "sud"})</h2>
                    <a
                      href={`${API_BASE}/api/v1/projects/${id}/plans/facade_rue/dxf`}
                      download
                      className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                    >
                      <Download className="h-3.5 w-3.5" /> DXF
                    </a>
                  </div>
                  <div className="p-4 flex justify-center bg-slate-50">
                    <CoupeElevation bm={buildingModel.model_json} mode="facade" width={760} height={440} />
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>
    </main>
  );
}
