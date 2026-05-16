"""HTTP client for the daemon's read-only stats endpoints.

The dashboard runs in a separate process; DuckDB on Windows refuses a second
connection while the daemon owns the file. So the dashboard never touches the
DB directly — it queries the daemon's /_contextos/* endpoints over HTTP.

If the daemon isn't running, every call raises DaemonUnreachable so the
dashboard can render a clear message instead of stack-tracing.
"""
from __future__ import annotations

from typing import Any

import httpx

from contextos.ledger.stats import Totals

_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


class DaemonUnreachable(Exception):
    """Daemon HTTP endpoint did not respond."""


def _get(base_url: str, path: str, **params: Any) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        r = httpx.get(url, params=params or None, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise DaemonUnreachable(f"{url}: {e}") from e


def totals(base_url: str) -> Totals:
    data = _get(base_url, "/_contextos/stats")
    # reduction_pct is a computed @property on Totals; don't pass it back in.
    return Totals(
        sessions=int(data["sessions"]),
        raw_tokens=int(data["raw_tokens"]),
        sent_tokens=int(data["sent_tokens"]),
        saved_tokens=int(data["saved_tokens"]),
        savings_usd=float(data["savings_usd"]),
    )


def sessions(base_url: str, limit: int = 50) -> list[dict[str, Any]]:
    return list(_get(base_url, "/_contextos/sessions", limit=limit))


def by_dimension(base_url: str, column: str) -> list[dict[str, Any]]:
    if column not in {"ide", "model"}:
        raise ValueError(f"unsupported dimension: {column}")
    return list(_get(base_url, f"/_contextos/by/{column}"))


def memory_map(base_url: str, session_id: str) -> list[dict[str, Any]]:
    return list(_get(base_url, f"/_contextos/memory-map/{session_id}"))
