from __future__ import annotations

from typing import Any

from contextos.classifier import Heat, Tagged
from contextos.classifier.rules import _fingerprint as fingerprint_msg
from contextos.session_memory import cold_run_id

_PLACEHOLDER_TEMPLATE = "[ContextOS: {n} earlier turn(s) elided — pending compaction]"
_SUMMARY_TEMPLATE = "[ContextOS summary of {n} earlier turn(s)]\n{summary}"


def _summary_message(n: int, summary: str) -> dict[str, Any]:
    return {"role": "user", "content": _SUMMARY_TEMPLATE.format(n=n, summary=summary)}


def _placeholder_message(n: int) -> dict[str, Any]:
    return {"role": "user", "content": _PLACEHOLDER_TEMPLATE.format(n=n)}


def rebuild_messages(
    tagged: list[Tagged],
    summaries: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Drop DEAD, collapse contiguous COLD runs (summary if available, else placeholder),
    keep HOT/WARM. Pure function. Does not mutate inputs."""
    summaries = summaries or {}
    out: list[dict[str, Any]] = []
    cold: list[Tagged] = []

    def flush_cold() -> None:
        if not cold:
            return
        run_id = cold_run_id([fingerprint_msg(c.message) for c in cold])
        summary = summaries.get(run_id)
        out.append(_summary_message(len(cold), summary) if summary
                   else _placeholder_message(len(cold)))
        cold.clear()

    for t in tagged:
        if t.heat is Heat.DEAD:
            continue
        if t.heat is Heat.COLD:
            cold.append(t)
            continue
        flush_cold()
        out.append(t.message)
    flush_cold()
    return out
