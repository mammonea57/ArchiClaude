"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2, FileCheck } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface Props {
  projectId: string;
  onGenerated?: () => void;
}

export function PcmiGenerator({ projectId, onGenerated }: Props) {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  async function handleGenerate() {
    setLoading(true);
    setMessage(null);
    try {
      await apiFetch<{ job_id: string }>(`/projects/${projectId}/pcmi/generate`, {
        method: "POST",
      });
      setMessage({ text: "Dossier en cours de génération…", type: "success" });
      onGenerated?.();
    } catch {
      setMessage({ text: "Erreur lors de la génération du dossier PC.", type: "error" });
    } finally {
      setLoading(false);
      setTimeout(() => setMessage(null), 6000);
    }
  }

  return (
    <div className="flex items-center gap-3">
      {message && (
        <span
          className={`text-sm animate-in fade-in ${
            message.type === "success" ? "text-slate-600" : "text-red-500"
          }`}
        >
          {message.text}
        </span>
      )}
      <Button
        onClick={handleGenerate}
        disabled={loading}
        className="gap-2 text-white font-medium"
        style={{ backgroundColor: "var(--ac-primary)" }}
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <FileCheck className="h-4 w-4" />
        )}
        Générer le dossier PC
      </Button>
    </div>
  );
}
