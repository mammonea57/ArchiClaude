"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { RuleValidator } from "@/components/forms/RuleValidator";
import { ToastContainer, useToast } from "@/components/ui/toast";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

// Placeholder rules for v1 — in production these come from the backend
const PLACEHOLDER_RULES: Record<string, string | null> = {
  hauteur_max_m: "12",
  emprise_sol_max_pct: "60",
  cos: null,
  stationnement_par_logement: "1",
  pleine_terre_min_pct: "20",
  retrait_front: "5",
  retrait_lateral: "3",
  retrait_fond: "4",
  destination_principale: "Habitat",
};

function RulesPageContent({ zoneId }: { zoneId: string }) {
  const router = useRouter();
  const { showToast } = useToast();
  const [validated, setValidated] = useState(false);

  function handleValidate(edits: Record<string, string>) {
    setValidated(true);
    showToast("Règles validées", "Les règles PLU ont été enregistrées.");
    setTimeout(() => router.back(), 1500);
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <Link
            href="/"
            className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"
          >
            <ArrowLeft className="h-4 w-4" />
            Retour
          </Link>
          <span className="text-slate-300">|</span>
          <span className="font-serif text-xl">Validation des règles PLU</span>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-10">
        <div className="mb-6">
          <h1 className="font-serif text-2xl text-slate-900">Zone {zoneId}</h1>
          <p className="mt-1 text-sm text-slate-500">
            Vérifiez et corrigez les règles extraites automatiquement du PLU.
          </p>
        </div>

        {validated ? (
          <div className="rounded-xl border border-teal-200 bg-teal-50 px-6 py-8 text-center">
            <p className="text-teal-700 font-semibold text-lg">
              Règles validées avec succès
            </p>
            <p className="mt-1 text-sm text-teal-600">Redirection en cours…</p>
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <RuleValidator
              zoneId={zoneId}
              extractedRules={PLACEHOLDER_RULES}
              confidence={0.78}
              onValidate={handleValidate}
            />
          </div>
        )}
      </div>
    </main>
  );
}

export default function RulesPage({
  params,
}: {
  params: Promise<{ zone_id: string }>;
}) {
  const { zone_id } = use(params);

  return (
    <ToastContainer>
      <RulesPageContent zoneId={zone_id} />
    </ToastContainer>
  );
}
