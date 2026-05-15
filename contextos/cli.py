from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from contextos import __version__
from contextos.daemon import read_pid
from contextos.daemon import stop as stop_daemon
from contextos.installer import detect, install_all, uninstall_all
from contextos.settings import get_settings

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
def start(foreground: bool = typer.Option(False, "--foreground", "-f")) -> None:
    """Start the proxy daemon."""
    if _is_running():
        console.print("[yellow]Already running.[/]")
        return
    if foreground:
        from contextos.daemon import run
        run()
        return
    # Background spawn (detached). Logs go to ~/.contextos/logs/.
    proc = subprocess.Popen(
        [sys.executable, "-m", "contextos.daemon"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    for _ in range(50):
        if _is_running():
            console.print(f"[green]Daemon started[/] (pid {proc.pid})")
            return
        time.sleep(0.1)
    console.print("[red]Daemon failed to become healthy in time.[/]")
    raise typer.Exit(1)


@app.command()
def stop() -> None:
    """Stop the proxy daemon."""
    if stop_daemon():
        console.print("[green]Stop signal sent.[/]")
    else:
        console.print("[yellow]Daemon not running.[/]")


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
