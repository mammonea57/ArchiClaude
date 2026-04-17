import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const features = [
  {
    title: "Analyse PLU",
    description:
      "Extraction automatique des règles d'urbanisme : zonage, hauteurs, emprise, CES/COS, reculs.",
    icon: (
      <svg
        className="w-6 h-6"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M9 6.75V15m6-6v8.25m.503 3.498 4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 0 0-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0Z"
        />
      </svg>
    ),
  },
  {
    title: "Calcul de capacité",
    description:
      "Surface de plancher maximale, nombre de logements estimé, gabarit optimisé selon les contraintes réglementaires.",
    icon: (
      <svg
        className="w-6 h-6"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5m.75-9 3-3 2.148 2.148A12.061 12.061 0 0 1 16.5 7.605"
        />
      </svg>
    ),
  },
  {
    title: "Note d'architecte",
    description:
      "Notice architecturale réglementaire générée automatiquement, prête à intégrer dans votre dossier de permis de construire.",
    icon: (
      <svg
        className="w-6 h-6"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
        />
      </svg>
    ),
  },
];

export default function HomePage() {
  return (
    <main className="min-h-screen bg-white">
      {/* Navigation */}
      <nav className="border-b border-slate-100 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <span className="font-display text-xl font-semibold text-slate-900">
            ArchiClaude
          </span>
          <Badge
            variant="outline"
            className="text-xs text-slate-500 border-slate-200"
          >
            Île-de-France
          </Badge>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-6 pt-24 pb-20 text-center">
        <Badge
          className="mb-6 text-xs font-medium px-3 py-1"
          style={{
            backgroundColor: "color-mix(in srgb, var(--ac-primary) 12%, transparent)",
            color: "var(--ac-primary)",
            border: "1px solid color-mix(in srgb, var(--ac-primary) 25%, transparent)",
          }}
        >
          Promoteurs immobiliers IDF
        </Badge>

        <h1 className="font-display text-5xl sm:text-6xl font-bold text-slate-900 leading-tight mb-6">
          ArchiClaude
        </h1>

        <p className="text-xl text-slate-600 max-w-2xl mx-auto mb-4 leading-relaxed">
          Faisabilité architecturale automatisée pour l&apos;Île-de-France
        </p>

        <p className="text-sm text-slate-500 max-w-xl mx-auto mb-10">
          Analysez le PLU, calculez la capacité constructible et générez votre
          notice architecturale en quelques minutes.
        </p>

        <Link
          href="/projects/new"
          className="inline-flex items-center gap-2 px-8 py-3.5 rounded-lg text-white font-medium text-sm transition-opacity hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style={{
            backgroundColor: "var(--ac-primary)",
            "--tw-ring-color": "var(--ac-primary)",
          } as React.CSSProperties}
        >
          Commencer
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3"
            />
          </svg>
        </Link>
      </section>

      {/* Divider */}
      <div className="max-w-6xl mx-auto px-6">
        <div className="border-t border-slate-100" />
      </div>

      {/* Feature cards */}
      <section className="max-w-6xl mx-auto px-6 py-20">
        <p className="text-center text-xs font-semibold uppercase tracking-widest text-slate-400 mb-12">
          Ce que fait ArchiClaude
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {features.map((feature) => (
            <Card
              key={feature.title}
              className="border border-slate-100 shadow-none hover:border-slate-200 hover:shadow-sm transition-all"
            >
              <CardHeader className="pb-3">
                <div
                  className="w-10 h-10 rounded-lg flex items-center justify-center mb-3"
                  style={{
                    backgroundColor: "color-mix(in srgb, var(--ac-primary) 10%, transparent)",
                    color: "var(--ac-primary)",
                  }}
                >
                  {feature.icon}
                </div>
                <CardTitle className="text-base font-semibold text-slate-900">
                  {feature.title}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-slate-500 leading-relaxed">
                  {feature.description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-100 py-8 px-6 text-center">
        <p className="text-xs text-slate-400">
          ArchiClaude &mdash; outil interne promoteur &mdash; Île-de-France
        </p>
      </footer>
    </main>
  );
}
