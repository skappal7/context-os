"""Realistic Claude Code payload through the full pipeline.

This is the regression test for the 2026-05-16 "berserk" incident: the rebuild
dropped an assistant turn that contained a tool_use, orphaning the matching
tool_result on the next user turn, which Anthropic rejected with a 400.

If this test fails, the IDE freeze is back.
"""
from __future__ import annotations

import json

import httpx
import pytest

from contextos.proxy import create_app
from contextos.safety import validate_payload


def _claude_code_payload() -> dict:
    """A trimmed-but-realistic Claude Code request: long system, several
    text turns, one cache_control anchor, one tool_use/tool_result pair
    that lives in the COLD/WARM range (i.e. far from the end)."""
    msgs: list[dict] = []
    # 20 chatter turns to push tool_use into the COLD window.
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"chatter turn {i}"})
    # Tool round-trip at indices 20-21 (still WARM-ish).
    msgs.append({
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I'll read the file."},
            {"type": "tool_use", "id": "toolu_ABC", "name": "Read",
             "input": {"path": "/foo"}},
        ],
    })
    msgs.append({
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_ABC",
             "content": "file contents..."},
        ],
    })
    # Recent HOT chatter + cache anchor.
    msgs.append({"role": "assistant", "content": "Got it."})
    msgs.append({
        "role": "user",
        "content": [{"type": "text", "text": "thanks",
                     "cache_control": {"type": "ephemeral"}}],
    })
    # Force the tool round-trip into COLD: add more recent turns.
    for i in range(10):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant",
                     "content": f"recent {i}"})
    return {"model": "claude-opus-4-7", "messages": msgs, "max_tokens": 1024}


@pytest.mark.asyncio
async def test_claude_code_payload_survives_pipeline(tmp_settings) -> None:
    captured: list[dict] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content.decode()))
        return httpx.Response(200, json={"ok": True},
                              headers={"content-type": "application/json"})

    app = create_app(tmp_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        await client.get("/_contextos/health")
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))

        payload = _claude_code_payload()
        r = await client.post(
            "/v1/messages", json=payload,
            headers={"user-agent": "claude-code/1.0", "x-api-key": "test"},
        )
        assert r.status_code == 200

    assert captured, "upstream never called"
    sent = captured[0]

    # 1. The rebuilt body must validate (no orphan tool_results, role ok).
    ok, reason = validate_payload(sent)
    assert ok, f"rebuilt body would have 400'd Anthropic: {reason}"

    # 2. The tool_use and matching tool_result must both still be there,
    #    in their original structured form.
    tool_use_ids = {
        b["id"] for m in sent["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_use"
    }
    tool_result_refs = {
        b["tool_use_id"] for m in sent["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result"
    }
    assert "toolu_ABC" in tool_use_ids
    assert "toolu_ABC" in tool_result_refs
    assert tool_result_refs.issubset(tool_use_ids), "orphan tool_result — the freeze bug"

    # 3. cache_control marker survived.
    cache_anchors = [
        b for m in sent["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and isinstance(b.get("cache_control"), dict)
    ]
    assert cache_anchors, "cache_control marker dropped — prompt caching broken"


@pytest.mark.asyncio
async def test_passthrough_forwards_body_unchanged(tmp_settings, monkeypatch) -> None:
    """With CONTEXTOS_PASSTHROUGH=1 the body MUST go out byte-for-byte."""
    tmp_settings.passthrough = True
    captured: list[bytes] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        captured.append(req.content)
        return httpx.Response(200, json={"ok": True},
                              headers={"content-type": "application/json"})

    app = create_app(tmp_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        await client.get("/_contextos/health")
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))

        payload = _claude_code_payload()
        original = json.dumps(payload).encode("utf-8")
        await client.post(
            "/v1/messages", content=original,
            headers={"user-agent": "claude-code/1.0", "x-api-key": "test",
                     "content-type": "application/json"},
        )

    assert captured == [original], "passthrough mutated the request body"


@pytest.mark.asyncio
async def test_full_session_endpoint_returns_all_turns(tmp_settings) -> None:
    """The append-only ledger must expose every turn for export."""
    def upstream(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True},
                              headers={"content-type": "application/json"})
    app = create_app(tmp_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        await client.get("/_contextos/health")
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))

        payload = {"model": "claude-opus-4-7",
                   "messages": [{"role": "user", "content": f"q{i}"} for i in range(30)]}
        await client.post("/v1/messages", json=payload,
                          headers={"user-agent": "claude-code/1.0", "x-api-key": "test"})

        sessions = (await client.get("/_contextos/sessions")).json()
        assert sessions
        sid = sessions[0]["session_id"]

        r = await client.get(f"/_contextos/session/{sid}/full")
        assert r.status_code == 200
        full = r.json()
        assert len(full) == 30, "ledger lost turns"
        assert full[0]["turn_index"] == 0
        assert full[-1]["turn_index"] == 29
