from decimal import Decimal

import pytest

from api.middleware.cost_tracking import (
    MODEL_PRICING,
    AnthropicUsage,
    compute_cost_cents,
)


def test_cost_for_sonnet_4_6_standard_call() -> None:
    usage = AnthropicUsage(
        model="claude-sonnet-4-6",
        input_tokens=10_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1_500,
    )
    cost = compute_cost_cents(usage)
    assert cost == Decimal("5.2500")


def test_cost_for_haiku_4_5() -> None:
    usage = AnthropicUsage(
        model="claude-haiku-4-5-20251001",
        input_tokens=10_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1_500,
    )
    cost = compute_cost_cents(usage)
    assert cost == Decimal("1.7500")


def test_cost_with_cache_read_discount() -> None:
    usage = AnthropicUsage(
        model="claude-sonnet-4-6",
        input_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=100_000,
        output_tokens=500,
    )
    cost = compute_cost_cents(usage)
    assert cost == Decimal("3.7500")


def test_cost_with_cache_creation_premium() -> None:
    usage = AnthropicUsage(
        model="claude-sonnet-4-6",
        input_tokens=0,
        cache_creation_input_tokens=50_000,
        cache_read_input_tokens=0,
        output_tokens=0,
    )
    cost = compute_cost_cents(usage)
    assert cost == Decimal("18.7500")


def test_unknown_model_raises() -> None:
    usage = AnthropicUsage(
        model="claude-mystery-v99",
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=50,
    )
    with pytest.raises(ValueError, match="Unknown Anthropic model"):
        compute_cost_cents(usage)


def test_model_pricing_has_required_keys() -> None:
    for model, pricing in MODEL_PRICING.items():
        assert "input_per_mtok_usd" in pricing, model
        assert "output_per_mtok_usd" in pricing, model
        assert "cache_read_per_mtok_usd" in pricing, model
        assert "cache_creation_per_mtok_usd" in pricing, model


def test_extract_usage_no_cache_fields() -> None:
    from types import SimpleNamespace

    from api.middleware.cost_tracking import extract_usage_from_anthropic_message

    response = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=50))
    result = extract_usage_from_anthropic_message(response, "claude-sonnet-4-6")
    assert result == AnthropicUsage("claude-sonnet-4-6", 100, 0, 0, 50)


def test_extract_usage_with_cache_fields() -> None:
    from types import SimpleNamespace

    from api.middleware.cost_tracking import extract_usage_from_anthropic_message

    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=500,
            output_tokens=200,
            cache_creation_input_tokens=1000,
            cache_read_input_tokens=3000,
        )
    )
    result = extract_usage_from_anthropic_message(response, "claude-opus-4-6")
    assert result == AnthropicUsage("claude-opus-4-6", 500, 1000, 3000, 200)
