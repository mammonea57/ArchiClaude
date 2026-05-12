"""Prompt templates for architectural rendering.

The structure : per camera preset we define a tailored prompt template that
emphasises what should be visible. Style cues (materials, lighting, mood)
are shared at the bottom.

Day 3 baseline. Will be tuned with user-supplied reference images later.
"""
from __future__ import annotations

# Trigger word for the archfr_idf_modern LoRA fine-tuned on 23 IDF reference
# renders. Always prepend so the model leans on the LoRA-learned style.
LORA_TRIGGER = "archfr_idf_modern"

# Shared architectural style cues — drives the photorealistic look.
STYLE_BASE = (
    f"{LORA_TRIGGER}, modern French residential building, contemporary IDF Paris suburbs architecture, "
    "L-shaped footprint, brick terra-cotta vertical accent tower, white render facade, "
    "wood cladding top floor attic, large floor-to-ceiling glass balcony doors, "
    "glass railings with black aluminum frames, ground floor with concrete commercial base, "
    "professional architectural photography, golden hour soft natural light, "
    "shallow depth of field, high detail, photorealistic, 8k, magazine quality"
)

NEGATIVE_BASE = (
    "blurry, low quality, distorted, warped, oversaturated, fantasy, cartoon, sketch, drawing, "
    "render artifacts, watermark, text, signature, ugly, disfigured, low contrast"
)

# Per-preset prompt prefix — describes the camera angle + subject focus.
PER_PRESET: dict[str, str] = {
    "oiseau_iso": (
        "aerial 3/4 view from above, bird's eye perspective showing the L-shape building "
        "footprint clearly, surrounded by Paris suburb urban context, Haussmannian neighbours visible, "
        "trees, sidewalks, parked cars"
    ),
    "rue_est_proche": (
        "close-up street-level photo from the main avenue, pedestrian eye level, "
        "the building's main facade with brick entrance volume tower visible, "
        "trees lining the sidewalk"
    ),
    "rue_est_eloignee": (
        "street view from the opposite sidewalk, full building visible, "
        "main facade with brick entrance tower, balconies, urban context with neighbours, "
        "parked cars, pedestrians"
    ),
    "rue_sud": (
        "secondary street view from the south, building corner visible, "
        "secondary brick accent on south facade, balconies, sidewalk, trees"
    ),
    "ensemble_recule": (
        "wide angle architectural shot of the entire building, full block context visible, "
        "neighbouring buildings, urban setting Paris suburbs, "
        "L-shape volume readable, all materials visible"
    ),
    "angle_3_4": (
        "classic three-quarter architectural photography angle, "
        "two facades visible at once, brick tower entrance prominent, "
        "balconies and glass railings, urban context"
    ),
    "entree_zoom": (
        "close-up of the building entrance, brick volume tower with glass entrance door, "
        "stone canopy above, ENTRÉE signage, sidewalk in foreground"
    ),
}


def build_prompt(preset: str, extra: str = "") -> tuple[str, str]:
    """Compose the (positive, negative) prompts for a given camera preset."""
    head = PER_PRESET.get(preset, "architectural photo of a residential building")
    parts = [head, STYLE_BASE]
    if extra:
        parts.append(extra)
    return ", ".join(parts), NEGATIVE_BASE
