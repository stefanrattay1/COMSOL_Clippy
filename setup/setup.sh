#!/usr/bin/env bash
# COMSOL Clippy - setup for Linux / WSL2 (lives in setup/, project root is the parent).
# Checks requirements, builds/repairs the vectorstore, registers the MCP server,
# verifies it, and runs a test query. Idempotent and re-runnable.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
VENV="$PROJECT_DIR/.venv"
PY="$VENV/bin/python"

# Keep the setup window readable: a per-chunk download timeout (so a stalled model
# download errors and retries instead of hanging), and no tqdm progress-bar spam.
export HF_HUB_DOWNLOAD_TIMEOUT=30
export HF_HUB_DISABLE_PROGRESS_BARS=1

echo "=============================================="
echo " COMSOL Clippy setup (Linux/WSL)"
echo " Project: $PROJECT_DIR"
echo "=============================================="

# --- Stage 1: ensure python3 ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "[setup] python3 not found; attempting apt install..."
  sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-pip || {
    echo "[setup] ERROR: could not install python3. Install it and re-run." >&2; exit 1; }
fi

# --- Stage 2: ensure venv + deps ---
HAVE_UV=0
if command -v uv >/dev/null 2>&1; then HAVE_UV=1; fi

if [ ! -x "$PY" ]; then
  echo "[setup] creating venv at .venv ..."
  if [ "$HAVE_UV" = "1" ]; then uv venv "$VENV"; else python3 -m venv "$VENV"; fi
fi

# Detect CUDA to choose the torch wheel.
TORCH_INDEX=""
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "[setup] NVIDIA GPU detected - installing CUDA (cu121) torch."
  TORCH_INDEX="--index-url https://download.pytorch.org/whl/cu121"
else
  echo "[setup] No GPU - installing CPU torch."
fi

pip_install() {
  if [ "$HAVE_UV" = "1" ]; then uv pip install --python "$PY" "$@"; else "$PY" -m pip install "$@"; fi
}

# Install torch first (with the right index), then the rest of the project.
if ! "$PY" -c "import torch" >/dev/null 2>&1; then
  echo "[setup] installing torch ..."
  # shellcheck disable=SC2086
  pip_install torch $TORCH_INDEX
fi
echo "[setup] installing project dependencies ..."
pip_install -e .

# --- Stage 3: ingest (incremental) ---
echo "[setup] building/repairing vectorstore ..."
"$PY" main.py ingest

# --- Stage 4: register MCP server ---
echo "[setup] registering MCP server in Claude config(s) ..."
"$PY" scripts/register_mcp.py --command "$PY" \
  --args "$(python3 -c 'import json;print(json.dumps(["main.py","serve"]))')" --cwd "$PROJECT_DIR"

if grep -qi microsoft /proc/version 2>/dev/null && command -v wslpath >/dev/null 2>&1; then
  DISTRO="${WSL_DISTRO_NAME:-}"
  WIN_USER="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n' || true)"
  if [ -n "$DISTRO" ] && [ -n "$WIN_USER" ]; then
    WIN_CFG="/mnt/c/Users/$WIN_USER/AppData/Roaming/Claude/claude_desktop_config.json"
    if [ -f "$WIN_CFG" ]; then
      echo "[setup] also registering wsl.exe wrapper into Windows Claude Desktop ..."
      WSL_WRAP_ARGS=$(python3 -c "import json,sys;print(json.dumps(['-d',sys.argv[1],'--cd',sys.argv[2],sys.argv[3],'main.py','serve']))" "$DISTRO" "$PROJECT_DIR" "$PY")
      "$PY" scripts/register_mcp.py --command "wsl.exe" --args "$WSL_WRAP_ARGS" --target "$WIN_CFG"
    fi
  fi
fi

# --- Stage 5: verify ---
echo "[setup] verifying ..."
"$PY" main.py status

# --- Stage 6: test query + optional live MCP test ---
echo ""
echo "=============================================="
echo " Test query"
echo "=============================================="
"$PY" main.py query "How do I set up conjugate heat transfer?" --top-k 3 || true

if command -v claude >/dev/null 2>&1; then
  echo ""
  echo "[setup] launching a one-shot Claude chat to exercise the MCP tool ..."
  claude -p "Use the comsol-clippy MCP tool search_comsol_docs to find how to set up conjugate heat transfer in COMSOL, and cite the manual and page." \
    || echo "[setup] (claude one-shot test skipped/failed - not fatal)"
fi

echo ""
echo "=============================================="
echo " Done. To test interactively:"
echo "   cd \"$PROJECT_DIR\" && claude   # then ask it to use search_comsol_docs"
echo " Or restart Claude Desktop and ask it to use search_comsol_docs."
echo "=============================================="
