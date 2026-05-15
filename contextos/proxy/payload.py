from __future__ import annotations

from typing import Any


# Naive token estimator: 1 token ~= 4 chars. Real tokenization comes later.
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def extract_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return message-like records for both Anthropic and OpenAI request bodies."""
    msgs = body.get("messages")
    if isinstance(msgs, list):
        return msgs
    return []


def stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    parts.append(str(block["text"]))
                elif "content" in block:
                    parts.append(stringify_content(block["content"]))
        return "\n".join(parts)
    return ""


def detect_model(body: dict[str, Any]) -> str | None:
    m = body.get("model")
    return m if isinstance(m, str) else None
