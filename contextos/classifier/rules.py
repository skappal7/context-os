from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from contextos.proxy.payload import stringify_content

HOT_WINDOW = 5     # last N turns always HOT
WARM_WINDOW = 15   # turns within this distance from end stay WARM (else COLD)


class Heat(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    DEAD = "DEAD"


@dataclass(slots=True)
class Tagged:
    index: int
    message: dict[str, Any]
    heat: Heat


def _fingerprint(msg: dict[str, Any]) -> str:
    role = str(msg.get("role", ""))
    content = stringify_content(msg.get("content", "")).strip()
    return hashlib.sha256(f"{role}\x1f{content}".encode()).hexdigest()


def classify(messages: list[dict[str, Any]]) -> list[Tagged]:
    """Tag each message in-order. Pure function — no I/O, no side effects."""
    n = len(messages)
    tagged: list[Tagged] = []
    seen: set[str] = set()

    for i, m in enumerate(messages):
        from_end = n - 1 - i
        fp = _fingerprint(m)
        content = stringify_content(m.get("content", "")).strip()

        # DEAD: byte-identical earlier message, or empty content.
        if not content or fp in seen:
            tagged.append(Tagged(i, m, Heat.DEAD))
            continue
        seen.add(fp)

        if from_end < HOT_WINDOW:
            heat = Heat.HOT
        elif from_end < WARM_WINDOW:
            heat = Heat.WARM
        else:
            heat = Heat.COLD
        tagged.append(Tagged(i, m, heat))

    return tagged
