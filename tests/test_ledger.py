from __future__ import annotations

import pytest

from contextos.ledger import Ledger
from contextos.ledger.db import TurnRecord


@pytest.mark.asyncio
async def test_session_and_turn_roundtrip(tmp_settings) -> None:
    ledger = Ledger(tmp_settings.db_path)
    try:
        await ledger.ensure_session("s1", "claude-code", "claude-opus-4-7")
        await ledger.insert_turn(
            TurnRecord(session_id="s1", turn_index=0, role="user", content="hello",
                       token_count_raw=2)
        )
        summary = ledger.session_summary("s1")
        assert summary is not None
        assert summary["ide"] == "claude-code"
        assert summary["model"] == "claude-opus-4-7"
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_ensure_session_idempotent(tmp_settings) -> None:
    ledger = Ledger(tmp_settings.db_path)
    try:
        await ledger.ensure_session("s2", "cursor", "gpt-4o")
        await ledger.ensure_session("s2", "cursor", "gpt-4o")
        assert ledger.session_summary("s2") is not None
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_record_payload(tmp_settings) -> None:
    ledger = Ledger(tmp_settings.db_path)
    try:
        await ledger.ensure_session("s3", None, None)
        pid = await ledger.record_payload("s3", ["t1", "t2"], 100, 40)
        assert pid
    finally:
        ledger.close()
