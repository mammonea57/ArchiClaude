"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

interface Workspace {
  id: string; name: string; description: string | null;
  is_personal: boolean; created_at: string;
}

export default function WorkspaceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [ws, setWs] = useState<Workspace | null>(null);

  useEffect(() => {
    apiFetch<Workspace>(`/workspaces/${id}`).then(setWs).catch(() => setWs(null));
  }, [id]);

  if (!ws) return <div className="p-8">Chargement...</div>;

  return (
    <main className="max-w-4xl mx-auto p-8">
      <div className="mb-6">
        <h1 className="font-display text-3xl font-bold text-slate-900">{ws.name}</h1>
        {ws.description && <p className="text-slate-500 mt-1">{ws.description}</p>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Link href={`/workspaces/${id}/members`} className="block bg-white border border-slate-200 rounded-lg p-6 hover:border-teal-500">
          <div className="font-semibold text-slate-900">Membres</div>
          <div className="text-sm text-slate-500 mt-1">Gérer les membres et invitations</div>
        </Link>
        <Link href="/projects" className="block bg-white border border-slate-200 rounded-lg p-6 hover:border-teal-500">
          <div className="font-semibold text-slate-900">Projets</div>
          <div className="text-sm text-slate-500 mt-1">Voir les projets de ce workspace</div>
        </Link>
      </div>
    </main>
  );
}
