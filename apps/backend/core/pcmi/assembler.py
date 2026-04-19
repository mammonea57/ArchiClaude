"""PCMI dossier assembler — builds unified PDF + ZIP from individual piece PDFs.

Usage::

    unified_pdf, zip_archive = assemble_dossier(
        pdfs_par_piece={"PCMI1": pdf_bytes, "PCMI2a": pdf_bytes, ...},
        nom_projet="Résidence Les Lilas",
        cartouche=cartouche,
    )

The unified PDF concatenates pieces in PCMI_ORDER with PDF outline bookmarks.
The ZIP contains each piece as an individually named PDF plus a README.txt.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from core.pcmi.schemas import PCMI_ORDER, PCMI_TITRES, CartouchePC


def _safe_filename(text: str) -> str:
    """Return *text* sanitised to alphanumeric + hyphens + underscores.

    Upper-case is lowercased, accented characters are stripped, whitespace
    is replaced by hyphens, and everything else is dropped.
    """
    # Very light normalisation — avoid the heavy `unicodedata` dance for now.
    replacements = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a", "ä": "a",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "ù": "u", "û": "u", "ü": "u",
        "ç": "c",
        " ": "-",
    }
    result = text.lower()
    for src, dst in replacements.items():
        result = result.replace(src, dst)
    # Keep only alphanumeric, hyphen, underscore, dot
    result = re.sub(r"[^a-z0-9\-_.]", "", result)
    # Collapse multiple hyphens
    result = re.sub(r"-{2,}", "-", result)
    return result.strip("-_")


def assemble_dossier(
    *,
    pdfs_par_piece: dict[str, bytes],
    nom_projet: str,
    cartouche: CartouchePC,
) -> tuple[bytes, bytes]:
    """Assemble a unified PDF and a ZIP archive from individual piece PDFs.

    Parameters
    ----------
    pdfs_par_piece:
        Mapping of PCMI code → PDF bytes (e.g. ``{"PCMI1": b"...", ...}``).
        Only keys that appear in PCMI_ORDER are included; extra keys are
        silently ignored.
    nom_projet:
        Human-readable project name (used in README.txt and as ZIP comment).
    cartouche:
        CartouchePC with project metadata (used in README.txt).

    Returns
    -------
    (unified_pdf_bytes, zip_bytes)
    """
    writer = PdfWriter()
    page_cursor = 0  # running page index for bookmarks

    ordered_pieces: list[tuple[str, bytes]] = []
    for code in PCMI_ORDER:
        if code in pdfs_par_piece:
            ordered_pieces.append((code, pdfs_par_piece[code]))

    for code, pdf_bytes in ordered_pieces:
        reader = PdfReader(BytesIO(pdf_bytes))
        bookmark_title = f"{code} — {PCMI_TITRES.get(code, code)}"
        writer.add_outline_item(bookmark_title, page_cursor)
        for page in reader.pages:
            writer.add_page(page)
        page_cursor += len(reader.pages)

    unified_buf = BytesIO()
    writer.write(unified_buf)
    unified_pdf_bytes = unified_buf.getvalue()

    # ── Build ZIP ──────────────────────────────────────────────────────────────
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for code, pdf_bytes in ordered_pieces:
            titre = PCMI_TITRES.get(code, code)
            safe_titre = _safe_filename(titre)
            filename = f"{code}-{safe_titre}.pdf"
            zf.writestr(filename, pdf_bytes)

        readme = _build_readme(
            nom_projet=nom_projet,
            cartouche=cartouche,
            pieces=[code for code, _ in ordered_pieces],
        )
        zf.writestr("README.txt", readme)

    return unified_pdf_bytes, zip_buf.getvalue()


def _build_readme(
    *,
    nom_projet: str,
    cartouche: CartouchePC,
    pieces: list[str],
) -> str:
    """Generate README.txt content for the ZIP archive."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "=== DOSSIER PC MAISON INDIVIDUELLE (PCMI) ===",
        "",
        f"Projet        : {nom_projet}",
        f"Adresse       : {cartouche.adresse}",
        f"Parcelles     : {' | '.join(cartouche.parcelles_refs)}",
        f"Pétitionnaire : {cartouche.petitionnaire_nom}",
        f"Indice        : {cartouche.indice}",
        f"Date          : {cartouche.date}",
        f"Généré le     : {now}",
        "",
        "=== PIÈCES INCLUSES ===",
        "",
    ]
    for code in pieces:
        titre = PCMI_TITRES.get(code, code)
        safe_titre = _safe_filename(titre)
        filename = f"{code}-{safe_titre}.pdf"
        lines.append(f"  [{code}] {titre}")
        lines.append(f"        → {filename}")
        lines.append("")

    lines += [
        "=== INFORMATIONS ===",
        "",
        "Ce dossier a été généré automatiquement par ArchiClaude.",
        "Vérifiez l'ensemble des pièces avant dépôt en mairie.",
        "archiclaude.app",
        "",
    ]
    return "\n".join(lines)
