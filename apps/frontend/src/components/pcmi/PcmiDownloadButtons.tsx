"use client";

import { Button } from "@/components/ui/button";
import { Download, Archive } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Props {
  projectId: string;
}

export function PcmiDownloadButtons({ projectId }: Props) {
  const pdfUrl = `${API_BASE}/api/v1/projects/${projectId}/pcmi/dossier.pdf`;
  const zipUrl = `${API_BASE}/api/v1/projects/${projectId}/pcmi/dossier.zip`;

  return (
    <div className="flex flex-wrap gap-3">
      <Button variant="outline" asChild>
        <a href={pdfUrl} download="dossier-pc.pdf" className="gap-2">
          <Download className="h-4 w-4" />
          Télécharger PDF unique
        </a>
      </Button>

      <Button variant="outline" asChild>
        <a href={zipUrl} download="dossier-pc.zip" className="gap-2">
          <Archive className="h-4 w-4" />
          Télécharger ZIP (pièces séparées)
        </a>
      </Button>
    </div>
  );
}
