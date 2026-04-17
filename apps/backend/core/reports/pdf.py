"""PDF generation via WeasyPrint.

generate_pdf_from_html(html: str) -> bytes
"""

from __future__ import annotations

import weasyprint


def generate_pdf_from_html(html: str) -> bytes:
    """Convert an HTML string to PDF bytes using WeasyPrint.

    Args:
        html: Full HTML document string (e.g. from render_feasibility_html).

    Returns:
        PDF file contents as bytes.
    """
    return weasyprint.HTML(string=html).write_pdf()
