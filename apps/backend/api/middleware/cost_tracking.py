from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-opus-4-6": {
        "input_per_mtok_usd": Decimal("15"),
        "output_per_mtok_usd": Decimal("75"),
        "cache_read_per_mtok_usd": Decimal("1.50"),
        "cache_creation_per_mtok_usd": Decimal("18.75"),
    },
    "claude-sonnet-4-6": {
        "input_per_mtok_usd": Decimal("3"),
        "output_per_mtok_usd": Decimal("15"),
        "cache_read_per_mtok_usd": Decimal("0.30"),
        "cache_creation_per_mtok_usd": Decimal("3.75"),
    },
    "claude-haiku-4-5-20251001": {
        "input_per_mtok_usd": Decimal("1"),
        "output_per_mtok_usd": Decimal("5"),
        "cache_read_per_mtok_usd": Decimal("0.10"),
        "cache_creation_per_mtok_usd": Decimal("1.25"),
    },
}


@dataclass(frozen=True)
class AnthropicUsage:
    model: str
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int


def compute_cost_cents(usage: AnthropicUsage) -> Decimal:
    pricing = MODEL_PRICING.get(usage.model)
    if pricing is None:
        raise ValueError(f"Unknown Anthropic model: {usage.model}")

    cost_usd = (
        Decimal(usage.input_tokens) * pricing["input_per_mtok_usd"] / Decimal(1_000_000)
        + Decimal(usage.cache_creation_input_tokens)
        * pricing["cache_creation_per_mtok_usd"]
        / Decimal(1_000_000)
        + Decimal(usage.cache_read_input_tokens) * pricing["cache_read_per_mtok_usd"] / Decimal(1_000_000)
        + Decimal(usage.output_tokens) * pricing["output_per_mtok_usd"] / Decimal(1_000_000)
    )
    cost_cents = cost_usd * Decimal(100)
    return cost_cents.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def extract_usage_from_anthropic_message(response: Any, model: str) -> AnthropicUsage:
    u = response.usage
    return AnthropicUsage(
        model=model,
        input_tokens=int(u.input_tokens),
        cache_creation_input_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        cache_read_input_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
        output_tokens=int(u.output_tokens),
    )
