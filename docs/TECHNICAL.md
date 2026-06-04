# COMSOL Clippy — Technical Reference

A local, GPU-accelerated **RAG** system over COMSOL manuals, exposed as an **MCP
server** so Claude (Desktop or Code) can answer COMSOL questions with cited passages.

- **Embeddings:** [`Alibaba-NLP/gte-Qwen2-1.5B-instruct`](https://huggingface.co/Alibaba-NLP/gte-Qwen2-1.5B-instruct) (1536-dim) — GPU fp16 with automatic CPU fallback.
- **Vectorstore:** ChromaDB (persistent, on-disk, no external service).
- **Server:** MCP over stdio (FastMCP); tools `search_comsol_docs`, `list_sources`. The model is pre-warmed in a background thread on `serve` so the first query isn't slow.
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
default WSL distro, checks it has Python, and hands off to `setup/setup.sh`. If WSL is
unavailable, it falls back to **native Windows Python** (CPU). The MCP entry is
registered to match whichever runtime was chosen. WSL builds the venv at `.venv`;
native Windows uses `.venv-win` (the two are never mixed).

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
.venv/bin/python main.py serve             # start the MCP server (stdio)
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
comsol_clippy/       package: config, pdf, embeddings, manifest, store, ingest, server, cli
main.py              CLI entry (serve | ingest | query | status)
setup/               setup.sh (Linux/WSL) + setup.ps1 (Windows)
scripts/             register_mcp.py (safe Claude-config merge)
data/                GENERATED: chroma/ + manifest.json
docs/                this file
config.toml          tunable settings
pyproject.toml       dependencies
```

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
