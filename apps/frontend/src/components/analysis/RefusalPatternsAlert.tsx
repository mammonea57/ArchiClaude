"use client";

interface RefusalPattern {
  motif: string;
  occurrences: number;
  recommandation: string;
}

interface RefusalPatternsAlertProps {
  gabaritDominant: number | null;
  projetDepasse: boolean;
  depassementNiveaux: number;
  patterns: RefusalPattern[];
}

function getSeverityColor(occurrences: number): {
  bg: string;
  border: string;
  text: string;
  badge: string;
} {
  if (occurrences >= 3) {
    return {
      bg: "bg-red-50",
      border: "border-red-200",
      text: "text-red-800",
      badge: "bg-red-100 text-red-700",
    };
  }
  if (occurrences === 2) {
    return {
      bg: "bg-orange-50",
      border: "border-orange-200",
      text: "text-orange-800",
      badge: "bg-orange-100 text-orange-700",
    };
  }
  return {
    bg: "bg-yellow-50",
    border: "border-yellow-200",
    text: "text-yellow-800",
    badge: "bg-yellow-100 text-yellow-700",
  };
}

export function RefusalPatternsAlert({
  gabaritDominant,
  projetDepasse,
  depassementNiveaux,
  patterns,
}: RefusalPatternsAlertProps) {
  if (!gabaritDominant && patterns.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Gabarit banner */}
      {gabaritDominant !== null && (
        <div
          className={`flex items-start gap-3 p-3 rounded-lg border ${
            projetDepasse
              ? "bg-orange-50 border-orange-300"
              : "bg-green-50 border-green-200"
          }`}
        >
          <span className="text-lg">{projetDepasse ? "⚠" : "✓"}</span>
          <div>
            <p
              className={`text-sm font-semibold ${
                projetDepasse ? "text-orange-800" : "text-green-800"
              }`}
            >
              Gabarit dominant R+{gabaritDominant - 1} à 200m
            </p>
            {projetDepasse ? (
              <p className="text-xs text-orange-700 mt-0.5">
                Le projet dépasse le gabarit dominant de{" "}
                <span className="font-semibold">
                  {depassementNiveaux} niveau
                  {depassementNiveaux > 1 ? "x" : ""}
                </span>{" "}
                — risque de recours accru.
              </p>
            ) : (
              <p className="text-xs text-green-700 mt-0.5">
                Le projet s&apos;inscrit dans le gabarit dominant du quartier.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Refusal patterns list */}
      {patterns.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Motifs de refus identifiés à 500m
          </p>
          {patterns.map((p, idx) => {
            const colors = getSeverityColor(p.occurrences);
            return (
              <div
                key={idx}
                className={`flex items-start gap-3 p-3 rounded-lg border ${colors.bg} ${colors.border}`}
              >
                <span
                  className={`text-xs font-bold px-2 py-0.5 rounded-full whitespace-nowrap ${colors.badge}`}
                >
                  ×{p.occurrences}
                </span>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${colors.text}`}>
                    {p.motif}
                  </p>
                  {p.recommandation && (
                    <p className="text-xs text-gray-600 mt-0.5 leading-relaxed">
                      {p.recommandation}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
