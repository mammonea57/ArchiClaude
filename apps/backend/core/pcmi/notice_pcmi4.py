"""PCMI4 notice architecturale generator.

Produces a formatted PDF from the architectural notice markdown, with a
cartouche at the bottom of each page. PDF rendering is done via WeasyPrint.

WeasyPrint requires system libraries (libgobject, pango, cairo). When they
are unavailable the module still imports cleanly — ``generate_notice_pcmi4_pdf``
will raise ``RuntimeError`` unless the caller mocks ``weasyprint`` in tests.
"""

from __future__ import annotations

import logging
from pathlib import Path

import markdown as markdown_lib
from jinja2 import Environment, FileSystemLoader

from core.pcmi.schemas import CartouchePC

try:
    import weasyprint  # type: ignore[import-untyped]
except OSError:
    weasyprint = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)

# Exact separator marker used in Opus dual-format output.
SEPARATOR = "---NOTICE_PCMI4_SEPARATOR---"

_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def extract_notice_from_opus(opus_raw: str) -> str:
    """Extract PCMI4 notice section from dual-format Opus output.

    Opus produces:
      note_opportunite + SEPARATOR + notice_pcmi4

    Returns the notice section (Part 2), stripped.
    Returns the full input unchanged if no separator is found.
    """
    if SEPARATOR not in opus_raw:
        return opus_raw

    parts = opus_raw.split(SEPARATOR, maxsplit=1)
    return parts[1].strip()


def generate_notice_pcmi4_pdf(*, notice_md: str, cartouche: CartouchePC) -> bytes:
    """Render the PCMI4 notice markdown to a PDF.

    Args:
        notice_md: Markdown content of the PCMI4 notice architecturale.
        cartouche: Project cartouche metadata for title block / page footer.

    Returns:
        PDF as raw bytes.

    Raises:
        RuntimeError: If WeasyPrint system libraries are not available.
    """
    if weasyprint is None:
        raise RuntimeError(
            "WeasyPrint is not available: system libraries (libgobject / pango) "
            "are missing. Install them following: "
            "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html"
        )

    # Convert markdown to HTML
    notice_html = markdown_lib.markdown(notice_md, extensions=["extra"])

    # Render Jinja2 template
    jinja_env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )
    template = jinja_env.get_template("notice_pcmi4.html.j2")
    html_str = template.render(
        cartouche=cartouche,
        notice_html=notice_html,
        parcelles=", ".join(cartouche.parcelles_refs),
    )

    return weasyprint.HTML(string=html_str).write_pdf()
