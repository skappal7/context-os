from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol

from fastapi.concurrency import run_in_threadpool

from contextos.llm.download import ensure_gguf

log = logging.getLogger("contextos.llm.generator")


class LLMUnavailable(Exception):
    """The local model couldn't be loaded or invoked. Callers should degrade."""


class Generator(Protocol):
    async def generate(self, prompt: str, max_tokens: int = 512) -> str: ...
    async def aclose(self) -> None: ...


class LlamaCppGenerator:
    """Lazy-loaded llama-cpp wrapper. The model is downloaded and loaded on the
    first generate() call so daemon startup stays fast and idle RAM stays low."""

    def __init__(
        self,
        repo_id: str,
        filename: str,
        model_dir: Path,
        n_ctx: int = 4096,
        n_threads: int | None = None,
    ) -> None:
        self._repo_id = repo_id
        self._filename = filename
        self._model_dir = model_dir
        self._n_ctx = n_ctx
        self._n_threads = n_threads
        self._llm = None  # lazy
        self._load_lock = threading.Lock()
        self._load_failed = False

    def _ensure_loaded(self) -> None:
        if self._llm is not None or self._load_failed:
            return
        with self._load_lock:
            if self._llm is not None or self._load_failed:
                return
            try:
                from llama_cpp import Llama
                path = ensure_gguf(self._repo_id, self._filename, self._model_dir)
                self._llm = Llama(
                    model_path=str(path),
                    n_ctx=self._n_ctx,
                    n_threads=self._n_threads,
                    verbose=False,
                )
                log.info("loaded %s (%d ctx)", path.name, self._n_ctx)
            except Exception as e:
                self._load_failed = True
                raise LLMUnavailable(str(e)) from e

    def _infer(self, prompt: str, max_tokens: int) -> str:
        self._ensure_loaded()
        assert self._llm is not None
        try:
            # Use the chat-completion API so the model's instruction template
            # (e.g. Qwen <|im_start|>/<|im_end|>) is applied and EOS is honored.
            out = self._llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return str(out["choices"][0]["message"]["content"]).strip()
        except Exception as e:
            raise LLMUnavailable(str(e)) from e

    async def generate(self, prompt: str, max_tokens: int = 512) -> str:
        try:
            return await run_in_threadpool(self._infer, prompt, max_tokens)
        except LLMUnavailable:
            raise
        except Exception as e:
            raise LLMUnavailable(str(e)) from e

    async def aclose(self) -> None:
        # llama-cpp owns its own memory; closing the Llama object releases it.
        self._llm = None
