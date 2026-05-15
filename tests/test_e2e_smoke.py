from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import duckdb
import httpx
import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _MockUpstream(BaseHTTPRequestHandler):
    captured: ClassVar[list[dict]] = []

    def log_message(self, *args, **kwargs) -> None:  # silence
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        type(self).captured.append({"path": self.path, "body": json.loads(body)})
        payload = b'{"id":"resp_1","choices":[{"message":{"content":"hi"}}]}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _wait_for_health(url: str, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            time.sleep(0.2)
    return False


@pytest.mark.skipif(os.name == "nt" and "CI" in os.environ,
                    reason="subprocess port races flaky on Windows CI runners")
def test_daemon_serves_request_end_to_end(tmp_path: Path) -> None:
    upstream_port = _free_port()
    proxy_port = _free_port()
    server = HTTPServer(("127.0.0.1", upstream_port), _MockUpstream)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    env = os.environ.copy()
    env.update({
        "CONTEXTOS_DATA_DIR": str(tmp_path / "data"),
        "CONTEXTOS_LOG_DIR": str(tmp_path / "logs"),
        "CONTEXTOS_PROXY_PORT": str(proxy_port),
        "CONTEXTOS_OPENAI_UPSTREAM": f"http://127.0.0.1:{upstream_port}",
        "CONTEXTOS_ANTHROPIC_UPSTREAM": f"http://127.0.0.1:{upstream_port}",
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "contextos.daemon"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_health(f"http://127.0.0.1:{proxy_port}/_contextos/health"):
            err = proc.stderr.read().decode(errors="ignore")[:500]
            pytest.fail(f"daemon never became healthy. stderr={err}")

        r = httpx.post(
            f"http://127.0.0.1:{proxy_port}/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "ping"}],
            },
            headers={"user-agent": "cursor/0.1", "authorization": "Bearer test"},
            timeout=10.0,
        )
        assert r.status_code == 200
        assert b"hi" in r.content
        assert _MockUpstream.captured, "upstream never received the call"
        assert _MockUpstream.captured[-1]["path"].endswith("/chat/completions")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()
        server.server_close()

    # Verify the ledger recorded the session.
    db = duckdb.connect(str(tmp_path / "data" / "ledger.duckdb"), read_only=True)
    try:
        n = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert n >= 1
        turns = db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        assert turns >= 1
    finally:
        db.close()
