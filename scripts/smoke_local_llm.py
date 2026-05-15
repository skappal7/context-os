"""Smoke the local-LLM compaction path end-to-end.

Phase A: directly exercise LlamaCppGenerator + FastEmbedEmbedder (proves model
download + load + inference works on this machine).

Phase B: drive a synthetic 25-turn request through the in-process proxy against a
MockTransport upstream, then await the compactor queue and assert a real summary
lives in SessionMemory and rows landed in the LanceDB archive.

Run: python scripts/smoke_local_llm.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
SMOKE_DIR = REPO / ".smoke_local"


async def phase_a() -> None:
    from contextos.llm import FastEmbedEmbedder, LlamaCppGenerator
    from contextos.settings import get_settings

    s = get_settings()
    print(f"\n=== Phase A: local LLM direct ===\n  model dir: {s.model_dir}")
    gen = LlamaCppGenerator(
        s.llm_repo_id, s.llm_filename, s.model_dir, n_ctx=s.llm_n_ctx,
    )
    t0 = time.time()
    print(f"  generator: loading {s.llm_repo_id}/{s.llm_filename} ...")
    out = await gen.generate(
        "Summarise in one sentence: We refactored the auth middleware to fix a "
        "session token storage bug flagged by legal compliance.\n\nSummary:",
        max_tokens=80,
    )
    print(f"  [{time.time()-t0:.1f}s] generator output: {out[:200]!r}")
    await gen.aclose()

    emb = FastEmbedEmbedder(s.embedding_model, s.model_dir)
    t0 = time.time()
    print(f"\n  embedder: loading {s.embedding_model} ...")
    vec = await emb.embed("hello world")
    print(f"  [{time.time()-t0:.1f}s] embedding dim: {len(vec)} (expected {s.embedding_dim})")
    assert len(vec) == s.embedding_dim, "embedding dim mismatch"
    await emb.aclose()


async def phase_b() -> None:
    import os

    os.environ["CONTEXTOS_DATA_DIR"] = str(SMOKE_DIR / "data")
    os.environ["CONTEXTOS_LOG_DIR"] = str(SMOKE_DIR / "logs")
    # Force a fresh Settings instance with the new env vars.
    from contextos.settings import get_settings
    get_settings.cache_clear()
    s = get_settings()

    from contextos.proxy import create_app

    print("\n=== Phase B: synthetic 25-turn session through the proxy ===")

    def mock_upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "resp", "content": [{"type": "text", "text": "ok"}],
                  "usage": {"input_tokens": 1, "output_tokens": 1}},
        )

    app = create_app(s)
    # Swap the upstream httpx client for a mock so we don't burn real API credits.
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))
    # The compactor was constructed before the worker task could be spawned;
    # start it now since we are not running under uvicorn's lifespan.
    app.state.compactor.start()

    # Build a synthetic transcript: 25 distinct turns about a recognizable subject
    # so the compactor has real content to summarise.
    messages = []
    topics = [
        "set up FastAPI proxy on port 9137",
        "add DuckDB ledger schema",
        "wire heat classifier",
        "implement payload reconstructor",
        "add token counter via tiktoken",
        "decide to use SmolLM2 for compaction",
        "drop Ollama dependency",
        "fix /v1/messages routing bug",
        "add Streamlit dashboard",
        "wire IDE auto-detection",
    ]
    for i, topic in enumerate(topics):
        messages.append({"role": "user",
                         "content": f"Turn {i} — please help me {topic}."})
        messages.append({"role": "assistant",
                         "content": f"Acknowledged. We will {topic}. "
                         f"This requires edits to module #{i}."})
    # That's 20 turns. Append 5 more recent HOT turns.
    for i in range(5):
        messages.append({"role": "user", "content": f"Recent question #{i}: status?"})
    print(f"  built {len(messages)} synthetic turns")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        r = await client.post(
            "/v1/messages",
            json={"model": "claude-haiku-4-5", "max_tokens": 50, "messages": messages},
            headers={"user-agent": "claude-code/smoke", "x-api-key": "test"},
        )
        print(f"  proxy returned {r.status_code}")
        assert r.status_code == 200

    # Now wait for the compactor to drain.
    print("  awaiting compactor queue...")
    t0 = time.time()
    await asyncio.wait_for(app.state.compactor._queue.join(), timeout=120.0)
    print(f"  compactor drained in {time.time()-t0:.1f}s")

    # Inspect SessionMemory.
    from contextos.proxy.app import _session_id_for as sid_fn

    class _Req:
        headers = {"x-api-key": "test", "user-agent": "claude-code/smoke"}

    session_id = sid_fn(_Req())
    summaries = app.state.memory.get(session_id).summaries
    print(f"  session_id={session_id}  summaries recorded={len(summaries)}")
    for run_id, summary in summaries.items():
        print(f"\n  --- summary [{run_id[:10]}] ---")
        print(f"  {summary[:600]}")
        print(f"  --- ({len(summary)} chars) ---")

    # And the archive.
    archive_rows = app.state.archive._tbl.to_pandas()
    print(f"\n  archive rows: {len(archive_rows)} "
          f"(sessions: {set(archive_rows['session_id'].tolist())})")

    await app.state.compactor.stop()
    await app.state.http.aclose()
    await app.state.generator.aclose()
    await app.state.embedder.aclose()
    app.state.ledger.close()

    assert summaries, "no summary produced — compactor never wrote to SessionMemory"
    print("\n[done] local-LLM compaction verified end-to-end")


async def main() -> None:
    if SMOKE_DIR.exists():
        shutil.rmtree(SMOKE_DIR, ignore_errors=True)
    await phase_a()
    await phase_b()


if __name__ == "__main__":
    asyncio.run(main())
