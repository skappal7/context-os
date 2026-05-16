# Installing ContextOS

This is the full first-run walkthrough. Most users only need `pip install contextos-dd && contextos install` — but if you want to know exactly what's happening, this is the doc.

---

## Prerequisites

- **Python 3.11 or 3.12**
- **One of the supported IDEs already installed:** Claude Code, Cursor, Codex CLI, Continue, or Aider
- **An API key already configured in your IDE** for Anthropic or OpenAI. ContextOS doesn't manage API keys; your IDE keeps doing that.
- **~500 MB of free disk** for the local models
- **Internet access** during install (for the model download) — unless you use `--skip-models`

ContextOS works on Windows, macOS, and Linux.

---

## Step 1 — Install the package

```bash
pip install contextos-dd
```

This pulls the package and its dependencies (FastAPI, DuckDB, LanceDB, llama-cpp-python, fastembed, etc.). Takes 30–60 seconds depending on your connection.

### Windows note: prebuilt llama-cpp wheel

On Windows, `pip` may try to build `llama-cpp-python` from source and hit Windows' 260-char path limit. Avoid that by installing the prebuilt wheel **first**:

```powershell
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
pip install contextos-dd
```

### Old or virtualised CPUs

ContextOS pins `llama-cpp-python==0.2.90` because newer wheels include AVX-512 instructions that crash on Intel 12th/13th-gen consumer CPUs (where AVX-512 is microcode-disabled). If your CPU is older than ~2013, even 0.2.90 may not work — open an issue and we'll add a fallback.

---

## Step 2 — Run `contextos install`

```bash
contextos install
```

What happens, in order:

1. **IDE detection.** Looks for these files; patches whichever exist:
   - `~/.claude/settings.json` (Claude Code)
   - `~/.cursor/settings.json` (Cursor)
   - `~/.codex/config.json` (Codex CLI)
   - `~/.continue/config.json` (Continue)
   - `~/.aider.conf.yml` (Aider)
2. **Backup.** Every file we touch is copied to `~/.contextos/backups/<ide>.<timestamp>.<ext>` first.
3. **Patch.** We set the API base URL to `http://127.0.0.1:9137`.
4. **Model download (the slow step).** Two files pulled from HuggingFace into `~/.contextos/models/`:
   - `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` — ~400 MB
   - `BAAI/bge-small-en-v1.5` ONNX bundle — ~30 MB
5. **Daemon start.** The proxy starts on `127.0.0.1:9137` and writes its PID to `~/.contextos/daemon.pid`.

Total time: **2–5 minutes** depending on connection speed.

### Air-gapped or offline install

```bash
contextos install --skip-models
```

The daemon will still start and route IDE traffic correctly. Compaction silently no-ops until models are present — you'll lose narrative summaries but still get **DEAD-turn removal and HOT-window trimming (~25–35% savings)**.

To install models later, when you have internet:

```bash
contextos warmup
```

Or place the files manually in `~/.contextos/models/` — filenames must match those in step 4.

---

## Step 3 — Verify

```bash
contextos doctor
```

Expected output:

```
Paths
  OK  data dir   ~/.contextos
  OK  log dir    ~/.contextos/logs
  OK  db file    ~/.contextos/ledger.duckdb
  OK  model dir  ~/.contextos/models

Dependencies
  OK  llama-cpp-python
  OK  fastembed
  OK  lancedb
  OK  streamlit

Network
  OK  proxy http://127.0.0.1:9137  daemon running
  OK  dashboard port 9138 free

IDEs
  OK  claude-code  ~/.claude/settings.json
```

Then use your IDE normally. Open the dashboard to see token savings in real time:

```bash
contextos dashboard
```

Browser opens `http://127.0.0.1:9138`.

---

## What lives where

```
~/.contextos/
  ledger.duckdb          session + turn ledger (DuckDB; ~1 MB per long session)
  daemon.pid             daemon pid (deleted on clean shutdown)
  backups/
    claude-code.20260515T101500Z.json
    claude-code.latest.json
    cursor.latest.json
    ...
  archive/               LanceDB vector store for retrieval
  models/
    Qwen2.5-0.5B-Instruct-Q4_K_M.gguf   ~400 MB
    models--BAAI--bge-small-en-v1.5/     ~30 MB
  logs/
    contextos.log        rolling daemon log (UTF-8)
```

On Windows these paths live under `%LOCALAPPDATA%\DataDojo\contextos\` (typically `C:\Users\<you>\AppData\Local\DataDojo\contextos\`).

---

## Privacy guarantees, plainly

**ContextOS does not send your code or conversation to any third party we control.** The only outbound HTTP traffic ContextOS initiates:

1. **Model downloads** during `install` or `warmup` — public files from HuggingFace.
2. **Forwarding your IDE's chat request upstream** — to whatever cloud LLM (`api.anthropic.com`, `api.openai.com`, etc.) your IDE was already configured to use.

That's it. No telemetry, no usage reporting, no cloud sync, no shared memory, no analytics. The proxy reduces the payload before forwarding; everything else stays on disk in `~/.contextos/`.

---

## Uninstall

```bash
contextos uninstall
```

- Restores every IDE config we touched (from `~/.contextos/backups/*.latest.*`).
- Stops the daemon.
- **Does not** delete the ledger, archive, models, or logs — they stay in case you reinstall later.

To wipe everything:

```bash
contextos uninstall
rm -rf ~/.contextos          # Linux / macOS
Remove-Item -Recurse -Force $env:LOCALAPPDATA\DataDojo\contextos   # Windows
```

Then `pip uninstall contextos-dd` to remove the package itself.

---

## Troubleshooting

### `contextos doctor` shows daemon stopped

```bash
contextos start
```

If that fails, two logs exist for the background daemon:

- `~/.contextos/logs/daemon.stderr.log` — anything the daemon wrote to stderr (uncaught exceptions, OS-level death messages, uvicorn startup errors)
- `~/.contextos/logs/contextos.log` — the daemon's own Python logging (request flow, savings)

For live diagnostics, run the daemon in the foreground:

```bash
contextos start --foreground
```

Everything streams to your terminal in real time. Ctrl+C stops it cleanly.

### `llama-cpp-python` install errored with `[WinError -1073741795]` or `STATUS_ILLEGAL_INSTRUCTION`

Your CPU doesn't support an instruction the wheel uses (usually AVX-512). ContextOS pins `0.2.90` to avoid this; if it still trips, reinstall:

```bash
pip install --force-reinstall "llama-cpp-python==0.2.90" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

### Pip errored about Windows long paths

Install the prebuilt wheel first (see Step 1). Or enable Long Paths globally:

```powershell
# Run once as Administrator:
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

### Compaction is too slow / takes ~30s on first batch

The first compaction job loads the model into RAM (~5–10s on CPU). Subsequent jobs are 1–2s. If it's still slow, your model file may be corrupt:

```bash
rm ~/.contextos/models/Qwen2.5-*.gguf
contextos warmup
```

### Model download failed

Check connectivity to `huggingface.co`. Behind a corporate proxy? Set `HF_HUB_ENABLE_HF_TRANSFER=0` and/or `HTTPS_PROXY=http://your-proxy:port` in the environment before running `contextos warmup`.

### Streamlit dashboard says "Ledger not found yet"

You haven't made any API calls through the proxy yet. Make one call from your IDE; refresh the page.

### IDE still hits the cloud directly after install

Restart the IDE. Most IDEs read their settings file at startup and don't notice mid-session changes.

---

## Next steps

- Browse the dashboard: `contextos dashboard`
- Read the [README](./README.md) for the high-level pitch
- File issues at https://github.com/DataDojo/context-os/issues
