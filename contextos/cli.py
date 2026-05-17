from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from contextos import __version__
from contextos.daemon import read_pid
from contextos.daemon import stop as stop_daemon
from contextos.installer import detect, install_all, uninstall_all
from contextos.settings import Settings, get_settings


def _dashboard_pid_file(s: Settings) -> Path:
    return s.data_dir / "dashboard.pid"


def _snapshot_db(s: Settings, keep: int = 7) -> Path | None:
    """Copy ledger.duckdb to backups/ledger-YYYYMMDD-HHMMSS.duckdb, keep N newest.
    Called BEFORE the daemon starts so the file is unlocked on Windows."""
    if not s.db_path.exists():
        return None
    s.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = s.backup_dir / f"ledger-{stamp}.duckdb"
    try:
        shutil.copy2(s.db_path, dst)
    except OSError:
        return None
    snaps = sorted(s.backup_dir.glob("ledger-*.duckdb"))
    for old in snaps[:-keep]:
        with contextlib.suppress(OSError):
            old.unlink()
    return dst


def _spawn_dashboard(s: Settings) -> int | None:
    """Spawn Streamlit detached on the dashboard port. Returns child PID or None
    if streamlit isn't installed."""
    import importlib.util
    if importlib.util.find_spec("streamlit") is None:
        return None
    script = Path(__file__).parent / "dashboard" / "app.py"
    s.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = s.log_dir / "dashboard.log"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(script),
        "--server.port", str(s.dashboard_port),
        "--server.address", s.proxy_host,
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    kwargs: dict = {
        "stdout": open(log_path, "ab", buffering=0),  # noqa: SIM115
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    proc = subprocess.Popen(cmd, **kwargs)
    _dashboard_pid_file(s).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def _stop_dashboard(s: Settings) -> bool:
    pid_file = _dashboard_pid_file(s)
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(FileNotFoundError):
            pid_file.unlink()

app = typer.Typer(add_completion=False, help="ContextOS - agentic memory lifecycle manager")
console = Console()


def _health_url() -> str:
    s = get_settings()
    return f"http://{s.proxy_host}:{s.proxy_port}/_contextos/health"


def _is_running() -> bool:
    try:
        r = httpx.get(_health_url(), timeout=1.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"context-os {__version__}")


@app.command()
def status() -> None:
    """Show daemon and IDE status."""
    s = get_settings()
    running = _is_running()
    pid = read_pid(s.pid_file)
    table = Table(title="ContextOS Status")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("daemon", "[green]running[/]" if running else "[red]stopped[/]")
    table.add_row("pid", str(pid) if pid else "-")
    table.add_row("proxy", f"http://{s.proxy_host}:{s.proxy_port}")
    table.add_row("data dir", str(s.data_dir))
    console.print(table)

    targets = detect()
    if targets:
        t = Table(title="Detected IDEs")
        t.add_column("IDE")
        t.add_column("Config")
        for x in targets:
            t.add_row(x.name, str(x.config_path))
        console.print(t)
    else:
        console.print("[yellow]No supported IDE configs found.[/]")


@app.command()
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f"),
    no_dashboard: bool = typer.Option(False, "--no-dashboard",
                                       help="Don't auto-launch the dashboard."),
    no_browser: bool = typer.Option(False, "--no-browser",
                                     help="Don't open the dashboard in a browser."),
) -> None:
    """Start the proxy daemon (and dashboard, by default)."""
    if _is_running():
        console.print("[yellow]Already running.[/]")
        return
    # Backup ledger BEFORE anything claims the file lock.
    s_pre = get_settings()
    snap = _snapshot_db(s_pre)
    if snap is not None:
        console.print(f"[dim]ledger snapshot: {snap.name}[/]")
    if foreground:
        from contextos.daemon import run
        run()
        return

    # Background spawn. Two Windows-specific concerns to handle:
    # 1. The child must outlive the parent — otherwise when this CLI exits
    #    (timeout, Ctrl+C, anything), Windows tears the daemon down with it.
    #    Solved with DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP.
    # 2. Any death message the daemon emits to stderr must survive, or future
    #    silent crashes are undebuggable. Solved by piping to log files in
    #    the data dir.
    s = get_settings()
    s.log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = s.log_dir / "daemon.stdout.log"
    stderr_log = s.log_dir / "daemon.stderr.log"

    # Handles must remain open for the subprocess's lifetime — a context manager
    # would close them before Popen inherits them. Suppress SIM115.
    popen_kwargs: dict = {
        "stdout": open(stdout_log, "ab", buffering=0),  # noqa: SIM115
        "stderr": open(stderr_log, "ab", buffering=0),  # noqa: SIM115
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200.
        # Together they make the child a true Windows service-style daemon that
        # cannot be killed by the parent exiting or by Ctrl+C in the parent.
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )

    proc = subprocess.Popen(
        [sys.executable, "-m", "contextos.daemon"], **popen_kwargs,
    )

    # Health-poll for up to 30s with dot progress. LanceDB + DuckDB cold-start on
    # a typical Windows laptop takes 5-10s; the old 5s window was too tight.
    deadline = time.time() + 30.0
    console.print("starting daemon ", end="")
    while time.time() < deadline:
        if _is_running():
            console.print(f"\n[green]daemon ready[/] (pid {proc.pid})")
            if not no_dashboard:
                dash_pid = _spawn_dashboard(s)
                if dash_pid is None:
                    console.print("[yellow]dashboard skipped: streamlit not installed.[/]")
                    console.print("  install with: pip install 'contextos-dd[dashboard]'")
                else:
                    url = f"http://{s.proxy_host}:{s.dashboard_port}"
                    console.print(f"[green]dashboard ready[/] (pid {dash_pid}) at {url}")
                    if not no_browser:
                        # Streamlit needs a couple seconds to bind. Open anyway —
                        # the browser will retry the page if connection refused.
                        with contextlib.suppress(Exception):
                            webbrowser.open(url)
            return
        console.print(".", end="")
        time.sleep(0.25)
    console.print("")

    # Timeout. Do NOT kill the daemon — it may still be coming up. Just report
    # where the user can find evidence of what went wrong.
    console.print("[yellow]Daemon didn't become healthy within 30s.[/]")
    console.print(f"  pid: {proc.pid} (still running; investigate before killing)")
    console.print(f"  stderr: {stderr_log}")
    console.print(f"  stdout: {stdout_log}")
    console.print(f"  app log: {s.log_dir / 'contextos.log'}")
    console.print("\nTry: [bold]contextos start --foreground[/] to see live output.")
    raise typer.Exit(1)


@app.command()
def stop() -> None:
    """Stop the proxy daemon and dashboard."""
    s = get_settings()
    if stop_daemon():
        console.print("[green]daemon stop signal sent.[/]")
    else:
        console.print("[yellow]daemon not running.[/]")
    if _stop_dashboard(s):
        console.print("[green]dashboard stop signal sent.[/]")


@app.command(name="export")
def export_cmd(
    session_id: str = typer.Argument(..., help="Session id (from `contextos status`)"),
    out: Path = typer.Option(..., "--out", "-o", help="Output JSON file"),  # noqa: B008
) -> None:
    """Export the full, untrimmed history for a session to a JSON file.

    Pulls from the daemon's append-only ledger over HTTP — proves that
    classification/rebuild never deletes turns from disk."""
    s = get_settings()
    url = f"http://{s.proxy_host}:{s.proxy_port}/_contextos/session/{session_id}/full"
    try:
        r = httpx.get(url, timeout=10.0)
    except httpx.HTTPError as e:
        console.print(f"[red]daemon unreachable:[/] {e}")
        raise typer.Exit(1) from None
    if r.status_code != 200:
        console.print(f"[red]error {r.status_code}:[/] {r.text[:200]}")
        raise typer.Exit(1)
    turns = r.json()
    if not turns:
        console.print(f"[yellow]no turns recorded for session {session_id}[/]")
        raise typer.Exit(1)
    out.write_text(json.dumps(turns, indent=2), encoding="utf-8")
    console.print(f"[green]wrote {len(turns)} turns[/] -> {out}")


@app.command()
def install(
    skip_models: bool = typer.Option(
        False, "--skip-models",
        help="Don't download the local LLM + embedder during install "
             "(use for air-gapped installs; first compaction will pull them).",
    ),
) -> None:
    """Detect supported IDEs, back up their configs, patch base URLs, "
    download local models, start daemon."""
    patched = install_all()
    if not patched:
        console.print("[yellow]No IDE configs were patched (none detected).[/]")
    else:
        for t in patched:
            console.print(f"[green]patched[/] {t.name}  ({t.config_path})")

    if not skip_models:
        console.print("\n[bold]Downloading local models[/] (one time, ~430 MB)")
        try:
            from contextos.llm import warmup as do_warmup
            do_warmup(get_settings(), on_progress=lambda m: console.print(f"  {m}"))
            console.print("[green]models ready[/]")
        except Exception as e:
            console.print(f"[yellow]warmup skipped: {e}[/]")
            console.print("  models will be downloaded on first compaction.")
    else:
        console.print("[yellow]--skip-models set; models will download on first use.[/]")

    if not _is_running():
        start(foreground=False)


@app.command()
def warmup() -> None:
    """Download the local LLM and embedder into the model cache."""
    from contextos.llm import warmup as do_warmup
    console.print("[bold]Downloading local models[/]")
    try:
        out = do_warmup(get_settings(), on_progress=lambda m: console.print(f"  {m}"))
        for label, path in out.items():
            console.print(f"[green]{label}[/]: {path}")
    except Exception as e:
        console.print(f"[red]warmup failed:[/] {e}")
        raise typer.Exit(1) from None


@app.command()
def uninstall() -> None:
    """Restore IDE configs and stop the daemon."""
    restored = uninstall_all()
    for t in restored:
        console.print(f"[green]restored[/] {t.name}")
    stop_daemon()
    console.print("Done.")


@app.command()
def dashboard(
    port: int = typer.Option(None, help="Override dashboard port (default from settings)"),
) -> None:
    """Launch the Streamlit dashboard."""
    s = get_settings()
    bind_port = port or s.dashboard_port
    script = Path(__file__).parent / "dashboard" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(script),
        "--server.port", str(bind_port),
        "--server.address", s.proxy_host,
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    console.print(f"[green]Launching dashboard[/] at http://{s.proxy_host}:{bind_port}")
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        console.print("[red]Streamlit not installed.[/] Run: pip install 'context-os[dashboard]'")
        raise typer.Exit(1) from None


def _check(label: str, ok: bool, detail: str = "") -> None:
    mark = "[green]OK[/]" if ok else "[red]!![/]"
    console.print(f"  {mark} {label}" + (f"  [dim]{detail}[/]" if detail else ""))


def _module_present(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def _port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


@app.command()
def doctor() -> None:
    """Run preflight checks: paths, deps, ports, IDE configs, daemon health."""
    s = get_settings()
    console.print("[bold]ContextOS doctor[/]")

    console.print("\n[bold]Paths[/]")
    _check(f"data dir   {s.data_dir}", s.data_dir.exists())
    _check(f"log dir    {s.log_dir}", s.log_dir.exists())
    _check(f"db file    {s.db_path}", s.db_path.exists(), "created on first request")
    _check(f"model dir  {s.model_dir}", s.model_dir.exists())

    console.print("\n[bold]Dependencies[/]")
    _check("llama-cpp-python", _module_present("llama_cpp"),
           "required for compaction summaries")
    _check("fastembed",        _module_present("fastembed"),
           "required for retrieval embeddings")
    _check("lancedb",          _module_present("lancedb"))
    _check("streamlit",        _module_present("streamlit"),
           "install with: pip install 'context-os[dashboard]'")

    console.print("\n[bold]Network[/]")
    running = _is_running()
    if running:
        _check(f"proxy http://{s.proxy_host}:{s.proxy_port}", True, "daemon running")
    else:
        _check(f"port {s.proxy_port} free", _port_free(s.proxy_host, s.proxy_port),
               "daemon stopped - port should be free")
    _check(f"dashboard port {s.dashboard_port} free",
           _port_free(s.proxy_host, s.dashboard_port))

    console.print("\n[bold]IDEs[/]")
    targets = detect()
    if not targets:
        console.print("  [yellow]no supported IDE configs found[/]")
    for t in targets:
        _check(f"{t.name}  {t.config_path}", True)


if __name__ == "__main__":
    app()
