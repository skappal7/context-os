from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from contextos.classifier import Heat, Tagged
from contextos.classifier.rules import _fingerprint as fingerprint_msg


def cold_run_id(fingerprints: list[str]) -> str:
    """Stable hash over an ordered set of message fingerprints. Lets the same
    contiguous COLD block recur across requests without regenerating its summary."""
    h = hashlib.sha256()
    for fp in fingerprints:
        h.update(fp.encode())
        h.update(b"\x1f")
    return h.hexdigest()[:32]


def cold_runs(tagged: list[Tagged]) -> list[tuple[str, list[Tagged]]]:
    """Return [(run_id, [tagged...])] for each contiguous COLD run."""
    out: list[tuple[str, list[Tagged]]] = []
    current: list[Tagged] = []
    for t in tagged:
        if t.heat is Heat.COLD:
            current.append(t)
            continue
        if current:
            out.append((cold_run_id([fingerprint_msg(c.message) for c in current]), current))
            current = []
    if current:
        out.append((cold_run_id([fingerprint_msg(c.message) for c in current]), current))
    return out


@dataclass
class SessionState:
    summaries: dict[str, str] = field(default_factory=dict)   # run_id -> summary
    pending_recalls: list[str] = field(default_factory=list)  # one-turn injection queue


class SessionMemory:
    """In-process per-session state. Single-writer (proxy daemon)."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        return self._sessions.setdefault(session_id, SessionState())

    def put_summary(self, session_id: str, run_id: str, summary: str) -> None:
        self.get(session_id).summaries[run_id] = summary

    def pop_recalls(self, session_id: str) -> list[str]:
        s = self.get(session_id)
        items, s.pending_recalls = s.pending_recalls, []
        return items

    def push_recall(self, session_id: str, content: str) -> None:
        self.get(session_id).pending_recalls.append(content)
