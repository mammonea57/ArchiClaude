"""Unit tests for core/pcmi/assembler.py."""

from __future__ import annotations

import zipfile
from io import BytesIO

from pypdf import PdfReader
from reportlab.pdfgen import canvas as rl_canvas

from core.pcmi.assembler import _build_readme, _safe_filename, assemble_dossier
from core.pcmi.schemas import PCMI_ORDER, CartouchePC

# ── Helpers ────────────────────────────────────────────────────────────────────


def _minimal_pdf_bytes(page_text: str = "test") -> bytes:
    """Generate a valid 1-page PDF via reportlab canvas."""
    buf = BytesIO()
    c = rl_canvas.Canvas(buf)
    c.drawString(100, 700, page_text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _sample_cartouche() -> CartouchePC:
    return CartouchePC(
        nom_projet="Résidence Les Lilas",
        adresse="12 avenue Gambetta, 93100 Montreuil",
        parcelles_refs=["AV0042", "AV0043"],
        petitionnaire_nom="SCI Gambetta Invest",
        petitionnaire_contact="contact@gambettainvest.fr",
        architecte_nom="Cabinet Archi & Co",
        architecte_ordre="CROA Île-de-France n° 12345",
        architecte_contact="archi@archi-co.fr",
        piece_num="",
        piece_titre="",
        echelle="",
        date="Avril 2026",
        indice="A",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSafeFilename:
    def test_spaces_become_hyphens(self) -> None:
        assert _safe_filename("Plan de situation") == "plan-de-situation"

    def test_accents_stripped(self) -> None:
        result = _safe_filename("Façades et élévations")
        assert "ç" not in result
        assert "é" not in result
        assert result  # non-empty

    def test_alphanumeric_preserved(self) -> None:
        assert _safe_filename("PCMI2a") == "pcmi2a"

    def test_special_chars_removed(self) -> None:
        result = _safe_filename("foo/bar:baz")
        assert "/" not in result
        assert ":" not in result


class TestAssembleDossier:
    def test_assemble_dossier_returns_pdf_and_zip(self) -> None:
        """3 minimal PDFs → unified valid PDF + ZIP with 3 PDFs + README."""
        codes = PCMI_ORDER[:3]  # PCMI1, PCMI2a, PCMI2b
        pdfs = {code: _minimal_pdf_bytes(code) for code in codes}
        cartouche = _sample_cartouche()

        unified_pdf, zip_bytes = assemble_dossier(
            pdfs_par_piece=pdfs,
            nom_projet="Test Projet",
            cartouche=cartouche,
        )

        # Unified PDF is valid
        assert isinstance(unified_pdf, bytes)
        assert unified_pdf[:4] == b"%PDF"
        reader = PdfReader(BytesIO(unified_pdf))
        assert len(reader.pages) == 3

        # ZIP is valid and contains 3 PDFs + README.txt
        assert isinstance(zip_bytes, bytes)
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        pdf_names = [n for n in names if n.endswith(".pdf")]
        assert len(pdf_names) == 3
        assert "README.txt" in names

    def test_unified_pdf_page_count_matches_input(self) -> None:
        """Each input PDF contributes its pages to the unified output."""
        pdfs = {code: _minimal_pdf_bytes(code) for code in PCMI_ORDER}
        unified_pdf, _ = assemble_dossier(
            pdfs_par_piece=pdfs,
            nom_projet="Full Dossier",
            cartouche=_sample_cartouche(),
        )
        reader = PdfReader(BytesIO(unified_pdf))
        assert len(reader.pages) == len(PCMI_ORDER)

    def test_pieces_ordered_by_pcmi_order(self) -> None:
        """ZIP filenames appear in the same order as PCMI_ORDER."""
        codes = ["PCMI3", "PCMI1", "PCMI5"]  # intentionally out of order
        pdfs = {code: _minimal_pdf_bytes(code) for code in codes}
        _, zip_bytes = assemble_dossier(
            pdfs_par_piece=pdfs,
            nom_projet="Ordre Test",
            cartouche=_sample_cartouche(),
        )
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            pdf_names = [n for n in zf.namelist() if n.endswith(".pdf")]
        # Should be ordered PCMI1, PCMI3, PCMI5
        assert pdf_names[0].startswith("PCMI1")
        assert pdf_names[1].startswith("PCMI3")
        assert pdf_names[2].startswith("PCMI5")

    def test_unknown_codes_ignored(self) -> None:
        """Extra keys not in PCMI_ORDER are silently ignored."""
        pdfs = {
            "PCMI1": _minimal_pdf_bytes("PCMI1"),
            "PCMI99": _minimal_pdf_bytes("unknown"),
        }
        unified_pdf, zip_bytes = assemble_dossier(
            pdfs_par_piece=pdfs,
            nom_projet="Extra Keys",
            cartouche=_sample_cartouche(),
        )
        reader = PdfReader(BytesIO(unified_pdf))
        assert len(reader.pages) == 1

        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            pdf_names = [n for n in zf.namelist() if n.endswith(".pdf")]
        assert len(pdf_names) == 1

    def test_zip_contains_readme_with_pieces_list(self) -> None:
        """README.txt is present and mentions all included piece codes."""
        codes = PCMI_ORDER[:4]
        pdfs = {code: _minimal_pdf_bytes(code) for code in codes}
        _, zip_bytes = assemble_dossier(
            pdfs_par_piece=pdfs,
            nom_projet="README Test",
            cartouche=_sample_cartouche(),
        )
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            readme = zf.read("README.txt").decode("utf-8")

        for code in codes:
            assert code in readme, f"README missing piece code {code}"

    def test_zip_readme_contains_project_info(self) -> None:
        """README.txt includes project name, address and parcelles."""
        pdfs = {"PCMI1": _minimal_pdf_bytes("PCMI1")}
        cartouche = _sample_cartouche()
        _, zip_bytes = assemble_dossier(
            pdfs_par_piece=pdfs,
            nom_projet="Projet Gambetta",
            cartouche=cartouche,
        )
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            readme = zf.read("README.txt").decode("utf-8")

        assert "Projet Gambetta" in readme
        assert cartouche.adresse in readme
        assert "AV0042" in readme


class TestBuildReadme:
    def test_readme_contains_all_pieces(self) -> None:
        pieces = ["PCMI1", "PCMI2a", "PCMI4"]
        readme = _build_readme(
            nom_projet="Test",
            cartouche=_sample_cartouche(),
            pieces=pieces,
        )
        for code in pieces:
            assert code in readme

    def test_readme_is_string(self) -> None:
        readme = _build_readme(
            nom_projet="Test",
            cartouche=_sample_cartouche(),
            pieces=["PCMI1"],
        )
        assert isinstance(readme, str)
        assert len(readme) > 50
