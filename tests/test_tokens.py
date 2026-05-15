from __future__ import annotations

from contextos.pricing import savings_usd
from contextos.tokens import count_message_tokens, count_tokens


def test_count_tokens_nonempty() -> None:
    assert count_tokens("hello world") > 0
    assert count_tokens("") == 0


def test_count_message_tokens_grows_with_size() -> None:
    small = [{"role": "user", "content": "hi"}]
    big = [{"role": "user", "content": "hi " * 200}]
    assert count_message_tokens(big) > count_message_tokens(small)


def test_savings_known_model() -> None:
    assert savings_usd("claude-opus-4-7", 1_000_000) == 15.0


def test_savings_unknown_model_zero() -> None:
    assert savings_usd("mystery-model", 1_000_000) == 0.0
