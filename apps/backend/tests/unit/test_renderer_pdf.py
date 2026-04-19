"""Unit tests for core/programming/plans/renderer_pdf.py."""

from __future__ import annotations

import io
import struct

import pytest

from core.pcmi.schemas import CartouchePC
from core.programming.plans.renderer_pdf import jpeg_to_pdf, svg_to_pdf


def _sample_cartouche(piece_num: str = "PCMI1", piece_titre: str = "Plan de situation") -> CartouchePC:
    return CartouchePC(
        nom_projet="Résidence Les Lilas",
        adresse="12 avenue Gambetta, 93100 Montreuil",
        parcelles_refs=["AV0042", "AV0043"],
        petitionnaire_nom="SCI Gambetta Invest",
        petitionnaire_contact="contact@gambettainvest.fr",
        architecte_nom="Cabinet Archi & Co",
        architecte_ordre="CROA Île-de-France n° 12345",
        architecte_contact="archi@archi-co.fr",
        piece_num=piece_num,
        piece_titre=piece_titre,
        echelle="1/500",
        date="Avril 2026",
        indice="A",
    )


_MINIMAL_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm">
  <rect x="10" y="10" width="190" height="277" fill="#e0e8f0" stroke="#333" stroke-width="1"/>
  <text x="50" y="50" font-family="Helvetica" font-size="12">Plan de situation</text>
</svg>
"""


def _minimal_jpeg_bytes() -> bytes:
    """Return a valid 2×2 red JPEG as bytes (hand-crafted minimal JFIF)."""
    # Use Pillow if available, otherwise fall back to a raw JPEG byte sequence.
    try:
        from PIL import Image

        img = Image.new("RGB", (2, 2), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()
    except ImportError:
        pass

    # Minimal valid JPEG for a 1×1 red pixel (SOI + APP0 + SOF0 + … + EOI)
    # Generated once offline and embedded as a literal for hermeticity.
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1eB"
        b"\xc8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
        b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
        b"\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br"
        b"\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJ"
        b"STUVWXYZ\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd0\x00\x00\x00"
        b"\x1f\xff\xd9"
    )


class TestSvgToPdf:
    def test_svg_to_pdf_returns_bytes(self) -> None:
        """Valid SVG → bytes that start with %PDF and are >500 bytes."""
        result = svg_to_pdf(
            svg_string=_MINIMAL_SVG,
            format="A4",
            orientation="portrait",
            cartouche=_sample_cartouche(),
        )
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF", f"Expected PDF header, got {result[:8]!r}"
        assert len(result) > 500, f"PDF too small: {len(result)} bytes"

    def test_svg_to_pdf_a3_landscape(self) -> None:
        """SVG → A3 landscape PDF is valid and >500 bytes."""
        result = svg_to_pdf(
            svg_string=_MINIMAL_SVG,
            format="A3",
            orientation="landscape",
            cartouche=_sample_cartouche("PCMI2a", "Plan de masse"),
        )
        assert result[:4] == b"%PDF"
        assert len(result) > 500

    def test_svg_to_pdf_a1_landscape(self) -> None:
        """SVG → A1 landscape PDF is valid."""
        result = svg_to_pdf(
            svg_string=_MINIMAL_SVG,
            format="A1",
            orientation="landscape",
            cartouche=_sample_cartouche("PCMI2b", "Plans de niveaux"),
        )
        assert result[:4] == b"%PDF"

    def test_svg_to_pdf_with_architecte(self) -> None:
        """Cartouche with full architect info still renders correctly."""
        cart = _sample_cartouche()
        result = svg_to_pdf(svg_string=_MINIMAL_SVG, cartouche=cart)
        assert result[:4] == b"%PDF"

    def test_svg_to_pdf_unknown_format_defaults_a4(self) -> None:
        """Unknown format string defaults to A4."""
        result = svg_to_pdf(
            svg_string=_MINIMAL_SVG,
            format="A5",  # type: ignore[arg-type]
            orientation="portrait",
            cartouche=_sample_cartouche(),
        )
        assert result[:4] == b"%PDF"


class TestJpegToPdf:
    def test_jpeg_to_pdf_embeds_image(self) -> None:
        """Minimal 2×2 red JPEG bytes → valid PDF (>500 bytes, %PDF header)."""
        jpeg = _minimal_jpeg_bytes()
        result = jpeg_to_pdf(
            jpeg_bytes=jpeg,
            format="A4",
            orientation="landscape",
            cartouche=_sample_cartouche("PCMI7", "Photographie proche"),
        )
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF", f"Expected PDF header, got {result[:8]!r}"
        assert len(result) > 500

    def test_jpeg_to_pdf_a3(self) -> None:
        """JPEG → A3 landscape PDF is valid."""
        jpeg = _minimal_jpeg_bytes()
        result = jpeg_to_pdf(
            jpeg_bytes=jpeg,
            format="A3",
            orientation="landscape",
            cartouche=_sample_cartouche("PCMI8", "Photographie lointain"),
        )
        assert result[:4] == b"%PDF"

    def test_jpeg_to_pdf_portrait(self) -> None:
        """JPEG → A4 portrait PDF is valid."""
        jpeg = _minimal_jpeg_bytes()
        result = jpeg_to_pdf(
            jpeg_bytes=jpeg,
            format="A4",
            orientation="portrait",
            cartouche=_sample_cartouche(),
        )
        assert result[:4] == b"%PDF"
