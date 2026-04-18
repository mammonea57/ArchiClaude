"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Trash2, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ToastContainer, useToast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api";

function SettingsPageContent({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { showToast } = useToast();
  const [projectName, setProjectName] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSaveName() {
    if (!projectName.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: projectName.trim() }),
      });
      showToast("Nom mis à jour", projectName.trim());
    } catch (e) {
      setError(e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await apiFetch(`/projects/${projectId}`, { method: "DELETE" });
      setDeleteOpen(false);
      router.push("/projects");
    } catch (e) {
      setError(e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau");
      setDeleting(false);
    }
  }

  async function handleClone() {
    try {
      const cloned = await apiFetch<{ id: string }>(`/projects/${projectId}/clone`, {
        method: "POST",
      });
      showToast("Projet cloné", "Redirection vers le nouveau projet…");
      setTimeout(() => router.push(`/projects/${cloned.id}`), 1200);
    } catch (e) {
      setError(e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau");
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-2xl mx-auto flex items-center gap-4">
          <Link
            href={`/projects/${projectId}`}
            className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"
          >
            <ArrowLeft className="h-4 w-4" />
            Retour au projet
          </Link>
          <span className="text-slate-300">|</span>
          <span className="font-serif text-xl">Paramètres du projet</span>
        </div>
      </nav>

      <div className="max-w-2xl mx-auto px-6 py-10 space-y-8">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Project name */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
          <h2 className="font-serif text-lg text-slate-900">Nom du projet</h2>
          <div className="space-y-2">
            <Label htmlFor="project-name">Nom</Label>
            <div className="flex gap-2">
              <Input
                id="project-name"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="Ex: 12 rue de la Paix, Paris 75001"
                className="flex-1"
              />
              <Button
                onClick={handleSaveName}
                disabled={saving || !projectName.trim()}
                className="bg-teal-600 hover:bg-teal-700 text-white"
              >
                {saving ? "Enregistrement…" : "Enregistrer"}
              </Button>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
          <h2 className="font-serif text-lg text-slate-900">Actions</h2>

          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-slate-900">Cloner le projet</p>
                <p className="text-xs text-slate-500">
                  Crée une copie indépendante avec toutes les données actuelles.
                </p>
              </div>
              <Button
                variant="outline"
                onClick={handleClone}
                className="gap-2 shrink-0"
              >
                <Copy className="h-4 w-4" />
                Cloner
              </Button>
            </div>

            <div className="flex items-center justify-between rounded-lg border border-red-100 bg-red-50 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-red-900">Supprimer le projet</p>
                <p className="text-xs text-red-600">
                  Cette action est irréversible. Toutes les données seront perdues.
                </p>
              </div>
              <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
                <DialogTrigger asChild>
                  <Button variant="destructive" className="gap-2 shrink-0">
                    <Trash2 className="h-4 w-4" />
                    Supprimer
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Supprimer le projet ?</DialogTitle>
                    <DialogDescription>
                      Cette action est irréversible. Le projet et toutes ses données
                      (analyses, versions, rapports) seront définitivement supprimés.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <Button
                      variant="outline"
                      onClick={() => setDeleteOpen(false)}
                      disabled={deleting}
                    >
                      Annuler
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={handleDelete}
                      disabled={deleting}
                    >
                      {deleting ? "Suppression…" : "Supprimer définitivement"}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

export default function ProjectSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <ToastContainer>
      <SettingsPageContent projectId={id} />
    </ToastContainer>
  );
}
