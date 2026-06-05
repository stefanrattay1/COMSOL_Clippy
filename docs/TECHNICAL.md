# COMSOL Clippy — Technical Reference

A local, GPU-accelerated **RAG** system over COMSOL manuals, exposed as an **MCP
server** so Claude (Desktop or Code) can answer COMSOL questions with cited passages.

- **Embeddings:** [`Qwen/Qwen3-VL-Embedding-2B`](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B) (2048-dim) — GPU fp16 with automatic CPU fallback. The repo uses it in text-only mode for COMSOL manuals, but the model can also embed images/screenshots if the pipeline grows into multimodal retrieval later.
- **Vectorstore:** ChromaDB (persistent, on-disk, no external service).
- **Server:** MCP over stdio (FastMCP); tools `search_comsol_docs`, `list_sources`. `serve` is a thin shim that forwards to a shared daemon holding the single model copy (see [Shared daemon](#shared-daemon-one-model-for-all-windows)), pre-warmed so the first query isn't slow.
- **Self-repairing:** a hash manifest re-embeds only new/changed sources and drops removed ones.

## Supported source files

In `source/` (matched case-insensitively):
- **PDF** (`.pdf`) — text layer extracted via PyMuPDF; **images/figures are ignored**
  (no OCR). Chunks carry real **page numbers** → citations like `[Manual.pdf p.412]`
  (or `p.412–413` across a page break).
- **Plain text** (`.txt`, `.md`, `.markdown`, `.rst`, `.csv`, `.text`) — read with
  encoding fallbacks (utf-8 → utf-8-sig → latin-1). No pages, so cited by chunk number:
  `[notes.md #3]`.
- A file that yields no text (scanned/image-only PDF, or empty) is skipped with a
  warning; a corrupt/password-protected file is caught per-file and skipped so it can't
  abort the whole run. Word `.docx` is not supported (export to PDF).
- Add extensions in `comsol_clippy/pdf.py` (`TEXT_EXTS`).

## Entry point

`start.cmd` (project root) is a **polyglot** launcher:

- On **Windows** it runs as a `.cmd` file (double-click) → `setup/setup.ps1`.
- On **Linux/WSL** run `bash start.cmd` → `setup/setup.sh`.

Both setup scripts run the full pipeline and are idempotent.

### Adaptive runtime
`setup.ps1` prefers running the server inside **WSL2** (for the GPU): it detects the
default WSL distro first, then any other listed distro that can actually launch `bash`,
converts the project path inside WSL with `wslpath`, and hands off to `setup/setup.sh`.
If WSL is unavailable, it falls back to **native Windows Python** (CPU). The MCP entry is
registered to match whichever runtime was chosen. WSL builds the venv at `.venv`;
native Windows uses `.venv-win` (the two are never mixed).

After dependency installation, both setup scripts print the **actual torch runtime
device** (`cuda` or `cpu`) from the environment they just built, and if an existing
venv looks broken they rebuild it once before continuing.

**Windows with no Python:** the native fallback auto-installs it. `Find-Python` first
checks whether a real `python` runs (ignoring the Microsoft Store stub), then probes
`%LOCALAPPDATA%\Programs\Python`, `%ProgramFiles%\Python`, etc. If none is found it runs
`winget install -e --id Python.Python.3.12 --silent` and re-probes the install
locations (PATH is **not** refreshed mid-session, so probing — not `python` on PATH — is
what makes it work). Only if `winget` itself is missing (very old Windows 10) does it
stop with a download link. So on Win10 21H2+/Win11 the single `start.cmd` is fully
automated even from a machine with neither WSL nor Python.

## Manual commands

```bash
.venv/bin/python main.py ingest            # build/repair the store (incremental)
.venv/bin/python main.py ingest --dry-run  # show what would change
.venv/bin/python main.py ingest --rebuild  # force full re-embed
.venv/bin/python main.py query "..."        # search from the CLI
.venv/bin/python main.py status            # health check + smoke query
.venv/bin/python main.py serve             # start the MCP server (stdio shim)
.venv/bin/python main.py daemon            # run the shared search daemon (usually auto-spawned)
.venv/bin/python main.py stop-daemon       # stop the daemon, freeing the model's RAM now
.venv/bin/python main.py restart-daemon    # stop it; the next query respawns with current code/config
.venv/bin/python main.py uninstall         # unregister the MCP server + stop the daemon
```

## Shared daemon (one model for all windows)

MCP uses **stdio**, so every Claude window launches its own `serve` process. If each
of those loaded the embedding model, N open windows would mean N model copies in RAM
(~700 MB host RSS each, plus a CUDA context per process). To avoid that:

- **`serve` is a thin shim.** It imports no torch/chromadb (stays ~tens of MB) and
  forwards each tool call over a **Unix socket** to a daemon.
- **The daemon** (`comsol_clippy/daemon.py`) loads the model + store **once** and is
  shared by every window. The first shim to start auto-spawns it; the rest connect.
  A file lock serializes the spawn so a simultaneous launch race produces only one
  daemon.
- **Latency vs. RAM:** the daemon pre-warms the model on startup (first query fast),
  and **idle-exits after 30 min** of no connections (`--idle-timeout`, `0` = never) so
  the RAM is reclaimed when you stop working. The next `serve` respawns it.
- **Picks up updates automatically:** the daemon also self-exits (when idle) if
  `config.toml` or any `comsol_clippy/*.py` changes, so after an update/`ingest` the
  next query runs fresh code. `setup` additionally calls `restart-daemon` explicitly.
- **Native Windows fallback:** the daemon needs `AF_UNIX` + `fcntl` (POSIX). On native
  Windows (the CPU fallback runtime) `serve` loads the model **in-process** instead —
  the original behaviour. Under WSL (the GPU path, where shared RAM matters) the daemon
  is always used.

**Runtime files** (socket, lock, pid, log) live under `$XDG_RUNTIME_DIR/comsol-clippy-<hash>/`
(falling back to `/tmp`), **not** under `data/`. This is deliberate: under WSL the
project lives on a Windows drive (`/mnt/...`, DrvFs), and `AF_UNIX` `bind()` fails there
with `Errno 95 Operation not supported`. The `<hash>` is derived from the project root so
two checkouts don't share a socket. `daemon.log` captures the daemon's startup/errors.

### Protocol

Newline-delimited JSON over the socket (`comsol_clippy/protocol.py`), stdlib only:

```
request:  {"method": "search"|"list_sources"|"ping", "params": {...}}
response: {"ok": true, "result": <json>} | {"ok": false, "error": "<message>"}
```

## How re-embedding works

`data/manifest.json` links the vectorstore to each source PDF by `sha256`. On every
`ingest`:

- **new file** → embed it
- **changed file** (hash differs) → drop its old chunks, re-embed
- **removed file** → delete its chunks
- **missing store / changed model or chunk params** → full rebuild

Unchanged runs are a fast no-op.

## Configuration

Edit [`../config.toml`](../config.toml) — embedding model, chunk sizes, batch size,
paths. Changing the model or chunk params triggers a full rebuild on the next `ingest`.

## Layout

```
start.cmd            single cross-platform launcher (root)
source/              your input PDFs
comsol_clippy/       package: config, pdf, embeddings, manifest, store, ingest,
                              server, cli, daemon, client, protocol, workflow/
main.py              CLI entry (serve | ingest | query | status)
setup/               setup.sh (Linux/WSL) + setup.ps1 (Windows)
scripts/             register_mcp.py (safe Claude-config merge)
data/                GENERATED: chroma/ + manifest.json
docs/                this file
config.toml          tunable settings
pyproject.toml       dependencies
```

## Optional `.mph` workflow suite

`comsol_clippy/workflow/` is an optional automation layer around the external
`mph` package. It is deliberately isolated from the default RAG path so the light
test suite and basic setup do not require COMSOL/JPype.

- `workflow/runtime.py` lazily creates an `mph` client, loads/snapshots models,
  applies structured edits, and saves `.mph` files.
- `workflow/plan.py` defines the JSON plan schema used by both hand-authored plans
  and AI-generated plans.
- `workflow/agent.py` builds a planner prompt from the user request, current model
  snapshot, and optional manual search hits from the existing RAG engine.
- `workflow/cli.py` exposes `python main.py workflow ...` commands for inspect,
  create, apply-plan, agent-prompt, and apply-agent-response.

The planner/agent integration is intentionally provider-agnostic: this repo builds
the grounded prompt and parses the resulting JSON plan, but does not hard-code a
specific hosted LLM dependency.

## MCP tools

- `search_comsol_docs(query, top_k=5)` → relevant passages, each prefixed with a
  citation like `[HeatTransferModuleUsersGuide.pdf p.412]`.
- `list_sources()` → indexed manuals with page/chunk counts.

## Config files touched (merged, never clobbered)

- Windows Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux Claude Desktop: `~/.config/claude/claude_desktop_config.json`
- Claude Code: `~/.claude.json`

A `.bak` is written before each edit; existing servers (e.g. `legalgpt`) are preserved.

## Troubleshooting

- **Tools don't appear in Claude Desktop:** fully quit and reopen it (not just close the window).
- **`status` says collection MISSING/empty:** run `main.py ingest`.
- **CUDA OOM:** lower `[embedding].batch_size` in `config.toml`.
- **Re-embed everything:** `main.py ingest --rebuild`.
- **Hugging Face model download is flaky or slow:** the setup exports
  `HF_HUB_DISABLE_XET=1` so downloads stay on the plain HTTPS path instead of the
  Xet transport. That trims one moving part from setup and avoids Xet-specific
  failures while fetching the embedding model.
- **High RAM with several Claude windows:** check `main.py status` shows the daemon
  `running` (one model copy shared). `main.py stop-daemon` frees it immediately; it
  also self-exits after 30 min idle. If a query says "backend unavailable", see
  `$XDG_RUNTIME_DIR/comsol-clippy-*/daemon.log` for the daemon's startup error.
- **`Errno 95 Operation not supported` in daemon.log:** the socket landed on a Windows
  drive (DrvFs). It should live under `$XDG_RUNTIME_DIR`/`/tmp`; ensure that env var
  points at a native-Linux tmpfs.

### Debugging the daemon

The daemon normally runs detached (auto-spawned by the first shim) and logs its
stderr to `$XDG_RUNTIME_DIR/comsol-clippy-<hash>/daemon.log` (falls back to
`$TMPDIR`; the `<hash>` is a short digest of the project root so two checkouts
don't collide). To watch it live instead, stop any running copy and run it in the
foreground:

```bash
python main.py stop-daemon    # free the existing copy first
python main.py daemon         # runs in the foreground; Ctrl-C to stop
```

You'll see `[daemon] listening on …`, the pre-warm line once the model loads, and
any per-request errors as they happen. A clean `[daemon] could not bind …` line
means another daemon already owns the socket (or the path isn't bindable — see the
DrvFs note above). `python main.py status` reports whether the daemon is
`running`/`stopped` and ends with a smoke query that exercises the full path.
