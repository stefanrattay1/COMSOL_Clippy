#!/usr/bin/env bash
# COMSOL Clippy - setup for Linux / WSL2 (lives in setup/, project root is the parent).
# Checks requirements, builds/repairs the vectorstore, registers the MCP server,
# verifies it, and runs a test query. Idempotent and re-runnable.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
VENV="$PROJECT_DIR/.venv"
PY="$VENV/bin/python"
HAS_SOURCES=1

# --- Flag surface (parsed before any heavy work so --help is instant). ---
SKIP_CLAUDE_TEST=0
SKIP_INGEST=0
REBUILD=0
DEVICE_OVERRIDE=""   # "", "cpu", or "gpu"

usage() {
  cat <<'USAGE'
COMSOL Clippy setup (Linux/WSL)

Usage: start.cmd [options]      (or: bash setup/setup.sh [options])

Options:
  --skip-claude-test   Don't launch the one-shot `claude -p` MCP smoke test.
  --skip-ingest        Register/verify without (re-)embedding source documents.
  --rebuild            Force a full re-embed of every document.
  --cpu                Install/use CPU torch even if an NVIDIA GPU is present.
  --gpu                Install/use CUDA torch even if nvidia-smi is not detected.
  -h, --help           Show this help and exit.

Re-runnable and idempotent. Without options, runs the full setup pipeline.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-claude-test) SKIP_CLAUDE_TEST=1 ;;
    --skip-ingest)      SKIP_INGEST=1 ;;
    --rebuild)          REBUILD=1 ;;
    --cpu)              DEVICE_OVERRIDE="cpu" ;;
    --gpu)              DEVICE_OVERRIDE="gpu" ;;
    -h|--help)          usage; exit 0 ;;
    *) echo "[setup] unknown option: $1" >&2; echo "" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# --- Concurrency guard: don't let two setup runs race on the venv/pip/ingest. ---
# flock holds an exclusive lock for the life of this script; a second run exits early
# with a clear message instead of corrupting a half-built venv.
LOCK="$PROJECT_DIR/.setup.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "[setup] Another setup is already running in this folder. Wait for it to finish, then re-run." >&2
    exit 1
  fi
fi

# --- Friendly failure: turn the next 'set -e' abort into plain language. ---
fail() { echo ""; echo "[setup] PROBLEM: $1" >&2; echo "[setup] $2" >&2; exit 1; }
trap 'fail "setup stopped on an unexpected error (line $LINENO)." "Scroll up for the last command'\''s output; fix that and re-run start.cmd."' ERR

# Keep the setup window readable: a per-chunk download timeout (so a stalled model
# download errors and retries instead of hanging), and no tqdm progress-bar spam.
export HF_HUB_DOWNLOAD_TIMEOUT=30
export HF_HUB_DISABLE_PROGRESS_BARS=1
# Use the plain HTTPS download path, not Xet: the pinned (old) huggingface_hub still
# calls the deprecated hf_xet.download_files(), which spams a DeprecationWarning on
# every model fetch. Disabling Xet avoids that code path. (Also set centrally in
# comsol_clippy/__init__.py; exported here so any direct HF call during setup is covered.)
export HF_HUB_DISABLE_XET=1

echo "=============================================="
echo " COMSOL Clippy setup (Linux/WSL)"
echo " Project: $PROJECT_DIR"
echo "=============================================="

# --- Stage 1: ensure python3 ---
if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "[setup] python3 not found; attempting apt install..."
    sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-pip || {
      echo "[setup] ERROR: could not install python3. Install it and re-run." >&2; exit 1; }
  else
    echo "[setup] ERROR: python3 is missing and this Linux distribution has no apt-get fallback in setup.sh." >&2
    echo "[setup] Install python3 + python3-venv, then re-run start.cmd." >&2
    exit 1
  fi
fi

# --- Stage 2: ensure venv + deps ---
HAVE_UV=0
if command -v uv >/dev/null 2>&1; then HAVE_UV=1; fi

create_venv() {
  echo "[setup] creating venv at .venv ..."
  if [ "$HAVE_UV" = "1" ]; then uv venv "$VENV"; else python3 -m venv "$VENV"; fi
}

reset_venv() {
  echo "[setup] rebuilding .venv ..."
  rm -rf "$VENV"
  create_venv
}

venv_looks_usable() {
  [ -x "$PY" ] && "$PY" -c 'import site, sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' >/dev/null 2>&1
}

supported_sources_present() {
  PROJECT_DIR_ENV="$PROJECT_DIR" "$PY" -c 'import os, sys; from pathlib import Path; from comsol_clippy.pdf import list_sources; sys.exit(0 if list_sources(Path(os.environ["PROJECT_DIR_ENV"]) / "source") else 1)' >/dev/null 2>&1
}

probe_runtime_device() {
  "$PY" -c 'from comsol_clippy.embeddings import detect_device; print(detect_device())'
}

if [ "$HAVE_UV" = "0" ] && ! python3 -c "import venv" >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "[setup] python3-venv missing; attempting apt install..."
    sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip || {
      echo "[setup] ERROR: could not install python3-venv. Install it and re-run." >&2; exit 1; }
  else
    echo "[setup] ERROR: python3 exists but the venv module is unavailable, and no apt-get fallback is available." >&2
    echo "[setup] Install python3-venv (or use uv), then re-run start.cmd." >&2
    exit 1
  fi
fi

if [ -d "$VENV" ] && ! venv_looks_usable; then
  echo "[setup] existing .venv looks broken; rebuilding it before install ..."
  reset_venv
elif ! venv_looks_usable; then
  create_venv
fi

# Detect CUDA to choose the torch wheel (an explicit --cpu/--gpu overrides detection).
TORCH_INDEX=""
TORCH_CHECK='import torch'
want_cuda=0
if [ "$DEVICE_OVERRIDE" = "gpu" ]; then
  want_cuda=1
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "[setup] --gpu given but nvidia-smi not found; installing CUDA torch anyway (it may fall back to CPU at runtime)."
  fi
elif [ "$DEVICE_OVERRIDE" = "cpu" ]; then
  echo "[setup] --cpu given - installing CPU torch."
elif command -v nvidia-smi >/dev/null 2>&1; then
  want_cuda=1
fi

if [ "$want_cuda" = "1" ]; then
  echo "[setup] installing CUDA (cu121) torch."
  TORCH_INDEX="--index-url https://download.pytorch.org/whl/cu121"
  TORCH_CHECK='import sys, torch; sys.exit(0 if getattr(torch.version, "cuda", None) else 1)'
else
  echo "[setup] installing CPU torch."
fi

pip_install() {
  if [ "$HAVE_UV" = "1" ]; then uv pip install --python "$PY" "$@"; else "$PY" -m pip install "$@"; fi
}

install_runtime_stack() {
  if ! "$PY" -c "$TORCH_CHECK" >/dev/null 2>&1; then
    echo "[setup] installing torch ..."
    # shellcheck disable=SC2086
    pip_install --upgrade pip
    pip_install --upgrade torch $TORCH_INDEX
  fi
  echo "[setup] installing project dependencies ..."
  pip_install -e .
}

install_runtime_stack

if RUNTIME_DEVICE="$(probe_runtime_device 2>/dev/null)"; then
  echo "[setup] runtime device available to torch: $RUNTIME_DEVICE"
else
  echo "[setup] environment health probe failed after install; rebuilding .venv once ..."
  reset_venv
  install_runtime_stack
  RUNTIME_DEVICE="$(probe_runtime_device)"
  echo "[setup] runtime device available to torch: $RUNTIME_DEVICE"
fi

# --- Stage 3: ingest (incremental) ---
if ! supported_sources_present; then
  HAS_SOURCES=0
  echo ""
  echo "[setup] NOTE: the 'source/' folder is empty."
  echo "[setup] Add your COMSOL manuals (PDF) or notes (.txt/.md) to:"
  echo "[setup]   $PROJECT_DIR/source"
  echo "[setup] then re-run start.cmd. Continuing setup so the server still registers."
elif [ "$SKIP_INGEST" = "1" ]; then
  echo "[setup] skipping ingest by request (--skip-ingest)."
else
  echo "[setup] building/repairing vectorstore ..."
  if [ "$REBUILD" = "1" ]; then
    "$PY" main.py ingest --rebuild
  else
    "$PY" main.py ingest
  fi
fi

# --- Stage 4: register MCP server ---
echo "[setup] registering MCP server in Claude config(s) ..."
"$PY" scripts/register_mcp.py --command "$PY" --arg main.py --arg serve --cwd "$PROJECT_DIR"

if grep -qi microsoft /proc/version 2>/dev/null && command -v wslpath >/dev/null 2>&1; then
  DISTRO="${WSL_DISTRO_NAME:-}"
  WIN_APPDATA_WIN="$(cmd.exe /c 'echo %APPDATA%' 2>/dev/null | tr -d '\r\n' || true)"
  WIN_APPDATA="$(wslpath -u "$WIN_APPDATA_WIN" 2>/dev/null || true)"
  if [ -n "$DISTRO" ] && [ -n "$WIN_APPDATA" ]; then
    WIN_CFG="$WIN_APPDATA/Claude/claude_desktop_config.json"
    echo "[setup] also registering wsl.exe wrapper into Windows Claude Desktop ..."
    "$PY" scripts/register_mcp.py --command "wsl.exe" \
      --arg=-d --arg "$DISTRO" --arg=--cd --arg "$PROJECT_DIR" --arg "$PY" --arg main.py --arg serve \
      --target "$WIN_CFG"
  elif [ -n "$DISTRO" ]; then
    echo "[setup] could not resolve the Windows Claude Desktop config path from WSL; skipping that registration."
  fi
fi

# --- Stage 5: restart any running daemon so this run's code/store takes effect ---
echo "[setup] restarting search daemon (if running) ..."
"$PY" main.py restart-daemon || true

# --- Stage 6: verify ---
if [ "$HAS_SOURCES" = "1" ]; then
  echo "[setup] verifying ..."
  "$PY" main.py status
else
  echo "[setup] skipping vectorstore verification until source/ has documents."
fi

# --- Stage 7: test query + optional live MCP test ---
if [ "$HAS_SOURCES" = "1" ]; then
  echo ""
  echo "=============================================="
  echo " Test query"
  echo "=============================================="
  "$PY" main.py query "How do I set up conjugate heat transfer?" --top-k 3 || true

  if [ "$SKIP_CLAUDE_TEST" = "1" ]; then
    echo "[setup] skipping the claude one-shot MCP test by request (--skip-claude-test)."
  elif command -v claude >/dev/null 2>&1; then
    echo ""
    echo "[setup] launching a one-shot Claude chat to exercise the MCP tool ..."
    claude -p "Use the comsol-clippy MCP tool search_comsol_docs to find how to set up conjugate heat transfer in COMSOL, and cite the manual and page." \
      || echo "[setup] (claude one-shot test skipped/failed - not fatal)"
  fi
else
  echo "[setup] skipping query smoke test until source/ has documents."
fi

echo ""
echo "=============================================="
echo " Done — next steps"
echo "=============================================="
if [ "$HAS_SOURCES" = "0" ]; then
  echo " 1) ADD DOCUMENTS: drop your COMSOL manuals (PDF) or notes (.txt/.md) into:"
  echo "      $PROJECT_DIR/source"
  echo " 2) Re-run start.cmd to embed them."
else
  echo " The MCP server is registered and the vectorstore is ready."
fi
echo ""
echo " Test interactively:"
echo "   cd \"$PROJECT_DIR\" && claude   # then ask it to use search_comsol_docs"
echo " Or restart Claude Desktop and ask it to use search_comsol_docs."
echo ""
echo " Re-run options: start.cmd --help"
echo "=============================================="
