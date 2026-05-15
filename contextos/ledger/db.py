from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from fastapi.concurrency import run_in_threadpool

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


@dataclass(slots=True)
class TurnRecord:
    session_id: str
    turn_index: int
    role: str
    content: str
    token_count_raw: int = 0
    turn_id: str = ""

    def __post_init__(self) -> None:
        if not self.turn_id:
            self.turn_id = uuid.uuid4().hex


class Ledger:
    """Single-writer DuckDB wrapper. All writes serialized via asyncio.Lock."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._conn = duckdb.connect(str(db_path))
        self._conn.execute(_SCHEMA)
        self._write_lock = asyncio.Lock()

    def close(self) -> None:
        self._conn.close()

    async def ensure_session(self, session_id: str, ide: str | None, model: str | None) -> None:
        async with self._write_lock:
            await run_in_threadpool(
                self._conn.execute,
                "INSERT INTO sessions(session_id, ide, model) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                [session_id, ide, model],
            )

    async def insert_turn(self, t: TurnRecord) -> None:
        async with self._write_lock:
            await run_in_threadpool(
                self._conn.execute,
                "INSERT INTO turns(turn_id, session_id, turn_index, role, raw_content, "
                "token_count_raw) VALUES (?, ?, ?, ?, ?, ?)",
                [t.turn_id, t.session_id, t.turn_index, t.role, t.content, t.token_count_raw],
            )

    async def record_payload(
        self,
        session_id: str,
        turn_ids: list[str],
        total_tokens_sent: int,
        tokens_saved: int,
    ) -> str:
        payload_id = uuid.uuid4().hex
        async with self._write_lock:
            await run_in_threadpool(
                self._conn.execute,
                "INSERT INTO sent_payloads(payload_id, session_id, turn_ids_included, "
                "total_tokens_sent, tokens_saved) VALUES (?, ?, ?, ?, ?)",
                [payload_id, session_id, json.dumps(turn_ids), total_tokens_sent, tokens_saved],
            )
        return payload_id

    async def add_session_tokens(
        self, session_id: str, raw: int, sent: int, savings_usd: float
    ) -> None:
        async with self._write_lock:
            await run_in_threadpool(
                self._conn.execute,
                "UPDATE sessions SET raw_tokens_in = raw_tokens_in + ?, "
                "sent_tokens_in = sent_tokens_in + ?, "
                "savings_usd = savings_usd + ? WHERE session_id = ?",
                [raw, sent, savings_usd, session_id],
            )

    def session_summary(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT session_id, ide, model, raw_tokens_in, sent_tokens_in, savings_usd "
            "FROM sessions WHERE session_id = ?",
            [session_id],
        ).fetchone()
        if not row:
            return None
        return {
            "session_id": row[0],
            "ide": row[1],
            "model": row[2],
            "raw_tokens_in": row[3],
            "sent_tokens_in": row[4],
            "savings_usd": row[5],
        }
