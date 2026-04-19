"""Unit tests for core.pcmi.notice_pcmi4 — PCMI4 notice architecturale.

TDD: tests written before implementation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.pcmi.notice_pcmi4 import SEPARATOR, extract_notice_from_opus
from core.pcmi.schemas import CartouchePC


def _make_cartouche() -> CartouchePC:
    return CartouchePC(
        nom_projet="Résidence Test",
        adresse="12 rue de la Paix, 75001 Paris",
        parcelles_refs=["75056AB0012"],
        petitionnaire_nom="SCI Test",
        petitionnaire_contact="test@example.com",
    )


# ---------------------------------------------------------------------------
# extract_notice_from_opus
# ---------------------------------------------------------------------------


class TestExtractNoticeFromOpus:
    def test_extracts_notice_section(self) -> None:
        """With separator: returns only Part 2 (notice)."""
        part1 = "## Synthèse\nOpportunité excellente.\n## Contraintes\nNéant."
        part2 = "## 1. Terrain et ses abords\nLe terrain est plat."
        opus_raw = f"{part1}\n{SEPARATOR}\n{part2}"

        result = extract_notice_from_opus(opus_raw)
        assert result.strip() == part2.strip()
        assert "Opportunité excellente" not in result
        assert "Terrain et ses abords" in result

    def test_no_separator_returns_full(self) -> None:
        """Without separator: full input returned unchanged."""
        raw = "## Synthèse\nPas de séparateur ici."
        result = extract_notice_from_opus(raw)
        assert result == raw

    def test_strips_leading_whitespace_from_notice(self) -> None:
        """Notice section is returned stripped of leading/trailing whitespace."""
        part2 = "## 1. Terrain et ses abords\nContenu notice."
        opus_raw = f"Partie 1\n{SEPARATOR}\n\n\n{part2}\n\n"
        result = extract_notice_from_opus(opus_raw)
        assert result == part2.strip()

    def test_separator_constant_is_correct(self) -> None:
        """SEPARATOR must be the exact expected marker string."""
        assert SEPARATOR == "---NOTICE_PCMI4_SEPARATOR---"


# ---------------------------------------------------------------------------
# generate_notice_pcmi4_pdf
# ---------------------------------------------------------------------------


class TestGenerateNoticePcmi4Pdf:
    def test_returns_pdf_bytes(self) -> None:
        """Valid markdown + cartouche → PDF starts with b'%PDF' and >1000 bytes."""
        from core.pcmi.notice_pcmi4 import generate_notice_pcmi4_pdf

        notice_md = """## 1. Terrain et ses abords
Le terrain se situe en zone UB du PLU de Paris.

## 2. Projet dans son contexte
Le projet s'inscrit dans un tissu urbain dense.

## 3. Composition du projet
Immeuble de 4 niveaux sur rez-de-chaussée.

## 4. Accès et stationnement
Accès par la rue principale. Un parking souterrain est prévu.

## 5. Espaces libres et plantations
Un jardin de pleine terre de 80 m² est prévu en fond de parcelle.
"""
        cartouche = _make_cartouche()

        # WeasyPrint may not be available in test environment (no libgobject).
        # We mock it to return a fake PDF-like bytes object.
        fake_pdf = b"%PDF-1.4\nfake pdf content for testing purposes only\n" + b"x" * 1100
        mock_html_instance = MagicMock()
        mock_html_instance.write_pdf.return_value = fake_pdf

        with patch("core.pcmi.notice_pcmi4.weasyprint") as mock_wp:
            mock_wp.HTML.return_value = mock_html_instance
            result = generate_notice_pcmi4_pdf(notice_md=notice_md, cartouche=cartouche)

        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"
        assert len(result) > 1000

    def test_pdf_generation_renders_html(self) -> None:
        """generate_notice_pcmi4_pdf must call weasyprint.HTML with an html string."""
        from core.pcmi.notice_pcmi4 import generate_notice_pcmi4_pdf

        notice_md = "## 1. Terrain et ses abords\nLe terrain est plat."
        cartouche = _make_cartouche()

        fake_pdf = b"%PDF-1.4\n" + b"x" * 1100
        mock_html_instance = MagicMock()
        mock_html_instance.write_pdf.return_value = fake_pdf

        with patch("core.pcmi.notice_pcmi4.weasyprint") as mock_wp:
            mock_wp.HTML.return_value = mock_html_instance
            generate_notice_pcmi4_pdf(notice_md=notice_md, cartouche=cartouche)

        # weasyprint.HTML must have been called with string= kwarg
        mock_wp.HTML.assert_called_once()
        call_kwargs = mock_wp.HTML.call_args
        assert "string" in call_kwargs.kwargs or (
            len(call_kwargs.args) == 0 and "string" in str(call_kwargs)
        )


# ---------------------------------------------------------------------------
# architect_prompt SYSTEM_PROMPT dual-format extension
# ---------------------------------------------------------------------------


class TestArchitectPromptDualFormat:
    def test_system_prompt_contains_separator(self) -> None:
        """SYSTEM_PROMPT must include the dual-format separator marker."""
        from core.analysis.architect_prompt import SYSTEM_PROMPT

        assert "---NOTICE_PCMI4_SEPARATOR---" in SYSTEM_PROMPT

    def test_system_prompt_contains_pcmi4_sections(self) -> None:
        """SYSTEM_PROMPT must instruct Opus to produce the 5 PCMI4 sections."""
        from core.analysis.architect_prompt import SYSTEM_PROMPT

        assert "Terrain et ses abords" in SYSTEM_PROMPT
        assert "Composition du projet" in SYSTEM_PROMPT
        assert "Espaces libres et plantations" in SYSTEM_PROMPT

    def test_system_prompt_preserves_original_content(self) -> None:
        """Existing SYSTEM_PROMPT content (architect persona) must be preserved."""
        from core.analysis.architect_prompt import SYSTEM_PROMPT

        assert "architecte DPLG" in SYSTEM_PROMPT
        assert "gabarit-enveloppe" in SYSTEM_PROMPT
        assert "Île-de-France" in SYSTEM_PROMPT
