"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

interface Props {
  projectId: string;
  materialsConfig: Record<string, string>;
  cameraConfig: {
    lat: number;
    lng: number;
    heading: number;
    pitch: number;
    fov: number;
  };
  photoSource: string;
  photoSourceId: string;
  photoBaseUrl: string;
  exportLayers: () => Promise<{ mask: Blob; normal: Blob; depth: Blob }>;
  onRenderComplete?: (renderId: string) => void;
}

type RenderStatus = "idle" | "exporting" | "uploading" | "rendering" | "done" | "failed";

export function RenderTrigger({
  projectId,
  materialsConfig,
  cameraConfig,
  photoSource,
  photoSourceId,
  photoBaseUrl,
  exportLayers,
  onRenderComplete,
}: Props) {
  const [status, setStatus] = useState<RenderStatus>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [renderUrl, setRenderUrl] = useState<string | null>(null);

  async function handleGenerate() {
    setStatus("exporting");
    setErrorMsg(null);
    setRenderUrl(null);

    try {
      const layers = await exportLayers();

      setStatus("uploading");
      const formData = new FormData();
      formData.append("mask", layers.mask, "mask.png");
      formData.append("normal", layers.normal, "normal.png");
      formData.append("depth", layers.depth, "depth.png");
      formData.append(
        "payload",
        JSON.stringify({
          photo_source: photoSource,
          photo_source_id: photoSourceId,
          photo_base_url: photoBaseUrl,
          camera: cameraConfig,
          materials_config: materialsConfig,
        }),
      );

      setStatus("rendering");
      const data = await apiFetch<{ render_id: string; job_id: string }>(
        `/projects/${projectId}/pcmi6/renders`,
        {
          method: "POST",
          // API route accepts both JSON (v1 placeholder) and multipart (v2)
          body: JSON.stringify({
            photo_source: photoSource,
            photo_source_id: photoSourceId,
            photo_base_url: photoBaseUrl,
            camera: cameraConfig,
            materials_config: materialsConfig,
          }),
          headers: { "Content-Type": "application/json" },
        },
      );

      setStatus("done");
      onRenderComplete?.(data.render_id);
    } catch (err) {
      setStatus("failed");
      setErrorMsg(err instanceof Error ? err.message : "Erreur lors de la génération");
    }
  }

  const label = {
    idle: "Générer le rendu",
    exporting: "Export des calques…",
    uploading: "Envoi en cours…",
    rendering: "Rendu IA en cours…",
    done: "Rendu terminé",
    failed: "Réessayer",
  }[status];

  return (
    <div className="flex flex-col gap-2">
      <Button
        onClick={handleGenerate}
        disabled={status !== "idle" && status !== "failed" && status !== "done"}
        style={{ backgroundColor: "var(--ac-primary)", color: "white" }}
        className="w-full"
      >
        {label}
      </Button>
      {errorMsg && <p className="text-xs text-red-600">{errorMsg}</p>}
      {renderUrl && (
        <div className="mt-2 border border-slate-200 rounded-lg overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={renderUrl} alt="Rendu PCMI6" className="w-full h-auto" />
        </div>
      )}
    </div>
  );
}
