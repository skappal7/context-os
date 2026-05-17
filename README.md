<div align="center">

# 🧠 ContextOS

### *Stop paying for tokens your AI doesn't need.*

**A local-first memory layer for Claude Code, Cursor, Codex, Continue, and Aider.**
ContextOS sits between your IDE and the cloud LLM, quietly trimming stale conversation history before it costs you money.

[![PyPI](https://img.shields.io/pypi/v/contextos-dd?color=blue&label=pypi)](https://pypi.org/project/contextos-dd/)
[![Python](https://img.shields.io/pypi/pyversions/contextos-dd)](https://pypi.org/project/contextos-dd/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-55%20passing-brightgreen)](#)
[![Local-First](https://img.shields.io/badge/privacy-local--first-purple)](#-privacy)

```bash
pip install contextos-dd && contextos install
```

</div>

---

## ✨ What it does

> Your long AI sessions get expensive because every message resends the entire history. **ContextOS fixes that** — on your machine, with zero session data leaving your computer.

| 🪶 | **50–70% fewer tokens** on long sessions |
|---|---|
| ⚡ | **Sub-100ms overhead** — local FastAPI proxy with streaming passthrough |
| 🔒 | **Zero telemetry, zero cloud sync** — everything in `~/.contextos/` |
| 🧩 | **Works with 5 IDEs out of the box** — one install command, all of them |
| 📊 | **Live dashboard** showing what was trimmed, what was saved, and why |
| 💾 | **Append-only ledger** — your history is never destroyed, just compressed for transit |

---

## 🚀 60-second install

```bash
pip install contextos-dd
contextos install
```

That single command:

1. 🔍 Detects supported IDE configs (Claude Code, Cursor, Codex CLI, Continue, Aider)
2. 💾 Backs them up to `~/.contextos/backups/`
3. 🔌 Patches them to route through the local proxy on `127.0.0.1:9137`
4. 📥 Downloads two small models (~430 MB, **one time**) to `~/.contextos/models/`
5. ▶️ Starts the daemon **and** opens the dashboard in your browser

> 💡 **Offline / air-gapped?** Use `contextos install --skip-models`. Models download on first compaction.

📖 See [`INSTALL.md`](./INSTALL.md) for the full walkthrough.

---

## 🧬 How it works

```
┌────────────┐    raw history     ┌────────────────┐    trimmed payload   ┌──────────────┐
│ Claude Code│ ─────────────────► │   ContextOS    │ ───────────────────► │  Anthropic   │
│   Cursor   │                    │   (localhost   │                      │   OpenAI     │
│   Codex    │ ◄───────────────── │     :9137)     │ ◄─────────────────── │              │
└────────────┘    streamed reply  └────────┬───────┘     full response    └──────────────┘
                                            │
                                  ┌─────────┴──────────┐
                                  │  Local DuckDB +    │
                                  │  Qwen2.5-0.5B +    │
                                  │  bge-small-en      │
                                  └────────────────────┘
```

Every turn in your conversation is tagged by **heat**:

| Heat | Meaning | What ContextOS does |
|------|---------|---------------------|
| 🔥 **HOT** | last 5 turns | Always sent verbatim |
| ☀️ **WARM** | within last 15 | Always sent verbatim |
| ❄️ **COLD** | older | Replaced by a narrative summary from local Qwen2.5 |
| 💀 **DEAD** | duplicate or empty | Dropped silently |

Trigger phrases like *"as we discussed earlier"* fire a vector recall from a local LanceDB store and re-inject the missing context on the next turn — so summarized history is still semantically retrievable.

---

## 🎛️ Commands

| Command | What it does |
|---|---|
| `contextos install` | Detect IDEs, back up configs, patch URLs, download models, start daemon + dashboard |
| `contextos install --skip-models` | Same as above but skip the model download (air-gapped) |
| `contextos start` | Start daemon + dashboard; auto-snapshots the ledger first |
| `contextos start --no-dashboard` | Start the daemon only (no browser) |
| `contextos start --foreground` | Run daemon in the foreground (debugging) |
| `contextos stop` | Stop daemon **and** dashboard |
| `contextos status` | Show daemon health and detected IDEs |
| `contextos dashboard` | Launch the Streamlit dashboard at `http://127.0.0.1:9138` |
| `contextos doctor` | Preflight checks: paths, deps, ports, IDE configs |
| `contextos export <sid> --out file.json` | Export full untrimmed history for a session (proves nothing was deleted) |
| `contextos warmup` | (Re-)download local models |
| `contextos uninstall` | Restore original IDE configs, stop daemon |

---

## 📦 What gets downloaded

| File | Size | Purpose |
|---|---|---|
| `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` | ~400 MB | Compaction — summarizing COLD turns |
| `bge-small-en-v1.5` ONNX | ~30 MB | Embeddings for semantic recall |

One time. Lives on disk forever. Re-pull anytime with `contextos warmup`.

---

## 🔐 Privacy

ContextOS is **local-first by construction**:

- 🚫 **No telemetry.** Zero. We do not phone home.
- 🚫 **No cloud sync.** Sessions, summaries, embeddings, logs — all in `~/.contextos/` on your machine.
- 🚫 **No background uploads.** Ever.
- ✅ **Your code never reaches a third party.** The only outbound call ContextOS makes is forwarding your IDE's request to the LLM you already chose.

The **only** network traffic ContextOS initiates on its own:

- Model downloads during `install` / `warmup` (from HuggingFace)
- Forwarding your IDE's chat requests upstream — the same request your IDE was going to send anyway, just smaller.

---

## 📁 Where stuff lives

```
~/.contextos/                       (Windows: %LOCALAPPDATA%\DataDojo\contextos\)
├── ledger.duckdb                   # append-only session + turn ledger
├── daemon.pid                      # daemon process id
├── dashboard.pid                   # dashboard process id
├── backups/                        # snapshots: ledger backups + IDE config backups
│   ├── ledger-20260517-091944.duckdb
│   └── settings.json.<ts>.bak
├── archive/                        # LanceDB vector store of compacted turns
├── models/                         # Qwen2.5 GGUF + bge-small ONNX
└── logs/
    ├── contextos.log               # rolling app log (10MB × 5)
    ├── daemon.stdout.log
    └── daemon.stderr.log
```

`contextos uninstall` restores IDE configs and stops the daemon. It does **not** delete the ledger or models — they stay in case you reinstall. Nuke everything by deleting the directory above.

---

## 🩹 Troubleshooting

<details>
<summary><b>The daemon won't start / "Daemon didn't become healthy in 30s"</b></summary>

```bash
contextos start --foreground
```

Runs the daemon in your terminal so you can see the real error live. Common culprits:

- **Port 9137 already in use** — another tool grabbed it. `contextos doctor` will flag this.
- **AVX-512 crash on Intel 12th/13th-gen** — already pinned to `llama-cpp-python==0.2.90`, but if you upgraded manually, downgrade back.
- **Long Paths not enabled (Windows)** — see [INSTALL.md](./INSTALL.md#windows-long-paths).
- **Look at the logs:** `~/.contextos/logs/daemon.stderr.log` is the smoking gun.
</details>

<details>
<summary><b>Claude Code / IDE feels frozen or returns errors after install</b></summary>

**Emergency kill-switch — disables trimming without uninstalling:**

```bash
# Windows
set CONTEXTOS_PASSTHROUGH=1
contextos stop && contextos start

# macOS / Linux
export CONTEXTOS_PASSTHROUGH=1
contextos stop && contextos start
```

This makes the proxy a transparent pipe — your IDE works exactly like before, but you keep the dashboard and ledger. If this fixes the issue, please open a [GitHub issue](https://github.com/skappal7/context-os/issues) with the contents of `~/.contextos/logs/daemon.stderr.log`.

**Full rollback:**

```bash
contextos uninstall    # restores original IDE configs
```

Then restart your IDE.
</details>

<details>
<summary><b>Dashboard shows empty charts or "no data"</b></summary>

The dashboard needs a few turns of activity before charts populate:

- Most panels need 1+ active session — use your IDE for a couple of minutes.
- Some charts (by-IDE / by-model breakdowns) only render meaningfully when you have multiple sessions across multiple tools.
- The "RUNNING" spinner at top-right is Streamlit's autorefresh — that's normal.
</details>

<details>
<summary><b>Worried about losing chat history</b></summary>

You can't lose it. The ledger is **append-only** — classification and rebuild only affect what gets *sent upstream*, never what's stored on disk.

Prove it to yourself:

```bash
contextos status                        # find your session id
contextos export <session_id> --out my_history.json
```

You'll get a JSON file with every turn ever recorded for that session, in order. Plus, `contextos start` snapshots the ledger to `backups/` automatically every time it runs (keeps the last 7).
</details>

<details>
<summary><b>"Dashboard skipped: streamlit not installed"</b></summary>

```bash
pip install 'contextos-dd[dashboard]'
```
</details>

<details>
<summary><b>Uninstall didn't fully clean up</b></summary>

`contextos uninstall` is intentionally conservative — it restores IDE configs and stops the daemon, but leaves your ledger and models. Wipe everything by deleting the data directory:

- **Windows:** `rmdir /s %LOCALAPPDATA%\DataDojo\contextos`
- **macOS/Linux:** `rm -rf ~/.contextos`
</details>

---

## 🛣️ Roadmap

| Version | Status | Highlights |
|---------|--------|-----------|
| **v0.1.0** | ✅ shipped | Initial MVP: proxy, ledger, classifier, compactor, dashboard |
| **v0.1.1** | ✅ shipped | Windows daemon stability + LanceDB API drift fix |
| **v0.1.2** | ✅ shipped | Dashboard reads daemon over HTTP (fixes DuckDB lock on Windows) |
| **v0.1.3** | ✅ shipped | **Protocol-aware pipeline** (tool_use linkage, cache_control, fail-closed validator) + seamless one-command launch + auto-backup |
| **v0.1.4** | 🚧 planned | Dashboard UX overhaul with narrative insights |
| **v0.2.0** | 🔭 planned | Per-conversation session IDs, OpenAI tool-calling pinning, local semantic search |
| **Pro** | 🔭 future | MCP server, team/shared memory, React+WebSocket dashboard, cloud rollups (optional, encrypted) |

---

## 🛠️ Develop

```bash
git clone https://github.com/skappal7/context-os
cd context-os
pip install -e ".[dev,dashboard]"
ruff check .
pytest -q
```

55 tests across the proxy, classifier, compactor, ledger, dashboard, and safety layer. Includes a realistic Claude Code fixture (tool_use + tool_result + cache_control) that locks in the v0.1.3 regression fix.

---

## 📜 License & credits

Apache-2.0. Built by [DataDojo](https://github.com/DataDojo).

Vendored under the hood: [FastAPI](https://fastapi.tiangolo.com/) · [DuckDB](https://duckdb.org/) · [LanceDB](https://lancedb.com/) · [llama.cpp](https://github.com/ggerganov/llama.cpp) (via [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)) · [fastembed](https://github.com/qdrant/fastembed) · [Qwen2.5](https://huggingface.co/Qwen) · [BAAI/bge-small-en](https://huggingface.co/BAAI/bge-small-en-v1.5) · [Streamlit](https://streamlit.io/).

<div align="center">

---

**If ContextOS saves you tokens, give it a ⭐ on [GitHub](https://github.com/skappal7/context-os).**

</div>
