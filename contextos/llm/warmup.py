from __future__ import annotations

import logging
from pathlib import Path

from contextos.settings import Settings

log = logging.getLogger("contextos.llm.warmup")


def warmup(settings: Settings, on_progress=None) -> dict[str, Path]:
    """Pre-download the generator GGUF and embedder ONNX into model_dir.

    Returns a dict of {label: local_path}. Raises on network or HF errors so the
    caller can decide whether to abort install or continue without models."""
    def _emit(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    out: dict[str, Path] = {}

    from contextos.llm.download import ensure_gguf
    _emit(f"downloading {settings.llm_filename} (~400 MB) ...")
    gguf_path = ensure_gguf(
        settings.llm_repo_id, settings.llm_filename, settings.model_dir,
    )
    out["generator"] = gguf_path
    _emit(f"  -> {gguf_path}")

    _emit(f"downloading embedder {settings.embedding_model} (~30 MB) ...")
    from fastembed import TextEmbedding
    TextEmbedding(model_name=settings.embedding_model, cache_dir=str(settings.model_dir))
    out["embedder"] = settings.model_dir
    _emit("  -> cached")

    return out
