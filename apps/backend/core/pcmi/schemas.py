"""PCMI dossier schemas — dataclasses for PC complet generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class CartouchePC:
    nom_projet: str
    adresse: str
    parcelles_refs: list[str]
    petitionnaire_nom: str
    petitionnaire_contact: str
    architecte_nom: str | None = None
    architecte_ordre: str | None = None
    architecte_contact: str | None = None
    piece_num: str = ""
    piece_titre: str = ""
    echelle: str = ""
    date: str = ""
    indice: str = "A"
    logo_agence_url: str | None = None


@dataclass
class PcmiPiece:
    code: str
    titre: str
    svg_content: str | None = None
    pdf_bytes: bytes | None = None
    html_content: str | None = None
    error: str | None = None


@dataclass
class PcmiDossier:
    project_id: str
    indice_revision: str
    pieces: list[PcmiPiece]
    pdf_unique_bytes: bytes | None = None
    zip_bytes: bytes | None = None
    cartouche: CartouchePC | None = None
    map_base: Literal["scan25", "planv2"] = "scan25"
    generated_at: datetime = field(default_factory=datetime.utcnow)
    status: Literal["queued", "generating", "done", "failed"] = "queued"
    error_msg: str | None = None


PCMI_ORDER = ["PCMI1", "PCMI2a", "PCMI2b", "PCMI3", "PCMI4", "PCMI5", "PCMI7", "PCMI8"]

PCMI_TITRES = {
    "PCMI1": "Plan de situation",
    "PCMI2a": "Plan de masse",
    "PCMI2b": "Plans de niveaux",
    "PCMI3": "Plan en coupe",
    "PCMI4": "Notice architecturale",
    "PCMI5": "Plans des façades",
    "PCMI7": "Photographie environnement proche",
    "PCMI8": "Photographie environnement lointain",
}

PCMI_FORMATS = {
    "PCMI1": ("A4", "portrait"),
    "PCMI2a": ("A3", "landscape"),
    "PCMI2b": ("A1", "landscape"),
    "PCMI3": ("A3", "landscape"),
    "PCMI4": ("A4", "portrait"),
    "PCMI5": ("A3", "landscape"),
    "PCMI7": ("A4", "landscape"),
    "PCMI8": ("A4", "landscape"),
}
