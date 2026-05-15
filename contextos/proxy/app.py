from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from contextos import __version__
from contextos.archive import ArchiveStore
from contextos.classifier import classify
from contextos.compactor import CompactionJob, CompactorService
from contextos.ledger import Ledger
from contextos.ledger.db import TurnRecord
from contextos.llm import FastEmbedEmbedder, LlamaCppGenerator
from contextos.pricing import savings_usd
from contextos.proxy.payload import detect_model, extract_messages, stringify_content
from contextos.reconstructor import rebuild_messages
from contextos.retrieval import detect_trigger, recall_for
from contextos.session_memory import SessionMemory, cold_runs
from contextos.settings import Settings, get_settings
from contextos.tokens import count_message_tokens, count_tokens

log = logging.getLogger("contextos.proxy")

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


def _filter_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


def _session_id_for(request: Request) -> str:
    h = hashlib.sha256()
    h.update(request.headers.get("authorization", "").encode())
    h.update(request.headers.get("x-api-key", "").encode())
    h.update(request.headers.get("user-agent", "").encode())
    return h.hexdigest()[:16]


def _detect_ide(request: Request) -> str | None:
    ua = request.headers.get("user-agent", "").lower()
    for needle, name in (("claude", "claude-code"), ("cursor", "cursor"),
                         ("codex", "codex"), ("continue", "continue"), ("aider", "aider")):
        if needle in ua:
            return name
    return None


def _is_chat_endpoint(path: str) -> bool:
    return path.endswith("/messages") or path.endswith("/chat/completions")


def _inject_recalls(messages: list[dict], recalls: list[str]) -> list[dict]:
    if not recalls:
        return messages
    return [{"role": "user", "content": r} for r in recalls] + messages


async def _process_body(
    body_bytes: bytes,
    *,
    ledger: Ledger,
    compactor: CompactorService,
    memory: SessionMemory,
    session_id: str,
    ide: str | None,
) -> tuple[bytes, dict[str, Any]]:
    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body_bytes, {}

    messages = extract_messages(body)
    if not messages:
        return body_bytes, {}

    model = detect_model(body)
    await ledger.ensure_session(session_id, ide, model)

    for idx, m in enumerate(messages):
        content = stringify_content(m.get("content", ""))
        await ledger.insert_turn(TurnRecord(
            session_id=session_id, turn_index=idx, role=str(m.get("role", "user")),
            content=content, token_count_raw=count_tokens(content),
        ))

    tagged = classify(messages)

    # Submit any unseen COLD runs for async compaction. Never blocks.
    for run_id, run in cold_runs(tagged):
        if run_id not in memory.get(session_id).summaries:
            compactor.submit(CompactionJob(
                session_id=session_id, run_id=run_id,
                messages=[t.message for t in run],
            ))

    summaries = memory.get(session_id).summaries
    rebuilt = rebuild_messages(tagged, summaries)
    rebuilt = _inject_recalls(rebuilt, memory.pop_recalls(session_id))

    raw_tokens = count_message_tokens(messages)
    sent_tokens = count_message_tokens(rebuilt)
    saved = max(0, raw_tokens - sent_tokens)
    dollars = savings_usd(model, saved)

    body["messages"] = rebuilt
    new_bytes = json.dumps(body).encode("utf-8")

    await ledger.record_payload(session_id, [], sent_tokens, saved)
    await ledger.add_session_tokens(session_id, raw_tokens, sent_tokens, dollars)

    return new_bytes, {
        "raw_tokens": raw_tokens, "sent_tokens": sent_tokens,
        "saved": saved, "savings_usd": dollars, "model": model,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    timeout = httpx.Timeout(settings.request_timeout_s, connect=settings.connect_timeout_s)
    shared_ledger = Ledger(settings.db_path)
    shared_http = httpx.AsyncClient(timeout=timeout)
    shared_archive = ArchiveStore(settings.archive_dir, settings.embedding_dim)
    shared_generator = LlamaCppGenerator(
        settings.llm_repo_id, settings.llm_filename, settings.model_dir,
        n_ctx=settings.llm_n_ctx,
    )
    shared_embedder = FastEmbedEmbedder(settings.embedding_model, settings.model_dir)
    shared_memory = SessionMemory()
    shared_compactor = CompactorService(
        settings, shared_generator, shared_embedder, shared_archive, shared_memory,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("contextos %s listening on %s:%s", __version__,
                 settings.proxy_host, settings.proxy_port)
        app.state.compactor.start()
        try:
            yield
        finally:
            await app.state.compactor.stop()
            await app.state.generator.aclose()
            await app.state.embedder.aclose()
            await app.state.http.aclose()
            app.state.ledger.close()

    app = FastAPI(title="ContextOS Proxy", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.ledger = shared_ledger
    app.state.http = shared_http
    app.state.archive = shared_archive
    app.state.generator = shared_generator
    app.state.embedder = shared_embedder
    app.state.memory = shared_memory
    app.state.compactor = shared_compactor
    app.state.background_tasks = set()

    @app.get("/_contextos/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    async def _post_response_hook(session_id: str, body_bytes: bytes) -> None:
        """Run trigger detection on the upstream response. Decoded best-effort —
        SSE chunks and JSON bodies are both pattern-matched as raw text."""
        text = body_bytes.decode("utf-8", errors="ignore")
        if not detect_trigger(text):
            return
        recalled = await recall_for(
            settings, app.state.embedder, app.state.archive, session_id, text,
        )
        if recalled:
            app.state.memory.push_recall(session_id, recalled)

    async def _forward(request: Request, upstream_base: str, path: str) -> Response:
        body = await request.body()
        headers = _filter_headers(dict(request.headers))
        session_id = _session_id_for(request)

        if request.method == "POST" and _is_chat_endpoint(path) and body:
            ide = _detect_ide(request)
            new_body, stats = await _process_body(
                body,
                ledger=app.state.ledger,
                compactor=app.state.compactor,
                memory=app.state.memory,
                session_id=session_id,
                ide=ide,
            )
            if stats:
                log.info("session=%s model=%s raw=%d sent=%d saved=%d ($%.4f)",
                         session_id, stats.get("model"), stats["raw_tokens"],
                         stats["sent_tokens"], stats["saved"], stats["savings_usd"])
            body = new_body

        url = f"{upstream_base.rstrip('/')}/{path.lstrip('/')}"
        upstream_req = app.state.http.build_request(
            request.method, url, headers=headers, content=body, params=request.query_params
        )
        upstream_resp = await app.state.http.send(upstream_req, stream=True)
        resp_headers = _filter_headers(dict(upstream_resp.headers))

        capture = bytearray()
        capture_enabled = _is_chat_endpoint(path) and request.method == "POST"

        async def iter_body() -> AsyncIterator[bytes]:
            try:
                if upstream_resp.is_stream_consumed:
                    chunk = upstream_resp.content
                    if capture_enabled:
                        capture.extend(chunk)
                    yield chunk
                else:
                    async for chunk in upstream_resp.aiter_raw():
                        if capture_enabled:
                            capture.extend(chunk)
                        yield chunk
            finally:
                await upstream_resp.aclose()
                if capture_enabled and capture:
                    # Fire-and-forget; never blocks the client response.
                    task = asyncio.create_task(
                        _post_response_hook(session_id, bytes(capture))
                    )
                    app.state.background_tasks.add(task)
                    task.add_done_callback(app.state.background_tasks.discard)

        return StreamingResponse(
            iter_body(),
            status_code=upstream_resp.status_code,
            headers=resp_headers,
            media_type=upstream_resp.headers.get("content-type"),
        )

    # Anthropic's only chat endpoint is /v1/messages — route it explicitly so it
    # doesn't get swallowed by the generic /v1/ OpenAI catch-all below.
    @app.api_route("/v1/messages", methods=["POST"])
    async def anthropic_messages(request: Request) -> Response:
        return await _forward(request, settings.anthropic_upstream, "v1/messages")

    @app.api_route("/v1/complete", methods=["POST"], include_in_schema=False)
    async def anthropic_complete(request: Request) -> Response:
        return await _forward(request, settings.anthropic_upstream, "v1/complete")

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def openai_passthrough(path: str, request: Request) -> Response:
        return await _forward(request, settings.openai_upstream, f"v1/{path}")

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        include_in_schema=False,
    )
    async def anthropic_passthrough(path: str, request: Request) -> Response:
        if path.startswith("_contextos"):
            return JSONResponse({"error": "not found"}, status_code=404)
        return await _forward(request, settings.anthropic_upstream, path)

    return app
