"""Pre-instruction checklist generator.

Deterministic function that produces a sorted list of PreInstructionItem
objects based on the project's risk score, alerts, acoustic classification,
and number of levels.
"""

from __future__ import annotations

from core.feasibility.schemas import PreInstructionItem


def generate_checklist(
    *,
    alerts: list[dict],
    risk_score: int,
    classement_sonore: int | None = None,
    nb_niveaux: int = 0,
) -> list[PreInstructionItem]:
    """Generate a deterministic pre-instruction checklist.

    Args:
        alerts: List of alert dicts with at least a ``type`` key.
        risk_score: Integer risk score (0–100).
        classement_sonore: Road/railway acoustic classification (1–5).
            Values <= 2 trigger an acoustic study.
        nb_niveaux: Number of levels including ground floor.
            Values >= 4 trigger a RE2020 thermal study.

    Returns:
        Sorted list of PreInstructionItem, descending by timing_jours
        (J-90 first, J-15 last).
    """
    alert_types = {a.get("type", "") for a in alerts}
    items: list[PreInstructionItem] = []

    # ── Always present ────────────────────────────────────────────────────────

    items.append(
        PreInstructionItem(
            demarche="Levé géomètre-expert (topographie + bornage)",
            timing_jours=90,
            priorite="obligatoire",
            raison="Nécessaire avant tout dépôt de PC pour définir l'emprise exacte.",
            contact_type="geometre_expert",
        )
    )

    items.append(
        PreInstructionItem(
            demarche="Consultation notariale — servitudes notariales et droits réels",
            timing_jours=60,
            priorite="obligatoire",
            raison="Vérification des servitudes privées non visibles au cadastre.",
            contact_type="notaire",
        )
    )

    # ── RDV pré-instruction en mairie (always present, priority varies) ───────

    rdv_priorite = "fortement_recommande" if risk_score > 40 else "recommande"
    items.append(
        PreInstructionItem(
            demarche="RDV pré-instruction en mairie / service urbanisme",
            timing_jours=60,
            priorite=rdv_priorite,
            raison=(
                "Risque élevé détecté — validation informelle recommandée avant dépôt."
                if risk_score > 40
                else "Bonne pratique pour anticiper les demandes de pièces complémentaires."
            ),
            contact_type="mairie",
        )
    )

    # ── Conditional: ABF ──────────────────────────────────────────────────────

    if "abf" in alert_types:
        items.append(
            PreInstructionItem(
                demarche="Consultation ABF (Architecte des Bâtiments de France)",
                timing_jours=45,
                priorite="obligatoire",
                raison="Périmètre monument historique détecté — avis conforme obligatoire.",
                contact_type="abf",
            )
        )

    # ── Conditional: étude sol G2 ─────────────────────────────────────────────

    if alert_types & {"argiles", "sol_pollue"}:
        raison = (
            "Présence d'argile (retrait-gonflement) — dimensionnement fondations requis."
            if "argiles" in alert_types
            else "Site potentiellement pollué (BASIAS/BASOL) — diagnostic obligatoire."
        )
        items.append(
            PreInstructionItem(
                demarche="Étude sol G2 (géotechnique avant-projet)",
                timing_jours=75,
                priorite="obligatoire",
                raison=raison,
                contact_type="bureau_etudes_geotechnique",
            )
        )

    # ── Conditional: étude acoustique ────────────────────────────────────────

    if classement_sonore is not None and classement_sonore <= 2:
        items.append(
            PreInstructionItem(
                demarche="Étude acoustique (isolation de façade)",
                timing_jours=45,
                priorite="obligatoire",
                raison=f"Classement sonore {classement_sonore} — exigences réglementaires renforcées.",
                contact_type="bureau_etudes_acoustique",
            )
        )

    # ── Conditional: étude thermique RE2020 ──────────────────────────────────

    if nb_niveaux >= 4:
        items.append(
            PreInstructionItem(
                demarche="Étude thermique RE2020 (modélisation énergétique)",
                timing_jours=30,
                priorite="obligatoire",
                raison=f"Bâtiment R+{nb_niveaux - 1} — modélisation RE2020 obligatoire avant DCE.",
                contact_type="bureau_etudes_thermique",
            )
        )

    # ── Conditional: notification anticipée des voisins ──────────────────────

    if risk_score > 60:
        items.append(
            PreInstructionItem(
                demarche="Notification anticipée des voisins (concertation préalable)",
                timing_jours=15,
                priorite="recommande",
                raison="Risque de recours élevé — concertation préventive recommandée.",
                contact_type=None,
            )
        )

    # ── Sort descending by timing_jours (J-90 first) ─────────────────────────

    items.sort(key=lambda i: i.timing_jours, reverse=True)
    return items
