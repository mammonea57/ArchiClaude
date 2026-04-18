import Link from "next/link";
import { CostsDashboard } from "@/components/admin/CostsDashboard";

export default function AdminPage() {
  return (
    <div className="space-y-10">
      {/* KPI / Costs */}
      <section>
        <h2 className="text-xl font-serif mb-4">Coûts d&apos;extraction</h2>
        <CostsDashboard />
      </section>

      {/* Quick links */}
      <section>
        <h2 className="text-xl font-serif mb-4">Outils</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Link
            href="/admin/flags"
            className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm hover:border-teal-400 hover:shadow-md transition-all group"
          >
            <h3 className="font-semibold text-slate-900 group-hover:text-teal-700">
              Feature flags
            </h3>
            <p className="text-sm text-slate-500 mt-1">
              Activer / désactiver les fonctionnalités par utilisateur.
            </p>
          </Link>

          <Link
            href="/admin/playground"
            className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm hover:border-teal-400 hover:shadow-md transition-all group"
          >
            <h3 className="font-semibold text-slate-900 group-hover:text-teal-700">
              Playground extraction
            </h3>
            <p className="text-sm text-slate-500 mt-1">
              Tester l&apos;extraction PLU pour une commune et une zone données.
            </p>
          </Link>

          <Link
            href="/admin/telemetry"
            className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm hover:border-teal-400 hover:shadow-md transition-all group"
          >
            <h3 className="font-semibold text-slate-900 group-hover:text-teal-700">
              Télémétrie corrections
            </h3>
            <p className="text-sm text-slate-500 mt-1">
              Statistiques sur les corrections et zones problématiques.
            </p>
          </Link>
        </div>
      </section>
    </div>
  );
}
