from __future__ import annotations

# USD per 1M input tokens. Conservative public list prices as of late 2025.
# Match by longest prefix; unknown models priced at 0 (we'd rather under-report than lie).
_PRICES_PER_M: dict[str, float] = {
    "claude-opus-4": 15.0,
    "claude-sonnet-4": 3.0,
    "claude-haiku-4": 0.80,
    "claude-3-5-sonnet": 3.0,
    "claude-3-5-haiku": 0.80,
    "gpt-4o-mini": 0.15,
    "gpt-4o": 2.50,
    "gpt-4.1": 2.00,
    "o1": 15.0,
    "o3": 2.00,
}


def input_price_per_token(model: str | None) -> float:
    if not model:
        return 0.0
    matches = [p for p in _PRICES_PER_M if model.startswith(p)]
    if not matches:
        return 0.0
    best = max(matches, key=len)
    return _PRICES_PER_M[best] / 1_000_000.0


def savings_usd(model: str | None, tokens_saved: int) -> float:
    return max(0, tokens_saved) * input_price_per_token(model)
