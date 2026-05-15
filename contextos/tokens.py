from __future__ import annotations

from functools import lru_cache

import tiktoken

# cl100k_base is a reasonable cross-vendor approximation. Anthropic doesn't ship a public
# tokenizer; OpenAI models use cl100k or o200k. We accept ~5% drift in counts — the
# *delta* between raw and sent payloads (savings %) is what matters, not absolute totals.
_ENCODING_NAME = "cl100k_base"


@lru_cache(maxsize=1)
def _enc() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_enc().encode(text, disallowed_special=()))


def count_message_tokens(messages: list[dict]) -> int:
    """Approximate token count over a messages array (Anthropic or OpenAI shape).

    Each message carries small structural overhead (role tag, separators). We add a
    flat 4 tokens per message as a proxy for those wrapper tokens — same convention
    OpenAI's cookbook uses.
    """
    from contextos.proxy.payload import stringify_content

    total = 0
    for m in messages:
        total += count_tokens(stringify_content(m.get("content", "")))
        total += count_tokens(str(m.get("role", "")))
        total += 4
    return total
