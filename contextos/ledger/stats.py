"""Pure SQL compute over a DuckDB connection.

Used by both the daemon's HTTP endpoints and direct test fixtures. Keeping the
SQL in one place means the dashboard and tests can't drift apart.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from contextos.classifier.rules import HOT_WINDOW, WARM_WINDOW


@dataclass(slots=True)
class Totals:
    sessions: int
    raw_tokens: int
    sent_tokens: int
    saved_tokens: int
    savings_usd: float

    @property
    def reduction_pct(self) -> float:
        return 100.0 * self.saved_tokens / self.raw_tokens if self.raw_tokens else 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reduction_pct"] = self.reduction_pct
        return d


def totals(conn: duckdb.DuckDBPyConnection) -> Totals:
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(raw_tokens_in), 0), "
        "COALESCE(SUM(sent_tokens_in), 0), COALESCE(SUM(savings_usd), 0) FROM sessions"
    ).fetchone()
    sess, raw, sent, usd = row or (0, 0, 0, 0.0)
    return Totals(int(sess), int(raw), int(sent), int(raw) - int(sent), float(usd))


def sessions(conn: duckdb.DuckDBPyConnection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT session_id, ide, model, started_at, raw_tokens_in, sent_tokens_in, "
        "savings_usd FROM sessions ORDER BY started_at DESC LIMIT ?",
        [limit],
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        raw, sent = int(r[4] or 0), int(r[5] or 0)
        out.append({
            "session_id": r[0], "ide": r[1] or "-", "model": r[2] or "-",
            "started_at": str(r[3]) if r[3] is not None else None,
            "raw_tokens": raw, "sent_tokens": sent, "saved": raw - sent,
            "reduction_pct": 100.0 * (raw - sent) / raw if raw else 0.0,
            "savings_usd": float(r[6] or 0.0),
        })
    return out


def by_dimension(conn: duckdb.DuckDBPyConnection, column: str) -> list[dict[str, Any]]:
    if column not in {"ide", "model"}:
        raise ValueError(f"unsupported dimension: {column}")
    rows = conn.execute(
        f"SELECT COALESCE({column}, '-') AS k, "
        "COALESCE(SUM(raw_tokens_in), 0), COALESCE(SUM(sent_tokens_in), 0), "
        "COALESCE(SUM(savings_usd), 0) FROM sessions GROUP BY k ORDER BY 4 DESC"
    ).fetchall()
    return [
        {"key": r[0], "raw_tokens": int(r[1]), "sent_tokens": int(r[2]),
         "saved": int(r[1]) - int(r[2]), "savings_usd": float(r[3])}
        for r in rows
    ]


def full_session(conn: duckdb.DuckDBPyConnection, session_id: str) -> list[dict[str, Any]]:
    """Every turn ever recorded for this session. The ledger is append-only;
    no pipeline action deletes from this view."""
    rows = conn.execute(
        "SELECT turn_index, role, raw_content, token_count_raw FROM turns "
        "WHERE session_id = ? ORDER BY turn_index",
        [session_id],
    ).fetchall()
    return [
        {"turn_index": int(r[0]), "role": r[1], "content": r[2],
         "tokens": int(r[3] or 0)}
        for r in rows
    ]


def memory_map(conn: duckdb.DuckDBPyConnection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT turn_index, role, token_count_raw FROM turns WHERE session_id = ? "
        "ORDER BY turn_index",
        [session_id],
    ).fetchall()
    if not rows:
        return []
    n = len(rows)
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        from_end = n - 1 - i
        if from_end < HOT_WINDOW:
            heat = "HOT"
        elif from_end < WARM_WINDOW:
            heat = "WARM"
        else:
            heat = "COLD"
        out.append({"turn_index": int(r[0]), "role": r[1],
                    "tokens": int(r[2] or 0), "heat": heat})
    return out
