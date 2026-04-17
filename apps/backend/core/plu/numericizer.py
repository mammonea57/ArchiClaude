"""Convert ParsedRules → NumericRules via Claude Sonnet tool_use."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic

from core.plu.prompt import build_numericizer_prompt
from core.plu.schemas import NumericRules, ParsedRules, RuleFormula

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NUMERICIZER_MODEL = "claude-sonnet-4-6-20250514"

# JSON Schema for NumericRules — used as the tool input schema
_NUMERIC_RULES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hauteur_max_m": {"type": ["number", "null"], "description": "Hauteur maximale en mètres"},
        "hauteur_max_niveaux": {"type": ["integer", "null"], "description": "Nombre de niveaux maximum"},
        "hauteur_max_ngf": {"type": ["number", "null"], "description": "Altitude NGF maximale en mètres"},
        "hauteur_facade_m": {"type": ["number", "null"], "description": "Hauteur de façade en mètres"},
        "emprise_max_pct": {"type": ["number", "null"], "description": "CES maximum en pourcentage (0-100)"},
        "recul_voirie_m": {"type": ["number", "null"], "description": "Recul minimal par rapport aux voies en mètres"},
        "recul_voirie_formula": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                        "min_value": {"type": ["number", "null"]},
                        "max_value": {"type": ["number", "null"]},
                        "units": {"type": "string"},
                        "raw_text": {"type": "string"},
                    },
                    "required": ["expression"],
                },
                {"type": "null"},
            ]
        },
        "recul_limite_lat_m": {"type": ["number", "null"], "description": "Recul latéral minimal en mètres"},
        "recul_limite_lat_formula": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                        "min_value": {"type": ["number", "null"]},
                        "max_value": {"type": ["number", "null"]},
                        "units": {"type": "string"},
                        "raw_text": {"type": "string"},
                    },
                    "required": ["expression"],
                },
                {"type": "null"},
            ]
        },
        "recul_fond_m": {"type": ["number", "null"], "description": "Recul de fond de parcelle en mètres"},
        "recul_fond_formula": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                        "min_value": {"type": ["number", "null"]},
                        "max_value": {"type": ["number", "null"]},
                        "units": {"type": "string"},
                        "raw_text": {"type": "string"},
                    },
                    "required": ["expression"],
                },
                {"type": "null"},
            ]
        },
        "cos": {"type": ["number", "null"], "description": "Coefficient d'occupation des sols"},
        "sdp_max_m2": {"type": ["number", "null"], "description": "Surface de plancher maximum en m²"},
        "pleine_terre_min_pct": {"type": "number", "description": "Pleine terre minimum en pourcentage", "default": 0.0},
        "surface_vegetalisee_min_pct": {"type": ["number", "null"], "description": "Surface végétalisée minimum en pourcentage"},
        "coef_biotope_min": {"type": ["number", "null"], "description": "Coefficient de biotope minimum"},
        "stationnement_par_logement": {"type": ["number", "null"], "description": "Places de stationnement par logement"},
        "stationnement_par_m2_bureau": {"type": ["number", "null"], "description": "Places de stationnement par m² de bureau"},
        "stationnement_par_m2_commerce": {"type": ["number", "null"], "description": "Places de stationnement par m² de commerce"},
        "bandes_constructibles": {
            "anyOf": [
                {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": ["principale", "secondaire", "fond"]},
                            "hauteur_max_m": {"type": ["number", "null"]},
                            "emprise_max_pct": {"type": ["number", "null"]},
                            "depth_from_voie_m": {"type": ["number", "null"]},
                        },
                        "required": ["name"],
                    },
                },
                {"type": "null"},
            ]
        },
        "article_refs": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Références d'articles par champ",
        },
        "extraction_confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confiance globale de l'extraction (0.0 à 1.0)",
        },
        "extraction_warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Liste d'alertes pour valeurs ambiguës ou manquantes",
        },
    },
    "required": ["extraction_confidence", "extraction_warnings"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def numericize_rules(parsed: ParsedRules) -> NumericRules:
    """Convert textual ParsedRules to numeric NumericRules via LLM tool_use.

    Args:
        parsed: The textual rules extracted by extract_rules().

    Returns:
        ``NumericRules`` with all extractable numeric values populated.
    """
    # Exclude cache/source metadata — LLM only needs the rule text fields
    input_dict = parsed.model_dump(exclude={"cached", "source"})
    result_dict = await _call_numericizer_llm(input_dict)
    return NumericRules(**_sanitize_result(result_dict))


# ---------------------------------------------------------------------------
# Internal LLM call (separated for easy mocking)
# ---------------------------------------------------------------------------


async def _call_numericizer_llm(parsed_dict: dict[str, Any]) -> dict[str, Any]:
    """Call Claude Sonnet with tool_use to get structured NumericRules output.

    Uses the ``extract_numeric_rules`` tool so the model returns a validated
    JSON structure rather than free-form text.
    """
    client = anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY", "")
    )

    tool_def: dict[str, Any] = {
        "name": "extract_numeric_rules",
        "description": (
            "Extrait les valeurs numériques structurées depuis les règles PLU textuelles. "
            "Convertit les règles textuelles en valeurs numériques exploitables par "
            "le moteur de faisabilité."
        ),
        "input_schema": _NUMERIC_RULES_SCHEMA,
    }

    user_message = (
        "Voici les règles PLU textuelles à convertir en valeurs numériques :\n\n"
        + json.dumps(parsed_dict, ensure_ascii=False, indent=2)
    )

    response = await client.messages.create(
        model=_NUMERICIZER_MODEL,
        max_tokens=2000,
        system=build_numericizer_prompt(),
        tools=[tool_def],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": user_message}],
    )

    # Extract tool_use block from response
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_numeric_rules":
            return dict(block.input)  # type: ignore[union-attr]

    # Fallback: no tool_use block — return minimal defaults
    log.warning("numericizer: no tool_use block in LLM response")
    return {
        "extraction_confidence": 0.0,
        "extraction_warnings": ["LLM did not use tool_use"],
    }


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def _sanitize_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Ensure the result dict is compatible with the NumericRules Pydantic model.

    - Converts nested RuleFormula dicts to the right structure.
    - Fills in defaults for required fields.
    - Strips unknown keys to avoid Pydantic validation errors.
    """
    result = dict(raw)

    # Ensure required defaults
    result.setdefault("extraction_confidence", 0.0)
    result.setdefault("extraction_warnings", [])
    result.setdefault("article_refs", {})
    result.setdefault("pleine_terre_min_pct", 0.0)

    # Convert nested formula dicts to RuleFormula if needed
    formula_fields = [
        "recul_voirie_formula",
        "recul_limite_lat_formula",
        "recul_fond_formula",
    ]
    for field in formula_fields:
        val = result.get(field)
        if isinstance(val, dict):
            try:
                result[field] = RuleFormula(**val)
            except Exception:
                log.warning("numericizer: could not parse RuleFormula for %s", field)
                result[field] = None

    # Remove unknown keys that NumericRules doesn't accept
    known_fields = set(NumericRules.model_fields.keys())
    for key in list(result.keys()):
        if key not in known_fields:
            del result[key]

    return result
