"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

interface PlanExportButtonProps {
  /** The project ID used to build API URLs */
  projectId: string;
  /** The plan type key used in the API path (e.g. "masse", "niveau_0", "coupe") */
  planType: string;
  /** Current SVG content (for direct SVG export without re-fetching) */
  svgContent?: string;
  /** Base URL for the API. Defaults to /api/v1 */
  apiBase?: string;
}

export function PlanExportButton({
  projectId,
  planType,
  svgContent,
  apiBase = "/api/v1",
}: PlanExportButtonProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  function exportSvg() {
    setOpen(false);
    if (!svgContent) return;
    const blob = new Blob([svgContent], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function exportDxf() {
    setOpen(false);
    setLoading(true);
    try {
      const url = `${apiBase}/projects/${projectId}/plans/${planType}/dxf`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = `${planType}.dxf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      console.error("DXF export failed:", err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative inline-block">
      <Button
        size="sm"
        variant="outline"
        onClick={() => setOpen((v) => !v)}
        disabled={loading}
      >
        {loading ? "Export…" : "Exporter ▾"}
      </Button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[160px] rounded-md border border-slate-200 bg-white shadow-md py-1">
          <button
            className="w-full text-left px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
            onClick={exportSvg}
            disabled={!svgContent}
          >
            Exporter SVG
          </button>
          <button
            className="w-full text-left px-4 py-2 text-sm hover:bg-slate-50"
            onClick={exportDxf}
          >
            Exporter DXF
          </button>
        </div>
      )}

      {/* Click-outside overlay */}
      {open && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setOpen(false)}
        />
      )}
    </div>
  );
}
