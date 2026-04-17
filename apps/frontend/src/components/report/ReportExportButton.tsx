"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Download, Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface ReportExportButtonProps {
  resultId: string;
}

export function ReportExportButton({ resultId }: ReportExportButtonProps) {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleExport() {
    setLoading(true);
    setMessage(null);
    try {
      await apiFetch<{ job_id: string }>(`/feasibility/${resultId}/report.pdf`, {
        method: "POST",
      });
      setMessage("Génération en cours… Vous recevrez le PDF sous peu.");
    } catch {
      setMessage("Erreur lors de la génération du PDF.");
    } finally {
      setLoading(false);
      setTimeout(() => setMessage(null), 6000);
    }
  }

  return (
    <div className="flex items-center gap-3">
      {message && (
        <span className="text-sm text-slate-500 animate-in fade-in">{message}</span>
      )}
      <Button
        onClick={handleExport}
        disabled={loading}
        className="gap-2 text-white font-medium"
        style={{ backgroundColor: "var(--ac-primary)" }}
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Download className="h-4 w-4" />
        )}
        Exporter PDF
      </Button>
    </div>
  );
}
