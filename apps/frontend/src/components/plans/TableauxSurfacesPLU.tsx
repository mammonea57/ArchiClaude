"use client";

import type { BuildingModelPayload } from "@/lib/types";

interface TableauxProps {
  bm: BuildingModelPayload;
  /** Optional bilan programme section — richer SDP/SHAB breakdown if available. */
  bilanProgramme?: {
    terrain_m2?: number;
    sdp_m2?: number;
    shab_libre_m2?: number;
    shab_social_m2?: number;
    shab_commerce_m2?: number;
    rendement_plan_shab_sur_sdp?: number;
    nb_parkings_ss_sol?: number;
    nb_parkings_exterieurs?: number;
  } | null;
}

const fmtM2 = (v: number) => `${Math.round(v).toLocaleString("fr-FR")} m²`;
const fmtPct = (v: number) => `${(v * 100).toFixed(1)} %`;

/**
 * Tableaux réglementaires PC4 — surfaces par niveau + conformité PLU (constats).
 * Source unique : BuildingModelPayload + optional bilan programme. Pas de hardcode.
 */
export function TableauxSurfacesPLU({ bm, bilanProgramme }: TableauxProps) {
  const env = bm.envelope;
  const parcelle = bm.site.parcelle_surface_m2;
  const empriseM2 = env.emprise_m2;
  const cesConstat = parcelle > 0 ? empriseM2 / parcelle : 0;
  const pleineTerreM2 = Math.max(0, parcelle - empriseM2);
  const pleineTerrePct = parcelle > 0 ? pleineTerreM2 / parcelle : 0;

  // Per-niveau breakdown from BM: SP from niveau.surface_plancher_m2,
  // SHAB = sum of cellules (type=logement) .surface_m2.
  const niveaux = [...bm.niveaux].sort((a, b) => a.index - b.index);
  const perNiveau = niveaux.map((n) => {
    const logements = n.cellules.filter((c) => c.type === "logement");
    const shab = logements.reduce((acc, c) => acc + (c.surface_m2 ?? 0), 0);
    const circ = (n.circulations_communes ?? []).reduce((acc, c) => acc + (c.surface_m2 ?? 0), 0);
    const autres = n.cellules
      .filter((c) => c.type !== "logement")
      .reduce((acc, c) => acc + (c.surface_m2 ?? 0), 0);
    return {
      code: n.code,
      usage: n.usage_principal,
      sp: n.surface_plancher_m2 ?? 0,
      shab,
      circ,
      autres,
      nbLogements: logements.length,
    };
  });
  const totBM = perNiveau.reduce(
    (acc, r) => ({
      sp: acc.sp + r.sp,
      shab: acc.shab + r.shab,
      circ: acc.circ + r.circ,
      autres: acc.autres + r.autres,
      nbLogements: acc.nbLogements + r.nbLogements,
    }),
    { sp: 0, shab: 0, circ: 0, autres: 0, nbLogements: 0 },
  );

  // Prefer bilan totals (post-solver rounded values) when available, else BM sums.
  const sdpTotal = bilanProgramme?.sdp_m2 ?? totBM.sp;
  const shabTotal = bilanProgramme
    ? (bilanProgramme.shab_libre_m2 ?? 0) + (bilanProgramme.shab_social_m2 ?? 0) + (bilanProgramme.shab_commerce_m2 ?? 0)
    : totBM.shab;
  const rendement = sdpTotal > 0 ? shabTotal / sdpTotal : 0;

  return (
    <div className="space-y-6">
      {/* ─── Tableau surfaces ─── */}
      <section className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <header className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Tableau des surfaces</h2>
            <p className="text-xs text-slate-400">PC4 · Ventilation par niveau — SDP, SHAB, circulations</p>
          </div>
          <span className="text-xs text-slate-400">Source : BM v{bm.metadata.version}{bilanProgramme ? " + bilan" : ""}</span>
        </header>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Niveau</th>
                <th className="px-4 py-2 text-left font-medium">Usage</th>
                <th className="px-4 py-2 text-right font-medium">Logements</th>
                <th className="px-4 py-2 text-right font-medium">SHAB</th>
                <th className="px-4 py-2 text-right font-medium">Circ. communes</th>
                <th className="px-4 py-2 text-right font-medium">Autres</th>
                <th className="px-4 py-2 text-right font-medium">SP</th>
              </tr>
            </thead>
            <tbody>
              {perNiveau.map((r) => (
                <tr key={r.code} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-semibold text-slate-900">{r.code}</td>
                  <td className="px-4 py-2 text-slate-600">{r.usage}</td>
                  <td className="px-4 py-2 text-right font-mono text-slate-700">{r.nbLogements}</td>
                  <td className="px-4 py-2 text-right font-mono text-slate-900">{fmtM2(r.shab)}</td>
                  <td className="px-4 py-2 text-right font-mono text-slate-500">{fmtM2(r.circ)}</td>
                  <td className="px-4 py-2 text-right font-mono text-slate-500">{fmtM2(r.autres)}</td>
                  <td className="px-4 py-2 text-right font-mono text-slate-900">{fmtM2(r.sp)}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-slate-300 bg-slate-50">
                <td className="px-4 py-2 font-bold text-slate-900">Total</td>
                <td className="px-4 py-2 text-slate-600" />
                <td className="px-4 py-2 text-right font-mono font-bold text-slate-900">{totBM.nbLogements}</td>
                <td className="px-4 py-2 text-right font-mono font-bold text-slate-900">{fmtM2(shabTotal)}</td>
                <td className="px-4 py-2 text-right font-mono text-slate-700">{fmtM2(totBM.circ)}</td>
                <td className="px-4 py-2 text-right font-mono text-slate-700">{fmtM2(totBM.autres)}</td>
                <td className="px-4 py-2 text-right font-mono font-bold text-slate-900">{fmtM2(sdpTotal)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Summary row */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 px-5 py-4 border-t border-slate-100 bg-slate-50/50 text-sm">
          <Stat label="Terrain" value={fmtM2(parcelle)} />
          <Stat label="Emprise bâtie" value={fmtM2(empriseM2)} hint={fmtPct(cesConstat)} />
          <Stat label="Pleine terre" value={fmtM2(pleineTerreM2)} hint={fmtPct(pleineTerrePct)} />
          <Stat label="SDP" value={fmtM2(sdpTotal)} />
          <Stat label="SHAB / SDP" value={fmtPct(rendement)} hint={`${fmtM2(shabTotal)} hab.`} />
        </div>

        {bilanProgramme && (
          <div className="px-5 pb-4 flex flex-wrap gap-4 text-xs text-slate-600">
            {typeof bilanProgramme.shab_libre_m2 === "number" && (
              <span>SHAB libre : <b className="text-slate-900">{fmtM2(bilanProgramme.shab_libre_m2)}</b></span>
            )}
            {typeof bilanProgramme.shab_social_m2 === "number" && bilanProgramme.shab_social_m2 > 0 && (
              <span>SHAB LLS : <b className="text-slate-900">{fmtM2(bilanProgramme.shab_social_m2)}</b></span>
            )}
            {typeof bilanProgramme.shab_commerce_m2 === "number" && bilanProgramme.shab_commerce_m2 > 0 && (
              <span>Commerce : <b className="text-slate-900">{fmtM2(bilanProgramme.shab_commerce_m2)}</b></span>
            )}
            {typeof bilanProgramme.nb_parkings_ss_sol === "number" && (
              <span>Parkings S/S : <b className="text-slate-900">{bilanProgramme.nb_parkings_ss_sol}</b></span>
            )}
            {typeof bilanProgramme.nb_parkings_exterieurs === "number" && (
              <span>Parkings ext. : <b className="text-slate-900">{bilanProgramme.nb_parkings_exterieurs}</b></span>
            )}
          </div>
        )}
      </section>

      {/* ─── Tableau PLU ─── */}
      <section className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <header className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">
              Tableau PLU — zone <span className="font-mono">{bm.metadata.zone_plu}</span>
            </h2>
            <p className="text-xs text-slate-400">PC4 · Constats par rapport au règlement communal</p>
          </div>
        </header>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Règle</th>
                <th className="px-4 py-2 text-right font-medium">Constat projet</th>
                <th className="px-4 py-2 text-left font-medium">Unité / article</th>
              </tr>
            </thead>
            <tbody>
              <PLURow label="Emprise au sol" value={`${Math.round(empriseM2)} (${fmtPct(cesConstat)})`} unit="m² · CES constaté · art. UA.9" />
              <PLURow label="Hauteur totale" value={`${env.hauteur_totale_m.toFixed(1)}`} unit="m au-dessus du sol naturel · art. UA.10" />
              <PLURow label="Nombre de niveaux" value={`R+${env.niveaux - 1} (${env.niveaux} niveaux)`} unit="étages sur rez" />
              <PLURow label="Hauteur sous plafond — RDC" value={`${env.hauteur_rdc_m.toFixed(2)}`} unit="m" />
              <PLURow label="Hauteur sous plafond — étages courants" value={`${env.hauteur_etage_courant_m.toFixed(2)}`} unit="m" />
              <PLURow label="Pleine terre" value={`${Math.round(pleineTerreM2)} (${fmtPct(pleineTerrePct)})`} unit="m² · art. UA.13" />
              <PLURow
                label="Toiture"
                value={
                  (() => {
                    const toit = (env as { toiture?: { type?: string; vegetalisee?: boolean; accessible?: boolean } }).toiture;
                    if (!toit) return "non renseignée";
                    const parts = [toit.type ?? "terrasse"];
                    if (toit.vegetalisee) parts.push("végétalisée");
                    if (toit.accessible) parts.push("accessible");
                    return parts.join(", ");
                  })()
                }
                unit="—"
              />
              <PLURow label="Orientation voirie" value={(bm.site.voirie_orientations ?? []).join(" / ") || "—"} unit="cardinale" />
            </tbody>
          </table>
        </div>

        <div className="px-5 py-3 border-t border-slate-100 bg-amber-50/50 text-xs text-amber-800">
          ⚠ Les valeurs maximales réglementaires (emprise max, hauteur max, retraits min)
          nécessitent l&apos;extraction PLU pour la zone <b>{bm.metadata.zone_plu}</b>.
          Une fois l&apos;extraction validée, la colonne « autorisé » et le badge de
          conformité seront ajoutés automatiquement.
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-xs text-slate-400">{label}</p>
      <p className="font-semibold text-slate-900">{value}</p>
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

function PLURow({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <tr className="border-t border-slate-100">
      <td className="px-4 py-2 text-slate-700">{label}</td>
      <td className="px-4 py-2 text-right font-mono font-semibold text-slate-900">{value}</td>
      <td className="px-4 py-2 text-xs text-slate-500">{unit}</td>
    </tr>
  );
}
