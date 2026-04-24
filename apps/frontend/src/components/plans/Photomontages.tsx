"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Camera, RefreshCw } from "lucide-react";
import type { BuildingModelPayload } from "@/lib/types";
import { PhotomontageRender } from "./PhotomontageRender";

interface RenderOut {
  id: string;
  label?: string | null;
  status: string;
  photo_source?: string | null;
  photo_base_url?: string | null;
  render_url?: string | null;
  thumbnail_url?: string | null;
  created_at?: string;
}

interface PhotomontagesProps {
  projectId: string;
  bm?: BuildingModelPayload;
  communeName?: string;
  address?: string;
}

export function Photomontages({ projectId, bm, communeName, address }: PhotomontagesProps) {
  const [renders, setRenders] = useState<RenderOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<{ items: RenderOut[]; total: number }>(`/projects/${projectId}/pcmi6/renders`);
      setRenders(res.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur chargement renders");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between bg-white border border-slate-200 rounded-xl px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Photomontages PC6 · PC7 · PC8</h2>
          <p className="text-xs text-slate-400">
            Pièces d&apos;insertion paysagère — rendus SVG générés automatiquement depuis le modèle bâtiment.
            Peuvent être remplacés par un photomontage IA sur photo réelle via le wizard (à venir).
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Actualiser
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-100 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* SVG photomontages — auto-generated from BM */}
      {bm && (
        <section className="space-y-4">
          <PhotomontageRender bm={bm} shot="pc6" communeName={communeName} address={address} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <PhotomontageRender bm={bm} shot="pc7" width={620} height={400} communeName={communeName} address={address} />
            <PhotomontageRender bm={bm} shot="pc8" width={620} height={400} communeName={communeName} address={address} />
          </div>
        </section>
      )}

      {/* Rendus IA existants (si API pcmi6 renvoie des items) */}
      {renders.length > 0 && (
        <section className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <header className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">
              Rendus IA générés <span className="text-xs font-normal text-slate-400">· {renders.length}</span>
            </h3>
            <span className="text-xs text-slate-400">Via pipeline PCMI6</span>
          </header>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 p-4">
            {renders.map((r) => (
              <article key={r.id} className="border border-slate-200 rounded-lg overflow-hidden bg-slate-50">
                <div className="aspect-video bg-slate-200 relative">
                  {r.render_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={r.render_url} alt={r.label ?? r.id} className="w-full h-full object-cover" />
                  ) : r.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={r.thumbnail_url} alt={r.label ?? r.id} className="w-full h-full object-cover" />
                  ) : (
                    <div className="flex items-center justify-center h-full text-xs text-slate-400">
                      <Camera className="h-5 w-5" />
                    </div>
                  )}
                  <span className={`absolute top-2 right-2 text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                    r.status === "complete" ? "bg-emerald-100 text-emerald-800"
                      : r.status === "failed" ? "bg-red-100 text-red-800"
                      : "bg-amber-100 text-amber-800"
                  }`}>
                    {r.status}
                  </span>
                </div>
                <div className="p-2.5">
                  <p className="text-xs font-semibold text-slate-900 truncate">{r.label ?? r.id.slice(0, 8)}</p>
                  <p className="text-[11px] text-slate-400 truncate">{r.photo_source ?? "—"}</p>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      <p className="text-xs text-slate-400 text-center pt-1">
        Les photomontages ci-dessus sont générés depuis la volumétrie du modèle bâtiment —
        utilisables en pièces PC en l&apos;état ou remplaçables par un rendu IA sur photo réelle
        (pipeline <span className="font-mono">/pcmi6/renders</span>).
      </p>
    </div>
  );
}
