"""Unit tests for core.pcmi.schemas."""

from __future__ import annotations

from core.pcmi.schemas import (
    PCMI_FORMATS,
    PCMI_ORDER,
    PCMI_TITRES,
    CartouchePC,
    PcmiDossier,
    PcmiPiece,
)


def test_cartouche_minimal() -> None:
    c = CartouchePC(
        nom_projet="Résidence Les Lilas",
        adresse="12 rue de la Paix, 75001 Paris",
        parcelles_refs=["75056AB0012"],
        petitionnaire_nom="SCI Dupont",
        petitionnaire_contact="dupont@example.com",
    )
    assert c.indice == "A"
    assert c.architecte_nom is None
    assert c.architecte_ordre is None
    assert c.architecte_contact is None
    assert c.logo_agence_url is None
    assert c.piece_num == ""
    assert c.piece_titre == ""
    assert c.echelle == ""
    assert c.date == ""


def test_pcmi_order_has_8_pieces() -> None:
    assert len(PCMI_ORDER) == 8
    # No PCMI6 in the list
    assert "PCMI6" not in PCMI_ORDER
    assert "PCMI1" in PCMI_ORDER
    assert "PCMI8" in PCMI_ORDER


def test_pcmi_formats_complete() -> None:
    # Every piece in PCMI_ORDER must have a format entry
    for code in PCMI_ORDER:
        assert code in PCMI_FORMATS, f"Missing format for {code}"
    fmt_a4_portrait = PCMI_FORMATS["PCMI1"]
    assert fmt_a4_portrait == ("A4", "portrait")
    fmt_a3_landscape = PCMI_FORMATS["PCMI2a"]
    assert fmt_a3_landscape == ("A3", "landscape")


def test_pcmi_titres_complete() -> None:
    # Every piece in PCMI_ORDER must have a titre entry
    for code in PCMI_ORDER:
        assert code in PCMI_TITRES, f"Missing titre for {code}"
    assert PCMI_TITRES["PCMI1"] == "Plan de situation"
    assert PCMI_TITRES["PCMI4"] == "Notice architecturale"


def test_pcmi_piece_defaults() -> None:
    p = PcmiPiece(code="PCMI1", titre="Plan de situation")
    assert p.svg_content is None
    assert p.pdf_bytes is None
    assert p.html_content is None
    assert p.error is None


def test_pcmi_dossier_defaults() -> None:
    d = PcmiDossier(
        project_id="proj-001",
        indice_revision="A",
        pieces=[],
    )
    assert d.status == "queued"
    assert d.map_base == "scan25"
    assert d.pdf_unique_bytes is None
    assert d.zip_bytes is None
    assert d.cartouche is None
    assert d.error_msg is None
    assert d.generated_at is not None
