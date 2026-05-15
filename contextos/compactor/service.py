from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from contextos.archive import ArchiveStore
from contextos.compactor.prompt import build_summary_prompt
from contextos.llm import Embedder, Generator, LLMUnavailable
from contextos.proxy.payload import stringify_content
from contextos.session_memory import SessionMemory
from contextos.settings import Settings

log = logging.getLogger("contextos.compactor")


@dataclass(slots=True)
class CompactionJob:
    session_id: str
    run_id: str
    messages: list[dict]


def _render_transcript(messages: list[dict]) -> str:
    parts: list[str] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = stringify_content(m.get("content", "")).strip()
        if content:
            parts.append(f"{role.upper()}: {content}")
    return "\n\n".join(parts)


class CompactorService:
    """Async, fire-and-forget compaction worker. Never blocks the proxy hot path."""

    def __init__(
        self,
        settings: Settings,
        generator: Generator,
        embedder: Embedder,
        archive: ArchiveStore,
        memory: SessionMemory,
    ) -> None:
        self._settings = settings
        self._generator = generator
        self._embedder = embedder
        self._archive = archive
        self._memory = memory
        self._queue: asyncio.Queue[CompactionJob] = asyncio.Queue(maxsize=128)
        self._task: asyncio.Task | None = None
        self._seen_runs: set[tuple[str, str]] = set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker(), name="contextos-compactor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def submit(self, job: CompactionJob) -> bool:
        key = (job.session_id, job.run_id)
        if key in self._seen_runs:
            return False
        if job.run_id in self._memory.get(job.session_id).summaries:
            return False
        try:
            self._queue.put_nowait(job)
            self._seen_runs.add(key)
            return True
        except asyncio.QueueFull:
            log.warning("compactor queue full; dropping job for %s", job.session_id)
            return False

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._process(job)
            except Exception as e:
                log.warning("compaction failed for %s/%s: %s",
                            job.session_id, job.run_id, e)
            finally:
                self._queue.task_done()

    async def _process(self, job: CompactionJob) -> None:
        transcript = _render_transcript(job.messages)
        if not transcript:
            return
        try:
            summary = await self._generator.generate(
                build_summary_prompt(transcript),
                max_tokens=self._settings.llm_max_tokens,
            )
        except LLMUnavailable as e:
            log.info("generator unavailable, skipping compaction: %s", e)
            return
        if not summary:
            return

        self._memory.put_summary(job.session_id, job.run_id, summary)

        for m in job.messages:
            content = stringify_content(m.get("content", "")).strip()
            if not content:
                continue
            try:
                vec = await self._embedder.embed(content)
            except LLMUnavailable:
                continue
            if len(vec) != self._settings.embedding_dim:
                log.warning("embedding dim %d != expected %d; skipping archive",
                            len(vec), self._settings.embedding_dim)
                continue
            try:
                await self._archive.add(job.session_id, content, summary, vec)
            except Exception as e:
                log.warning("archive add failed: %s", e)
