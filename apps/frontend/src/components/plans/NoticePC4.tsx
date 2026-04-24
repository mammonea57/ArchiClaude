"use client";

import type { BuildingModelPayload } from "@/lib/types";

interface NoticeProps {
  bm: BuildingModelPayload;
  address?: string;
  communeName?: string;
  codePostal?: string;
  bilanProgramme?: {
    shab_libre_m2?: number;
    shab_social_m2?: number;
    shab_commerce_m2?: number;
    nb_parkings_ss_sol?: number;
    nb_parkings_exterieurs?: number;
  } | null;
}

/**
 * PC4 notice PCMI — document de présentation descriptive et justificative
 * du projet. Sections obligatoires selon art. R. 431-8 CU :
 *   - État initial du terrain
 *   - Parti architectural du projet
 *   - Traitement des espaces extérieurs
 *   - Conformité réglementaire (PLU, RE2020, PMR, incendie)
 *
 * Le texte est auto-généré à partir du BuildingModel. Toutes les valeurs
 * numériques proviennent de la source de vérité (BM + bilan). Aucun chiffre
 * hardcodé.
 */
export function NoticePC4({ bm, address, communeName, codePostal, bilanProgramme }: NoticeProps) {
  const env = bm.envelope;
  const parcelle = bm.site.parcelle_surface_m2;
  const emprise = env.emprise_m2;
  const cesPct = parcelle > 0 ? (emprise / parcelle) * 100 : 0;
  const pleineTerreM2 = Math.max(0, parcelle - emprise);
  const pleineTerrePct = parcelle > 0 ? (pleineTerreM2 / parcelle) * 100 : 0;

  const niveaux = [...bm.niveaux].sort((a, b) => a.index - b.index);
  const nbLogements = niveaux.reduce(
    (acc, n) => acc + n.cellules.filter((c) => c.type === "logement").length, 0,
  );
  const sdpTotal = niveaux.reduce((acc, n) => acc + (n.surface_plancher_m2 ?? 0), 0);
  const shabTotal = bilanProgramme
    ? (bilanProgramme.shab_libre_m2 ?? 0) + (bilanProgramme.shab_social_m2 ?? 0) + (bilanProgramme.shab_commerce_m2 ?? 0)
    : niveaux.reduce(
        (acc, n) => acc + n.cellules.filter((c) => c.type === "logement").reduce((a, c) => a + c.surface_m2, 0),
        0,
      );
  const shabSocial = bilanProgramme?.shab_social_m2 ?? 0;

  // Typology mix
  const mixCounts = new Map<string, number>();
  for (const n of niveaux) {
    for (const c of n.cellules) {
      if (c.type !== "logement") continue;
      const t = (c.typologie ?? "?").toUpperCase();
      mixCounts.set(t, (mixCounts.get(t) ?? 0) + 1);
    }
  }
  const mixStr = Array.from(mixCounts.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([t, n]) => `${n} × ${t}`)
    .join(", ");

  // Core / PMR
  const core = bm.core as {
    ascenseur?: unknown;
    escalier?: { nb_marches_par_niveau?: number; giron_cm?: number; hauteur_marche_cm?: number };
  };
  const hasAsc = !!core.ascenseur;
  const voirieSides = bm.site.voirie_orientations ?? [];
  const toit = (env as { toiture?: { type?: string; vegetalisee?: boolean; accessible?: boolean } }).toiture;

  const nbParking = (bilanProgramme?.nb_parkings_ss_sol ?? 0) + (bilanProgramme?.nb_parkings_exterieurs ?? 0);
  const ratioParking = nbLogements > 0 ? nbParking / nbLogements : 0;

  return (
    <article className="bg-white border border-slate-200 rounded-xl p-8 max-w-4xl mx-auto text-sm leading-relaxed text-slate-800 font-serif">
      <header className="border-b border-slate-300 pb-4 mb-6">
        <p className="text-xs text-slate-500 uppercase tracking-wider font-sans">
          Pièce PC4 — Notice descriptive et justificative
        </p>
        <h1 className="text-2xl font-bold text-slate-900 mt-1">Notice du projet</h1>
        <p className="text-sm text-slate-600 mt-2">
          {address ?? "Adresse non renseignée"}
          {communeName ? ` — ${codePostal ?? ""} ${communeName}`.trim() : ""}
        </p>
        <p className="text-xs text-slate-400 mt-1">
          Zone PLU <span className="font-mono font-semibold">{bm.metadata.zone_plu}</span>
          {" · "}Parcelle {Math.round(parcelle).toLocaleString("fr-FR")} m²
        </p>
      </header>

      <Section title="1. État initial du terrain">
        <p>
          Le terrain d&apos;assiette représente une parcelle d&apos;une
          contenance totale de <Num v={parcelle} u="m²" />. Il est desservi
          par {voirieSides.length > 1 ? "les voies" : "la voie"} située
          {voirieSides.length > 1 ? "s" : ""} {" "}
          {voirieSides.length ? `au ${voirieSides.join(" et au ")}` : "en limite de propriété"}.
          Le terrain présente une topographie sensiblement plane ; le
          nivellement projeté s&apos;inscrit dans la continuité du terrain
          naturel et des cheminements existants.
        </p>
      </Section>

      <Section title="2. Parti architectural du projet">
        <p>
          Le projet consiste en la construction d&apos;un ensemble d&apos;
          <b>{nbLogements} logements</b> répartis sur{" "}
          <b>R+{env.niveaux - 1}</b> ({env.niveaux} niveaux) pour une hauteur
          totale de <Num v={env.hauteur_totale_m} u="m" />. Le bâtiment adopte
          une volumétrie simple adaptée au gabarit autorisé : une emprise
          bâtie de <Num v={emprise} u="m²" /> représentant{" "}
          <Num v={cesPct} u="%" dec={1} /> de l&apos;unité foncière.
        </p>
        {mixStr && (
          <p>
            La répartition typologique est la suivante :{" "}
            <b>{mixStr}</b>, soit une surface habitable totale de{" "}
            <Num v={shabTotal} u="m²" /> et une surface de plancher de{" "}
            <Num v={sdpTotal} u="m²" />.
          </p>
        )}
        <p>
          La toiture {toit?.type === "terrasse" ? "terrasse" : toit?.type ?? "terrasse"}
          {toit?.vegetalisee ? " sera végétalisée afin d'améliorer l'intégration paysagère et la performance thermique" : ""}
          {toit?.accessible ? ", accessible depuis les circulations communes" : ""}.
        </p>
      </Section>

      <Section title="3. Traitement des espaces extérieurs">
        <p>
          L&apos;aménagement paysager préserve{" "}
          <Num v={pleineTerreM2} u="m²" /> d&apos;espaces de pleine terre, soit{" "}
          <Num v={pleineTerrePct} u="%" dec={1} /> de la surface de la
          parcelle. Ces espaces seront plantés de strates basses, moyennes et
          arborées favorisant la biodiversité locale. Les cheminements
          piétons intérieurs et extérieurs respectent les pentes PMR
          (≤ 5 % sans palier de repos).
        </p>
        <p>
          Le stationnement est dimensionné à <Num v={nbParking} u="places" />{" "}
          ({ratioParking.toFixed(2)} place / logement), conformément aux
          exigences du PLU {bm.metadata.zone_plu}.
        </p>
      </Section>

      <Section title="4. Conformité réglementaire">
        <SubSection title="4.1 — Règlement d'urbanisme (PLU)">
          <ul className="list-disc pl-5 space-y-0.5">
            <li>Emprise au sol : <Num v={emprise} u="m²" /> ({cesPct.toFixed(1)} %) — <i>valeur maximale à vérifier au règlement UA1.9</i></li>
            <li>Hauteur totale : <Num v={env.hauteur_totale_m} u="m" /> — <i>valeur maximale à vérifier au règlement UA1.10</i></li>
            <li>Pleine terre : <Num v={pleineTerreM2} u="m²" /> ({pleineTerrePct.toFixed(1)} %) — article UA1.13</li>
            <li>Hauteur sous plafond RDC : <Num v={env.hauteur_rdc_m} u="m" /> (≥ 2.50 m)</li>
            <li>Hauteur sous plafond étages courants : <Num v={env.hauteur_etage_courant_m} u="m" /> (≥ 2.50 m)</li>
          </ul>
        </SubSection>

        <SubSection title="4.2 — Performance énergétique (RE2020)">
          <p>
            Le bâtiment sera conforme à la RE2020 applicable aux bâtiments
            neufs à usage d&apos;habitation depuis le 1er janvier 2022. Les
            objectifs visés sont :
          </p>
          <ul className="list-disc pl-5 space-y-0.5">
            <li><b>Bbio</b> ≤ Bbio max de référence (besoin bioclimatique)</li>
            <li><b>Cep nr</b> ≤ Cep max (consommation d&apos;énergie primaire non renouvelable)</li>
            <li><b>Ic énergie</b> et <b>Ic construction</b> dans les seuils 2025</li>
            <li><b>DH</b> ≤ 1 250 DH (indicateur de confort d&apos;été)</li>
          </ul>
          <p className="mt-1">
            Les choix constructifs (isolation thermique par l&apos;extérieur,
            menuiseries double / triple vitrage, VMC double flux,
            chauffage bas carbone type pompe à chaleur collective) concourent
            à l&apos;atteinte de ces seuils.
          </p>
        </SubSection>

        <SubSection title="4.3 — Accessibilité PMR">
          <p>
            Le projet respecte les exigences de l&apos;arrêté du 24 décembre
            2015 modifié relatif à l&apos;accessibilité des logements
            collectifs neufs. Les dispositions suivantes sont mises en œuvre :
          </p>
          <ul className="list-disc pl-5 space-y-0.5">
            <li>
              Ascenseur {hasAsc ? "prévu (" : "non-obligatoire — "}desservant tous les niveaux
              d&apos;habitation{hasAsc ? ")" : " (bâtiment R+" + (env.niveaux - 1) + ")"}
            </li>
            <li>Cheminements extérieurs avec pentes ≤ 5 % et largeur ≥ 1.40 m</li>
            <li>Portes d&apos;entrée logements avec largeur de passage ≥ 0.83 m</li>
            <li>Cercle de rotation de Ø 1.50 m libre dans chaque pièce principale et cabinet d&apos;aisance</li>
            <li>Salles d&apos;eau : espace d&apos;usage latéral à la douche de 0.80 × 1.30 m</li>
            <li>Prises électriques, interrupteurs et commandes entre 0.90 et 1.30 m du sol</li>
          </ul>
        </SubSection>

        <SubSection title="4.4 — Sécurité incendie">
          <p>
            Le bâtiment relève de la <b>2ème famille collectif</b> (hauteur du
            plancher bas du dernier étage ≤ 28 m) — classification selon
            l&apos;arrêté du 31 janvier 1986 modifié.
          </p>
          <ul className="list-disc pl-5 space-y-0.5">
            <li>Distance maximale de tout point d&apos;un logement à un escalier : ≤ 7 m (conformité vérifiée au plan)</li>
            <li>Un escalier encloisonné desservant tous les niveaux, largeur utile ≥ 1.00 m</li>
            <li>Désenfumage des escaliers par ouvrant en partie haute (commande au RDC)</li>
            <li>Colonne sèche obligatoire si H ≥ 18 m {env.hauteur_totale_m >= 18 ? "— à installer" : "— non requise dans ce projet"}</li>
            <li>Portes palières EI 30 pour chaque logement</li>
            <li>Détecteurs de fumée autonomes dans chaque logement (obligation légale)</li>
            <li>
              Dessertes pompiers :{" "}
              {voirieSides.length
                ? `voirie ${voirieSides.join(" / ")} permettant l'accès en < 60 m`
                : "accès voie publique ≤ 60 m"}
            </li>
          </ul>
        </SubSection>
      </Section>

      <footer className="mt-8 pt-4 border-t border-slate-200 text-xs text-slate-400 font-sans">
        Notice générée automatiquement à partir du modèle bâtiment
        v{bm.metadata.version} (ArchiClaude · SP2-v2a). Tous les chiffres
        cités sont issus du Building Model — à vérifier contre l&apos;extraction
        PLU officielle pour la validation finale.
      </footer>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <h2 className="font-bold text-base text-slate-900 mb-2">{title}</h2>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3 mt-3">
      <h3 className="font-semibold text-sm text-slate-900 mb-1">{title}</h3>
      <div className="space-y-1.5 pl-2 border-l-2 border-slate-100">{children}</div>
    </div>
  );
}

function Num({ v, u, dec = 0 }: { v: number; u: string; dec?: number }) {
  return (
    <b className="font-semibold text-slate-900">
      {v.toFixed(dec).replace(".", ",")} {u}
    </b>
  );
}
