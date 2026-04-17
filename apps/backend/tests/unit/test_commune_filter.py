"""Unit tests for core.plu.commune_filter — PLUi commune-specific paragraph filtering."""

from __future__ import annotations

from core.plu.commune_filter import normalize_commune_name, strip_other_communes

# ---------------------------------------------------------------------------
# normalize_commune_name
# ---------------------------------------------------------------------------


def test_normalize_diacritics() -> None:
    """Diacritics should be stripped: E with accent -> e, a-circumflex -> a, etc."""
    assert normalize_commune_name("Évreux") == "evreux"
    assert normalize_commune_name("Châtillon") == "chatillon"
    assert normalize_commune_name("Créteil") == "creteil"
    assert normalize_commune_name("  Bôle  ") == "bole"


# ---------------------------------------------------------------------------
# strip_other_communes
# ---------------------------------------------------------------------------


def test_keeps_target_commune() -> None:
    """Paragraphs for the target commune should be kept, others removed."""
    text = (
        "Article UB.10 — Hauteur\n"
        "\nPour la commune de Nogent-sur-Marne :\n"
        "La hauteur maximale est de 18 mètres.\n"
        "\nPour la commune de Saint-Mandé :\n"
        "La hauteur maximale est de 12 mètres.\n"
    )
    result = strip_other_communes(text, "Nogent-sur-Marne")
    assert "Nogent-sur-Marne" in result
    assert "Saint-Mandé" not in result


def test_keeps_neutral_paragraphs() -> None:
    """Paragraphs without any commune header should be kept (neutral/general)."""
    text = (
        "Dispositions générales\n"
        "Les constructions doivent respecter le gabarit.\n"
        "\nPour la commune de Vincennes :\n"
        "Hauteur limitée à 15 m.\n"
        "\nArticle UB.11 — Aspect extérieur\n"
        "Les façades doivent être en pierre ou enduit.\n"
    )
    result = strip_other_communes(text, "Nogent-sur-Marne")
    # General/neutral paragraphs kept
    assert "Dispositions générales" in result
    assert "Aspect extérieur" in result
    # Vincennes-specific paragraph removed
    assert "Vincennes" not in result


def test_no_commune_markers() -> None:
    """Text without any commune-specific markers should be returned unchanged."""
    text = (
        "Article UA.1 — Destinations\n"
        "Les constructions à destination d'habitation sont autorisées.\n"
        "La hauteur maximale est de 12 mètres.\n"
    )
    result = strip_other_communes(text, "Nogent-sur-Marne")
    assert result == text


def test_prefix_matching() -> None:
    """Saint-Mande vs Saint-Maur should be distinguished correctly (no false match)."""
    text = (
        "\nPour la commune de Saint-Mandé :\n"
        "Hauteur 12 m.\n"
        "\nPour la commune de Saint-Maur-des-Fossés :\n"
        "Hauteur 15 m.\n"
    )
    result = strip_other_communes(text, "Saint-Mandé")
    assert "Saint-Mandé" in result
    assert "Saint-Maur" not in result
