"""Architect analysis prompt construction — system prompt + user prompt builder."""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
Tu es un architecte DPLG expérimenté en Île-de-France, spécialisé dans les projets \
de construction neuve et de réhabilitation soumis au Code de l'urbanisme français. \
Tu maîtrises parfaitement les PLU des communes d'IDF, les gabarits-enveloppes, les règles \
de prospect, d'alignement, de mitoyenneté, d'emprise au sol et de pleine terre. \
Tu connais les contraintes ABF (Architecte des Bâtiments de France), les PPRI, les servitudes, \
les règles d'incendie pour les ERP, les obligations LLS/SRU, les exigences PMR, et la RE2020.

Tu utilises systématiquement le lexique métier suivant dans tes analyses :
faîtage, acrotère, gabarit-enveloppe, vue droite, vue oblique, prospect, alignement, \
mitoyenneté, emprise au sol, pleine terre, coefficient de biotope, \
SHON, SDP, COS, CES, hauteur totale, hauteur à l'égout, \
recul, bande de constructibilité, servitude de cours communes.

Ta réponse doit IMPÉRATIVEMENT respecter la structure suivante en markdown :

## 1. Synthèse
(5-8 lignes) Verdict global sur la faisabilité du projet, avec le chiffre clé \
(SDP maximale, nombre de logements) et une appréciation qualitative du site.

## 2. Opportunités
Liste bullet des opportunités : marché DVF, exposition solaire, desserte TC, \
comparables réalisés, bonus de constructibilité applicables (logements sociaux, bioclim, etc.).

## 3. Contraintes
Liste bullet des contraintes : gabarit PLU, servitudes, voisinage immédiat, \
bruit (lden), obligations LLS, règles incendie si ERP.

## 4. Alertes
Liste des alertes classées par gravité (CRITIQUE / MAJEURE / MINEURE) : \
ABF périmètre, PPRI zone inondable, recours tiers-partie probable, sol potentiellement pollué.

## 5. Recommandations
3 à 5 actions concrètes et chiffrées pour optimiser le projet (ex. : augmenter la pleine \
terre pour bénéficier du bonus bioclim, adapter le faîtage au gabarit voisin, etc.).

Longueur attendue : 600 à 1200 mots.
Réponds en français. Sois précis, factuel et opérationnel — des décisions à 5-50 M€ \
s'appuient sur ton analyse.

EN PLUS de la note d'opportunité, tu dois fournir dans ta réponse :

## Score de risque recours
Un score de 0 à 100 évaluant la probabilité de recours sur ce projet.
Justifie en 2-3 lignes. Format: "SCORE_RISQUE_OPUS: XX" suivi de la justification.

## Recommandations pré-instruction contextuelles
3-5 démarches prioritaires contextuelles avant dépôt, au-delà de la checklist standard.

## Commentaire vues
Si des données de conflits de vue sont fournies, commente les risques et recommande des ajustements.

## Commentaire ombres
Si des données d'ombre portée sont fournies, commente l'impact et l'argument juridique.

---

IMPORTANT — FORMAT DE SORTIE EN DEUX PARTIES :

Tu dois produire DEUX sections séparées par le marqueur exact `---NOTICE_PCMI4_SEPARATOR---`.

PARTIE 1 : Note d'opportunité (promoteur interne)
Structure imposée : Synthèse / Opportunités / Contraintes / Alertes / Recommandations
Ton : décisionnaire, lexique promoteur

---NOTICE_PCMI4_SEPARATOR---

PARTIE 2 : Notice architecturale PCMI4 (dossier PC officiel, article R.431-8)
Structure imposée EXACTEMENT dans cet ordre :
## 1. Terrain et ses abords
## 2. Projet dans son contexte
## 3. Composition du projet
## 4. Accès et stationnement
## 5. Espaces libres et plantations

Ton : formel, administratif, factuel. Pas d'opportunités ni d'alertes dans cette partie.
Longueur 500-900 mots au total pour la notice PCMI4.
"""

# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


def build_architect_prompt(
    *,
    feasibility_summary: dict[str, Any],
    zone_code: str,
    commune_name: str,
    site_context: dict[str, Any] | None = None,
    compliance_summary: dict[str, Any] | None = None,
    comparables: list[dict[str, Any]] | None = None,
    alerts: list[str] | None = None,
    jurisprudences_context: str | None = None,
    recours_context: str | None = None,
    vue_analysis_context: dict | None = None,
    shadow_context: dict | None = None,
    risk_score_calcule: int | None = None,
    local_context: dict | None = None,
) -> str:
    """Assemble the user prompt for the architect analysis.

    Args:
        feasibility_summary: Dict with keys like sdp_max_m2, nb_logements_max,
            emprise_sol_m2, hauteur_max_m, etc.
        zone_code: PLU zone code (e.g. "UB", "UA", "UC").
        commune_name: Human-readable commune name (e.g. "Vincennes").
        site_context: Optional dict from site analysis (orientation, bruit_lden, etc.).
        compliance_summary: Optional compliance check results.
        comparables: Optional list of comparable building permit dicts.
        alerts: Optional list of alert strings (ABF, PPRI, etc.).
        jurisprudences_context: Optional pre-formatted jurisprudence text.
            Will be tagged with [jurisprudence].
        recours_context: Optional pre-formatted recours text.
            Will be tagged with [recours_local].
        vue_analysis_context: Optional vue droite/oblique conflict analysis dict.
        shadow_context: Optional shadow simulation results dict.
        risk_score_calcule: Optional calculated risk score (0-100).
        local_context: Optional local context dict (gabarit, PC historiques).

    Returns:
        Assembled user prompt string ready to send to the LLM.
    """
    parts: list[str] = []

    # --- Core project info ---
    parts.append("# Projet à analyser\n")
    parts.append(f"**Commune :** {commune_name}")
    parts.append(f"**Zone PLU :** {zone_code}\n")

    # --- Faisabilité ---
    parts.append("## Résultats de faisabilité\n")
    parts.append("```json")
    parts.append(json.dumps(feasibility_summary, ensure_ascii=False, indent=2))
    parts.append("```\n")

    # --- Site context ---
    if site_context:
        parts.append("## Contexte site\n")
        parts.append("```json")
        parts.append(json.dumps(site_context, ensure_ascii=False, indent=2))
        parts.append("```\n")

    # --- Compliance ---
    if compliance_summary:
        parts.append("## Vérifications réglementaires\n")
        parts.append("```json")
        parts.append(json.dumps(compliance_summary, ensure_ascii=False, indent=2))
        parts.append("```\n")

    # --- Comparables ---
    if comparables:
        parts.append("## Projets comparables réalisés dans la commune\n")
        for i, comp in enumerate(comparables, 1):
            parts.append(f"**Comparable {i} :** {json.dumps(comp, ensure_ascii=False)}")
        parts.append("")

    # --- Alerts ---
    if alerts:
        parts.append("## Alertes identifiées\n")
        for alert in alerts:
            parts.append(f"- {alert}")
        parts.append("")

    # --- RAG context: jurisprudences ---
    if jurisprudences_context:
        parts.append("## Jurisprudences pertinentes\n")
        parts.append("[jurisprudence]")
        parts.append(jurisprudences_context)
        parts.append("[/jurisprudence]\n")

    # --- RAG context: recours ---
    if recours_context:
        parts.append("## Recours locaux recensés\n")
        parts.append("[recours_local]")
        parts.append(recours_context)
        parts.append("[/recours_local]\n")

    # --- Risk score calculé ---
    if risk_score_calcule is not None:
        parts.append(f"### Score de risque calculé: {risk_score_calcule}/100\n")

    # --- Local context (gabarit, PC historiques) ---
    if local_context:
        parts.append("### Contexte local (gabarit, PC historiques)\n")
        parts.append("```json")
        parts.append(json.dumps(local_context, ensure_ascii=False, indent=2))
        parts.append("```\n")

    # --- Vue analysis ---
    if vue_analysis_context:
        parts.append("### Analyse vues droite/oblique\n")
        parts.append("```json")
        parts.append(json.dumps(vue_analysis_context, ensure_ascii=False, indent=2))
        parts.append("```\n")

    # --- Shadow analysis ---
    if shadow_context:
        parts.append("### Analyse ombre portée\n")
        parts.append("```json")
        parts.append(json.dumps(shadow_context, ensure_ascii=False, indent=2))
        parts.append("```\n")

    # --- Final instruction with required section names ---
    parts.append(
        "Sur la base de toutes ces données, rédige l'analyse architecturale complète "
        "en respectant impérativement la structure en 5 sections :\n"
        "**Synthèse**, **Opportunités**, **Contraintes**, **Alertes**, **Recommandations**."
    )

    return "\n".join(parts)
