"""Unit tests for protocol-awareness: tool_use linkage, cache_control pinning,
fail-closed validator. These lock in the fix for the Claude Code freeze.
"""
from __future__ import annotations

from contextos.classifier import Heat, classify
from contextos.safety import (
    collect_tool_result_refs,
    collect_tool_use_ids,
    pin_critical,
    protocol_critical_indices,
    validate_payload,
)


def _tool_use(id_: str, name: str = "read") -> dict:
    return {"role": "assistant",
            "content": [{"type": "tool_use", "id": id_, "name": name, "input": {}}]}


def _tool_result(id_: str, content: str = "ok") -> dict:
    return {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": id_, "content": content}]}


def _text(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _block(role: str, text: str, *, cache: bool = False) -> dict:
    block: dict = {"type": "text", "text": text}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return {"role": role, "content": [block]}


# ---------- collection helpers ----------

def test_collect_tool_use_ids() -> None:
    msgs = [_tool_use("a1"), _tool_result("a1"), _tool_use("a2"), _text("user", "hi")]
    assert collect_tool_use_ids(msgs) == {"a1", "a2"}


def test_collect_tool_result_refs() -> None:
    msgs = [_tool_use("a1"), _tool_result("a1"), _tool_result("a99")]
    assert collect_tool_result_refs(msgs) == {"a1", "a99"}


# ---------- protocol_critical_indices ----------

def test_critical_pins_tool_use_referenced_by_tool_result() -> None:
    msgs = [
        _text("user", "do thing"),       # 0
        _tool_use("a1"),                  # 1 — must survive
        _tool_result("a1"),               # 2 — must survive (always)
        _text("assistant", "done"),       # 3
    ]
    assert protocol_critical_indices(msgs) == {1, 2}


def test_critical_pins_cache_control() -> None:
    msgs = [_text("user", "warmup"), _block("user", "anchor", cache=True)]
    assert protocol_critical_indices(msgs) == {1}


def test_critical_ignores_orphan_tool_use() -> None:
    # tool_use with no matching tool_result is NOT critical (nothing references it)
    msgs = [_tool_use("a1"), _text("user", "next")]
    assert protocol_critical_indices(msgs) == set()


# ---------- pin_critical mutates heat ----------

def test_pin_critical_upgrades_to_hot() -> None:
    # Build 20 msgs where a tool_use/tool_result pair sits at the *start* (would be COLD).
    msgs = [_tool_use("toolu_old"), _tool_result("toolu_old")]
    for i in range(20):
        msgs.append(_text("user" if i % 2 == 0 else "assistant", f"turn-{i}"))
    tagged = classify(msgs)
    assert tagged[0].heat is Heat.COLD
    assert tagged[1].heat is Heat.COLD
    pin_critical(tagged, msgs)
    assert tagged[0].heat is Heat.HOT
    assert tagged[1].heat is Heat.HOT


# ---------- validate_payload ----------

def test_validate_accepts_clean_payload() -> None:
    body = {"messages": [_text("user", "hi"), _text("assistant", "hello")]}
    ok, reason = validate_payload(body)
    assert ok, reason


def test_validate_rejects_empty() -> None:
    ok, reason = validate_payload({"messages": []})
    assert not ok
    assert "no messages" in reason


def test_validate_rejects_assistant_first() -> None:
    body = {"messages": [_text("assistant", "hi")]}
    ok, reason = validate_payload(body)
    assert not ok
    assert "first message role" in reason


def test_validate_rejects_orphan_tool_result() -> None:
    # The classic Claude Code breakage: tool_result without surviving tool_use.
    body = {"messages": [_text("user", "ctx"), _tool_result("toolu_missing")]}
    ok, reason = validate_payload(body)
    assert not ok
    assert "orphan" in reason
