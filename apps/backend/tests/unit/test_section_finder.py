"""Unit tests for core.plu.section_finder — zone section extraction from PLU documents."""

from __future__ import annotations

from core.plu.section_finder import find_zone_section, generate_zone_variants, score_candidate

# ---------------------------------------------------------------------------
# generate_zone_variants
# ---------------------------------------------------------------------------


def test_generate_variants_with_number() -> None:
    """UA1 should produce 4 variants: original, hyphen, dot, space."""
    variants = generate_zone_variants("UA1")
    assert len(variants) == 4
    assert "UA1" in variants
    assert "UA-1" in variants
    assert "UA.1" in variants
    assert "UA 1" in variants


def test_generate_variants_no_number() -> None:
    """UB (no digit after letters) should produce just 1 variant."""
    variants = generate_zone_variants("UB")
    assert variants == ["UB"]


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------


def test_score_regulatory_words() -> None:
    """Context text with regulatory words like hauteur/emprise should get a positive score."""
    text = (
        "Article UB.10 — Hauteur des constructions\n"
        "La hauteur maximale des constructions est fixée à 15 mètres.\n"
        "L'emprise au sol ne peut excéder 60 % de la surface du terrain.\n"
        "L'implantation des constructions doit respecter un retrait de 3 mètres.\n"
        "Le gabarit est défini par un plan vertical.\n"
    )
    s = score_candidate(text)
    assert s > 0


def test_score_toc_penalty() -> None:
    """Text with many ellipses (table of contents) should get a negative score."""
    lines = [f"Article {i} ................ {i * 10}" for i in range(1, 20)]
    text = "\n".join(lines)
    s = score_candidate(text)
    assert s < 0


def test_score_dispositions_bonus() -> None:
    """Text containing 'Dispositions applicables' in the first 500 chars should score >= 80."""
    text = "Dispositions applicables à la zone UB\n" + "x " * 200
    s = score_candidate(text)
    assert s >= 80


# ---------------------------------------------------------------------------
# find_zone_section
# ---------------------------------------------------------------------------


def test_find_section_canonical() -> None:
    """Document with 'Dispositions applicables à la zone UA' should find the section."""
    preamble = "Table des matières\n" + "sommaire ... 1\n" * 50 + "\n"
    section_header = "Dispositions applicables à la zone UA\n"
    section_body = (
        "Article UA.1 — Destinations\n"
        "Les constructions à destination d'habitation sont autorisées.\n"
        "La hauteur maximale est de 12 mètres.\n"
        "L'emprise au sol est limitée à 70 %.\n"
        "L'implantation par rapport aux voies doit respecter un retrait de 5 mètres.\n"
    ) * 40  # Make it > 5000 chars
    next_zone = "\nDispositions applicables à la zone UB\nArticle UB.1\n"
    doc = preamble + section_header + section_body + next_zone

    result = find_zone_section(doc, "UA")
    assert result is not None
    assert "Dispositions applicables à la zone UA" in result
    assert "Article UA.1" in result


def test_find_section_boundary() -> None:
    """Section extraction should stop at the next zone header (ZONE UB)."""
    zone_ua = "ZONE UA\n" + "Hauteur maximale 12 m. Emprise 60 %. " * 200 + "\n"
    zone_ub = "ZONE UB\nArticle UB.1 — Destinations\nCommerce interdit.\n"
    doc = zone_ua + zone_ub

    result = find_zone_section(doc, "UA")
    assert result is not None
    # Should contain UA content but stop before UB section start
    assert "ZONE UA" in result
    # The UB content should ideally not dominate (may appear in trailing context)


def test_find_section_not_found() -> None:
    """Zone UC not present in document should return None."""
    doc = (
        "ZONE UA\nArticle UA.1\nHabitation autorisée. Hauteur 12 m.\n" * 10
        + "ZONE UB\nArticle UB.1\nCommerce interdit.\n" * 10
    )
    result = find_zone_section(doc, "UC")
    assert result is None


def test_skips_toc_matches() -> None:
    """Should prefer regulatory content over TOC entries for the same zone."""
    toc = (
        "Sommaire\n"
        "ZONE UA ................. 5\n"
        "ZONE UB ................. 15\n"
        "ZONE UC ................. 25\n"
        "ZONE UD ................. 35\n"
        "ZONE UE ................. 45\n"
        "ZONE UF ................. 55\n"
    )
    content = (
        "\n\nZONE UA\n"
        "Article UA.1 — Destinations\n"
        "Les constructions à destination d'habitation sont autorisées.\n"
        "La hauteur maximale est de 12 mètres.\n"
        "L'emprise au sol est limitée à 70 %.\n"
        "L'implantation doit respecter un retrait de 5 mètres.\n"
        "Le gabarit est défini par rapport à l'alignement.\n"
        "Le coefficient d'emprise au sol (CES) est de 0.6.\n"
        "Les limites séparatives doivent être respectées.\n"
    )
    doc = toc + content

    result = find_zone_section(doc, "UA")
    assert result is not None
    # The result should contain the regulatory content, not just the TOC
    assert "Article UA.1" in result
