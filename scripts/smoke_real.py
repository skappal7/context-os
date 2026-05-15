"""Manual smoke against the real Anthropic API.

Loads ANTHROPIC_API_KEY from .env without ever printing it, spawns the daemon as a
subprocess, makes one /v1/messages call through the proxy, prints a redacted summary
of the result, then stops the daemon.

Run: python scripts/smoke_real.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import duckdb
import httpx

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_health(url: str, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1.0).status_code == 200:
                return True
        except httpx.HTTPError:
            time.sleep(0.2)
    return False


def main() -> int:
    if not ENV_FILE.exists():
        print("ERROR: .env not found at", ENV_FILE)
        return 1
    env = load_env(ENV_FILE)
    key = env.get("ANTHROPIC_API_KEY")
    if not key or not key.startswith("sk-ant-"):
        print("ERROR: ANTHROPIC_API_KEY missing or malformed in .env")
        return 1
    print(f"[ok] loaded key ({len(key)} chars, prefix '{key[:8]}***')")

    proxy_port = free_port()
    data_dir = REPO / ".smoke" / "data"
    log_dir = REPO / ".smoke" / "logs"

    proc_env = os.environ.copy()
    proc_env.update({
        "CONTEXTOS_DATA_DIR": str(data_dir),
        "CONTEXTOS_LOG_DIR": str(log_dir),
        "CONTEXTOS_PROXY_PORT": str(proxy_port),
        # Pin to real Anthropic upstream explicitly.
        "CONTEXTOS_ANTHROPIC_UPSTREAM": "https://api.anthropic.com",
    })

    print(f"[..] starting daemon on 127.0.0.1:{proxy_port}")
    proc = subprocess.Popen(
        [sys.executable, "-m", "contextos.daemon"],
        env=proc_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not wait_health(f"http://127.0.0.1:{proxy_port}/_contextos/health"):
            err = proc.stderr.read().decode(errors="ignore")[:1000]
            print("ERROR: daemon never became healthy. stderr:")
            print(err)
            return 1
        print("[ok] daemon healthy")

        body = {
            "model": "claude-haiku-4-5",
            "max_tokens": 50,
            "messages": [
                {"role": "user", "content": "Reply with exactly: pong"},
            ],
        }
        print("[..] POST /v1/messages via proxy (real Anthropic upstream)")
        r = httpx.post(
            f"http://127.0.0.1:{proxy_port}/v1/messages",
            json=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                "user-agent": "contextos-smoke/0.1",
            },
            timeout=30.0,
        )
        print(f"[ok] proxy returned {r.status_code}")
        if r.status_code != 200:
            print("body:", r.text[:500])
            return 1
        resp = r.json()
        text_blocks = [b.get("text", "") for b in resp.get("content", [])
                       if b.get("type") == "text"]
        print(f"[ok] model said: {(' '.join(text_blocks))[:120]!r}")
        usage = resp.get("usage", {})
        print(f"[ok] anthropic usage: in={usage.get('input_tokens')} "
              f"out={usage.get('output_tokens')}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    db_path = data_dir / "ledger.duckdb"
    db = duckdb.connect(str(db_path), read_only=True)
    try:
        sessions = db.execute(
            "SELECT session_id, ide, model, raw_tokens_in, sent_tokens_in, savings_usd "
            "FROM sessions",
        ).fetchall()
        turns = db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        payloads = db.execute("SELECT COUNT(*) FROM sent_payloads").fetchone()[0]
    finally:
        db.close()

    print("\n[ledger]")
    for s in sessions:
        print(f"  session={s[0]} ide={s[1]} model={s[2]} "
              f"raw_in={s[3]} sent_in={s[4]} usd={s[5]:.6f}")
    print(f"  turns rows : {turns}")
    print(f"  payload rows: {payloads}")

    print("\n[done] smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
