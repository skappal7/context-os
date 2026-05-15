from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol

from fastapi.concurrency import run_in_threadpool

from contextos.llm.generator import LLMUnavailable  # shared exception type

log = logging.getLogger("contextos.llm.embedder")


class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def aclose(self) -> None: ...


class FastEmbedEmbedder:
    """Lazy-loaded fastembed wrapper. bge-small-en-v1.5 = 384-dim, ~30 MB ONNX,
    pure CPU. First embed() call downloads the model to model_dir."""

    def __init__(self, model_name: str, model_dir: Path) -> None:
        self._model_name = model_name
        self._model_dir = model_dir
        self._model = None
        self._load_lock = threading.Lock()
        self._load_failed = False

    def _ensure_loaded(self) -> None:
        if self._model is not None or self._load_failed:
            return
        with self._load_lock:
            if self._model is not None or self._load_failed:
                return
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(
                    model_name=self._model_name, cache_dir=str(self._model_dir),
                )
                log.info("loaded embedder %s", self._model_name)
            except Exception as e:
                self._load_failed = True
                raise LLMUnavailable(str(e)) from e

    def _infer(self, text: str) -> list[float]:
        self._ensure_loaded()
        assert self._model is not None
        try:
            vec = next(iter(self._model.embed([text])))
            return [float(x) for x in vec]
        except Exception as e:
            raise LLMUnavailable(str(e)) from e

    async def embed(self, text: str) -> list[float]:
        try:
            return await run_in_threadpool(self._infer, text)
        except LLMUnavailable:
            raise
        except Exception as e:
            raise LLMUnavailable(str(e)) from e

    async def aclose(self) -> None:
        self._model = None
