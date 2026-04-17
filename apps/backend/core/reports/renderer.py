"""HTML report renderer — Jinja2 + markdown.

render_feasibility_html(**kwargs) -> str
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import markdown
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=False,  # we control HTML via safe filter; markdown is pre-escaped
)


def render_feasibility_html(
    *,
    project_name: str,
    commune: str,
    zone: str,
    date: str,
    surface_parcelle_m2: float,
    sdp_brute_m2: float,
    niveaux: int,
    nb_logements: int,
    emprise_sol_m2: float,
    compliance_incendie: dict[str, Any],
    compliance_pmr: dict[str, Any],
    alertes: list[dict[str, Any]],
    analyse_architecte_md: str,
    cartouche: dict[str, Any],
    typologies: list[dict[str, Any]] | None = None,
) -> str:
    """Render the feasibility HTML report from template.

    Parameters match the Jinja2 template variables directly.
    analyse_architecte_md is converted from Markdown to HTML before injection.

    Returns full HTML string ready for WeasyPrint or browser display.
    """
    analyse_architecte_html = markdown.markdown(
        analyse_architecte_md,
        extensions=["extra", "nl2br"],
    )

    template = _env.get_template("feasibility.html.j2")
    return template.render(
        project_name=project_name,
        commune=commune,
        zone=zone,
        date=date,
        surface_parcelle_m2=surface_parcelle_m2,
        sdp_brute_m2=sdp_brute_m2,
        niveaux=niveaux,
        nb_logements=nb_logements,
        emprise_sol_m2=emprise_sol_m2,
        compliance_incendie=compliance_incendie,
        compliance_pmr=compliance_pmr,
        alertes=alertes,
        analyse_architecte_html=analyse_architecte_html,
        cartouche=cartouche,
        typologies=typologies or [],
    )
