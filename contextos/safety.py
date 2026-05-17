"""Protocol-aware safety: tool-use linkage, cache_control pinning, payload validation.

The classifier doesn't know what an Anthropic `tool_use` or `tool_result` block
is — it just sees a message dict. If the rebuild drops the assistant turn that
contained a `tool_use`, any surviving `user` turn with a matching `tool_result`
will be rejected by Anthropic with a 400 ("orphan tool_use_id"), which is what
broke Claude Code last night.

This module is the seatbelt:
- ``protocol_critical_indices`` finds turns that MUST survive rebuild.
- ``pin_critical`` upgrades their heat to HOT so the rebuild keeps them.
- ``validate_payload`` is the post-rebuild guard. If it returns False, the caller
  forwards the ORIGINAL body untouched (fail-closed).
"""
from __future__ import annotations

from typing import Any


def is_structured(content: Any) -> bool:
    return isinstance(content, list)


def _iter_blocks(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict)]


def collect_tool_use_ids(messages: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for m in messages:
        for b in _iter_blocks(m.get("content")):
            if b.get("type") == "tool_use" and isinstance(b.get("id"), str):
                out.add(b["id"])
    return out


def collect_tool_result_refs(messages: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for m in messages:
        for b in _iter_blocks(m.get("content")):
            if b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                out.add(b["tool_use_id"])
    return out


def protocol_critical_indices(messages: list[dict[str, Any]]) -> set[int]:
    """Indices the pipeline is forbidden to drop.

    Includes:
    - any turn containing a ``tool_use`` block whose id is referenced by a
      surviving ``tool_result`` (drop it and Anthropic 400s).
    - any turn containing a ``tool_result`` block (the matching tool_use must
      also survive — we pin both ends).
    - any turn carrying a ``cache_control`` marker (cache anchors are
      index-sensitive; moving them silently breaks prompt caching).
    """
    refs_needed = collect_tool_result_refs(messages)
    crit: set[int] = set()
    for i, m in enumerate(messages):
        for b in _iter_blocks(m.get("content")):
            t = b.get("type")
            if t == "tool_use" and b.get("id") in refs_needed:
                crit.add(i)
                break
            if t == "tool_result":
                crit.add(i)
                break
            if isinstance(b.get("cache_control"), dict):
                crit.add(i)
                break
    return crit


def pin_critical(tagged: list[Any], messages: list[dict[str, Any]]) -> None:
    """Upgrade protocol-critical turns to HOT in place. Tagged.heat is mutable."""
    from contextos.classifier import Heat

    crit = protocol_critical_indices(messages)
    if not crit:
        return
    for t in tagged:
        if t.index in crit:
            t.heat = Heat.HOT


def validate_payload(body: dict[str, Any]) -> tuple[bool, str]:
    """Post-rebuild sanity check. Returns (ok, reason).

    Catches structural breaks that would cause Anthropic/OpenAI to 400:
    - empty messages array
    - first message role != user (Anthropic hard requirement)
    - tool_result referencing a tool_use_id that no longer exists
    """
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return False, "no messages"

    first_role = msgs[0].get("role")
    if first_role != "user":
        return False, f"first message role is {first_role!r}, must be 'user'"

    tool_use = collect_tool_use_ids(msgs)
    refs = collect_tool_result_refs(msgs)
    missing = refs - tool_use
    if missing:
        sample = sorted(missing)[:3]
        return False, f"orphan tool_result refs: {sample}"

    return True, ""
