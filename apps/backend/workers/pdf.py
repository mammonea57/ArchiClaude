"""ARQ worker task for PDF report generation."""

from __future__ import annotations


async def generate_pdf_job(ctx: dict, *, result_id: str, html: str) -> dict:
    """Generate a PDF from HTML and return size metadata.

    Args:
        ctx: ARQ job context.
        result_id: ID of the feasibility result this report belongs to.
        html: Rendered HTML content to convert to PDF.

    Returns:
        dict with status and size_bytes of the generated PDF.
    """
    from core.reports.pdf import generate_pdf_from_html

    pdf_bytes = generate_pdf_from_html(html)
    return {"status": "done", "size_bytes": len(pdf_bytes)}
