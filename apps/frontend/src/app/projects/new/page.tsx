"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import ParcelSearch from "@/components/forms/ParcelSearch";
import BriefForm from "@/components/forms/BriefForm";
import { apiFetch } from "@/lib/api";
import type { GeocodingResult, Brief } from "@/lib/types";

// Dynamic import avoids SSR issues with maplibre-gl
const MapView = dynamic(() => import("@/components/map/MapView"), { ssr: false });

interface ParcelFromApi {
  id?: string;
  code_insee?: string;
  section?: string;
  numero?: string;
  contenance_m2?: number;
  commune?: string;
  geometry?: GeoJSON.Geometry;
  [key: string]: unknown;
}

interface CreateProjectResponse {
  id: string;
  name: string;
  status: string;
}

interface AnalyzeResponse {
  job_id: string;
  status: string;
}

export default function NewProjectPage() {
  const router = useRouter();

  // Map state
  const [mapCenter, setMapCenter] = useState<[number, number]>([2.35, 48.85]);
  const [mapZoom, setMapZoom] = useState(12);
  const [selectedResult, setSelectedResult] = useState<GeocodingResult | null>(null);
  const [selectedParcels, setSelectedParcels] = useState<ParcelFromApi[]>([]);
  const [fetchingParcel, setFetchingParcel] = useState(false);

  // Form state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // When user selects an address from search
  const handleAddressSelect = useCallback((result: GeocodingResult) => {
    setSelectedResult(result);
    setMapCenter([result.lng, result.lat]);
    setMapZoom(17);
  }, []);

  // When user clicks on the map — fetch parcel and toggle selection
  const handleMapClick = useCallback(async (lngLat: { lng: number; lat: number }) => {
    setFetchingParcel(true);
    try {
      const parcel = await apiFetch<ParcelFromApi>(
        `/parcels/at-point?lat=${lngLat.lat}&lng=${lngLat.lng}`,
      );
      if (parcel?.geometry) {
        setSelectedParcels((prev) => {
          // Check if this parcel is already selected (same section+numero)
          const key = `${parcel.code_insee}-${parcel.section}-${parcel.numero}`;
          const exists = prev.findIndex(
            (p) => `${p.code_insee}-${p.section}-${p.numero}` === key,
          );
          if (exists >= 0) {
            // Deselect — remove it
            return prev.filter((_, i) => i !== exists);
          }
          // Add to selection
          return [...prev, parcel];
        });
      }
    } catch {
      // Parcel fetch is optional — swallow errors silently
    } finally {
      setFetchingParcel(false);
    }
  }, []);

  // Remove a specific parcel from selection
  const handleRemoveParcel = useCallback((index: number) => {
    setSelectedParcels((prev) => prev.filter((_, i) => i !== index));
  }, []);

  // Build the parcels overlay for MapView
  const parcels = selectedParcels.length > 0
    ? selectedParcels.map((p) => ({ geometry: p.geometry as GeoJSON.Geometry, selected: true }))
    : undefined;

  // On brief form submit
  async function handleBriefSubmit(brief: Brief) {
    if (selectedParcels.length === 0) {
      setError("Veuillez sélectionner au moins une parcelle sur la carte.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const projectName = selectedResult
        ? (selectedResult.label.length > 80 ? selectedResult.label.slice(0, 80) : selectedResult.label)
        : `Projet ${selectedParcels.length} parcelles`;

      // Attach the selected parcels to the brief so the backend's
      // analyze endpoint fuses them (shapely unary_union) instead of
      // re-fetching a single parcel via the address geocoder. Multiple
      // selected parcels = explicit fusion intent.
      const briefWithParcels = {
        ...brief,
        parcelles_selectionnees: selectedParcels.map((p) => ({
          section: p.section,
          numero: p.numero,
          code_insee: p.code_insee,
          commune: p.commune,
          contenance_m2: p.contenance_m2,
          geometry: p.geometry,
        })),
      };

      const project = await apiFetch<CreateProjectResponse>("/projects", {
        method: "POST",
        body: JSON.stringify({ name: projectName, brief: briefWithParcels }),
      });

      await apiFetch<AnalyzeResponse>(`/projects/${project.id}/analyze`, {
        method: "POST",
      });

      router.push(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur lors de la création du projet.");
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 flex flex-col">
      {/* Navigation */}
      <nav className="border-b border-slate-100 bg-white px-6 py-4 shrink-0">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <Link href="/" className="font-display text-xl font-semibold text-slate-900">
            ArchiClaude
          </Link>
          <div className="flex items-center gap-4 text-sm text-slate-500">
            <Link href="/projects" className="hover:text-slate-700 transition-colors">
              Mes projets
            </Link>
            <Link href="/account" className="hover:text-slate-700 transition-colors">
              Mon compte
            </Link>
          </div>
        </div>
      </nav>

      {/* Page header */}
      <div className="max-w-7xl mx-auto w-full px-6 pt-8 pb-4 shrink-0">
        <div className="flex items-center gap-2 text-sm text-slate-400 mb-1">
          <Link href="/projects" className="hover:text-slate-600 transition-colors">
            Mes projets
          </Link>
          <span>/</span>
          <span className="text-slate-600">Nouveau projet</span>
        </div>
        <h1 className="font-display text-3xl font-bold text-slate-900">Nouveau projet</h1>
        <p className="text-sm text-slate-500 mt-1">
          Localisez et sélectionnez les parcelles du projet, puis renseignez votre programme
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="max-w-7xl mx-auto w-full px-6 pb-2 shrink-0">
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        </div>
      )}

      {/* Split layout */}
      <div className="flex-1 max-w-7xl mx-auto w-full px-6 pb-8 flex gap-6 min-h-0">
        {/* Left — Map + Search (60%) */}
        <div className="flex flex-col gap-3" style={{ flex: "0 0 60%" }}>
          <ParcelSearch onSelect={handleAddressSelect} />

          <div className="relative flex-1 min-h-0" style={{ minHeight: 480 }}>
            <MapView
              center={mapCenter}
              zoom={mapZoom}
              onMapClick={handleMapClick}
              parcels={parcels}
            />
            {fetchingParcel && (
              <div className="absolute inset-0 bg-white/30 rounded-xl flex items-center justify-center pointer-events-none">
                <span className="text-xs text-slate-600 bg-white px-3 py-1.5 rounded-full shadow">
                  Chargement de la parcelle…
                </span>
              </div>
            )}
            {!selectedResult && (
              <div className="absolute bottom-3 left-3 right-3 pointer-events-none">
                <div className="bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 text-xs text-slate-500 shadow text-center">
                  Recherchez une adresse ci-dessus, puis cliquez sur la carte pour sélectionner les parcelles
                </div>
              </div>
            )}
            {selectedResult && selectedParcels.length === 0 && (
              <div className="absolute bottom-3 left-3 right-3 pointer-events-none">
                <div className="bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 text-xs text-slate-500 shadow text-center">
                  Cliquez sur les parcelles à inclure dans le projet — cliquez à nouveau pour désélectionner
                </div>
              </div>
            )}
          </div>

          {/* Selected parcels list */}
          {selectedParcels.length > 0 && (
            <div className="bg-white rounded-lg border border-slate-200 px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-slate-700">
                  {selectedParcels.length} parcelle{selectedParcels.length > 1 ? "s" : ""} sélectionnée{selectedParcels.length > 1 ? "s" : ""}
                </h3>
                <button
                  onClick={() => setSelectedParcels([])}
                  className="text-xs text-slate-400 hover:text-red-500 transition-colors"
                >
                  Tout désélectionner
                </button>
              </div>
              <div className="space-y-1">
                {selectedParcels.map((p, i) => (
                  <div key={i} className="flex items-center justify-between text-xs text-slate-600 bg-slate-50 rounded px-2 py-1.5">
                    <span>
                      <span className="font-medium">{p.section} {p.numero}</span>
                      <span className="text-slate-400 ml-2">{p.commune}</span>
                      {p.contenance_m2 && (
                        <span className="text-slate-400 ml-2">({p.contenance_m2} m²)</span>
                      )}
                    </span>
                    <button
                      onClick={() => handleRemoveParcel(i)}
                      className="text-slate-300 hover:text-red-500 transition-colors ml-2"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <div className="mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500">
                Surface totale : {selectedParcels.reduce((sum, p) => sum + (p.contenance_m2 ?? 0), 0).toLocaleString("fr-FR")} m²
              </div>
            </div>
          )}
        </div>

        {/* Right — Brief form (40%) */}
        <div
          className="flex flex-col bg-white rounded-xl border border-slate-200 shadow-sm p-6 overflow-y-auto"
          style={{ flex: "0 0 40%" }}
        >
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-4">Programme</h2>
          <BriefForm onSubmit={handleBriefSubmit} loading={submitting} />
        </div>
      </div>
    </main>
  );
}
