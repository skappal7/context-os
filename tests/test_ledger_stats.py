from __future__ import annotations

import pytest

from contextos.ledger import Ledger, stats
from contextos.ledger.db import TurnRecord


async def _seed(tmp_settings) -> None:
    ledger = Ledger(tmp_settings.db_path)
    try:
        await ledger.ensure_session("s1", "claude-code", "claude-opus-4-7")
        await ledger.ensure_session("s2", "cursor", "gpt-4o")
        await ledger.add_session_tokens("s1", 1000, 400, 0.009)
        await ledger.add_session_tokens("s2", 2000, 800, 0.003)
        for i in range(20):
            await ledger.insert_turn(TurnRecord(
                session_id="s1", turn_index=i, role="user",
                content=f"q{i}", token_count_raw=10,
            ))
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_totals(tmp_settings) -> None:
    await _seed(tmp_settings)
    import duckdb
    conn = duckdb.connect(str(tmp_settings.db_path), read_only=True)
    try:
        t = stats.totals(conn)
        assert t.sessions == 2
        assert t.raw_tokens == 3000
        assert t.sent_tokens == 1200
        assert t.saved_tokens == 1800
        assert t.savings_usd == pytest.approx(0.012)
        assert t.reduction_pct == pytest.approx(60.0)
        # Serialization round-trip used by the HTTP endpoint.
        d = t.to_dict()
        assert d["reduction_pct"] == pytest.approx(60.0)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_sessions_and_dimensions(tmp_settings) -> None:
    await _seed(tmp_settings)
    import duckdb
    conn = duckdb.connect(str(tmp_settings.db_path), read_only=True)
    try:
        sess = stats.sessions(conn)
        assert {r["session_id"] for r in sess} == {"s1", "s2"}
        by_ide = stats.by_dimension(conn, "ide")
        assert {r["key"] for r in by_ide} == {"claude-code", "cursor"}
        with pytest.raises(ValueError):
            stats.by_dimension(conn, "nope")
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_memory_map_heat_derivation(tmp_settings) -> None:
    await _seed(tmp_settings)
    import duckdb
    conn = duckdb.connect(str(tmp_settings.db_path), read_only=True)
    try:
        mm = stats.memory_map(conn, "s1")
        assert len(mm) == 20
        assert [r["heat"] for r in mm[-5:]] == ["HOT"] * 5
        assert mm[0]["heat"] == "COLD"
        assert mm[10]["heat"] == "WARM"
    finally:
        conn.close()
