"use client";

export interface Version {
  id: string;
  version_number: number;
  version_label?: string;
  created_at: string;
}

interface VersionTimelineProps {
  versions: Version[];
  onSelect: (v: Version) => void;
  selectedIds?: string[];
}

export function VersionTimeline({
  versions,
  onSelect,
  selectedIds = [],
}: VersionTimelineProps) {
  if (versions.length === 0) {
    return (
      <p className="text-sm text-slate-400 italic">Aucune version enregistrée.</p>
    );
  }

  return (
    <div className="flex items-center gap-0 overflow-x-auto py-4">
      {versions.map((v, i) => {
        const isSelected = selectedIds.includes(v.id);
        const isLast = i === versions.length - 1;

        return (
          <div key={v.id} className="flex items-center">
            {/* Dot + label */}
            <button
              type="button"
              onClick={() => onSelect(v)}
              className="flex flex-col items-center gap-1 group"
            >
              <div
                className={`h-9 w-9 rounded-full border-2 flex items-center justify-center text-sm font-bold transition-all ${
                  isSelected
                    ? "border-teal-600 bg-teal-600 text-white shadow-md"
                    : "border-slate-300 bg-white text-slate-600 group-hover:border-teal-400 group-hover:text-teal-600"
                }`}
              >
                V{v.version_number}
              </div>
              <span
                className={`text-xs max-w-[80px] truncate text-center ${
                  isSelected ? "text-teal-700 font-semibold" : "text-slate-500"
                }`}
                title={v.version_label}
              >
                {v.version_label ?? new Date(v.created_at).toLocaleDateString("fr-FR")}
              </span>
            </button>

            {/* Connector line */}
            {!isLast && (
              <div className="h-0.5 w-12 bg-slate-200 mx-1 flex-shrink-0" />
            )}
          </div>
        );
      })}
    </div>
  );
}
