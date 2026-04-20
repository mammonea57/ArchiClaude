"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useBilan } from "@/lib/hooks/useBilan";
import type { BilanChapitre, BilanResult } from "@/lib/types";

function fmtEur(n: number): string {
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtPct(n: number): string {
  return new Intl.NumberFormat("fr-FR", {
    style: "percent",
    maximumFractionDigits: 2,
  }).format(n);
}

function fmtM2(n: number): string {
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(n)} m²`;
}

function MargeBadge({ pct }: { pct: number }) {
  // Seuil bancaire : 12 % minimum, sinon opération non finançable.
  const isBankable = pct >= 0.12;
  const bg = isBankable ? "#dcfce7" : "#fee2e2";
  const color = isBankable ? "#15803d" : "#b91c1c";
  const Icon = isBankable ? TrendingUp : TrendingDown;
  return (
    <div
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold"
      style={{ backgroundColor: bg, color }}
      title={isBankable ? "Finançable par les banques" : "Non finançable — marge < 12 %"}
    >
      <Icon className="h-3.5 w-3.5" />
      Marge HT {fmtPct(pct)}
      {!isBankable && <span className="ml-1 text-xs font-normal">(seuil 12 %)</span>}
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div
      className="rounded-xl border p-4"
      style={{
        backgroundColor: accent ? "#f0fdf4" : "#fff",
        borderColor: accent ? "#bbf7d0" : "#e2e8f0",
      }}
    >
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div
        className="mt-1 font-display text-2xl font-bold"
        style={{ color: accent ? "#15803d" : "#0f172a" }}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

function ChapterTable({ chap }: { chap: BilanChapitre }) {
  return (
    <details className="rounded-lg border border-slate-100 bg-white open:shadow-sm">
      <summary className="flex cursor-pointer items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-baseline gap-3">
          <span className="font-semibold text-slate-900">{chap.nom}</span>
          <span className="text-xs text-slate-400">{chap.postes.length} postes</span>
        </div>
        <div className="flex items-baseline gap-3">
          <span className="text-xs text-slate-400">{fmtPct(chap.pct_depenses_ht)}</span>
          <span className="font-mono font-semibold text-slate-900">
            {fmtEur(chap.total_ht)}
          </span>
        </div>
      </summary>
      <div className="overflow-x-auto border-t border-slate-100">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Poste</th>
              <th className="px-4 py-2 text-right font-medium">Base</th>
              <th className="px-4 py-2 text-right font-medium">Taux / Unit.</th>
              <th className="px-4 py-2 text-right font-medium">HT</th>
              <th className="px-4 py-2 text-right font-medium">TVA</th>
              <th className="px-4 py-2 text-right font-medium">TTC</th>
            </tr>
          </thead>
          <tbody>
            {chap.postes.map((p, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="px-4 py-2 text-slate-700">{p.libelle}</td>
                <td className="px-4 py-2 text-right font-mono text-xs text-slate-500">
                  {p.base > 0 ? fmtEur(p.base) : "—"}
                </td>
                <td className="px-4 py-2 text-right font-mono text-xs text-slate-500">
                  {typeof p.taux_ou_unitaire === "number" && p.taux_ou_unitaire > 0
                    ? p.taux_ou_unitaire < 1
                      ? fmtPct(p.taux_ou_unitaire)
                      : fmtEur(p.taux_ou_unitaire)
                    : typeof p.taux_ou_unitaire === "string" && p.taux_ou_unitaire
                      ? p.taux_ou_unitaire
                      : "—"}
                </td>
                <td className="px-4 py-2 text-right font-mono text-slate-900">
                  {fmtEur(p.montant_ht)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-xs text-slate-500">
                  {p.montant_tva > 0 ? fmtEur(p.montant_tva) : "—"}
                </td>
                <td className="px-4 py-2 text-right font-mono text-slate-700">
                  {fmtEur(p.montant_ttc)}
                </td>
              </tr>
            ))}
            <tr className="border-t-2 border-slate-200 bg-slate-50">
              <td colSpan={3} className="px-4 py-2 font-semibold text-slate-900">
                Total {chap.nom}
              </td>
              <td className="px-4 py-2 text-right font-mono font-semibold text-slate-900">
                {fmtEur(chap.total_ht)}
              </td>
              <td className="px-4 py-2 text-right font-mono font-semibold text-slate-700">
                {fmtEur(chap.total_tva)}
              </td>
              <td className="px-4 py-2 text-right font-mono font-semibold text-slate-700">
                {fmtEur(chap.total_ttc)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  );
}

function BilanContent({ bilan }: { bilan: BilanResult }) {
  const { programme, recettes } = bilan;
  const chapters = [
    bilan.foncier,
    bilan.travaux,
    bilan.honoraires,
    bilan.assurances,
    bilan.commercialisation,
    bilan.gestion_financiere,
    bilan.imprevus,
  ];
  const nbLogts = Math.round(programme.shab_libre_m2 / 55 + programme.shab_social_m2 / 55);
  return (
    <div className="space-y-8">
      {/* Top KPIs */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          label="Recettes HT"
          value={fmtEur(recettes.total_ht)}
          sub={`${fmtEur(recettes.total_ttc)} TTC`}
        />
        <KpiCard
          label="Dépenses HT"
          value={fmtEur(bilan.depenses_total_ht)}
          sub={`${fmtEur(bilan.depenses_total_ttc)} TTC`}
        />
        <KpiCard
          label="Marge HT"
          value={fmtEur(bilan.marge_ht)}
          sub={fmtPct(bilan.marge_pct_ht)}
          accent
        />
        <KpiCard
          label="Charge foncière max"
          value={fmtEur(bilan.charge_fonciere_max_ht)}
          sub="Recettes − hors foncier"
        />
      </section>

      {/* Warnings */}
      {bilan.warnings.length > 0 && (
        <section className="space-y-2">
          {bilan.warnings.map((w, i) => (
            <div
              key={i}
              className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{w}</span>
            </div>
          ))}
        </section>
      )}

      {/* Programme */}
      <section className="rounded-xl border border-slate-100 bg-white p-5">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-700">
          Programme
        </h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4">
          <div>
            <span className="text-slate-400">Terrain</span>
            <div className="font-semibold text-slate-900">{fmtM2(programme.terrain_m2)}</div>
          </div>
          <div>
            <span className="text-slate-400">SDP</span>
            <div className="font-semibold text-slate-900">{fmtM2(programme.sdp_m2)}</div>
          </div>
          <div>
            <span className="text-slate-400">SHAB</span>
            <div className="font-semibold text-slate-900">
              {fmtM2(programme.shab_libre_m2 + programme.shab_social_m2)}
            </div>
          </div>
          <div>
            <span className="text-slate-400">Rendement plan</span>
            <div className="font-semibold text-slate-900">
              {fmtPct(programme.rendement_plan_shab_sur_sdp)}
            </div>
          </div>
          <div>
            <span className="text-slate-400">Logements (est.)</span>
            <div className="font-semibold text-slate-900">≈ {nbLogts}</div>
          </div>
          <div>
            <span className="text-slate-400">Parkings ss-sol</span>
            <div className="font-semibold text-slate-900">{programme.nb_parkings_ss_sol}</div>
          </div>
          <div>
            <span className="text-slate-400">Chantier</span>
            <div className="font-semibold text-slate-900">
              {programme.duree_chantier_mois} mois
            </div>
          </div>
          <div>
            <span className="text-slate-400">CES</span>
            <div className="font-semibold text-slate-900">{fmtPct(programme.ces)}</div>
          </div>
        </div>
      </section>

      {/* Recettes */}
      <section className="rounded-xl border border-slate-100 bg-white p-5">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-700">
          Recettes de vente
        </h2>
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="pb-2 text-left font-medium">Destination</th>
              <th className="pb-2 text-right font-medium">SHAB</th>
              <th className="pb-2 text-right font-medium">Prix €HT/m²</th>
              <th className="pb-2 text-right font-medium">HT</th>
              <th className="pb-2 text-right font-medium">TTC</th>
            </tr>
          </thead>
          <tbody>
            {recettes.libre_ht > 0 && (
              <tr className="border-t border-slate-100">
                <td className="py-2 text-slate-700">Logement libre</td>
                <td className="py-2 text-right font-mono">{fmtM2(recettes.libre_surface_m2)}</td>
                <td className="py-2 text-right font-mono">{fmtEur(recettes.libre_prix_ht_m2)}</td>
                <td className="py-2 text-right font-mono text-slate-900">
                  {fmtEur(recettes.libre_ht)}
                </td>
                <td className="py-2 text-right font-mono text-slate-600">
                  {fmtEur(recettes.libre_ttc)}
                </td>
              </tr>
            )}
            {recettes.social_ht > 0 && (
              <tr className="border-t border-slate-100">
                <td className="py-2 text-slate-700">Logement social</td>
                <td className="py-2 text-right font-mono">{fmtM2(recettes.social_surface_m2)}</td>
                <td className="py-2 text-right font-mono">{fmtEur(recettes.social_prix_ht_m2)}</td>
                <td className="py-2 text-right font-mono text-slate-900">
                  {fmtEur(recettes.social_ht)}
                </td>
                <td className="py-2 text-right font-mono text-slate-600">
                  {fmtEur(recettes.social_ttc)}
                </td>
              </tr>
            )}
            {recettes.commerce_ht > 0 && (
              <tr className="border-t border-slate-100">
                <td className="py-2 text-slate-700">Commerce</td>
                <td className="py-2 text-right font-mono">
                  {fmtM2(recettes.commerce_surface_m2)}
                </td>
                <td className="py-2 text-right font-mono">
                  {fmtEur(recettes.commerce_prix_ht_m2)}
                </td>
                <td className="py-2 text-right font-mono text-slate-900">
                  {fmtEur(recettes.commerce_ht)}
                </td>
                <td className="py-2 text-right font-mono text-slate-600">
                  {fmtEur(recettes.commerce_ttc)}
                </td>
              </tr>
            )}
            <tr className="border-t-2 border-slate-200 bg-slate-50">
              <td className="py-2 font-semibold text-slate-900">Total</td>
              <td className="py-2 text-right font-mono font-semibold">
                {fmtM2(
                  recettes.libre_surface_m2 +
                    recettes.social_surface_m2 +
                    recettes.commerce_surface_m2,
                )}
              </td>
              <td className="py-2 text-right font-mono text-xs text-slate-500">
                {fmtEur(recettes.prix_m2_shab_moyen_ht)} /m² moy.
              </td>
              <td className="py-2 text-right font-mono font-semibold text-slate-900">
                {fmtEur(recettes.total_ht)}
              </td>
              <td className="py-2 text-right font-mono font-semibold text-slate-700">
                {fmtEur(recettes.total_ttc)}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* Dépenses */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-700">
            Dépenses — 7 chapitres
          </h2>
          <span className="text-xs text-slate-400">
            Cliquez un chapitre pour voir le détail des postes
          </span>
        </div>
        <div className="space-y-2">
          {chapters.map((c) => (
            <ChapterTable key={c.nom} chap={c} />
          ))}
          <div className="flex items-center justify-between rounded-lg border-2 border-slate-300 bg-slate-100 px-4 py-3">
            <span className="font-semibold text-slate-900">Total dépenses</span>
            <div className="flex items-baseline gap-4">
              <span className="text-xs text-slate-500">100%</span>
              <span className="font-mono text-lg font-bold text-slate-900">
                {fmtEur(bilan.depenses_total_ht)} HT
              </span>
              <span className="font-mono text-sm text-slate-600">
                {fmtEur(bilan.depenses_total_ttc)} TTC
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* TVA + Marge finale */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-slate-100 bg-white p-5">
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-700">
            TVA
          </h3>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">TVA sur ventes</dt>
              <dd className="font-mono text-slate-900">{fmtEur(bilan.tva_sur_ventes)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">TVA déductible</dt>
              <dd className="font-mono text-slate-900">− {fmtEur(bilan.tva_deductible)}</dd>
            </div>
            <div className="flex justify-between border-t border-slate-100 pt-2">
              <dt className="font-semibold text-slate-900">TVA résiduelle</dt>
              <dd className="font-mono font-semibold text-slate-900">
                {fmtEur(bilan.tva_residuelle)}
              </dd>
            </div>
          </dl>
        </div>

        <div
          className="rounded-xl border-2 p-5"
          style={{
            backgroundColor: "#f0fdf4",
            borderColor: "#bbf7d0",
          }}
        >
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-green-900">
              Rentabilité réelle
            </h3>
            <MargeBadge pct={bilan.marge_pct_ht} />
          </div>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-600">Recettes</dt>
              <dd className="font-mono text-slate-900">{fmtEur(bilan.recettes.total_ht)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-600">Dépenses</dt>
              <dd className="font-mono text-slate-900">− {fmtEur(bilan.depenses_total_ht)}</dd>
            </div>
            <div className="flex justify-between border-t border-green-200 pt-2">
              <dt className="font-bold text-green-900">Marge HT</dt>
              <dd className="font-mono text-xl font-bold text-green-900">
                {fmtEur(bilan.marge_ht)}
              </dd>
            </div>
            <div className="flex justify-between text-xs">
              <dt className="text-slate-500">Marge TTC</dt>
              <dd className="font-mono text-slate-700">
                {fmtEur(bilan.marge_ttc)} ({fmtPct(bilan.marge_pct_ttc)})
              </dd>
            </div>
          </dl>
        </div>
      </section>
    </div>
  );
}

export default function BilanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { bilan, loading, error, notFound } = useBilan(id);

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <Link href="/" className="font-display text-xl font-semibold text-slate-900">
            ArchiClaude
          </Link>
          <Link
            href="/account"
            className="text-sm text-slate-500 transition-colors hover:text-slate-700"
          >
            Mon compte
          </Link>
        </div>
      </nav>

      <div className="mx-auto max-w-6xl space-y-6 px-6 py-10">
        <Link
          href={`/projects/${id}`}
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 transition-colors hover:text-slate-700"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour au projet
        </Link>

        <div className="flex items-baseline justify-between">
          <h1 className="font-display text-3xl font-bold text-slate-900">Bilan promoteur</h1>
          {bilan && (
            <Badge
              className="text-xs"
              style={{ backgroundColor: "#f1f5f9", color: "#475569", borderColor: "transparent" }}
            >
              {bilan.option_label.toUpperCase()}
            </Badge>
          )}
        </div>

        {loading && (
          <div className="py-20 text-center text-sm text-slate-400">
            Calcul du bilan en cours…
          </div>
        )}
        {error && (
          <div className="py-20 text-center text-sm text-red-500">Erreur : {error}</div>
        )}
        {notFound && (
          <div className="rounded-xl border border-slate-100 bg-white p-10 text-center">
            <p className="text-sm text-slate-500">
              Aucun modèle bâtiment n&apos;a encore été généré — le bilan ne peut pas être calculé.
            </p>
            <Link
              href={`/projects/${id}/plans`}
              className="mt-3 inline-block text-sm font-medium"
              style={{ color: "var(--ac-primary)" }}
            >
              → Générer les plans d&apos;abord
            </Link>
          </div>
        )}
        {bilan && <BilanContent bilan={bilan} />}
      </div>
    </main>
  );
}
