"""Unit tests for core.analysis.refusal_patterns."""


from core.analysis.refusal_patterns import (
    GabaritInfo,
    analyze_local_context,
    deduplicate_pc,
)

# ---------------------------------------------------------------------------
# deduplicate_pc tests
# ---------------------------------------------------------------------------


def test_links_refused_then_accepted():
    """Same address with acceptance within 18 months → refusal marked subsequently_accepted."""
    pcs = [
        {
            "decision": "refuse",
            "adresse": "12 Rue de la Paix, Paris",
            "date_decision": "2022-01-15",
            "motif": "hauteur_excessive",
        },
        {
            "decision": "accepte",
            "adresse": "12 Rue de la Paix, Paris",
            "date_decision": "2022-09-01",
        },
    ]
    result = deduplicate_pc(pcs)
    refusal = next(r for r in result if r["decision"] == "refuse")
    assert refusal.get("subsequently_accepted") is True


def test_unrelated_refusal_kept():
    """Different address → refusal NOT marked as subsequently_accepted."""
    pcs = [
        {
            "decision": "refuse",
            "adresse": "12 Rue de la Paix, Paris",
            "date_decision": "2022-01-15",
        },
        {
            "decision": "accepte",
            "adresse": "99 Avenue Victor Hugo, Paris",
            "date_decision": "2022-06-01",
        },
    ]
    result = deduplicate_pc(pcs)
    refusal = next(r for r in result if r["decision"] == "refuse")
    assert "subsequently_accepted" not in refusal


def test_old_not_linked():
    """Same address but acceptance >18 months after refusal → NOT linked."""
    pcs = [
        {
            "decision": "refuse",
            "adresse": "12 Rue de la Paix, Paris",
            "date_decision": "2020-01-01",
        },
        {
            "decision": "accepte",
            "adresse": "12 Rue de la Paix, Paris",
            "date_decision": "2021-10-01",  # ~21 months later → outside window
        },
    ]
    result = deduplicate_pc(pcs)
    refusal = next(r for r in result if r["decision"] == "refuse")
    assert "subsequently_accepted" not in refusal


def test_links_by_parcelle_ref():
    """Matching parcelle_ref takes priority over address for deduplication."""
    pcs = [
        {
            "decision": "refuse",
            "parcelle_ref": "75056000AB0042",
            "adresse": "adresse A",
            "date_decision": "2023-03-01",
        },
        {
            "decision": "accepte",
            "parcelle_ref": "75056000AB0042",
            "adresse": "adresse B",  # different address
            "date_decision": "2023-08-01",
        },
    ]
    result = deduplicate_pc(pcs)
    refusal = next(r for r in result if r["decision"] == "refuse")
    assert refusal.get("subsequently_accepted") is True


def test_original_list_not_mutated():
    """deduplicate_pc must not mutate the input dicts."""
    original = [
        {
            "decision": "refuse",
            "adresse": "12 Rue de la Paix, Paris",
            "date_decision": "2022-01-15",
        },
        {
            "decision": "accepte",
            "adresse": "12 Rue de la Paix, Paris",
            "date_decision": "2022-06-01",
        },
    ]
    import copy
    original_copy = copy.deepcopy(original)
    deduplicate_pc(original)
    assert original == original_copy


# ---------------------------------------------------------------------------
# GabaritInfo tests
# ---------------------------------------------------------------------------


def test_gabarit_dominant():
    """Median of niveaux values is computed correctly."""
    batiments = [
        {"niveaux": 3, "hauteur_m": 9.0},
        {"niveaux": 4, "hauteur_m": 12.0},
        {"niveaux": 5, "hauteur_m": 15.0},
        {"niveaux": 3, "hauteur_m": 9.0},
        {"niveaux": 4, "hauteur_m": 12.0},
    ]
    g = GabaritInfo.from_batiments(batiments)
    # Sorted niveaux: [3, 3, 4, 4, 5] → median = 4
    assert g.median_niveaux == 4
    # Sorted hauteurs: [9, 9, 12, 12, 15] → median = 12
    assert g.median_m == 12.0


def test_projet_depasse():
    """Project with 5 storeys vs median 3 → exceeds, +2 niveaux."""
    batiments = [{"niveaux": 3}, {"niveaux": 3}, {"niveaux": 3}]
    g = GabaritInfo.from_batiments(batiments)
    assert g.projet_depasse(5) is True
    assert g.depassement_niveaux(5) == 2


def test_projet_coherent():
    """Project with same storey count as median → does NOT exceed."""
    batiments = [{"niveaux": 5}, {"niveaux": 5}, {"niveaux": 5}]
    g = GabaritInfo.from_batiments(batiments)
    assert g.projet_depasse(5) is False
    assert g.depassement_niveaux(5) == 0


def test_gabarit_no_batiments():
    """Empty list → 0 for both metrics, projet never exceeds."""
    g = GabaritInfo.from_batiments([])
    assert g.median_niveaux == 0
    assert g.median_m == 0.0
    assert g.projet_depasse(4) is False


# ---------------------------------------------------------------------------
# analyze_local_context integration test
# ---------------------------------------------------------------------------


def test_analyze_local_context_basic():
    """Smoke test for the full context analysis."""
    batiments = [{"niveaux": 3, "hauteur_m": 9.0}] * 5
    pcs = [
        {
            "decision": "refuse",
            "adresse": "10 Rue Test",
            "date_decision": "2022-01-01",
            "motif": "hauteur_excessive",
        },
        {
            "decision": "accepte",
            "adresse": "20 Rue Test",
            "date_decision": "2022-06-01",
        },
    ]
    ctx = analyze_local_context(batiments_200m=batiments, pc_500m=pcs, projet_niveaux=5)

    assert ctx["gabarit_dominant_niveaux"] == 3
    assert ctx["projet_depasse_gabarit"] is True
    assert ctx["depassement_niveaux"] == 2
    assert len(ctx["pc_acceptes_500m"]) == 1
    assert len(ctx["pc_refuses_500m"]) == 1
    assert any(p["motif"] == "hauteur_excessive" for p in ctx["patterns"])
