"""Refusal pattern analyser and PC deduplication for local context."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LINK_WINDOW_DAYS = 18 * 30  # 18 months expressed in days (≈540 days)


# ---------------------------------------------------------------------------
# GabaritInfo
# ---------------------------------------------------------------------------


class GabaritInfo:
    """Dominant building height profile derived from neighbouring buildings."""

    def __init__(self, median_niveaux: int, median_m: float) -> None:
        self.median_niveaux = median_niveaux
        self.median_m = median_m

    @classmethod
    def from_batiments(cls, batiments: list[dict]) -> GabaritInfo:
        """Compute median storey count and height from a list of building dicts.

        Each dict should contain at least one of:
          - ``niveaux`` (int): storey count
          - ``hauteur_m`` (float): total height in metres

        Buildings missing both fields are skipped.
        """
        niveaux_list: list[int] = []
        hauteur_list: list[float] = []

        for b in batiments:
            if "niveaux" in b and b["niveaux"] is not None:
                niveaux_list.append(int(b["niveaux"]))
            if "hauteur_m" in b and b["hauteur_m"] is not None:
                hauteur_list.append(float(b["hauteur_m"]))

        median_niveaux = int(statistics.median(niveaux_list)) if niveaux_list else 0
        median_m = statistics.median(hauteur_list) if hauteur_list else 0.0

        return cls(median_niveaux=median_niveaux, median_m=median_m)

    def projet_depasse(self, projet_niveaux: int) -> bool:
        """Return True if the project exceeds the dominant neighbourhood height.

        Returns False when no buildings were available to derive the gabarit.
        """
        if self.median_niveaux == 0:
            return False
        return projet_niveaux > self.median_niveaux

    def depassement_niveaux(self, projet_niveaux: int) -> int:
        """Return how many storeys the project exceeds the dominant height (min 0)."""
        return max(0, projet_niveaux - self.median_niveaux)


# ---------------------------------------------------------------------------
# PC deduplication
# ---------------------------------------------------------------------------


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def deduplicate_pc(pcs: list[dict]) -> list[dict]:
    """Identify refusals that were subsequently accepted on the same project.

    Two PCs are considered the same project when:
      - They share the same ``parcelle_ref``, OR
      - They share the same address (case-insensitive strip)

    AND the acceptance date is within 18 months of the refusal date.

    Matching refusals have ``subsequently_accepted=True`` added to their dict.
    Accepted PCs in such a pair are marked ``linked_refusal=True``.

    The original list is not mutated; a new list of dicts is returned.
    """
    result: list[dict] = [dict(pc) for pc in pcs]

    refusals = [pc for pc in result if pc.get("decision") == "refuse"]
    acceptances = [pc for pc in result if pc.get("decision") == "accepte"]

    for ref in refusals:
        ref_date = _parse_date(ref.get("date_decision"))
        ref_parcelle = ref.get("parcelle_ref", "").strip()
        ref_address = (ref.get("adresse") or "").strip().lower()

        for acc in acceptances:
            acc_date = _parse_date(acc.get("date_decision"))
            acc_parcelle = acc.get("parcelle_ref", "").strip()
            acc_address = (acc.get("adresse") or "").strip().lower()

            # Same project test
            same_parcelle = ref_parcelle and acc_parcelle and ref_parcelle == acc_parcelle
            same_address = ref_address and acc_address and ref_address == acc_address

            if not (same_parcelle or same_address):
                continue

            # Time window test: acceptance must be after refusal and within 18 months
            if ref_date and acc_date:
                delta = acc_date - ref_date
                if timedelta(0) <= delta <= timedelta(days=_LINK_WINDOW_DAYS):
                    ref["subsequently_accepted"] = True
                    acc["linked_refusal"] = True
                    break
            elif same_parcelle or same_address:
                # No date info → assume linked when identifiers match
                ref["subsequently_accepted"] = True
                acc["linked_refusal"] = True
                break

    return result


# ---------------------------------------------------------------------------
# Local context analysis
# ---------------------------------------------------------------------------


def analyze_local_context(
    *,
    batiments_200m: list[dict],
    pc_500m: list[dict],
    projet_niveaux: int,
) -> dict[str, Any]:
    """Aggregate local context: gabarit dominance and refusal patterns.

    Parameters
    ----------
    batiments_200m:
        Building footprints within 200 m, each with ``niveaux`` and/or
        ``hauteur_m`` fields.
    pc_500m:
        PC decisions within 500 m, each with at minimum ``decision``
        (``"accepte"`` | ``"refuse"``), optionally ``motif``, ``date_decision``,
        ``adresse``, ``parcelle_ref``.
    projet_niveaux:
        Storey count of the planned project (including ground floor).

    Returns
    -------
    dict
        Keys matching :class:`~core.feasibility.schemas.LocalContext`.
    """
    gabarit = GabaritInfo.from_batiments(batiments_200m)
    depasse = gabarit.projet_depasse(projet_niveaux)
    dep_niveaux = gabarit.depassement_niveaux(projet_niveaux)

    deduped = deduplicate_pc(pc_500m)

    accepted = [pc for pc in deduped if pc.get("decision") == "accepte"]
    refused = [
        pc for pc in deduped
        if pc.get("decision") == "refuse" and not pc.get("subsequently_accepted")
    ]

    # Build motif frequency map for active (non-subsequently-accepted) refusals
    motif_counts: dict[str, int] = {}
    motif_last_date: dict[str, str] = {}
    for pc in refused:
        motif = pc.get("motif") or "non_precise"
        motif_counts[motif] = motif_counts.get(motif, 0) + 1
        date_val = pc.get("date_decision") or ""
        existing = motif_last_date.get(motif, "")
        if date_val > existing:
            motif_last_date[motif] = date_val

    patterns = [
        {
            "motif": motif,
            "occurrences_500m": count,
            "dernier_cas": motif_last_date.get(motif),
            "projet_concerne": False,
            "recommandation": "",
        }
        for motif, count in sorted(motif_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "gabarit_dominant_niveaux": gabarit.median_niveaux or None,
        "gabarit_dominant_m": gabarit.median_m or None,
        "projet_depasse_gabarit": depasse,
        "depassement_niveaux": dep_niveaux,
        "pc_acceptes_500m": accepted,
        "pc_refuses_500m": refused,
        "patterns": patterns,
    }
