from __future__ import annotations

from contextos.classifier import Heat, Tagged
from contextos.reconstructor import rebuild_messages


def _t(i: int, heat: Heat, content: str = "x") -> Tagged:
    return Tagged(i, {"role": "user", "content": content}, heat)


def test_dead_dropped_hot_kept() -> None:
    out = rebuild_messages([_t(0, Heat.HOT, "a"), _t(1, Heat.DEAD, "b"), _t(2, Heat.HOT, "c")])
    assert [m["content"] for m in out] == ["a", "c"]


def test_cold_run_collapses_to_one_placeholder() -> None:
    tagged = [_t(0, Heat.COLD), _t(1, Heat.COLD), _t(2, Heat.COLD), _t(3, Heat.HOT, "live")]
    out = rebuild_messages(tagged)
    assert len(out) == 2
    assert "3 earlier turn" in out[0]["content"]
    assert out[1]["content"] == "live"


def test_warm_preserved_inline() -> None:
    tagged = [_t(0, Heat.COLD), _t(1, Heat.WARM, "w"), _t(2, Heat.HOT, "h")]
    out = rebuild_messages(tagged)
    assert [m["content"] for m in out] == [
        out[0]["content"], "w", "h",
    ]
    assert "1 earlier turn" in out[0]["content"]


def test_trailing_cold_flushed() -> None:
    tagged = [_t(0, Heat.HOT, "h"), _t(1, Heat.COLD)]
    out = rebuild_messages(tagged)
    assert out[0]["content"] == "h"
    assert "1 earlier turn" in out[1]["content"]
