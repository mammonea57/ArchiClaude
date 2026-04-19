"use client";

import { Download } from "lucide-react";

interface Revision {
  indice: string;
  generated_at: string;
  pdf_url: string;
}

interface Props {
  revisions: Revision[];
}

function formatDate(isoString: string): string {
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(isoString));
  } catch {
    return isoString;
  }
}

export function RevisionHistory({ revisions }: Props) {
  if (revisions.length === 0) {
    return (
      <p className="text-sm text-slate-400 italic py-2">Aucune révision générée.</p>
    );
  }

  return (
    <div className="divide-y divide-slate-100">
      {revisions.map((rev) => (
        <div
          key={rev.indice}
          className="flex items-center justify-between py-3 gap-4"
        >
          <div className="flex items-center gap-3 min-w-0">
            <span
              className="text-sm font-bold tabular-nums shrink-0"
              style={{ color: "var(--ac-primary)" }}
            >
              {rev.indice}
            </span>
            <span className="text-xs text-slate-400 truncate">
              {formatDate(rev.generated_at)}
            </span>
          </div>
          <a
            href={rev.pdf_url}
            download
            className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-800 transition-colors shrink-0"
          >
            <Download className="h-3.5 w-3.5" />
            Télécharger
          </a>
        </div>
      ))}
    </div>
  );
}
