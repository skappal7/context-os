from __future__ import annotations

from contextos.classifier import Heat, Tagged
from contextos.session_memory import SessionMemory, cold_run_id, cold_runs


def _t(i: int, heat: Heat, c: str) -> Tagged:
    return Tagged(i, {"role": "user", "content": c}, heat)


def test_cold_run_id_is_stable() -> None:
    a = cold_run_id(["fp1", "fp2", "fp3"])
    b = cold_run_id(["fp1", "fp2", "fp3"])
    assert a == b
    assert a != cold_run_id(["fp1", "fp2"])


def test_cold_runs_splits_on_non_cold() -> None:
    tagged = [
        _t(0, Heat.COLD, "a"), _t(1, Heat.COLD, "b"),
        _t(2, Heat.WARM, "w"),
        _t(3, Heat.COLD, "c"),
    ]
    runs = cold_runs(tagged)
    assert len(runs) == 2
    assert [t.message["content"] for t in runs[0][1]] == ["a", "b"]
    assert [t.message["content"] for t in runs[1][1]] == ["c"]


def test_session_memory_summary_and_recall() -> None:
    m = SessionMemory()
    m.put_summary("s1", "run-x", "S")
    assert m.get("s1").summaries["run-x"] == "S"
    m.push_recall("s1", "[RECALLED] foo")
    assert m.pop_recalls("s1") == ["[RECALLED] foo"]
    assert m.pop_recalls("s1") == []
