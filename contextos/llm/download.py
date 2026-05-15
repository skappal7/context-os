from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("contextos.llm.download")


def ensure_gguf(repo_id: str, filename: str, dest_dir: Path) -> Path:
    """Download a single GGUF file to dest_dir if not already cached. Returns the
    local path. Network failures bubble up — the caller decides whether to degrade."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = dest_dir / filename
    if local.exists():
        return local

    from huggingface_hub import hf_hub_download

    log.info("downloading %s/%s to %s (first run only)", repo_id, filename, dest_dir)
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(dest_dir),
    )
    return Path(path)
