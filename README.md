# ContextOS

**Local-first agentic memory lifecycle manager for Claude Code, Cursor, Codex, Continue, and Aider.**

ContextOS runs as a background daemon between your IDE and the cloud LLM. It classifies your conversation history by relevance, compresses stale turns into narrative summaries via a small on-device model, and forwards a clean, minimal payload upstream — cutting input tokens 50–70% on long sessions without quality loss.

**Zero bytes of your session content leave your machine** except the request that goes to your chosen cloud LLM (Anthropic, OpenAI) — which is exactly what your IDE was going to send anyway, just smaller.

Built by [DataDojo](https://github.com/DataDojo). Apache-2.0.

---

## Install

```bash
pip install contextos-dd
contextos install
```

That's it. `contextos install`:

1. Detects supported IDE configs (Claude Code, Cursor, Codex CLI, Continue, Aider)
2. Backs them up to `~/.contextos/backups/`
3. Patches them to route through the local proxy on `127.0.0.1:9137`
4. **Downloads two small models** (~430 MB total, one time) to `~/.contextos/models/`
5. Starts the daemon

The model download happens **once** during install so the first long session doesn't pause for it. For air-gapped or offline installs, use `contextos install --skip-models`.

See [INSTALL.md](./INSTALL.md) for the full first-run walkthrough, paths, privacy guarantees, troubleshooting, and uninstall semantics.

---

## What gets downloaded

| File | Size | Purpose | Where |
|---|---|---|---|
| `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` | ~400 MB | Compaction (summarising stale turns) | `~/.contextos/models/` |
| `bge-small-en-v1.5` ONNX | ~30 MB | Embeddings (vector recall) | `~/.contextos/models/` |

Both download once, then live on disk forever. Subsequent runs use the cache. Re-pull anytime with `contextos warmup`.

---

## Commands

| Command | What it does |
|---|---|
| `contextos install` | Detect IDEs, back up configs, patch URLs, download models, start daemon |
| `contextos install --skip-models` | Same as above but skip the model download |
| `contextos warmup` | Download / refresh local models |
| `contextos status` | Show daemon health and detected IDEs |
| `contextos start` / `stop` | Daemon lifecycle |
| `contextos dashboard` | Launch the Streamlit dashboard at `http://127.0.0.1:9138` |
| `contextos doctor` | Preflight checks: paths, deps, ports, IDE configs |
| `contextos uninstall` | Restore original IDE configs, stop daemon |

---

## How it works

1. IDE sends API call → `localhost:9137`
2. Proxy parses messages, classifies turns **HOT / WARM / COLD / DEAD**
3. **DEAD** (duplicates) dropped, **COLD** runs replaced with a narrative summary from the local Qwen2.5 model
4. Clean payload forwarded to `api.anthropic.com` / `api.openai.com`
5. Response streamed back unchanged; trigger phrases like *"as we discussed"* fire a vector recall from a local LanceDB archive for the next turn

---

## Privacy

- **Your code never goes to a third party.** The only outbound network call ContextOS makes is forwarding your IDE's API request to the cloud LLM you already configured your IDE to use.
- **No telemetry.** Zero. We do not phone home.
- **No cloud sync.** Sessions, summaries, embeddings, and logs live in `~/.contextos/` on your machine.
- **No background uploads.** Ever.

The only network traffic ContextOS initiates on its own:
- Model downloads during `install` or `warmup` — fetched from HuggingFace.
- Forwarding your IDE's chat requests upstream — exactly the request your IDE built.

---

## Where stuff lives

```
~/.contextos/
  ledger.duckdb          # session + turn ledger
  daemon.pid             # daemon process id
  backups/               # IDE configs we modified (so uninstall is reversible)
  archive/               # LanceDB vector store of compacted turns
  models/                # Qwen2.5 GGUF + bge-small ONNX
  logs/contextos.log     # rolling daemon log
```

`contextos uninstall` restores IDE configs and stops the daemon. By default it **does not** delete the ledger or models — they stay in case you reinstall. To wipe everything, delete `~/.contextos/` manually.

---

## Status

**Phase 1 MVP (this package):** proxy, ledger, classifier, compactor, retrieval, Streamlit dashboard, auto-install for 5 IDEs.

**`context-os-pro` (separate package, deferred):** MCP server, team / shared memory, cloud rollups, React dashboard, advanced semantic classifier.

---

## Develop

```bash
git clone https://github.com/DataDojo/context-os
cd context-os
pip install -e ".[dev,dashboard]"
ruff check .
pytest -q
```
