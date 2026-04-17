"""Site noise aggregation module.

Aggregates noise data from multiple sources (Cerema classifications and
Bruitparif IDF measurements) into a single worst-case site result.

Noise categories follow the French classement sonore des infrastructures de
transports terrestres (arrêté du 30 mai 1996):
  - Category 1: Lden ≥ 81 dB(A)  — most noisy
  - Category 2: Lden ≥ 76 dB(A)
  - Category 3: Lden ≥ 70 dB(A)
  - Category 4: Lden ≥ 65 dB(A)
  - Category 5: Lden < 65 dB(A)  — least noisy

Acoustic insulation obligations apply to buildings in categories 1–3.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.sources.bruitparif import BruitparifResult
from core.sources.cerema_bruit import ClassementSonore


@dataclass(frozen=True)
class BruitSiteResult:
    """Aggregated noise classification for a site."""

    classement_sonore: int | None          # 1–5 (1 = noisiest), None if no data
    source: str | None                     # "cerema", "bruitparif", "cerema+bruitparif"
    lden_dominant: float | None            # Lden in dB(A) from dominant source
    isolation_acoustique_obligatoire: bool  # True when category ≤ 3


def _lden_to_categorie(lden: float) -> int:
    """Convert an Lden value (dB(A)) to a French noise category (1–5).

    Args:
        lden: Day-evening-night noise level in dB(A).

    Returns:
        Integer 1–5 where 1 is the noisiest category.
    """
    if lden >= 81:
        return 1
    if lden >= 76:
        return 2
    if lden >= 70:
        return 3
    if lden >= 65:
        return 4
    return 5


def aggregate_bruit(
    *,
    cerema: list[ClassementSonore],
    bruitparif: BruitparifResult | None,
) -> BruitSiteResult:
    """Aggregate noise data from Cerema and Bruitparif into a site result.

    Takes the worst-case (lowest category number = most noise) from all
    available data sources.

    Args:
        cerema: List of :class:`ClassementSonore` segments near the site.
        bruitparif: Optional :class:`BruitparifResult` from Bruitparif IDF.

    Returns:
        :class:`BruitSiteResult` with the worst-case classification.
        When no data is available, returns classement=None and
        isolation_acoustique_obligatoire=False.
    """
    best_cerema_cat: int | None = None
    if cerema:
        best_cerema_cat = min(s.categorie for s in cerema)

    best_bp_cat: int | None = None
    bp_lden: float | None = None
    if bruitparif is not None:
        best_bp_cat = _lden_to_categorie(bruitparif.lden)
        bp_lden = bruitparif.lden

    # Determine overall worst category (lowest number)
    if best_cerema_cat is None and best_bp_cat is None:
        return BruitSiteResult(
            classement_sonore=None,
            source=None,
            lden_dominant=None,
            isolation_acoustique_obligatoire=False,
        )

    # Pick worst across sources
    if best_cerema_cat is not None and best_bp_cat is not None:
        if best_bp_cat <= best_cerema_cat:
            # Bruitparif is equal or worse
            final_cat = best_bp_cat
            source = "bruitparif" if best_bp_cat < best_cerema_cat else "cerema+bruitparif"
            lden = bp_lden
        else:
            final_cat = best_cerema_cat
            source = "cerema"
            lden = None  # Cerema doesn't always provide lden
            # Try to retrieve lden from the worst cerema segment
            worst_segs = [s for s in cerema if s.categorie == best_cerema_cat]
            if worst_segs and worst_segs[0].lden is not None:
                lden = worst_segs[0].lden
    elif best_cerema_cat is not None:
        final_cat = best_cerema_cat
        source = "cerema"
        worst_segs = [s for s in cerema if s.categorie == best_cerema_cat]
        lden = worst_segs[0].lden if worst_segs else None
    else:
        # bruitparif only
        assert best_bp_cat is not None
        final_cat = best_bp_cat
        source = "bruitparif"
        lden = bp_lden

    return BruitSiteResult(
        classement_sonore=final_cat,
        source=source,
        lden_dominant=lden,
        isolation_acoustique_obligatoire=(final_cat <= 3),
    )
