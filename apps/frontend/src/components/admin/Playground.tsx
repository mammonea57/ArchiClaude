"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api";

interface PlaygroundResult {
  zone_code?: string;
  commune?: string;
  rules?: Record<string, unknown>;
  confidence?: number;
  raw?: unknown;
}

export function Playground() {
  const [communeCode, setCommuneCode] = useState("");
  const [zoneCode, setZoneCode] = useState("");
  const [pdfUrl, setPdfUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleTest() {
    if (!communeCode.trim() || !zoneCode.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await apiFetch<PlaygroundResult>(
        "/admin/playground/test-extraction",
        {
          method: "POST",
          body: JSON.stringify({
            commune_insee: communeCode.trim(),
            zone_code: zoneCode.trim(),
            pdf_url: pdfUrl.trim() || undefined,
          }),
        },
      );
      setResult(data);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError("Endpoint non disponible (placeholder v1).");
      } else {
        setError(
          e instanceof ApiError ? `Erreur ${e.status}: ${JSON.stringify(e.body)}` : "Erreur réseau",
        );
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="commune-code">Code INSEE commune</Label>
          <Input
            id="commune-code"
            value={communeCode}
            onChange={(e) => setCommuneCode(e.target.value)}
            placeholder="75056"
            className="font-mono"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="zone-code">Code de zone PLU</Label>
          <Input
            id="zone-code"
            value={zoneCode}
            onChange={(e) => setZoneCode(e.target.value)}
            placeholder="UG3"
            className="font-mono"
          />
        </div>

        <div className="sm:col-span-2 space-y-2">
          <Label htmlFor="pdf-url">URL PDF (optionnel)</Label>
          <Input
            id="pdf-url"
            value={pdfUrl}
            onChange={(e) => setPdfUrl(e.target.value)}
            placeholder="https://example.com/plu.pdf"
          />
        </div>
      </div>

      <Button
        onClick={handleTest}
        disabled={loading || !communeCode.trim() || !zoneCode.trim()}
        className="bg-teal-600 hover:bg-teal-700 text-white"
      >
        {loading ? "Extraction en cours…" : "Tester l'extraction"}
      </Button>

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-2">
          <p className="text-sm font-semibold text-slate-700">Résultat JSON</p>
          <pre className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-900 p-4 text-xs text-green-300 leading-relaxed">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
