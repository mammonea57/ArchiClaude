"use client";

interface SmartMarginTableProps {
  sdpMax: number;
  sdpRecommandee: number;
  margePct: number;
  niveaux: number;
  emprisePct: number;
  logementsMax: number;
  logementsRecommandes: number;
  raison: string;
}

function MargeBadge({ pct }: { pct: number }) {
  let colorClass = "bg-green-100 text-green-700";
  if (pct < 97) colorClass = "bg-orange-100 text-orange-700";
  else if (pct < 100) colorClass = "bg-yellow-100 text-yellow-700";

  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${colorClass}`}>
      {pct.toFixed(0)}%
    </span>
  );
}

function formatSdp(value: number): string {
  return value.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + " m²";
}

export function SmartMarginTable({
  sdpMax,
  sdpRecommandee,
  margePct,
  niveaux,
  emprisePct,
  logementsMax,
  logementsRecommandes,
  raison,
}: SmartMarginTableProps) {
  const rows: Array<{
    label: string;
    max: string;
    recommended: string;
    badge?: React.ReactNode;
    locked?: boolean;
  }> = [
    {
      label: "SDP",
      max: formatSdp(sdpMax),
      recommended: formatSdp(sdpRecommandee),
      badge: <MargeBadge pct={margePct} />,
    },
    {
      label: "Niveaux",
      max: `R+${niveaux - 1}`,
      recommended: `R+${niveaux - 1}`,
      locked: true,
    },
    {
      label: "Emprise",
      max: `${emprisePct.toFixed(0)}%`,
      recommended: `${emprisePct.toFixed(0)}%`,
      locked: true,
    },
    {
      label: "Logements",
      max: String(logementsMax),
      recommended: String(logementsRecommandes),
      badge:
        logementsRecommandes < logementsMax ? (
          <span className="text-xs text-orange-600 font-medium">
            -{logementsMax - logementsRecommandes}
          </span>
        ) : undefined,
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-hidden rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Paramètre
              </th>
              <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Max PLU
              </th>
              <th className="px-3 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Recommandé
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={idx}
                className={`border-b border-gray-100 last:border-0 ${
                  idx % 2 === 0 ? "bg-white" : "bg-gray-50/50"
                }`}
              >
                <td className="px-3 py-2.5 font-medium text-gray-700">
                  {row.label}
                </td>
                <td className="px-3 py-2.5 text-right text-gray-500">
                  {row.max}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <span
                      className={
                        row.locked
                          ? "text-gray-400"
                          : "font-semibold text-gray-800"
                      }
                    >
                      {row.recommended}
                    </span>
                    {row.locked && (
                      <span
                        className="text-xs text-gray-400"
                        title="Toujours au maximum PLU"
                      >
                        =
                      </span>
                    )}
                    {row.badge}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Raison */}
      {raison && (
        <div className="p-2.5 bg-blue-50 rounded-lg border border-blue-100">
          <p className="text-xs text-blue-700 leading-relaxed">{raison}</p>
        </div>
      )}

      {/* Footer note */}
      <p className="text-xs text-gray-400 italic">
        Le nombre de niveaux et l&apos;emprise restent toujours au maximum PLU
      </p>
    </div>
  );
}
