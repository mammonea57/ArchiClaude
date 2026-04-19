"use client";
import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWorkspaces } from "@/lib/hooks/useWorkspaces";
import { RoleBadge } from "@/components/RoleBadge";
import { apiFetch } from "@/lib/api";

export default function WorkspacesPage() {
  const { workspaces, refresh } = useWorkspaces();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  async function create() {
    if (!name) return;
    await apiFetch("/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setName("");
    setCreating(false);
    refresh();
  }

  return (
    <main className="max-w-4xl mx-auto p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-display text-3xl font-bold text-slate-900">Mes workspaces</h1>
        <Button onClick={() => setCreating(!creating)} className="bg-teal-600 text-white hover:bg-teal-700">
          Créer un workspace
        </Button>
      </div>

      {creating && (
        <div className="bg-white border border-slate-200 rounded-lg p-4 mb-4 flex gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nom du workspace" />
          <Button onClick={create} className="bg-teal-600 text-white hover:bg-teal-700">Créer</Button>
          <Button variant="outline" onClick={() => setCreating(false)}>Annuler</Button>
        </div>
      )}

      <div className="space-y-2">
        {workspaces.map(({ workspace, role }) => (
          <Link key={workspace.id} href={`/workspaces/${workspace.id}`} className="block bg-white border border-slate-200 rounded-lg p-4 hover:border-teal-500">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-semibold text-slate-900">{workspace.name}</div>
                {workspace.description && <div className="text-sm text-slate-500">{workspace.description}</div>}
              </div>
              <div className="flex items-center gap-2">
                {workspace.is_personal && <span className="text-xs text-slate-400">Personnel</span>}
                <RoleBadge role={role} />
              </div>
            </div>
          </Link>
        ))}
      </div>
    </main>
  );
}
