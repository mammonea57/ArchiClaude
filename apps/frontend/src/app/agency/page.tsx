"use client";

import { CartoucheEditor } from "@/components/agency/CartoucheEditor";
import { ToastContainer, useToast } from "@/components/ui/toast";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

function AgencyPageContent() {
  const { showToast } = useToast();

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <Link
            href="/"
            className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"
          >
            <ArrowLeft className="h-4 w-4" />
            Accueil
          </Link>
          <span className="text-slate-300">|</span>
          <span className="font-serif text-xl">Paramètres de l&apos;agence</span>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-10">
        <div className="mb-6">
          <h1 className="font-serif text-2xl text-slate-900">
            Identité visuelle &amp; cartouche
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Ces informations apparaîtront sur les rapports et dossiers PC générés.
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <CartoucheEditor
            onSave={() => showToast("Paramètres enregistrés", "Votre cartouche a été mise à jour.")}
          />
        </div>
      </div>
    </main>
  );
}

export default function AgencyPage() {
  return (
    <ToastContainer>
      <AgencyPageContent />
    </ToastContainer>
  );
}
