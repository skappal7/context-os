from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import lancedb
import pyarrow as pa
from fastapi.concurrency import run_in_threadpool

log = logging.getLogger("contextos.archive")

_TABLE = "turns"


@dataclass(slots=True)
class ArchivedRow:
    archive_id: str
    session_id: str
    content: str
    summary: str
    distance: float = 0.0


class ArchiveStore:
    """LanceDB-backed archive for compacted turns. Single table, vector column
    sized to settings.embedding_dim. All writes/reads off the event loop."""

    def __init__(self, archive_dir: Path, embedding_dim: int) -> None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        self._dim = embedding_dim
        self._db = lancedb.connect(str(archive_dir))
        self._ensure_table()

    def _ensure_table(self) -> None:
        if _TABLE in self._db.list_tables():
            self._tbl = self._db.open_table(_TABLE)
            return
        schema = pa.schema([
            pa.field("archive_id", pa.string()),
            pa.field("session_id", pa.string()),
            pa.field("content", pa.string()),
            pa.field("summary", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), self._dim)),
        ])
        self._tbl = self._db.create_table(_TABLE, schema=schema)

    async def add(self, session_id: str, content: str, summary: str,
                  vector: list[float]) -> str:
        archive_id = uuid.uuid4().hex
        row = [{
            "archive_id": archive_id,
            "session_id": session_id,
            "content": content,
            "summary": summary,
            "vector": vector,
        }]
        await run_in_threadpool(self._tbl.add, row)
        return archive_id

    async def search(self, session_id: str, query_vector: list[float],
                     top_k: int = 3) -> list[ArchivedRow]:
        def _q() -> list[ArchivedRow]:
            df = (
                self._tbl.search(query_vector)
                .where(f"session_id = '{session_id}'")
                .limit(top_k)
                .to_list()
            )
            return [
                ArchivedRow(
                    archive_id=r["archive_id"],
                    session_id=r["session_id"],
                    content=r["content"],
                    summary=r["summary"],
                    distance=float(r.get("_distance", 0.0)),
                )
                for r in df
            ]

        return await run_in_threadpool(_q)
