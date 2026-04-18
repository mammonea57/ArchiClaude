"""Smart PLU margin calculator.

Computes a risk-adjusted SDP margin so the recommended programme stays
comfortably inside the regulatory maximum. The margin is floored at 96%
regardless of risk score, ensuring that even the worst-case project never
falls below a usable surface.
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Margin lookup table ───────────────────────────────────────────────────────
# Format: (max_risk_inclusive, margin_pct)
# Risk 0–20 → 100%, 21–40 → 98%, 41–60 → 97%, 61–80 → 96%, 81+ → 96%
_MARGIN_TABLE: list[tuple[int, float]] = [
    (20, 100.0),
    (40, 98.0),
    (60, 97.0),
    (80, 96.0),
    (101, 96.0),
]

_FLOOR_PCT: float = 96.0


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SmartMarginResult:
    """Immutable result of the smart-margin computation."""

    marge_pct: float
    sdp_recommandee: float
    sdp_max: float
    raison: str
    ajustement_comparables: bool


# ── Core function ─────────────────────────────────────────────────────────────

def compute_smart_margin(
    *,
    risk_score: int,
    sdp_max: float,
    comparables_max_pct_accepted: float | None = None,
) -> SmartMarginResult:
    """Compute risk-adjusted SDP margin.

    Args:
        risk_score: Integer risk score (0–100).
        sdp_max: Maximum SDP allowed by PLU rules, in m².
        comparables_max_pct_accepted: Optional — highest acceptance ratio
            observed in comparable projects in the same zone (percentage,
            e.g. 99.0 for 99%). If >= 97%, triggers an upward boost.

    Returns:
        SmartMarginResult with marge_pct floored at 96%.
    """
    # 1. Base margin from risk table
    base_pct = _lookup_margin(risk_score)

    # 2. Optional comparable boost
    ajustement = False
    if comparables_max_pct_accepted is not None and comparables_max_pct_accepted >= 97.0:
        boosted = min(100.0, round(comparables_max_pct_accepted))
        if boosted > base_pct:
            base_pct = boosted
        ajustement = True

    # 3. Floor — NEVER below 96%
    marge_pct = max(_FLOOR_PCT, base_pct)

    # 4. Recommended SDP
    sdp_recommandee = sdp_max * marge_pct / 100.0

    # 5. Human-readable reason
    raison = _build_raison(risk_score=risk_score, marge_pct=marge_pct, ajustement=ajustement)

    return SmartMarginResult(
        marge_pct=marge_pct,
        sdp_recommandee=sdp_recommandee,
        sdp_max=sdp_max,
        raison=raison,
        ajustement_comparables=ajustement,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lookup_margin(risk_score: int) -> float:
    """Return base margin percentage from the risk table."""
    for max_risk, pct in _MARGIN_TABLE:
        if risk_score <= max_risk:
            return pct
    return _FLOOR_PCT


def _build_raison(*, risk_score: int, marge_pct: float, ajustement: bool) -> str:
    parts: list[str] = []
    if marge_pct == 100.0:
        parts.append("Risque faible — programme à 100% de la capacité réglementaire.")
    elif marge_pct >= 98.0:
        parts.append("Risque modéré — marge de sécurité 2%.")
    elif marge_pct >= 97.0:
        parts.append("Risque moyen — marge de sécurité 3%.")
    else:
        parts.append(f"Risque élevé (score {risk_score}) — plancher à {marge_pct:.0f}%.")
    if ajustement:
        parts.append("Ajustement à la hausse confirmé par les comparables locaux.")
    return " ".join(parts)
