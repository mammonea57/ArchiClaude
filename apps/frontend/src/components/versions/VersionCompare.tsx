"use client";

interface VersionCompareProps {
  diff: Record<string, { old: unknown; new: unknown }>;
}

function stringify(val: unknown): string {
  if (val === null || val === undefined) return "—";
  if (typeof val === "object") return JSON.stringify(val);
  return String(val);
}

export function VersionCompare({ diff }: VersionCompareProps) {
  const fields = Object.keys(diff);

  if (fields.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-6 py-8 text-center">
        <p className="text-slate-500">Aucune modification entre ces deux versions.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-left text-sm">
        <thead className="border-b bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3 w-1/3">Champ</th>
            <th className="px-4 py-3 w-1/3">Ancienne valeur</th>
            <th className="px-4 py-3 w-1/3">Nouvelle valeur</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field, i) => {
            const entry = diff[field];
            const oldStr = stringify(entry.old);
            const newStr = stringify(entry.new);

            return (
              <tr
                key={field}
                className={`border-b last:border-0 ${i % 2 === 0 ? "bg-white" : "bg-slate-50/50"}`}
              >
                <td className="px-4 py-3 font-medium text-slate-700 font-mono text-xs">
                  {field}
                </td>
                <td className="px-4 py-3">
                  <span className="rounded bg-red-50 px-2 py-0.5 font-mono text-xs text-red-700 line-through decoration-red-400">
                    {oldStr}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="rounded bg-green-50 px-2 py-0.5 font-mono text-xs text-green-700">
                    {newStr}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
