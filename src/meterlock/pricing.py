"""Global Standard text pricing, verified in OpenAI Docs 2026-10-17.

See MODEL_SUPPORT.md for sources and qualification limits. Amounts are integer
nanodollars; model aliases and pricing must be rechecked before each release.
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Pricing:
    short_input_nd: int
    short_cached_input_nd: int
    short_cache_write_nd: int
    short_output_nd: int
    long_input_nd: int
    long_cached_input_nd: int
    long_cache_write_nd: int
    long_output_nd: int
    long_context_threshold: int = 272_000


LUNA = Pricing(200, 20, 250, 1_200, 400, 40, 500, 1_800)
MODEL_PRICING = MappingProxyType({
    "gpt-5.6-luna": LUNA,
    "gpt-6-luna": Pricing(100, 10, 125, 500, 200, 20, 250, 750),
    "gpt-6-sol": Pricing(2_000, 200, 2_500, 10_000, 4_000, 400, 5_000, 15_000),
})


def token_count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def reservation_cost_nd(
    input_upper_bound: int, max_output_tokens: int, *, model: str = "gpt-5.6-luna"
) -> int:
    """Assume every input token is a long-context cache write (highest rate)."""
    pricing = MODEL_PRICING[model]
    inputs = token_count(input_upper_bound, "input_upper_bound")
    outputs = token_count(max_output_tokens, "max_output_tokens")
    return inputs * pricing.long_cache_write_nd + outputs * pricing.long_output_nd


def actual_cost_nd(usage: dict[str, Any], *, model: str = "gpt-5.6-luna") -> int:
    pricing = MODEL_PRICING[model]
    inputs = token_count(usage["input_tokens"], "input_tokens")
    outputs = token_count(usage["output_tokens"], "output_tokens")
    details = usage.get("input_tokens_details")
    if not isinstance(details, dict):
        raise ValueError("input_tokens_details must be an object")
    cached = token_count(details.get("cached_tokens"), "cached_tokens")
    written = token_count(details.get("cache_write_tokens"), "cache_write_tokens")
    if cached + written > inputs:
        raise ValueError("cached and cache-write tokens exceed input_tokens")
    ordinary = inputs - cached - written
    if inputs > pricing.long_context_threshold:
        return (ordinary * pricing.long_input_nd
                + cached * pricing.long_cached_input_nd
                + written * pricing.long_cache_write_nd
                + outputs * pricing.long_output_nd)
    return (ordinary * pricing.short_input_nd
            + cached * pricing.short_cached_input_nd
            + written * pricing.short_cache_write_nd
            + outputs * pricing.short_output_nd)
