from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def _ro_connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Read-only connection so the dashboard never contends with the daemon writer."""
    return duckdb.connect(str(db_path), read_only=True)


def totals(db_path: Path) -> Totals:
    if not db_path.exists():
        return Totals(0, 0, 0, 0, 0.0)
    conn = _ro_connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(raw_tokens_in), 0), "
            "COALESCE(SUM(sent_tokens_in), 0), COALESCE(SUM(savings_usd), 0) FROM sessions"
        ).fetchone()
        sess, raw, sent, usd = row or (0, 0, 0, 0.0)
        return Totals(int(sess), int(raw), int(sent), int(raw) - int(sent), float(usd))
    finally:
        conn.close()


def sessions(db_path: Path, limit: int = 50) -> list[dict]:
    if not db_path.exists():
        return []
    conn = _ro_connect(db_path)
    try:
        rows = conn.execute(
            "SELECT session_id, ide, model, started_at, raw_tokens_in, sent_tokens_in, "
            "savings_usd FROM sessions ORDER BY started_at DESC LIMIT ?",
            [limit],
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            raw, sent = int(r[4] or 0), int(r[5] or 0)
            out.append({
                "session_id": r[0], "ide": r[1] or "-", "model": r[2] or "-",
                "started_at": r[3], "raw_tokens": raw, "sent_tokens": sent,
                "saved": raw - sent,
                "reduction_pct": 100.0 * (raw - sent) / raw if raw else 0.0,
                "savings_usd": float(r[6] or 0.0),
            })
        return out
    finally:
        conn.close()


def by_dimension(db_path: Path, column: str) -> list[dict]:
    if column not in {"ide", "model"}:
        raise ValueError(f"unsupported dimension: {column}")
    if not db_path.exists():
        return []
    conn = _ro_connect(db_path)
    try:
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
    finally:
        conn.close()


def memory_map(db_path: Path, session_id: str) -> list[dict]:
    """Derive a per-turn heat state for the dashboard's memory map.

    Heat is computed from turn position (last 5 = HOT, next 10 = WARM, rest = COLD)
    so the dashboard matches the classifier without needing a separate write path.
    """
    if not db_path.exists():
        return []
    conn = _ro_connect(db_path)
    try:
        rows = conn.execute(
            "SELECT turn_index, role, token_count_raw FROM turns WHERE session_id = ? "
            "ORDER BY turn_index",
            [session_id],
        ).fetchall()
        if not rows:
            return []
        n = len(rows)
        out: list[dict] = []
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
    finally:
        conn.close()
