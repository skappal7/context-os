from __future__ import annotations

import contextlib
import os
import signal
from pathlib import Path

import uvicorn

from contextos.proxy import create_app
from contextos.settings import configure_logging, get_settings


def run() -> None:
    s = get_settings()
    configure_logging(s)
    s.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    try:
        uvicorn.run(
            create_app(s),
            host=s.proxy_host,
            port=s.proxy_port,
            log_config=None,
            access_log=False,
        )
    finally:
        with contextlib.suppress(FileNotFoundError):
            s.pid_file.unlink()


def read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def stop() -> bool:
    s = get_settings()
    pid = read_pid(s.pid_file)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


if __name__ == "__main__":
    run()
