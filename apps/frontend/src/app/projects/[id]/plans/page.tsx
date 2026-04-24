"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Download, Expand, Pencil, Save, Trash2, X } from "lucide-react";
import { useBuildingModel } from "@/lib/hooks/useBuildingModel";
import { useFeasibility } from "@/lib/hooks/useFeasibility";
import { useBilan } from "@/lib/hooks/useBilan";
import { NiveauPlan } from "@/components/plans/NiveauPlan";
import { PlanMasse } from "@/components/plans/PlanMasse";
import { CoupeElevation } from "@/components/plans/CoupeElevation";
import { Axonometrie } from "@/components/plans/Axonometrie";
import { TableauxSurfacesPLU } from "@/components/plans/TableauxSurfacesPLU";
import { PlanSituation } from "@/components/plans/PlanSituation";
import { Photomontages } from "@/components/plans/Photomontages";
import { EtudeOmbres } from "@/components/plans/EtudeOmbres";
import { NoticePC4 } from "@/components/plans/NoticePC4";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogTitle,
} from "@/components/ui/dialog";
import type { BuildingModelNiveau } from "@/lib/types";
import { apiFetch } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TYPOS = ["STUDIO", "T1", "T2", "T3", "T4", "T5"] as const;

/** Extract "80" from "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne". */
function deriveNumber(address: string): string {
  const m = address.match(/^\s*(\d+[a-zA-Z]?(?:\s?bis|\s?ter)?)\s/);
  return m?.[1] ?? "—";
}

/** Extract "Rue des Héros Nogentais" from the full address. */
function deriveStreetName(address: string): string {
  const m = address.match(/^\s*\d+[a-zA-Z]?(?:\s?bis|\s?ter)?\s+(.+?)(?:\s+\d{5}|\s*,|$)/);
  return m?.[1] ?? address;
}

export default function PlansPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { buildingModel, loading, error, notFound, refresh } = useBuildingModel(id);
  const { project } = useFeasibility(id);
  const { bilan } = useBilan(id);
  const addressForPlan = project?.name ?? buildingModel?.model_json?.metadata?.address ?? "";
  const [openNiveau, setOpenNiveau] = useState<BuildingModelNiveau | null>(null);
  const [openKind, setOpenKind] = useState<"niveau" | "masse" | "coupe" | "facade" | null>(null);
  const [showCotations, setShowCotations] = useState(false);
  const [selectedAptId, setSelectedAptId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [pendingOpenings, setPendingOpenings] = useState<Record<string, number>>({});
  const [selectedOpeningId, setSelectedOpeningId] = useState<string | null>(null);
  const [pendingDeleteOpenings, setPendingDeleteOpenings] = useState<string[]>([]);
  const [addOpeningType, setAddOpeningType] = useState<"fenetre" | "porte_fenetre" | "porte_interieure" | null>(null);
  const [pendingAddOpenings, setPendingAddOpenings] = useState<Array<{
    type: "fenetre" | "porte_fenetre" | "porte_interieure";
    wall_id: string;
    position_along_wall_cm: number;
  }>>([]);
  const [selectedWallId, setSelectedWallId] = useState<string | null>(null);
  const [pendingDeleteWalls, setPendingDeleteWalls] = useState<string[]>([]);
  // wallOverrides = live geometry while dragging; committed on save
  const [wallOverrides, setWallOverrides] = useState<Record<string, [number, number][]>>({});
  // roomOverrides = polygons updated live when adjacent walls move
  const [roomOverrides, setRoomOverrides] = useState<Record<string, [number, number][]>>({});
  // Core + corridor editing state
  const [selectedCoreElement, setSelectedCoreElement] = useState<"escalier" | "ascenseur" | "palier" | null>(null);
  const [escalierCenter, setEscalierCenter] = useState<[number, number] | null>(null);
  const [ascCenter, setAscCenter] = useState<[number, number] | null>(null);
  const [palierCenter, setPalierCenter] = useState<[number, number] | null>(null);
  const [selectedCoreSide, setSelectedCoreSide] = useState<{ el: "escalier" | "ascenseur" | "palier"; side: string } | null>(null);
  const [selectedCirculationEdge, setSelectedCirculationEdge] = useState<number | null>(null);
  const [selectedCirculationId, setSelectedCirculationId] = useState<string | null>(null);
  const [circulationOverrides, setCirculationOverrides] = useState<Record<string, [number, number][]>>({});
  const [pendingDeleteCirculations, setPendingDeleteCirculations] = useState<string[]>([]);

  // Footprint ring (Coord[]) — derived once for cotations + cuts overlays
  const footprintRing = useMemo<[number, number][] | undefined>(() => {
    const g = buildingModel?.model_json?.envelope?.footprint_geojson as { coordinates?: number[][][] } | undefined;
    const ring = g?.coordinates?.[0];
    if (!Array.isArray(ring)) return undefined;
    return ring
      .filter((p): p is [number, number] => Array.isArray(p) && p.length >= 2 && typeof p[0] === "number" && typeof p[1] === "number")
      .map((p) => [p[0], p[1]] as [number, number]);
  }, [buildingModel]);

  // Find the selected apt across all floors
  const selectedApt = useMemo(() => {
    if (!buildingModel || !selectedAptId) return null;
    for (const niv of buildingModel.model_json.niveaux) {
      const c = niv.cellules.find((c) => c.id === selectedAptId);
      if (c) return c;
    }
    return null;
  }, [buildingModel, selectedAptId]);

  const [editTypo, setEditTypo] = useState<string>("");
  const [editLabels, setEditLabels] = useState<Record<string, string>>({});

  // Reset local edits when selection changes
  useMemo(() => {
    if (selectedApt) {
      setEditTypo(String(selectedApt.typologie || "").toUpperCase());
      const labels: Record<string, string> = {};
      for (const r of selectedApt.rooms ?? []) labels[r.id] = r.label_fr ?? "";
      setEditLabels(labels);
      setEditError(null);
    }
  }, [selectedAptId]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function savePatch(body: Record<string, unknown>) {
    setSaving(true);
    setEditError(null);
    try {
      const updated = await apiFetch<{ model_json: { niveaux: BuildingModelNiveau[] } }>(
        `/projects/${id}/building_model`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      // Refresh in-place (no page reload): re-fetch BM so all components
      // re-render with the new version. Reset all pending-edit buffers so
      // overrides are dropped in favour of the persisted geometry.
      await refresh();
      // If the dialog is open on a niveau, swap in the refreshed niveau so
      // the plan inside the dialog updates without needing to re-open it.
      if (openNiveau && updated?.model_json?.niveaux) {
        const n = updated.model_json.niveaux.find((x) => x.index === openNiveau.index);
        if (n) setOpenNiveau(n);
      }
      setPendingOpenings({});
      setPendingDeleteOpenings([]);
      setPendingAddOpenings([]);
      setPendingDeleteWalls([]);
      setWallOverrides({});
      setRoomOverrides({});
      setEscalierCenter(null);
      setAscCenter(null);
      setPalierCenter(null);
      setSelectedCoreElement(null);
      setCirculationOverrides({});
      setPendingDeleteCirculations([]);
      setSelectedOpeningId(null);
      setSelectedWallId(null);
      setAddOpeningType(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Erreur lors de la sauvegarde");
    } finally {
      setSaving(false);
    }
  }

  const handleSaveEdits = () => {
    if (!selectedApt) return;
    const body: Record<string, unknown> = { apt_id: selectedApt.id };
    const currentTypo = String(selectedApt.typologie || "").toUpperCase();
    if (editTypo && editTypo !== currentTypo) body.typologie = editTypo;
    const changedLabels: Record<string, string> = {};
    for (const r of selectedApt.rooms ?? []) {
      if ((editLabels[r.id] ?? "") !== (r.label_fr ?? "")) {
        changedLabels[r.id] = editLabels[r.id] ?? "";
      }
    }
    if (Object.keys(changedLabels).length) body.room_labels = changedLabels;
    if (!body.typologie && !body.room_labels) {
      setEditError("Aucune modification à enregistrer");
      return;
    }
    savePatch(body);
  };

  const handleDeleteApt = () => {
    if (!selectedApt) return;
    if (!confirm(`Supprimer l'appartement ${selectedApt.id} ?`)) return;
    savePatch({ apt_id: selectedApt.id, delete: true });
  };

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
            Plans générés depuis le modèle bâtiment (SP2-v2a) : masse, niveaux, coupe, façade et axonométrie.
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
            {/* Edit UI is integrated into the fullscreen Dialog (see end of file). */}
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

            <Tabs
              defaultValue={
                typeof window !== "undefined"
                  ? new URLSearchParams(window.location.search).get("tab") ?? "masse"
                  : "masse"
              }
              className="space-y-4"
            >
              <TabsList className="bg-white border border-slate-100 rounded-xl p-1 h-auto flex-wrap gap-1">
                <TabsTrigger value="masse" className="rounded-lg text-sm">Plan de masse</TabsTrigger>
                <TabsTrigger value="niveaux" className="rounded-lg text-sm">Plans de niveau</TabsTrigger>
                <TabsTrigger value="coupes" className="rounded-lg text-sm">Coupes</TabsTrigger>
                <TabsTrigger value="facades" className="rounded-lg text-sm">Façades</TabsTrigger>
                <TabsTrigger value="axo" className="rounded-lg text-sm">Axonométrie</TabsTrigger>
                <TabsTrigger value="tableaux" className="rounded-lg text-sm">Tableaux</TabsTrigger>
                <TabsTrigger value="situation" className="rounded-lg text-sm">Situation</TabsTrigger>
                <TabsTrigger value="photomontages" className="rounded-lg text-sm">Photomontages</TabsTrigger>
                <TabsTrigger value="ombres" className="rounded-lg text-sm">Ombres</TabsTrigger>
                <TabsTrigger value="notice" className="rounded-lg text-sm">Notice PC4</TabsTrigger>
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
                    <PlanMasse
                      bm={buildingModel.model_json}
                      width={820}
                      height={540}
                      streetName={deriveStreetName(addressForPlan)}
                      buildingNumber={deriveNumber(addressForPlan)}
                      showCutLines
                    />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="niveaux">
                <div className="flex items-center justify-end mb-3">
                  <label className="inline-flex items-center gap-2 text-xs text-slate-600 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={showCotations}
                      onChange={(e) => setShowCotations(e.target.checked)}
                      className="h-3.5 w-3.5 accent-teal-700"
                    />
                    Cotations PC (périmètre · pièces · ouvertures)
                  </label>
                </div>
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
                          <div className="flex items-center gap-3">
                            <button
                              type="button"
                              onClick={() => { setOpenNiveau(niv); setOpenKind("niveau"); }}
                              className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900"
                              title="Ouvrir en plein écran"
                            >
                              <Expand className="h-3.5 w-3.5" /> Ouvrir
                            </button>
                            <a
                              href={`${API_BASE}/api/v1/projects/${id}/plans/niveau_${niv.index}/dxf`}
                              download
                              className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                            >
                              <Download className="h-3.5 w-3.5" /> DXF
                            </a>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => { setOpenNiveau(niv); setOpenKind("niveau"); }}
                          className="w-full p-3 flex justify-center bg-slate-50 hover:bg-slate-100 transition-colors cursor-zoom-in"
                          title="Cliquer pour agrandir"
                        >
                          <NiveauPlan
                            niveau={niv}
                            corePosition={buildingModel.model_json.core.position_xy}
                            coreSurfaceM2={buildingModel.model_json.core.surface_m2}
                            hasAscenseur={!!buildingModel.model_json.core.ascenseur}
                            voirieSide={buildingModel.model_json.site.voirie_orientations?.[0] ?? "sud"}
                            isRdc={niv.index === 0}
                            width={620}
                            height={400}
                            northAngleDeg={buildingModel.model_json.site.north_angle_deg ?? 0}
                            footprint={footprintRing}
                            showCotations={showCotations}
                          />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </TabsContent>

              <TabsContent value="coupes">
                <div className="space-y-4">
                  <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                      <h2 className="text-sm font-semibold text-slate-700">
                        Coupe A-A&apos; <span className="text-xs font-normal text-slate-400">— transversale (perpendiculaire à la voirie)</span>
                      </h2>
                      <a
                        href={`${API_BASE}/api/v1/projects/${id}/plans/coupe/dxf`}
                        download
                        className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                      >
                        <Download className="h-3.5 w-3.5" /> DXF
                      </a>
                    </div>
                    <div className="p-4 flex justify-center bg-slate-50">
                      <CoupeElevation bm={buildingModel.model_json} mode="coupe" cutAxis="AA" width={760} height={440} />
                    </div>
                  </div>
                  <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                      <h2 className="text-sm font-semibold text-slate-700">
                        Coupe B-B&apos; <span className="text-xs font-normal text-slate-400">— longitudinale (parallèle à la voirie)</span>
                      </h2>
                      <span className="text-xs text-slate-400">
                        Traces AA&apos; / BB&apos; reportées sur le Plan de masse
                      </span>
                    </div>
                    <div className="p-4 flex justify-center bg-slate-50">
                      <CoupeElevation bm={buildingModel.model_json} mode="coupe" cutAxis="BB" width={760} height={440} />
                    </div>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="facades">
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                  {(["nord", "sud", "est", "ouest"] as const).map((side) => {
                    const voirie = buildingModel.model_json.site.voirie_orientations?.[0] ?? "sud";
                    const isMain = side === voirie;
                    return (
                      <div key={side} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                          <h2 className="text-sm font-semibold text-slate-700">
                            Façade {side.charAt(0).toUpperCase() + side.slice(1)}
                            {isMain && <span className="ml-2 text-xs font-normal text-teal-700">principale (voirie)</span>}
                          </h2>
                          {isMain && (
                            <a
                              href={`${API_BASE}/api/v1/projects/${id}/plans/facade_rue/dxf`}
                              download
                              className="inline-flex items-center gap-1 text-xs text-teal-700 hover:text-teal-900"
                            >
                              <Download className="h-3.5 w-3.5" /> DXF
                            </a>
                          )}
                        </div>
                        <div className="p-3 flex justify-center bg-slate-50">
                          <CoupeElevation
                            bm={buildingModel.model_json}
                            mode="facade"
                            facadeSide={side}
                            width={600}
                            height={400}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </TabsContent>

              <TabsContent value="axo">
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                    <h2 className="text-sm font-semibold text-slate-700">Volumétrie — Axonométrie 3D</h2>
                    <span className="text-xs text-slate-400">Projection isométrique · illustratif PC6</span>
                  </div>
                  <div className="p-4 flex justify-center bg-slate-50">
                    <Axonometrie bm={buildingModel.model_json} width={880} height={560} projection="iso" />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="tableaux">
                <TableauxSurfacesPLU
                  bm={buildingModel.model_json}
                  bilanProgramme={bilan?.programme ?? null}
                />
              </TabsContent>

              <TabsContent value="situation">
                {(() => {
                  const brief = (project?.brief ?? {}) as {
                    parcelles_selectionnees?: Array<{
                      geometry: GeoJSON.Geometry;
                      numero?: string;
                      section?: string;
                      contenance_m2?: number;
                    }>;
                    address_resolved?: string;
                    commune?: string;
                    postcode?: string;
                  };
                  const parcelles = brief.parcelles_selectionnees ?? [];
                  if (parcelles.length === 0) {
                    return (
                      <div className="rounded-xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">
                        Aucune parcelle cadastrale sélectionnée pour ce projet.
                        <br />Relance l&apos;analyse pour geocoder et importer les parcelles.
                      </div>
                    );
                  }
                  return (
                    <PlanSituation
                      parcelles={parcelles}
                      address={brief.address_resolved ?? addressForPlan}
                      communeName={brief.commune}
                      codePostal={brief.postcode}
                    />
                  );
                })()}
              </TabsContent>

              <TabsContent value="photomontages">
                {(() => {
                  const brief = (project?.brief ?? {}) as {
                    address_resolved?: string;
                    commune?: string;
                  };
                  return (
                    <Photomontages
                      projectId={id}
                      bm={buildingModel.model_json}
                      communeName={brief.commune}
                      address={brief.address_resolved ?? addressForPlan}
                    />
                  );
                })()}
              </TabsContent>

              <TabsContent value="ombres">
                {(() => {
                  const brief = (project?.brief ?? {}) as {
                    parcelles_selectionnees?: Array<{ geometry: GeoJSON.Geometry }>;
                  };
                  // Derive latitude from parcelles centroid if available
                  let lat = 48.85;
                  const ps = brief.parcelles_selectionnees ?? [];
                  if (ps.length > 0) {
                    let sy = 0, n = 0;
                    for (const p of ps) {
                      const g = p.geometry;
                      const rings = g?.type === "Polygon"
                        ? [g.coordinates[0]]
                        : g?.type === "MultiPolygon"
                          ? g.coordinates.map((x) => x[0])
                          : [];
                      for (const ring of rings) for (const c of ring as number[][]) { sy += c[1]; n++; }
                    }
                    if (n) lat = sy / n;
                  }
                  return <EtudeOmbres bm={buildingModel.model_json} latitudeDeg={lat} />;
                })()}
              </TabsContent>

              <TabsContent value="notice">
                {(() => {
                  const brief = (project?.brief ?? {}) as {
                    address_resolved?: string;
                    commune?: string;
                    postcode?: string;
                  };
                  return (
                    <NoticePC4
                      bm={buildingModel.model_json}
                      address={brief.address_resolved ?? addressForPlan}
                      communeName={brief.commune}
                      codePostal={brief.postcode}
                      bilanProgramme={bilan?.programme ?? null}
                    />
                  );
                })()}
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>

      {/* Fullscreen niveau modal */}
      <Dialog
        open={openNiveau !== null && openKind === "niveau"}
        onOpenChange={(open) => {
          if (!open) {
            setOpenNiveau(null); setOpenKind(null);
            setSelectedAptId(null); setEditMode(false);
            setPendingOpenings({});
            setSelectedOpeningId(null);
            setPendingDeleteOpenings([]);
            setAddOpeningType(null);
            setPendingAddOpenings([]);
            setSelectedWallId(null);
            setPendingDeleteWalls([]);
            setWallOverrides({});
            setRoomOverrides({});
            setSelectedCoreElement(null);
            setEscalierCenter(null);
            setAscCenter(null);
            setPalierCenter(null);
            setSelectedCoreSide(null);
            setSelectedCirculationId(null);
            setSelectedCirculationEdge(null);
            setCirculationOverrides({});
            setPendingDeleteCirculations([]);
          }
        }}
      >
        <DialogContent
          className="!grid-cols-1 !gap-0 !p-0 !block max-w-[98vw] w-[98vw] max-h-[98vh] h-[98vh] overflow-hidden"
        >
          <div className="flex items-center px-6 py-3 border-b border-slate-100 bg-white">
            <DialogTitle className="text-base font-semibold">
              {openNiveau ? `Plan ${openNiveau.code}` : "Plan"}
              {openNiveau && (
                <span className="ml-3 text-xs font-normal text-slate-500">
                  {openNiveau.usage_principal} — {openNiveau.cellules.filter((c) => c.type === "logement").length} logements — <span className="text-blue-600">click un appartement pour l&apos;éditer</span>
                </span>
              )}
            </DialogTitle>
          </div>
          <div className="flex h-[calc(98vh-56px)] w-full">
            <div className="flex-1 overflow-auto bg-slate-50 p-4 flex justify-center">
              {openNiveau && buildingModel && (
                <NiveauPlan
                  niveau={openNiveau}
                  corePosition={buildingModel.model_json.core.position_xy}
                  coreSurfaceM2={buildingModel.model_json.core.surface_m2}
                  hasAscenseur={!!buildingModel.model_json.core.ascenseur}
                  voirieSide={buildingModel.model_json.site.voirie_orientations?.[0] ?? "sud"}
                  isRdc={openNiveau.index === 0}
                  width={1600}
                  height={1050}
                  northAngleDeg={buildingModel.model_json.site.north_angle_deg ?? 0}
                  footprint={footprintRing}
                  showCotations={showCotations}
                  selectedAptId={selectedAptId}
                  onSelectApt={(aid) => setSelectedAptId(aid)}
                  editMode={editMode}
                  onGeometryChange={(payload) => {
                    if (payload.openings) {
                      setPendingOpenings((prev) => {
                        const next = { ...prev };
                        for (const o of payload.openings!) next[o.opening_id] = o.position_along_wall_cm;
                        return next;
                      });
                    }
                  }}
                  selectedOpeningId={selectedOpeningId}
                  onSelectOpening={setSelectedOpeningId}
                  addOpeningType={addOpeningType}
                  onAddOpening={(op) => {
                    setPendingAddOpenings((prev) => [...prev, op]);
                    setAddOpeningType(null);
                  }}
                  selectedWallId={selectedWallId}
                  onSelectWall={setSelectedWallId}
                  wallOverrides={wallOverrides}
                  roomOverrides={roomOverrides}
                  selectedCoreElement={selectedCoreElement}
                  onSelectCoreElement={(el) => {
                    setSelectedCoreElement(el);
                    if (el) {
                      setSelectedAptId(null);
                      setSelectedWallId(null);
                      setSelectedOpeningId(null);
                      setSelectedCirculationId(null);
                    }
                  }}
                  escalierCenter={
                    escalierCenter
                    ?? (buildingModel.model_json.core as { escalier?: { position_xy?: [number, number] } })?.escalier?.position_xy
                    ?? null
                  }
                  ascCenter={
                    ascCenter
                    ?? (buildingModel.model_json.core as { ascenseur?: { position_xy?: [number, number] } })?.ascenseur?.position_xy
                    ?? null
                  }
                  palierCenter={
                    palierCenter
                    ?? (buildingModel.model_json.core as { palier?: { position_xy?: [number, number] } })?.palier?.position_xy
                    ?? null
                  }
                  onCoreElementMove={(el, center) => {
                    if (el === "escalier") setEscalierCenter(center);
                    else if (el === "ascenseur") setAscCenter(center);
                    else setPalierCenter(center);
                  }}
                  escalierHiddenSides={(buildingModel.model_json.core as { escalier?: { hidden_sides?: string[] } })?.escalier?.hidden_sides}
                  ascHiddenSides={(buildingModel.model_json.core as { ascenseur?: { hidden_sides?: string[] } })?.ascenseur?.hidden_sides}
                  palierHiddenSides={(buildingModel.model_json.core as { palier?: { hidden_sides?: string[] } })?.palier?.hidden_sides}
                  escalierRemoved={!!(buildingModel.model_json.core as { escalier?: { removed?: boolean } })?.escalier?.removed}
                  ascRemoved={!!(buildingModel.model_json.core as { ascenseur?: { removed?: boolean } })?.ascenseur?.removed}
                  palierRemoved={!!(buildingModel.model_json.core as { palier?: { removed?: boolean } })?.palier?.removed}
                  selectedCoreSide={selectedCoreSide}
                  onSelectCoreSide={(el, side) => {
                    setSelectedCoreSide({ el, side });
                    setSelectedCoreElement(null);
                    setSelectedAptId(null);
                    setSelectedWallId(null);
                    setSelectedOpeningId(null);
                    setSelectedCirculationId(null);
                  }}
                  selectedCirculationId={selectedCirculationId}
                  onSelectCirculation={(cid) => {
                    setSelectedCirculationId(cid);
                    if (cid) {
                      setSelectedAptId(null);
                      setSelectedWallId(null);
                      setSelectedOpeningId(null);
                      setSelectedCoreElement(null);
                    }
                  }}
                  circulationOverrides={circulationOverrides}
                  onCirculationEdge={(id, coords) => {
                    setCirculationOverrides((prev) => ({ ...prev, [id]: coords }));
                  }}
                  selectedCirculationEdge={selectedCirculationEdge}
                  onSelectCirculationEdge={setSelectedCirculationEdge}
                  onWallMove={(wallId, newCoords) => {
                    if (!selectedApt) return;
                    const wall = selectedApt.walls?.find((w) => w.id === wallId);
                    if (!wall) return;
                    const oldCoords = wall.geometry?.coords as [number, number][];
                    if (!oldCoords || oldCoords.length < 2) return;
                    const [oa, ob] = oldCoords;
                    const isV = Math.abs(ob[0] - oa[0]) < 0.01;
                    const oldVal = isV ? oa[0] : oa[1];
                    const newVal = isV ? newCoords[0][0] : newCoords[0][1];
                    // Wall override
                    setWallOverrides((prev) => ({ ...prev, [wallId]: newCoords }));
                    // Update adjacent room polygons: move any vertex that
                    // was at the old wall position over to the new one.
                    const TOL = 0.15;
                    const nextRoomOverrides: Record<string, [number, number][]> = { ...roomOverrides };
                    for (const room of selectedApt.rooms ?? []) {
                      const base = (roomOverrides[room.id] ?? room.polygon_xy) as [number, number][];
                      const updated = base.map((pt) => {
                        const v = isV ? pt[0] : pt[1];
                        if (Math.abs(v - oldVal) < TOL) {
                          return isV ? [newVal, pt[1]] : [pt[0], newVal];
                        }
                        return pt;
                      }) as [number, number][];
                      if (updated.some((p, i) => p[0] !== base[i][0] || p[1] !== base[i][1])) {
                        nextRoomOverrides[room.id] = updated;
                      }
                    }
                    setRoomOverrides(nextRoomOverrides);
                  }}
                />
              )}
            </div>
            {/* Edit side panel — ALWAYS visible inside the fullscreen Dialog.
                Shows a placeholder when no apt is selected. */}
            <aside className="w-96 flex-shrink-0 bg-white border-l border-slate-200 overflow-y-auto">
              {/* Global edit-mode toggle — always visible in the dialog so
                  users can click on corridors / core / apts to edit them. */}
              <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between sticky top-0 bg-white z-10">
                <div>
                  <p className="text-xs font-medium text-slate-700">Mode édition</p>
                  <p className="text-[11px] text-slate-400">Active pour cliquer & éditer</p>
                </div>
                <button
                  type="button"
                  onClick={() => setEditMode((v) => !v)}
                  className={`text-xs rounded-md px-3 py-1.5 font-medium transition-colors ${
                    editMode ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  }`}
                >
                  {editMode ? "Activé" : "Activer"}
                </button>
              </div>
              {/* Save status + error — always visible while saving */}
              {(saving || editError) && (
                <div className={`mx-3 mt-2 rounded px-3 py-2 text-xs ${
                  saving ? "bg-blue-50 border border-blue-100 text-blue-700"
                    : "bg-red-50 border border-red-100 text-red-700"
                }`}>
                  {saving ? "⟳ Enregistrement en cours…" : editError}
                </div>
              )}

              {/* Core-side panel: a specific side (N/S/E/O) of escalier/ASC/palier */}
              {selectedCoreSide && buildingModel && (() => {
                const coreObj = buildingModel.model_json.core as {
                  escalier?: { hidden_sides?: string[] };
                  ascenseur?: { hidden_sides?: string[] };
                  palier?: { hidden_sides?: string[] };
                };
                const elName = selectedCoreSide.el === "escalier" ? "Escalier"
                  : selectedCoreSide.el === "ascenseur" ? "Ascenseur" : "Palier";
                const sideLabel: Record<string, string> = { nord: "Nord", sud: "Sud", est: "Est", ouest: "Ouest" };
                const sideLabelText = sideLabel[selectedCoreSide.side] ?? selectedCoreSide.side;
                const current: string[] = coreObj[selectedCoreSide.el]?.hidden_sides ?? [];
                return (
                  <div className="p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-slate-400 font-medium">Face</p>
                        <h3 className="font-semibold text-slate-900 text-lg flex items-center gap-2">
                          <Pencil className="h-4 w-4" /> {elName} — {sideLabelText}
                        </h3>
                      </div>
                      <button onClick={() => setSelectedCoreSide(null)} className="text-slate-400 hover:text-slate-700">
                        <X className="h-5 w-5" />
                      </button>
                    </div>
                    <p className="text-xs text-slate-500">
                      Supprimer cette face retire uniquement le trait de ce côté, sans toucher aux autres ni aux éléments internes.
                    </p>
                    <Button
                      onClick={() => {
                        const newHidden = Array.from(new Set([...current, selectedCoreSide.side]));
                        savePatch({ core: { [selectedCoreSide.el]: { hidden_sides: newHidden } } });
                        setSelectedCoreSide(null);
                      }}
                      disabled={saving}
                      className="w-full gap-2"
                      variant="outline"
                      style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                    >
                      <Trash2 className="h-4 w-4" />
                      Supprimer cette face
                    </Button>
                    {current.length > 0 && (
                      <Button
                        onClick={() => {
                          savePatch({ core: { [selectedCoreSide.el]: { hidden_sides: [] } } });
                          setSelectedCoreSide(null);
                        }}
                        disabled={saving}
                        variant="outline"
                        className="w-full gap-2"
                      >
                        Réafficher toutes les faces ({current.length} masquée(s))
                      </Button>
                    )}
                  </div>
                );
              })()}

              {/* Core-element panel (escalier / ASC / palier) */}
              {selectedCoreElement && !selectedCoreSide && buildingModel && (() => {
                const el = selectedCoreElement;
                const label = el === "escalier" ? "Escalier" : el === "ascenseur" ? "Ascenseur" : "Palier";
                const override = el === "escalier" ? escalierCenter
                               : el === "ascenseur" ? ascCenter
                               : palierCenter;
                const coreAny = buildingModel.model_json.core as Record<string, { removed?: boolean } | undefined>;
                const isRemoved = !!coreAny?.[el]?.removed;
                return (
                  <div className="p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-slate-400 font-medium">Édition</p>
                        <h3 className="font-semibold text-slate-900 text-lg flex items-center gap-2">
                          <Pencil className="h-4 w-4" /> {label}
                        </h3>
                      </div>
                      <button onClick={() => setSelectedCoreElement(null)} className="text-slate-400 hover:text-slate-700">
                        <X className="h-5 w-5" />
                      </button>
                    </div>
                    <p className="text-xs text-slate-500">
                      Drag le rond bleu ✢ pour repositionner {label.toLowerCase()} indépendamment. Tous les étages suivent.
                    </p>
                    {override && (
                      <p className="text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded p-2">
                        Nouvelle position : ({override[0].toFixed(1)}, {override[1].toFixed(1)}) m
                      </p>
                    )}
                    {isRemoved && (
                      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded p-2">
                        {label} masqué du plan. Clique « Restaurer » pour le réafficher.
                      </p>
                    )}
                    <div className="flex gap-2">
                      <Button
                        onClick={() => {
                          if (!override) { setEditError("Aucune modification"); return; }
                          savePatch({ core: { [el]: { position_xy: override } } });
                        }}
                        disabled={saving || !override}
                        className="flex-1 gap-2 text-white"
                        style={{ backgroundColor: "var(--ac-primary)" }}
                      >
                        <Save className="h-4 w-4" />
                        {saving ? "…" : "Enregistrer"}
                      </Button>
                      {isRemoved ? (
                        <Button
                          onClick={() => {
                            savePatch({ core: { [el]: { removed: false } } });
                            setSelectedCoreElement(null);
                          }}
                          disabled={saving}
                          variant="outline"
                          className="gap-1"
                        >
                          Restaurer
                        </Button>
                      ) : (
                        <Button
                          onClick={() => {
                            const msg = el === "escalier"
                              ? "Masquer l'escalier ? Un bâtiment sans escalier n'est pas conforme — à n'utiliser que si tu le déplaces vers un autre core."
                              : el === "ascenseur"
                              ? "Masquer l'ascenseur ?"
                              : "Masquer ce palier ?";
                            if (!confirm(msg)) return;
                            savePatch({ core: { [el]: { removed: true } } });
                            setSelectedCoreElement(null);
                          }}
                          disabled={saving}
                          variant="outline"
                          style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                          className="gap-1"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })()}
              {/* Corridor-selected panel */}
              {selectedCirculationId && !selectedCoreElement && !selectedCoreSide && buildingModel && (() => {
                const niv = buildingModel.model_json.niveaux.find((n) => n.index === openNiveau?.index);
                const circ = (niv?.circulations_communes ?? []).find((c) => c.id === selectedCirculationId);
                if (!circ) return null;
                const hasOverride = !!circulationOverrides[selectedCirculationId];
                const isHall = circ.id.includes("hall");
                const isPalier = circ.id.startsWith("palier");
                return (
                  <div className="p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-slate-400 font-medium">Édition circulation</p>
                        <h3 className="font-semibold text-slate-900 text-lg flex items-center gap-2">
                          <Pencil className="h-4 w-4" /> {circ.id}
                        </h3>
                      </div>
                      <button onClick={() => setSelectedCirculationId(null)} className="text-slate-400 hover:text-slate-700">
                        <X className="h-5 w-5" />
                      </button>
                    </div>
                    <p className="text-xs text-slate-500">Surface : {Math.round(circ.surface_m2 * 10) / 10} m²</p>
                    <p className="text-xs text-slate-500">
                      Click sur une arête du couloir pour la sélectionner (rouge pointillé), puis Supprimer / Couper.
                      Carrés roses au milieu des arêtes axis-aligned = drag pour redimensionner.
                    </p>
                    {hasOverride && (
                      <p className="text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded p-2">
                        Géométrie modifiée — non enregistrée.
                      </p>
                    )}
                    {selectedCirculationEdge != null && (() => {
                      const coords = (circulationOverrides[selectedCirculationId] ?? circ.polygon_xy) as [number, number][];
                      const i = selectedCirculationEdge;
                      const a = coords[i];
                      const b = coords[(i + 1) % coords.length];
                      const edgeLen = Math.hypot(b[0] - a[0], b[1] - a[1]);
                      const hiddenEdges: number[] = (circ as unknown as { hidden_edges?: number[] }).hidden_edges ?? [];
                      return (
                        <div className="border border-pink-200 bg-pink-50 rounded p-2 space-y-1.5">
                          <p className="text-xs font-medium text-pink-800">
                            Arête #{i} sélectionnée ({edgeLen.toFixed(1)} m)
                          </p>
                          <div className="flex gap-1.5">
                            <Button
                              onClick={() => {
                                const newHidden = Array.from(new Set([...hiddenEdges, i]));
                                savePatch({ circulations: [{ id: selectedCirculationId, hidden_edges: newHidden }] });
                                setSelectedCirculationEdge(null);
                              }}
                              variant="outline"
                              size="sm"
                              className="flex-1 gap-1"
                              style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                            >
                              <Trash2 className="h-3.5 w-3.5" /> Supprimer
                            </Button>
                            <Button
                              onClick={() => {
                                const mid = prompt(
                                  `Position de coupe (0 à ${edgeLen.toFixed(2)} m depuis le début) :`,
                                  (edgeLen / 2).toFixed(2),
                                );
                                if (!mid) return;
                                const pos = parseFloat(mid);
                                if (isNaN(pos) || pos <= 0.1 || pos >= edgeLen - 0.1) {
                                  alert(`Position invalide (0.1 à ${(edgeLen - 0.1).toFixed(2)} m)`);
                                  return;
                                }
                                const t = pos / edgeLen;
                                const mx = a[0] + t * (b[0] - a[0]);
                                const my = a[1] + t * (b[1] - a[1]);
                                // Insert new vertex at midpoint: 1 edge → 2 edges
                                const newPoly = [...coords];
                                newPoly.splice(i + 1, 0, [mx, my]);
                                savePatch({ circulations: [{ id: selectedCirculationId, polygon_xy: newPoly }] });
                                setSelectedCirculationEdge(null);
                              }}
                              variant="outline"
                              size="sm"
                              className="flex-1 gap-1"
                            >
                              ✂ Couper
                            </Button>
                          </div>
                          {hiddenEdges.length > 0 && (
                            <Button
                              onClick={() => {
                                savePatch({ circulations: [{ id: selectedCirculationId, hidden_edges: [] }] });
                                setSelectedCirculationEdge(null);
                              }}
                              variant="outline"
                              size="sm"
                              className="w-full mt-1"
                            >
                              Réafficher les {hiddenEdges.length} arête(s) masquée(s)
                            </Button>
                          )}
                        </div>
                      );
                    })()}
                    <div className="flex gap-2">
                      <Button
                        onClick={() => {
                          const body: Record<string, unknown> = {};
                          if (hasOverride) {
                            body.circulations = [{
                              id: selectedCirculationId,
                              polygon_xy: circulationOverrides[selectedCirculationId],
                            }];
                          }
                          if (pendingDeleteCirculations.length) body.delete_circulations = pendingDeleteCirculations;
                          if (!body.circulations && !body.delete_circulations) {
                            setEditError("Aucune modification"); return;
                          }
                          savePatch(body);
                        }}
                        disabled={saving || (!hasOverride && pendingDeleteCirculations.length === 0)}
                        className="flex-1 gap-2 text-white"
                        style={{ backgroundColor: "var(--ac-primary)" }}
                      >
                        <Save className="h-4 w-4" />
                        Enregistrer
                      </Button>
                      <Button
                        onClick={() => {
                          const msg = isPalier
                            ? `Supprimer le palier ${circ.id} ? Si un palier dessert des apts, ils perdront l'accès à l'escalier.`
                            : isHall
                            ? `Supprimer le hall ${circ.id} ? L'entrée du bâtiment sera bloquée.`
                            : `Supprimer la circulation ${circ.id} ? Les apts pourraient devenir inaccessibles.`;
                          if (!confirm(msg)) return;
                          savePatch({ delete_circulations: [selectedCirculationId] });
                          setSelectedCirculationId(null);
                        }}
                        variant="outline"
                        disabled={saving}
                        style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                        className="gap-2"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    <p className="text-xs text-slate-400 pt-1">
                      {isHall
                        ? "Hall d'entrée RDC — supprimer bloquerait l'accès au bâtiment."
                        : isPalier
                        ? "Palier — si c'est un palier orphelin, suppression OK. Sinon les apts desservis perdent l'escalier."
                        : "Couloir — suppression = apts alentour peuvent perdre leur accès."}
                    </p>
                  </div>
                );
              })()}
              {/* Placeholder (no apt/core/corridor/side selected) */}
              {!selectedApt && !selectedCoreElement && !selectedCirculationId && !selectedCoreSide && (
                <div className="px-5 py-10 text-sm leading-relaxed space-y-3">
                  <div className="text-center">
                    <Pencil className="h-5 w-5 mx-auto mb-3 text-slate-300" />
                    <p className="font-medium text-slate-600">Aucune sélection</p>
                  </div>
                  <div className="text-xs text-slate-500 space-y-2">
                    <p>
                      {editMode
                        ? "✅ Mode édition actif. Clique sur :"
                        : "Active le Mode édition en haut, puis clique sur :"}
                    </p>
                    <ul className="list-disc pl-5 space-y-1">
                      <li><b>Un appartement</b> — drag ouvertures & cloisons, renommer pièces, changer typologie</li>
                      <li><b>Un couloir</b> — drag bords pour redimensionner, supprimer</li>
                      <li><b>L&apos;escalier</b> / <b>l&apos;ascenseur</b> / <b>le palier</b> — chacun indépendamment déplaçable, chaque face (N/S/E/O) supprimable individuellement</li>
                    </ul>
                  </div>
                </div>
              )}
              {selectedApt && (
              <div>
                <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
                  <div>
                    <p className="text-xs text-slate-400 font-medium">Édition appartement</p>
                    <h3 className="font-semibold text-slate-900 text-lg flex items-center gap-2">
                      <Pencil className="h-4 w-4" /> {selectedApt.id}
                    </h3>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedAptId(null)}
                    className="text-slate-400 hover:text-slate-700"
                    aria-label="Désélectionner"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>

                <div className="px-5 py-4 space-y-5">
                  <div>
                    <label className="block text-xs font-medium text-slate-500 mb-1.5">Surface</label>
                    <p className="text-sm text-slate-900">
                      {Math.round((selectedApt.surface_m2 ?? 0) * 10) / 10} m²
                    </p>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-500 mb-1.5">Typologie</label>
                    <select
                      className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                      value={editTypo}
                      onChange={(e) => setEditTypo(e.target.value)}
                    >
                      {TYPOS.map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-500 mb-2">
                      Pièces ({(selectedApt.rooms ?? []).length})
                    </label>
                    <div className="space-y-1.5">
                      {(selectedApt.rooms ?? []).map((r) => (
                        <div key={r.id} className="flex items-center gap-2">
                          <input
                            type="text"
                            className="flex-1 border border-slate-200 rounded px-2 py-1 text-sm"
                            value={editLabels[r.id] ?? ""}
                            onChange={(e) =>
                              setEditLabels({ ...editLabels, [r.id]: e.target.value })
                            }
                            placeholder={r.label_fr ?? r.type}
                          />
                          <span className="text-xs text-slate-400 w-12 text-right">
                            {Math.round(r.surface_m2 ?? 0)} m²
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {editError && (
                    <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded p-2">
                      {editError}
                    </div>
                  )}

                  {editMode && (
                    <p className="text-xs text-slate-500 leading-relaxed pt-2 border-t border-slate-100">
                      Glisse les pastilles {" "}
                      <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500 align-middle mx-0.5" />
                      (portes) et {" "}
                      <span className="inline-block w-2.5 h-2.5 rounded-full bg-sky-500 align-middle mx-0.5" />
                      (fenêtres) le long des murs. Click dessus → sélection (bordure rouge) + bouton Supprimer.
                    </p>
                  )}
                  {editMode && selectedOpeningId && (() => {
                    const op = selectedApt.openings?.find((o) => o.id === selectedOpeningId);
                    if (!op) return null;
                    return (
                      <div className="border border-red-100 bg-red-50 rounded p-2 space-y-1.5">
                        <p className="text-xs font-medium text-red-800">Ouverture : {op.type}</p>
                        <Button
                          onClick={() => {
                            savePatch({ apt_id: selectedApt.id, delete_openings: [selectedOpeningId] });
                            setSelectedOpeningId(null);
                          }}
                          variant="outline"
                          size="sm"
                          className="gap-2 w-full"
                          style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Supprimer immédiatement
                        </Button>
                      </div>
                    );
                  })()}
                  {editMode && selectedWallId && (() => {
                    const wall = selectedApt.walls?.find((w) => w.id === selectedWallId);
                    if (!wall) return null;
                    const isPorteur = wall.type === "porteur";
                    const coords = wall.geometry?.coords as [number, number][] | undefined;
                    const wallLen = coords && coords.length >= 2
                      ? Math.hypot(coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])
                      : 0;
                    return (
                      <div className={`border rounded p-2 space-y-1.5 ${
                        isPorteur ? "border-slate-200 bg-slate-50" : "border-purple-100 bg-purple-50"
                      }`}>
                        <p className={`text-xs font-medium ${isPorteur ? "text-slate-800" : "text-purple-800"}`}>
                          {isPorteur ? "Mur porteur" : "Cloison"} sélectionné ({wallLen.toFixed(1)} m)
                        </p>
                        <div className="flex gap-1.5">
                          <Button
                            onClick={() => {
                              if (isPorteur && !confirm("Supprimer un mur porteur peut rompre la structure. Confirmer ?")) return;
                              savePatch({ apt_id: selectedApt.id, delete_walls: [selectedWallId] });
                              setSelectedWallId(null);
                            }}
                            variant="outline"
                            size="sm"
                            className="flex-1 gap-1"
                            style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Supprimer
                          </Button>
                          <Button
                            onClick={() => {
                              if (!coords || coords.length < 2) return;
                              const mid = prompt(
                                `Position de coupe (0 à ${wallLen.toFixed(2)} m depuis le début du mur) :`,
                                (wallLen / 2).toFixed(2),
                              );
                              if (!mid) return;
                              const pos = parseFloat(mid);
                              if (isNaN(pos) || pos <= 0.1 || pos >= wallLen - 0.1) {
                                alert(`Position invalide (doit être entre 0.1 et ${(wallLen - 0.1).toFixed(2)} m)`);
                                return;
                              }
                              const t = pos / wallLen;
                              const [a, b] = coords;
                              const mx = a[0] + t * (b[0] - a[0]);
                              const my = a[1] + t * (b[1] - a[1]);
                              const wAny = wall as unknown as { materiau?: string; hauteur_cm?: number };
                              savePatch({
                                apt_id: selectedApt.id,
                                delete_walls: [selectedWallId],
                                add_walls: [
                                  { type: wall.type, thickness_cm: wall.thickness_cm,
                                    geometry: { type: "LineString", coords: [a, [mx, my]] },
                                    materiau: wAny.materiau, hauteur_cm: wAny.hauteur_cm },
                                  { type: wall.type, thickness_cm: wall.thickness_cm,
                                    geometry: { type: "LineString", coords: [[mx, my], b] },
                                    materiau: wAny.materiau, hauteur_cm: wAny.hauteur_cm },
                                ],
                              });
                              setSelectedWallId(null);
                            }}
                            variant="outline"
                            size="sm"
                            className="flex-1 gap-1"
                          >
                            ✂ Couper
                          </Button>
                        </div>
                        <p className="text-xs text-slate-500">
                          Couper en 2 → tu pourras ensuite supprimer une des 2 moitiés.
                        </p>
                      </div>
                    );
                  })()}
                  {editMode && (
                    <div className="space-y-1.5 pt-2 border-t border-slate-100">
                      <p className="text-xs font-medium text-slate-700">Ajouter une ouverture</p>
                      <div className="grid grid-cols-3 gap-1.5">
                        <button
                          type="button"
                          onClick={() => setAddOpeningType(addOpeningType === "fenetre" ? null : "fenetre")}
                          className={`text-xs rounded-md px-2 py-1.5 font-medium border ${
                            addOpeningType === "fenetre"
                              ? "bg-sky-600 text-white border-sky-600"
                              : "bg-sky-50 text-sky-700 border-sky-200 hover:bg-sky-100"
                          }`}
                        >
                          Fenêtre
                        </button>
                        <button
                          type="button"
                          onClick={() => setAddOpeningType(addOpeningType === "porte_fenetre" ? null : "porte_fenetre")}
                          className={`text-xs rounded-md px-2 py-1.5 font-medium border ${
                            addOpeningType === "porte_fenetre"
                              ? "bg-sky-600 text-white border-sky-600"
                              : "bg-sky-50 text-sky-700 border-sky-200 hover:bg-sky-100"
                          }`}
                        >
                          Porte-fen.
                        </button>
                        <button
                          type="button"
                          onClick={() => setAddOpeningType(addOpeningType === "porte_interieure" ? null : "porte_interieure")}
                          className={`text-xs rounded-md px-2 py-1.5 font-medium border ${
                            addOpeningType === "porte_interieure"
                              ? "bg-amber-600 text-white border-amber-600"
                              : "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100"
                          }`}
                        >
                          Porte int.
                        </button>
                      </div>
                      {addOpeningType && (
                        <p className="text-xs text-green-700 bg-green-50 border border-green-100 rounded p-2">
                          Click sur un mur (en vert pointillé) du plan pour y poser l&apos;ouverture.
                        </p>
                      )}
                    </div>
                  )}
                  {(Object.keys(pendingOpenings).length > 0
                    || pendingDeleteOpenings.length > 0
                    || pendingAddOpenings.length > 0
                    || pendingDeleteWalls.length > 0
                    || Object.keys(wallOverrides).length > 0) && (
                    <p className="text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded p-2 space-y-0.5">
                      {pendingAddOpenings.length > 0 && <>✚ {pendingAddOpenings.length} ouverture(s) ajoutée(s)<br/></>}
                      {Object.keys(pendingOpenings).length > 0 && <>↔ {Object.keys(pendingOpenings).length} ouverture(s) déplacée(s)<br/></>}
                      {pendingDeleteOpenings.length > 0 && <>✕ {pendingDeleteOpenings.length} ouverture(s) supprimée(s)<br/></>}
                      {Object.keys(wallOverrides).length > 0 && <>↔ {Object.keys(wallOverrides).length} cloison(s) déplacée(s)<br/></>}
                      {pendingDeleteWalls.length > 0 && <>✕ {pendingDeleteWalls.length} cloison(s) supprimée(s)<br/></>}
                    </p>
                  )}

                  <div className="flex gap-2 pt-1">
                    <Button
                      onClick={() => {
                        if (!selectedApt) return;
                        const body: Record<string, unknown> = { apt_id: selectedApt.id };
                        const currentTypo = String(selectedApt.typologie || "").toUpperCase();
                        if (editTypo && editTypo !== currentTypo) body.typologie = editTypo;
                        const changedLabels: Record<string, string> = {};
                        for (const r of selectedApt.rooms ?? []) {
                          if ((editLabels[r.id] ?? "") !== (r.label_fr ?? "")) {
                            changedLabels[r.id] = editLabels[r.id] ?? "";
                          }
                        }
                        if (Object.keys(changedLabels).length) body.room_labels = changedLabels;
                        const opsArr = Object.entries(pendingOpenings).map(([opening_id, position_along_wall_cm]) => ({
                          opening_id, position_along_wall_cm,
                        }));
                        if (opsArr.length) body.openings = opsArr;
                        if (pendingDeleteOpenings.length) body.delete_openings = pendingDeleteOpenings;
                        if (pendingAddOpenings.length) body.add_openings = pendingAddOpenings;
                        if (pendingDeleteWalls.length) body.delete_walls = pendingDeleteWalls;
                        const wallsArr = Object.entries(wallOverrides).map(([wall_id, coords]) => ({
                          wall_id, geometry: { type: "LineString", coords },
                        }));
                        if (wallsArr.length) body.walls = wallsArr;
                        const roomsArr = Object.entries(roomOverrides).map(([room_id, polygon_xy]) => ({
                          room_id, polygon_xy,
                        }));
                        if (roomsArr.length) body.rooms = roomsArr;
                        if (!body.typologie && !body.room_labels && !body.openings
                            && !body.delete_openings && !body.add_openings
                            && !body.delete_walls && !body.walls && !body.rooms) {
                          setEditError("Aucune modification à enregistrer");
                          return;
                        }
                        savePatch(body);
                      }}
                      disabled={saving}
                      className="flex-1 gap-2 text-white"
                      style={{ backgroundColor: "var(--ac-primary)" }}
                    >
                      <Save className="h-4 w-4" />
                      {saving ? "Enregistrement…" : "Enregistrer"}
                    </Button>
                    <Button
                      variant="outline"
                      onClick={handleDeleteApt}
                      disabled={saving}
                      style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                      className="gap-2"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  <p className="text-xs text-slate-400 pt-1">
                    Chaque enregistrement crée une nouvelle version du BM (historique restaurable).
                  </p>
                </div>
              </div>
              )}
            </aside>
          </div>
        </DialogContent>
      </Dialog>
    </main>
  );
}
