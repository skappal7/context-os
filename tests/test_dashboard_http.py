from __future__ import annotations

import httpx
import pytest

from contextos.dashboard import queries
from contextos.dashboard.queries import DaemonUnreachable


def _client(handler) -> None:
    """Monkey-patch httpx.get to use a MockTransport handler."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client(transport=transport)

    def fake_get(url, **kwargs):
        return real_client.get(url, **kwargs)

    return fake_get


def test_totals_round_trip(monkeypatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/_contextos/stats"
        return httpx.Response(200, json={
            "sessions": 2, "raw_tokens": 1000, "sent_tokens": 400,
            "saved_tokens": 600, "savings_usd": 0.05, "reduction_pct": 60.0,
        })
    monkeypatch.setattr(httpx, "get", _client(handler))
    t = queries.totals("http://test")
    assert t.sessions == 2
    assert t.saved_tokens == 600
    assert t.reduction_pct == pytest.approx(60.0)


def test_sessions_passes_limit(monkeypatch) -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append({"path": req.url.path, "params": dict(req.url.params)})
        return httpx.Response(200, json=[{"session_id": "s1"}])
    monkeypatch.setattr(httpx, "get", _client(handler))
    queries.sessions("http://test", limit=25)
    assert seen[0]["params"] == {"limit": "25"}


def test_by_dimension_validates(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "get", _client(lambda r: httpx.Response(200, json=[])))
    queries.by_dimension("http://test", "ide")
    queries.by_dimension("http://test", "model")
    with pytest.raises(ValueError):
        queries.by_dimension("http://test", "nope")


def test_daemon_unreachable() -> None:
    # No transport mock — connection refused on a closed port.
    with pytest.raises(DaemonUnreachable):
        queries.totals("http://127.0.0.1:1")
