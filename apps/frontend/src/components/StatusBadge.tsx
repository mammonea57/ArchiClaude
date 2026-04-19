"use client";

const LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "Brouillon", color: "bg-slate-200 text-slate-700" },
  analyzed: { label: "Analysé", color: "bg-blue-100 text-blue-700" },
  reviewed: { label: "Validé", color: "bg-teal-100 text-teal-700" },
  ready_for_pc: { label: "Prêt pour dépôt", color: "bg-green-100 text-green-700" },
  archived: { label: "Archivé", color: "bg-slate-100 text-slate-500" },
};

export function StatusBadge({ status }: { status: string }) {
  const { label, color } = LABELS[status] ?? { label: status, color: "bg-slate-100 text-slate-700" };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {label}
    </span>
  );
}
