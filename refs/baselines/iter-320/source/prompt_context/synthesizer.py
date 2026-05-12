"""Render-prompt synthesizer v2 — consumes an ArchReasoning.

The reasoner has already decided WHAT the building should look like (and why).
This module's only job is to render those decisions into a 60-75 token
SD/SDXL prompt with the most important visual cues at the front (CLIP
truncates anything past 77 tokens).

Critical : the order matters. CLIP's truncation cuts the END of the prompt,
so the front carries the heaviest visual weight. We put :
  1. Trigger word (LoRA bias, 3 tokens)
  2. Critical scale + density (height, "dense urban faubourg block") — survives truncation
  3. Camera framing (preset-specific)
  4. Facade material (with PLU/voisinage justification baked in by reasoner)
  5. Toiture (BM-grounded)
  6. Balcons + RDC + 2025 trends
  7. Photo-style cues at the end (truncated first when over)
"""
from __future__ import annotations

import logging
from typing import Any

from .reasoner import reason_about_project
from .reasoning import ArchReasoning
from .trends_2025 import CURRENT_TRENDS

logger = logging.getLogger(__name__)

LORA_TRIGGER = "archfr_idf_modern"

_FRAMING: dict[str, str] = {
    "oiseau_iso": "aerial 3/4 bird's-eye view from above",
    "ensemble_recule": "wide three-quarter view from a distance, full block context",
    "angle_3_4": "classic 3/4 perspective shot",
    "rue_est_proche": "close-up street-level photo at pedestrian eye level",
    "rue_est_eloignee": "street view from the opposite sidewalk, full building visible",
    "rue_sud": "street view from the south sidewalk",
    "rue_se_proche": "pedestrian eye-level 3/4 view from the SE corner",
    "rue_se_eloignee": "wide street-level 3/4 view from the SE corner showing the L-shape footprint",
    "entree_zoom": "close-up of the main entrance",
}


def synthesize_prompt(
    bm_payload: dict[str, Any],
    preset: str,
    extra: str = "",
    project_id: str | None = None,
    target: str = "sd15",
) -> tuple[str, str]:
    """Build (positive_prompt, negative_prompt) by reasoning about the project.

    Args :
        bm_payload : output of GET /api/v1/projects/{id}/building_model
        preset : camera preset name
        extra : optional user-supplied addendum
        project_id : if provided, the reasoner also fetches voisinage data
        target : "sd15" (default, includes archfr_idf_modern LoRA trigger) or
            "sdxl" (drops the trigger, uses English-friendly notation,
            material-first ordering — better for JuggernautXL / RealVisXL).

    Returns :
        (prompt, negative) tuple, both targeting ≤ 77 tokens (CLIP-tokenizer).
    """
    reasoning = reason_about_project(bm_payload, project_id=project_id)
    return synthesize_from_reasoning(reasoning, preset, extra, target=target)


def synthesize_dual_prompts(
    bm_payload: dict[str, Any],
    preset: str,
    project_id: str | None = None,
) -> tuple[str, str, str]:
    """SDXL-only : produce TWO complementary prompts to feed both text encoders.

    SDXL has CLIP-L + OpenCLIP-bigG. Diffusers' SDXL pipeline accepts both
    `prompt` (CLIP-L) and `prompt_2` (bigG). Each is capped at 77 tokens, but
    they're concatenated downstream so we get ~150 effective tokens.

    Strategy :
      • `prompt`     → SCENE / COMPOSITION / CAMERA — what CLIP-L is good at.
      • `prompt_2`   → MATERIALS / TEXTURES / ACCENTS — bigG has richer vocab.
      • `negative`   → shared.

    Returns: (prompt, prompt_2, negative) — all natural English, no LoRA trigger.
    """
    reasoning = reason_about_project(bm_payload, project_id=project_id)
    framing = _FRAMING.get(preset, "architectural perspective view")
    en_height = _height_to_english(reasoning.choices["height"].chosen)
    context = reasoning.choices["context"].chosen

    # iter #312 — Front-load Option 4 materials into prompt (CLIP 77 tokens)
    # so the building TRULY renders with the right materials (not generic
    # white). Order : (1) photo type, (2) building type + Option 4 materials,
    # (3) composition, (4) quality. The materials must appear in the first
    # ~50 words for CLIP to actually weight them.
    prompt = (
        f"high-end architectural photograph of a French residential apartment building {en_height}, "
        "warm cream limestone stone ground floor RDC, terracotta red brick stair columns, "
        "matt anthracite zinc top floor cladding, cream-white render upper floors, "
        "cantilevered concrete balconies with thin black iron railings, "
        f"{framing}, {context}, "
        "shot 35mm f/8, soft late-morning daylight, clear pale-blue sky, "
        "sharp focus, rule-of-thirds composition, "
        "8K ultra-detailed photoreal documentary photograph, true-to-life colours, "
        "fine micro-detail in materials, accurate light/shadow gradient, professional clean"
    )

    # iter #312 — OPTION 4 HARDCODED OVERRIDE for the Nogent PC project.
    # User wants the building to explicitly read as : warm cream limestone
    # RDC + cream-white render upper floors + matt anthracite zinc attique
    # + terracotta red brick stair-core columns vertical accents + slim
    # cantilevered concrete balconies with thin black wrought iron railings.
    # The reasoner-derived facade_phrase was too generic ; FLUX rendered the
    # building mostly flat white. Forcing the Option 4 design at the front
    # of CLIP-77 token budget so the materials actually take effect.
    OPTION_4_FACADE = (
        "warm cream limestone stone ground floor base, "
        "terracotta red brick vertical stair-core columns at the corners, "
        "matt anthracite zinc set-back top floor cladding, "
        "RAL 9001 cream-white smooth lime render upper floors, "
        "continuous slim cantilevered concrete balconies with thin matt black wrought iron railings, "
        "pale stone window surrounds with deep reveals, dark walnut entrance door"
    )
    facade_phrase = OPTION_4_FACADE
    trend_ids = set(reasoning.trends_applied)
    trend_cues = [t.prompt_cue for t in CURRENT_TRENDS if t.id in trend_ids]
    extra_trends = _select_non_redundant_trend_cues(trend_cues, [facade_phrase, context])
    toiture = reasoning.choices["toiture"].chosen
    emit_toiture = toiture and "rooftop garden" not in facade_phrase.lower()

    prompt_2_parts = [facade_phrase]
    if emit_toiture:
        prompt_2_parts.append(toiture)
    prompt_2_parts.extend(extra_trends)
    prompt_2 = ", ".join(p for p in prompt_2_parts if p)

    # Shared negative — focused on actual failure modes, not on style.
    # Over-aggressive negatives (e.g. "magazine, golden hour, render")
    # produced flat dull "soviet block" renders. We keep only the bug
    # blockers and let FLUX use its photographic style.
    neg_parts = [
        "blurry, low quality, distorted, melted, watermark",
        "cartoon, sketch, drawing, illustration, line drawing, pencil, painting",
        "small house, suburban villa, low-rise, isolated building",
        "medieval, castle, manor, fantasy, ruins, old stone, weathered, ivy-covered",
        "thatched roof, gothic, arched windows, chimney stack",
        "shop, store, storefront, supermarket, commercial, arcade, mall, shopping centre",
        "ground floor shops, retail windows, signage, neon sign, advertising",
        "glass curtain wall, full-height windows, glazed ground floor, ground floor glazing",
        "pilotis, raised on stilts, building on columns, elevated walkway, underpass",
        # ── Foreground bug killers (the recurring failures we've seen) ──
        "aerial cityscape miniature, panoramic city below, faraway city view, distant skyline below, "
        "miniature city, scaled-down town, model town, sprawling cityscape under building",
        "panoramic horizon, mountain backdrop, valley below, ocean horizon, sea horizon, "
        "wide vista from a hilltop, hill view, viewpoint over a town",
        "lake, lakeshore, pond, swimming pool, infinity pool, water surface in foreground, "
        "reflective pool, ocean in foreground, beach, harbour, marina",
        "water reflection, mirror surface, wet pavement, puddle, glossy floor, glassy ground",
        "parking lot, parking space, car park, empty pavement, parking stripes, parking lines",
        "white painted parking markings on the ground, parking bays, parking grid",
        "underground parking entrance, basement parking, car ramp, garage door",
        "tile flooring, polished marble floor, marble dalles, ceramic tiles, "
        "checker pattern ground, paved tile pattern, granite slab pattern",
        "ground cracks, mud cracks, dried earth pattern, drought cracks, scratch lines on ground",
        "mountain, hills, mountain range, valley, cliff, alpine scenery, ski resort",
        "brutalist, soviet block, concrete bunker, post-war housing project, dystopian",
        "dotted sky, mottled sky, mosaic sky, pixelated sky, posterised, inverted sky reflection",
        "tabletop model, scale model, miniature architectural model, dollhouse, diorama, "
        "model on a podium, building on a plinth, model display",
        # ── iter #300 : kill green orb / lamppost-hallucination ghosts ──
        "green glowing orb, green floating sphere, neon green blob, glowing green ball, "
        "fluorescent green object, mint green orb, abstract green shape, green ghost, "
        "ufo, alien object, sci-fi glowing element, balloon, balloon-shape obstacle",
        # ── Flying-building / floating bug ──
        "building floating in mid-air, levitating building, suspended building, building in clouds, "
        "building seen from a helicopter, drone view of city below, city seen below the building, "
        "ground falling away beneath the building, flying over a town, "
        "building hovering above a town, top-down city pattern beneath the architecture",
        # ── Missing parcel separation : DISABLED ──
        # The phrase "asphalt road touching the building wall" was interpreted
        # by FLUX as "no road near the building at all" → it painted sky in
        # the foreground rather than a real street. We rely on the bahut+grille
        # mesh to enforce the setback in the depth, not on a negative.
        # "building flush with the public sidewalk, ...",
    ]
    bm_toit = (bm_payload.get("model_json", bm_payload)
               .get("envelope", {}).get("toiture", {}).get("type"))
    if bm_toit == "terrasse":
        neg_parts.append("mansard roof, sloped roof, tiled roof")
    return prompt, prompt_2, ", ".join(neg_parts)


def synthesize_from_reasoning(
    reasoning: ArchReasoning, preset: str, extra: str = "", target: str = "sd15"
) -> tuple[str, str]:
    """Render an already-built reasoning into a prompt.

    Useful when the caller wants to inspect the reasoning before the render.
    """
    framing = _FRAMING.get(preset, "architectural perspective view")
    height = reasoning.choices["height"].chosen
    toiture = reasoning.choices["toiture"].chosen
    context = reasoning.choices["context"].chosen
    facade_phrase = (
        reasoning.facade.to_prompt_phrase(max_zones=3, max_accents=2)
        if reasoning.facade else ""
    )

    trend_ids = set(reasoning.trends_applied)
    trend_cues = [t.prompt_cue for t in CURRENT_TRENDS if t.id in trend_ids]
    extra_trends = _select_non_redundant_trend_cues(
        trend_cues, [facade_phrase, toiture, context]
    )
    emit_toiture = toiture and "rooftop garden" not in facade_phrase.lower()

    if target == "sdxl":
        # SDXL-tuned ordering :
        #   1. Photoreal anchor + material-first description (SDXL responds
        #      strongly to "photorealistic … in <material>")
        #   2. English storey notation (R+5 → 6-storey)
        #   3. Composition + context at end
        #   4. No archfr_idf_modern trigger (LoRA is SD-1.5-only)
        en_height = _height_to_english(height)
        parts = [
            "photorealistic French residential apartment building",
            facade_phrase,                       # materials first — strongest weight
            en_height,                           # "6-storey"
            framing,                             # camera POV
            toiture if emit_toiture else "",
            context,
        ]
        parts.extend(extra_trends)
        parts.append("magazine architectural photography, golden hour, 8k")
    else:
        parts = [
            LORA_TRIGGER,
            height,
            framing,
            facade_phrase,
            toiture if emit_toiture else "",
            context,
        ]
        parts.extend(extra_trends)
        parts.append("architectural photography, photorealistic, 8k")

    if extra:
        parts.append(extra)

    prompt = ", ".join(p for p in parts if p)

    # Negative prompt — block the failure modes we observed.
    neg_parts = [
        "blurry, low quality, distorted, warped, melted, oversaturated",
        "fantasy, cartoon, sketch, drawing, render artifacts",
        "watermark, text, signature, ugly, wrong proportions",
        "small house, suburban villa, low-rise, isolated building, minimalist showroom",
    ]
    # Forbid roof types that don't match the BM's choice.
    bm_toit_type = (
        reasoning.bm_payload.get("model_json", reasoning.bm_payload)
        .get("envelope", {}).get("toiture", {}).get("type")
    )
    if bm_toit_type == "terrasse":
        neg_parts.append("mansard roof, sloped roof, tiled roof")
    elif bm_toit_type in ("mansard", "deux_pans", "tuile_plate"):
        neg_parts.append("flat roof")
    negative = ", ".join(neg_parts)

    return prompt, negative


def _height_to_english(height_phrase: str) -> str:
    """Translate French R+N notation to English 'X-storey'.

    "R+5 apartment building" → "6-storey apartment building"
    """
    import re
    m = re.match(r"R\+(\d+)\s+(.*)", height_phrase)
    if m:
        n = int(m.group(1)) + 1   # R+0 = 1 storey
        rest = m.group(2)
        return f"{n}-storey {rest}"
    return height_phrase


def _select_non_redundant_trend_cues(
    trend_cues: list[str], existing_text: list[str]
) -> list[str]:
    """Drop trend cues whose salient noun already appears in the choices.

    The reasoner per-element choices already encode most trend signal. We only
    keep trends that introduce a NEW noun (e.g. "wood cladding" if no wood
    mentioned yet, "shop windows" if RDC is residential). Saves ~30 tokens.
    """
    existing_lower = " ".join(existing_text).lower()
    SALIENT_NOUNS = [
        "balcon", "balcony", "facade", "rooftop", "terrasse", "wood",
        "cladding", "stone", "glass", "shop", "commercial", "entrance",
        "tree", "brick", "mansard", "zinc", "tile",
    ]
    keep = []
    for cue in trend_cues:
        cue_lower = cue.lower()
        # Drop if any salient noun in the trend cue is already mentioned.
        is_redundant = False
        for noun in SALIENT_NOUNS:
            if noun in cue_lower and noun in existing_lower:
                is_redundant = True
                break
        if not is_redundant:
            keep.append(cue)
    return keep
