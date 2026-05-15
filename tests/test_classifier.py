from __future__ import annotations

from contextos.classifier import Heat, classify
from contextos.classifier.rules import HOT_WINDOW, WARM_WINDOW


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def test_last_n_are_hot() -> None:
    msgs = [_msg("user", f"q{i}") for i in range(10)]
    tagged = classify(msgs)
    assert [t.heat for t in tagged[-HOT_WINDOW:]] == [Heat.HOT] * HOT_WINDOW


def test_dead_dedup() -> None:
    msgs = [_msg("user", "same"), _msg("assistant", "ok"), _msg("user", "same")]
    tagged = classify(msgs)
    # First "same" is HOT (last-5 window), duplicate (also in window) is DEAD.
    assert tagged[2].heat is Heat.DEAD


def test_empty_content_is_dead() -> None:
    tagged = classify([_msg("user", "")])
    assert tagged[0].heat is Heat.DEAD


def test_cold_beyond_warm_window() -> None:
    msgs = [_msg("user", f"q{i}") for i in range(WARM_WINDOW + 5)]
    tagged = classify(msgs)
    # First message is now WARM_WINDOW+4 from end -> COLD.
    assert tagged[0].heat is Heat.COLD


def test_warm_band() -> None:
    msgs = [_msg("user", f"q{i}") for i in range(WARM_WINDOW)]
    tagged = classify(msgs)
    # message at distance HOT_WINDOW from end -> WARM
    assert tagged[WARM_WINDOW - HOT_WINDOW - 1].heat is Heat.WARM
