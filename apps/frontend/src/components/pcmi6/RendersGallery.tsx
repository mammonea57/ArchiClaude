"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

interface Render {
  id: string;
  label: string | null;
  status: string;
  render_url: string | null;
  selected_for_pc: boolean;
  created_at: string;
}

export function RendersGallery({ projectId }: { projectId: string }) {
  const [renders, setRenders] = useState<Render[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<{ items: Render[]; total: number }>(`/projects/${projectId}/pcmi6/renders`)
      .then((data) => setRenders(data.items))
      .catch(() => setRenders([]))
      .finally(() => setLoading(false));
  }, [projectId]);

  async function handleSelectForPC(renderId: string) {
    await apiFetch(`/projects/${projectId}/pcmi6/renders/${renderId}`, {
      method: "PATCH",
      body: JSON.stringify({ selected_for_pc: true }),
      headers: { "Content-Type": "application/json" },
    });
    setRenders((prev) =>
      prev.map((r) => ({ ...r, selected_for_pc: r.id === renderId })),
    );
  }

  async function handleDelete(renderId: string) {
    if (!confirm("Supprimer ce rendu ?")) return;
    await apiFetch(`/projects/${projectId}/pcmi6/renders/${renderId}`, {
      method: "DELETE",
    });
    setRenders((prev) => prev.filter((r) => r.id !== renderId));
  }

  if (loading) return <p className="text-sm text-slate-500">Chargement des rendus…</p>;
  if (renders.length === 0) {
    return <p className="text-sm text-slate-400">Aucun rendu généré pour l&apos;instant.</p>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {renders.map((r) => (
        <div key={r.id} className="border border-slate-200 rounded-lg overflow-hidden">
          {r.render_url ? (
            <Image
              src={r.render_url}
              alt={r.label || "Rendu PCMI6"}
              width={400}
              height={300}
              className="w-full h-auto"
              unoptimized
            />
          ) : (
            <div className="h-48 bg-slate-100 flex items-center justify-center text-slate-400 text-sm">
              {r.status === "generating" ? "Génération en cours…" : "Indisponible"}
            </div>
          )}
          <div className="p-3 flex items-center justify-between">
            <div>
              <div className="font-semibold text-sm text-slate-900">
                {r.label || "Sans nom"}
              </div>
              <div className="text-xs text-slate-400">{new Date(r.created_at).toLocaleString("fr-FR")}</div>
            </div>
            <div className="flex gap-1">
              {r.selected_for_pc ? (
                <span className="text-xs bg-teal-100 text-teal-700 px-2 py-1 rounded">
                  Sélectionné PC
                </span>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleSelectForPC(r.id)}
                >
                  Pour PC
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleDelete(r.id)}
              >
                Suppr.
              </Button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
