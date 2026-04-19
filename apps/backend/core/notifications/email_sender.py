"""Send templated emails via Resend."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

_SUBJECTS = {
    "workspace_invitation": "Invitation à rejoindre {workspace_name} sur ArchiClaude",
    "project_analyzed": "{project_name} — analyse de faisabilité disponible",
    "project_ready_for_pc": "{project_name} — dossier PC prêt",
    "mention": "Vous avez été mentionné sur {project_name}",
    "comment": "Nouveau commentaire sur {project_name}",
    "signup_confirmation": "Bienvenue sur ArchiClaude",
}


def _extract_keys(template: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", template)


def _render(template_name: str, variables: dict[str, Any]) -> tuple[str, str]:
    """Return (subject, html)."""
    subject_tpl = _SUBJECTS.get(template_name, "ArchiClaude")
    subject = subject_tpl.format(
        **{k: variables.get(k, "") for k in _extract_keys(subject_tpl)}
    )
    tpl = _env.get_template(f"{template_name}.html.j2")
    vars_with_defaults = {
        "app_url": os.environ.get("PUBLIC_APP_URL", ""),
        **variables,
        "subject": subject,
    }
    html = tpl.render(**vars_with_defaults)
    return subject, html


async def send(*, to: str, template: str, variables: dict[str, Any]) -> bool:
    """Send a templated email via Resend. Returns True on success, False otherwise."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping email to %s", to)
        return False

    try:
        import resend

        resend.api_key = api_key
        subject, html = _render(template, variables)
        from_email = os.environ.get("RESEND_FROM_EMAIL", "noreply@archiclaude.app")
        resend.Emails.send(
            {
                "from": from_email,
                "to": to,
                "subject": subject,
                "html": html,
            }
        )
        return True
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False
