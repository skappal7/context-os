from __future__ import annotations

import asyncio

import pytest

from contextos.archive import ArchiveStore
from contextos.compactor import CompactionJob, CompactorService
from contextos.session_memory import SessionMemory


class StubGenerator:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    async def generate(self, prompt: str, max_tokens: int = 512) -> str:
        self.calls += 1
        return self.response

    async def aclose(self) -> None:
        return None


class StubEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [0.1] * self.dim

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_compactor_writes_summary_and_archive(tmp_settings) -> None:
    archive = ArchiveStore(tmp_settings.archive_dir, tmp_settings.embedding_dim)
    memory = SessionMemory()
    gen = StubGenerator("This is the compacted summary.")
    emb = StubEmbedder(tmp_settings.embedding_dim)
    service = CompactorService(tmp_settings, gen, emb, archive, memory)
    service.start()
    try:
        job = CompactionJob(
            session_id="s1", run_id="run-1",
            messages=[
                {"role": "user", "content": "old turn one"},
                {"role": "assistant", "content": "old turn two"},
            ],
        )
        assert service.submit(job) is True
        assert service.submit(job) is False  # dedup

        await asyncio.wait_for(service._queue.join(), timeout=2.0)

        assert memory.get("s1").summaries["run-1"] == "This is the compacted summary."
        assert gen.calls == 1
        assert emb.calls == 2
        hits = await archive.search("s1", [0.1] * tmp_settings.embedding_dim, top_k=5)
        assert len(hits) == 2
    finally:
        await service.stop()
