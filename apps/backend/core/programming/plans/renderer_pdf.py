"""PDF renderer — converts SVG or JPEG plan sheets to PDF with cartouche.

Each output is a single A4/A3/A1 page at the requested orientation,
with a 40 mm cartouche strip at the bottom and 20 mm margins all around.
"""

from __future__ import annotations

from io import BytesIO, StringIO
from typing import Literal

from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A1, A3, A4, landscape, portrait
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from svglib.svglib import svg2rlg

from core.pcmi.cartouche_pc import CARTOUCHE_HEIGHT_MM
from core.pcmi.schemas import CartouchePC

FORMATS: dict[str, tuple[float, float]] = {"A1": A1, "A3": A3, "A4": A4}

MARGIN_MM = 20.0


def _get_page_size(
    format: str,  # noqa: A002
    orientation: str,
) -> tuple[float, float]:
    """Return page dimensions in ReportLab points (1 pt = 1/72 in)."""
    size = FORMATS.get(format, A4)
    return landscape(size) if orientation == "landscape" else portrait(size)


def _draw_cartouche_on_canvas(
    c: rl_canvas.Canvas,
    cartouche: CartouchePC,
    page_width_pt: float,
) -> None:
    """Draw 40 mm cartouche strip at the very bottom of the current page.

    Layout mirrors the SVG cartouche defined in cartouche_pc.py:
      • Left 55 %: PROJET / ADRESSE / PARCELLES  (top half)
                   Pétitionnaire                  (bottom half)
      • Right 45 %: Pièce num + titre / Échelle / Date / Indice (top half)
                    Architecte (optional)          (bottom half)
      • ArchiClaude signature — bottom-right, 5 pt gray
    """
    cart_h = CARTOUCHE_HEIGHT_MM * mm
    col_split = page_width_pt * 0.55
    half_h = cart_h / 2.0
    pad = 2.0 * mm

    # Outer border
    c.setStrokeColorRGB(0.13, 0.13, 0.13)
    c.setLineWidth(0.3 * mm)
    c.rect(0, 0, page_width_pt, cart_h, fill=0, stroke=1)

    # Vertical divider at 55 %
    c.line(col_split, 0, col_split, cart_h)

    # Horizontal divider at half height
    c.line(0, half_h, page_width_pt, half_h)

    # ── TOP-LEFT — PROJET / ADRESSE / PARCELLES ────────────────────────────────
    c.setFont("Helvetica-Bold", 6)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    y = cart_h - pad - 6
    c.drawString(pad, y, "PROJET")

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    y -= 9
    c.drawString(pad, y, cartouche.nom_projet[:60])

    c.setFont("Helvetica-Bold", 6)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    y -= 8
    c.drawString(pad, y, "ADRESSE")

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    y -= 9
    c.drawString(pad, y, cartouche.adresse[:60])

    c.setFont("Helvetica-Bold", 6)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    y -= 8
    c.drawString(pad, y, "PARCELLES")

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    y -= 9
    parcelles_str = " | ".join(cartouche.parcelles_refs)
    c.drawString(pad, y, parcelles_str[:80])

    # ── TOP-RIGHT — Pièce num + titre / Échelle / Date / Indice ───────────────
    rx = col_split + pad
    c.setFont("Helvetica-Bold", 8)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    y_tr = cart_h - pad - 8
    if cartouche.piece_num:
        piece_label = f"{cartouche.piece_num} — {cartouche.piece_titre}"
    else:
        piece_label = cartouche.piece_titre
    c.drawString(rx, y_tr, piece_label[:50])

    c.setFont("Helvetica", 6)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    y_tr -= 9
    c.drawString(rx, y_tr, f"Échelle : {cartouche.echelle}")
    y_tr -= 8
    c.drawString(rx, y_tr, f"Date : {cartouche.date}")
    y_tr -= 8
    c.drawString(rx, y_tr, f"Indice : {cartouche.indice}")

    # ── BOTTOM-LEFT — Pétitionnaire ────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 6)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    y_bl = half_h - pad - 6
    c.drawString(pad, y_bl, "PÉTITIONNAIRE")

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    y_bl -= 9
    c.drawString(pad, y_bl, cartouche.petitionnaire_nom[:60])

    c.setFont("Helvetica", 6)
    c.setFillColorRGB(0.27, 0.27, 0.27)
    y_bl -= 8
    c.drawString(pad, y_bl, cartouche.petitionnaire_contact[:60])

    # ── BOTTOM-RIGHT — Architecte (optional) ──────────────────────────────────
    if cartouche.architecte_nom:
        rx2 = col_split + pad
        c.setFont("Helvetica-Bold", 6)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        y_br = half_h - pad - 6
        c.drawString(rx2, y_br, "ARCHITECTE")

        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.07, 0.07, 0.07)
        y_br -= 9
        c.drawString(rx2, y_br, cartouche.architecte_nom[:50])

        if cartouche.architecte_ordre:
            c.setFont("Helvetica", 6)
            c.setFillColorRGB(0.27, 0.27, 0.27)
            y_br -= 8
            c.drawString(rx2, y_br, cartouche.architecte_ordre[:50])

        if cartouche.architecte_contact:
            c.setFont("Helvetica", 6)
            c.setFillColorRGB(0.27, 0.27, 0.27)
            y_br -= 8
            c.drawString(rx2, y_br, cartouche.architecte_contact[:50])

    # ── ArchiClaude signature — bottom-right, 5 pt gray ──────────────────────
    c.setFont("Helvetica", 5)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    sig = "Généré par ArchiClaude — archiclaude.app"
    c.drawRightString(page_width_pt - pad, pad, sig)


def svg_to_pdf(
    *,
    svg_string: str,
    format: Literal["A1", "A3", "A4"] = "A4",  # noqa: A002
    orientation: Literal["portrait", "landscape"] = "portrait",
    cartouche: CartouchePC,
) -> bytes:
    """Convert an SVG string → single-page PDF with cartouche.

    The SVG drawing is scaled to fill the available area above the cartouche,
    respecting 20 mm margins on all sides except the bottom (where the cartouche
    replaces the margin).
    """
    page_w, page_h = _get_page_size(format, orientation)
    cart_h = CARTOUCHE_HEIGHT_MM * mm
    margin = MARGIN_MM * mm

    available_w = page_w - 2 * margin
    available_h = page_h - cart_h - margin  # top margin only; bottom is cartouche

    # Parse SVG
    drawing = svg2rlg(StringIO(svg_string))

    if drawing is not None and drawing.width > 0 and drawing.height > 0:
        scale = min(available_w / drawing.width, available_h / drawing.height)
        drawing.width = drawing.width * scale
        drawing.height = drawing.height * scale
        drawing.transform = (scale, 0, 0, scale, 0, 0)

    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))

    if drawing is not None:
        # Draw SVG above cartouche, centred horizontally
        draw_x = margin + (available_w - drawing.width) / 2
        draw_y = cart_h + (available_h - drawing.height) / 2
        renderPDF.draw(drawing, c, draw_x, draw_y)

    # Draw cartouche at bottom of page
    c.saveState()
    _draw_cartouche_on_canvas(c, cartouche, page_w)
    c.restoreState()

    c.showPage()
    c.save()
    return buf.getvalue()


def jpeg_to_pdf(
    *,
    jpeg_bytes: bytes,
    format: Literal["A1", "A3", "A4"] = "A4",  # noqa: A002
    orientation: Literal["portrait", "landscape"] = "landscape",
    cartouche: CartouchePC,
) -> bytes:
    """Embed a JPEG image into a single-page PDF with cartouche.

    The image is centred in the available area while preserving its
    original aspect ratio.
    """
    page_w, page_h = _get_page_size(format, orientation)
    cart_h = CARTOUCHE_HEIGHT_MM * mm
    margin = MARGIN_MM * mm

    available_w = page_w - 2 * margin
    available_h = page_h - cart_h - margin

    img_reader = ImageReader(BytesIO(jpeg_bytes))
    img_w_px, img_h_px = img_reader.getSize()

    if img_w_px > 0 and img_h_px > 0:
        scale = min(available_w / img_w_px, available_h / img_h_px)
        draw_w = img_w_px * scale
        draw_h = img_h_px * scale
    else:
        draw_w, draw_h = available_w, available_h

    # Centre in available area
    draw_x = margin + (available_w - draw_w) / 2
    draw_y = cart_h + (available_h - draw_h) / 2

    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.drawImage(img_reader, draw_x, draw_y, width=draw_w, height=draw_h)

    c.saveState()
    _draw_cartouche_on_canvas(c, cartouche, page_w)
    c.restoreState()

    c.showPage()
    c.save()
    return buf.getvalue()
