"""Cartouche PC — generates an SVG <g> block for the PC dossier title block.

The cartouche is 40mm high and spans the full page width.
It follows the standard French PC dossier layout conventions.
"""

from __future__ import annotations

import xml.sax.saxutils as saxutils

from core.pcmi.schemas import CartouchePC

CARTOUCHE_HEIGHT_MM = 40.0
SIGNATURE = "Généré par ArchiClaude — archiclaude.app"


def _esc(value: str) -> str:
    """Escape a string for safe inclusion in XML/SVG text content."""
    return saxutils.escape(str(value))


def render_cartouche_svg(cartouche: CartouchePC, width_mm: float) -> str:
    """Generate SVG cartouche block (40mm high, full page width).

    Returns a ``<g>`` element (not a full SVG document).
    The coordinate system uses millimetres; the caller embeds this ``<g>``
    inside a parent ``<svg>`` that has ``viewBox`` in mm units.

    Layout::

        ┌─────────────────────────────────┬───────────────────────┐  h/2
        │  PROJET / ADRESSE / PARCELLES   │  Pièce num + titre    │
        │                                 │  Échelle / Date/Indice│
        ├─────────────────────────────────┼───────────────────────┤  h/2
        │  Pétitionnaire                  │  Architecte (opt)     │
        │  ArchiClaude signature (small)  │                       │
        └─────────────────────────────────┴───────────────────────┘
    """
    h = CARTOUCHE_HEIGHT_MM
    w = width_mm
    col1_w = w * 0.55
    col2_x = col1_w
    half_h = h / 2.0

    # Font sizes in mm (approximate pt equivalents for SVG viewBox in mm)
    fs_label = 2.2   # small label
    fs_value = 3.0   # regular value
    fs_small = 1.5   # signature / fine print

    # Padding inside cells
    pad = 2.0

    lines: list[str] = []

    # ── outer border ──────────────────────────────────────────────────────────
    lines.append(
        f'<rect x="0" y="0" width="{w}" height="{h}" '
        f'fill="white" stroke="#222222" stroke-width="0.3"/>'
    )

    # ── vertical divider at col1_w ────────────────────────────────────────────
    lines.append(
        f'<line x1="{col1_w}" y1="0" x2="{col1_w}" y2="{h}" '
        f'stroke="#222222" stroke-width="0.3"/>'
    )

    # ── horizontal divider at h/2 ─────────────────────────────────────────────
    lines.append(
        f'<line x1="0" y1="{half_h}" x2="{w}" y2="{half_h}" '
        f'stroke="#222222" stroke-width="0.3"/>'
    )

    # ── TOP-LEFT: Projet / Adresse / Parcelles ────────────────────────────────
    y_tl = pad + fs_label
    lines.append(
        f'<text x="{pad}" y="{y_tl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#666666" font-weight="bold">PROJET</text>'
    )
    y_tl += fs_value + 0.5
    lines.append(
        f'<text x="{pad}" y="{y_tl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_value}" '
        f'fill="#111111">{_esc(cartouche.nom_projet)}</text>'
    )
    y_tl += fs_label + 1.0
    lines.append(
        f'<text x="{pad}" y="{y_tl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#666666" font-weight="bold">ADRESSE</text>'
    )
    y_tl += fs_value + 0.5
    lines.append(
        f'<text x="{pad}" y="{y_tl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_value}" '
        f'fill="#111111">{_esc(cartouche.adresse)}</text>'
    )
    y_tl += fs_label + 1.0
    lines.append(
        f'<text x="{pad}" y="{y_tl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#666666" font-weight="bold">PARCELLES</text>'
    )
    y_tl += fs_value + 0.5
    parcelles_str = " | ".join(cartouche.parcelles_refs)
    lines.append(
        f'<text x="{pad}" y="{y_tl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_value}" '
        f'fill="#111111">{_esc(parcelles_str)}</text>'
    )

    # ── TOP-RIGHT: Pièce num + titre / Échelle / Date / Indice ───────────────
    rx = col2_x + pad
    y_tr = pad + fs_label
    if cartouche.piece_num:
        piece_label = f"{_esc(cartouche.piece_num)} — {_esc(cartouche.piece_titre)}"
    else:
        piece_label = _esc(cartouche.piece_titre)
    lines.append(
        f'<text x="{rx}" y="{y_tr}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_value}" '
        f'fill="#111111" font-weight="bold">{piece_label}</text>'
    )
    y_tr += fs_value + 1.5
    lines.append(
        f'<text x="{rx}" y="{y_tr}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#666666">Échelle : {_esc(cartouche.echelle)}</text>'
    )
    y_tr += fs_label + 1.0
    lines.append(
        f'<text x="{rx}" y="{y_tr}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#666666">Date : {_esc(cartouche.date)}</text>'
    )
    y_tr += fs_label + 1.0
    lines.append(
        f'<text x="{rx}" y="{y_tr}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#666666">Indice : {_esc(cartouche.indice)}</text>'
    )

    # ── BOTTOM-LEFT: Pétitionnaire ────────────────────────────────────────────
    y_bl = half_h + pad + fs_label
    lines.append(
        f'<text x="{pad}" y="{y_bl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#666666" font-weight="bold">PÉTITIONNAIRE</text>'
    )
    y_bl += fs_value + 0.5
    lines.append(
        f'<text x="{pad}" y="{y_bl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_value}" '
        f'fill="#111111">{_esc(cartouche.petitionnaire_nom)}</text>'
    )
    y_bl += fs_label + 0.5
    lines.append(
        f'<text x="{pad}" y="{y_bl}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
        f'fill="#444444">{_esc(cartouche.petitionnaire_contact)}</text>'
    )

    # ── BOTTOM-RIGHT: Architecte (optional) ───────────────────────────────────
    if cartouche.architecte_nom:
        y_br = half_h + pad + fs_label
        lines.append(
            f'<text x="{rx}" y="{y_br}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
            f'fill="#666666" font-weight="bold">ARCHITECTE</text>'
        )
        y_br += fs_value + 0.5
        lines.append(
            f'<text x="{rx}" y="{y_br}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_value}" '
            f'fill="#111111">{_esc(cartouche.architecte_nom)}</text>'
        )
        if cartouche.architecte_ordre:
            y_br += fs_label + 0.5
            lines.append(
                f'<text x="{rx}" y="{y_br}" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
                f'fill="#444444">{_esc(cartouche.architecte_ordre)}</text>'
            )
        if cartouche.architecte_contact:
            y_br += fs_label + 0.5
            lines.append(
                f'<text x="{rx}" y="{y_br}" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_label}" '
                f'fill="#444444">{_esc(cartouche.architecte_contact)}</text>'
            )

    # ── ArchiClaude signature — bottom-right, small gray ─────────────────────
    sig_x = w - pad
    sig_y = h - pad
    lines.append(
        f'<text x="{sig_x}" y="{sig_y}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_small}" '
        f'fill="#999999" text-anchor="end">{_esc(SIGNATURE)}</text>'
    )

    inner = "\n  ".join(lines)
    return f"<g>\n  {inner}\n</g>"
