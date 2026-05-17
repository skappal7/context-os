from __future__ import annotations

import hashlib
import json
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
    content = msg.get("content", "")
    # Structured content (Anthropic tool_use/tool_result blocks) must be
    # fingerprinted by shape — stringify_content returns "" for tool_use blocks,
    # which would collapse them to DEAD and break the protocol.
    if isinstance(content, list):
        body = json.dumps(content, sort_keys=True, default=str)
    else:
        body = stringify_content(content).strip()
    return hashlib.sha256(f"{role}\x1f{body}".encode()).hexdigest()


def _is_empty(content: Any) -> bool:
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        return len(content) == 0
    return content is None


def classify(messages: list[dict[str, Any]]) -> list[Tagged]:
    """Tag each message in-order. Pure function — no I/O, no side effects."""
    n = len(messages)
    tagged: list[Tagged] = []
    seen: set[str] = set()

    for i, m in enumerate(messages):
        from_end = n - 1 - i
        fp = _fingerprint(m)

        # DEAD: byte-identical earlier message, or empty content.
        if _is_empty(m.get("content", "")) or fp in seen:
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
