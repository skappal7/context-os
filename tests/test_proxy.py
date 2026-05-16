from __future__ import annotations

import json

import httpx
import pytest

from contextos.proxy import create_app


@pytest.mark.asyncio
async def test_health(tmp_settings) -> None:
    app = create_app(tmp_settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream("GET", "/_contextos/health") as r,
    ):
        assert r.status_code == 200
        body = b""
        async for chunk in r.aiter_bytes():
            body += chunk
        data = json.loads(body)
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_anthropic_passthrough_streams(tmp_settings, monkeypatch) -> None:
    """Mock upstream; verify body forwarded and streamed back."""
    upstream_calls: list[dict] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        upstream_calls.append({
            "url": str(request.url),
            "body": request.content.decode(),
            "method": request.method,
        })
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: chunk1\n\ndata: chunk2\n\n",
        )

    app = create_app(tmp_settings)
    # Replace the lifespan-created httpx client with one using a MockTransport.
    # Drive lifespan manually so app.state is populated.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Trigger lifespan via a warmup request.
        await client.get("/_contextos/health")
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

        req_body = {"model": "claude-opus-4-7",
                    "messages": [{"role": "user", "content": "hi"}]}
        r = await client.post(
            "/v1/messages",
            json=req_body,
            headers={"x-api-key": "test", "user-agent": "claude-code/0.1"},
        )
        assert r.status_code == 200
        assert b"chunk1" in r.content
        assert len(upstream_calls) == 1
        assert "/v1/messages" in upstream_calls[0]["url"]


@pytest.mark.asyncio
async def test_pipeline_rewrites_long_history(tmp_settings) -> None:
    """Long history → DEAD/COLD elision → upstream sees fewer messages."""
    seen_bodies: list[dict] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(json.loads(request.content.decode()))
        return httpx.Response(200, content=b'{"ok": true}',
                              headers={"content-type": "application/json"})

    app = create_app(tmp_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.get("/_contextos/health")
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

        # 25 unique turns + one duplicate -> DEAD; many should collapse to COLD placeholder.
        messages = [{"role": "user" if i % 2 == 0 else "assistant",
                     "content": f"turn-{i}"} for i in range(25)]
        messages.append({"role": "user", "content": "turn-0"})  # duplicate -> DEAD
        await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": messages},
            headers={"user-agent": "cursor/1.0"},
        )
        assert seen_bodies, "upstream not called"
        rebuilt = seen_bodies[0]["messages"]
        assert len(rebuilt) < len(messages)
        # Duplicate at end is DEAD (first occurrence kept); last kept is turn-24.
        assert rebuilt[-1]["content"] == "turn-24"
        # A placeholder must appear somewhere.
        assert any("ContextOS" in m.get("content", "") for m in rebuilt)


@pytest.mark.asyncio
async def test_stats_endpoints_serve_dashboard(tmp_settings) -> None:
    """The dashboard hits these endpoints over HTTP — they must work even
    while the proxy is also handling chat traffic."""
    app = create_app(tmp_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        # Seed a session by forwarding one request (mock upstream).
        def upstream(r: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True},
                                  headers={"content-type": "application/json"})
        await client.get("/_contextos/health")
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o",
                  "messages": [{"role": "user", "content": "hi"}]},
            headers={"user-agent": "cursor/1.0", "x-api-key": "test"},
        )

        r = await client.get("/_contextos/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["sessions"] >= 1

        r = await client.get("/_contextos/sessions?limit=10")
        assert r.status_code == 200
        sess = r.json()
        assert sess and "session_id" in sess[0]

        r = await client.get("/_contextos/by/ide")
        assert r.status_code == 200

        r = await client.get(f"/_contextos/memory-map/{sess[0]['session_id']}")
        assert r.status_code == 200

        r = await client.get("/_contextos/by/bogus")
        assert r.status_code == 400
