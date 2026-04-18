"use client";

import { use, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { VersionTimeline, type Version } from "@/components/versions/VersionTimeline";
import { VersionCompare } from "@/components/versions/VersionCompare";
import { ToastContainer, useToast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api";

function VersionsPageContent({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const router = useRouter();

  const [versions, setVersions] = useState<Version[]>([]);
  const [loadingVersions, setLoadingVersions] = useState(true);
  const [selectedA, setSelectedA] = useState<string>("");
  const [selectedB, setSelectedB] = useState<string>("");
  const [diff, setDiff] = useState<Record<string, { old: unknown; new: unknown }> | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [creatingVersion, setCreatingVersion] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Version[]>(`/projects/${projectId}/versions`)
      .then((data) => {
        setVersions(data);
        if (data.length >= 2) {
          setSelectedA(data[data.length - 2].id);
          setSelectedB(data[data.length - 1].id);
        }
      })
      .catch((e) =>
        setError(
          e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau",
        ),
      )
      .finally(() => setLoadingVersions(false));
  }, [projectId]);

  const loadDiff = useCallback(
    async (a: string, b: string) => {
      if (!a || !b || a === b) return;
      setLoadingDiff(true);
      try {
        const data = await apiFetch<Record<string, { old: unknown; new: unknown }>>(
          `/projects/${projectId}/versions/compare?a=${a}&b=${b}`,
        );
        setDiff(data);
      } catch (e) {
        setError(e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau");
      } finally {
        setLoadingDiff(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    if (selectedA && selectedB) loadDiff(selectedA, selectedB);
  }, [selectedA, selectedB, loadDiff]);

  async function createVersion() {
    setCreatingVersion(true);
    try {
      const newVersion = await apiFetch<Version>(`/projects/${projectId}/versions`, {
        method: "POST",
        body: JSON.stringify({ version_label: `Version ${versions.length + 1}` }),
      });
      setVersions((prev) => [...prev, newVersion]);
      showToast("Nouvelle version créée", `Version ${newVersion.version_number}`);
    } catch (e) {
      setError(e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau");
    } finally {
      setCreatingVersion(false);
    }
  }

  function handleTimelineSelect(v: Version) {
    if (!selectedA || selectedA === selectedB) {
      setSelectedA(v.id);
    } else {
      setSelectedB(v.id);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <Link
            href={`/projects/${projectId}`}
            className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"
          >
            <ArrowLeft className="h-4 w-4" />
            Retour au projet
          </Link>
          <span className="text-slate-300">|</span>
          <span className="font-serif text-xl">Historique des versions</span>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-10 space-y-8">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Timeline */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-serif text-lg text-slate-900">Versions</h2>
            <Button
              size="sm"
              onClick={createVersion}
              disabled={creatingVersion}
              className="bg-teal-600 hover:bg-teal-700 text-white gap-1"
            >
              <Plus className="h-4 w-4" />
              {creatingVersion ? "Création…" : "Nouvelle version"}
            </Button>
          </div>

          {loadingVersions ? (
            <p className="text-sm text-slate-400">Chargement…</p>
          ) : (
            <VersionTimeline
              versions={versions}
              onSelect={handleTimelineSelect}
              selectedIds={[selectedA, selectedB].filter(Boolean)}
            />
          )}
        </div>

        {/* Comparison selectors */}
        {versions.length >= 2 && (
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="font-serif text-lg text-slate-900 mb-4">Comparer deux versions</h2>
            <div className="flex items-center gap-4">
              <div className="flex-1">
                <label className="text-xs text-slate-500 mb-1 block">Version A</label>
                <Select value={selectedA} onValueChange={setSelectedA}>
                  <SelectTrigger>
                    <SelectValue placeholder="Sélectionner…" />
                  </SelectTrigger>
                  <SelectContent>
                    {versions.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        V{v.version_number} — {v.version_label ?? new Date(v.created_at).toLocaleDateString("fr-FR")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <span className="text-slate-400 mt-5">→</span>

              <div className="flex-1">
                <label className="text-xs text-slate-500 mb-1 block">Version B</label>
                <Select value={selectedB} onValueChange={setSelectedB}>
                  <SelectTrigger>
                    <SelectValue placeholder="Sélectionner…" />
                  </SelectTrigger>
                  <SelectContent>
                    {versions.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        V{v.version_number} — {v.version_label ?? new Date(v.created_at).toLocaleDateString("fr-FR")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        )}

        {/* Diff */}
        {diff !== null && (
          <div>
            <h2 className="font-serif text-lg text-slate-900 mb-3">Différences</h2>
            {loadingDiff ? (
              <p className="text-sm text-slate-400">Chargement…</p>
            ) : (
              <VersionCompare diff={diff} />
            )}
          </div>
        )}

        {versions.length === 0 && !loadingVersions && (
          <div className="rounded-xl border border-slate-200 bg-white px-6 py-12 text-center">
            <p className="text-slate-500 mb-4">Aucune version enregistrée pour ce projet.</p>
            <Button
              onClick={createVersion}
              disabled={creatingVersion}
              className="bg-teal-600 hover:bg-teal-700 text-white"
            >
              Créer la première version
            </Button>
          </div>
        )}
      </div>
    </main>
  );
}

export default function VersionsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <ToastContainer>
      <VersionsPageContent projectId={id} />
    </ToastContainer>
  );
}
