from __future__ import annotations

import logging
import re

from contextos.archive import ArchiveStore
from contextos.llm import Embedder, LLMUnavailable
from contextos.settings import Settings

log = logging.getLogger("contextos.retrieval")

_TRIGGERS = [
    r"\bas we (?:discussed|established|decided)\b",
    r"\bthe previous implementation\b",
    r"\breferring back to\b",
    r"\bthe schema we defined\b",
    r"\bthe (?:earlier|prior) (?:approach|design|decision)\b",
    r"\bwe (?:already|previously) (?:agreed|decided|noted)\b",
]
_TRIGGER_RE = re.compile("|".join(_TRIGGERS), re.IGNORECASE)


def detect_trigger(text: str) -> bool:
    if not text:
        return False
    return _TRIGGER_RE.search(text) is not None


async def recall_for(
    settings: Settings,
    embedder: Embedder,
    archive: ArchiveStore,
    session_id: str,
    query_text: str,
) -> str | None:
    if not query_text.strip():
        return None
    try:
        vec = await embedder.embed(query_text)
    except LLMUnavailable:
        return None
    if len(vec) != settings.embedding_dim:
        return None
    rows = await archive.search(session_id, vec, settings.retrieval_top_k)
    if not rows:
        return None
    blocks = [r.summary or r.content for r in rows]
    body = "\n---\n".join(b.strip() for b in blocks if b)
    return f"[RECALLED CONTEXT]\n{body}\n[/RECALLED CONTEXT]" if body else None
