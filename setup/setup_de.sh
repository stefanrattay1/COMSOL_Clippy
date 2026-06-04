#!/usr/bin/env bash
# COMSOL Clippy - Setup fuer Linux / WSL2 (liegt in setup/, Projektwurzel ist das
# uebergeordnete Verzeichnis). Deutsche Ausgabe-Variante von setup.sh.
# Prueft Voraussetzungen, baut/repariert den Vektorspeicher, registriert den
# MCP-Server, verifiziert ihn und fuehrt eine Testabfrage aus. Idempotent und
# wiederholbar.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
VENV="$PROJECT_DIR/.venv"
PY="$VENV/bin/python"
HAS_SOURCES=1

# --- Flag-Verarbeitung (vor jeder schweren Arbeit, damit --help sofort kommt). ---
SKIP_CLAUDE_TEST=0
SKIP_INGEST=0
REBUILD=0
DEVICE_OVERRIDE=""   # "", "cpu" oder "gpu"

usage() {
  cat <<'USAGE'
COMSOL Clippy Setup (Linux/WSL)

Verwendung: start_de.cmd [Optionen]      (oder: bash setup/setup_de.sh [Optionen])

Optionen:
  --skip-claude-test   Den einmaligen `claude -p` MCP-Schnelltest nicht starten.
  --skip-ingest        Registrieren/verifizieren ohne (erneutes) Einbetten der Quelldokumente.
  --rebuild            Erzwingt ein vollstaendiges Neu-Einbetten aller Dokumente.
  --cpu                CPU-torch installieren/verwenden, auch wenn eine NVIDIA-GPU vorhanden ist.
  --gpu                CUDA-torch installieren/verwenden, auch wenn nvidia-smi nicht erkannt wird.
  -h, --help           Diese Hilfe anzeigen und beenden.

Wiederholbar und idempotent. Ohne Optionen wird die vollstaendige Setup-Pipeline ausgefuehrt.
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
    *) echo "[setup] unbekannte Option: $1" >&2; echo "" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# --- Parallelitaetsschutz: zwei Setup-Laeufe duerfen nicht um venv/pip/ingest konkurrieren. ---
# flock haelt waehrend der Skriptlaufzeit eine exklusive Sperre; ein zweiter Lauf beendet sich
# frueh mit einer klaren Meldung, statt eine halbfertige venv zu beschaedigen.
LOCK="$PROJECT_DIR/.setup.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "[setup] In diesem Ordner laeuft bereits ein Setup. Warten Sie, bis es fertig ist, und starten Sie erneut." >&2
    exit 1
  fi
fi

# --- Freundlicher Fehlerabbruch: den naechsten 'set -e'-Abbruch in Klartext uebersetzen. ---
fail() { echo ""; echo "[setup] PROBLEM: $1" >&2; echo "[setup] $2" >&2; exit 1; }
trap 'fail "Setup wegen eines unerwarteten Fehlers gestoppt (Zeile $LINENO)." "Scrollen Sie nach oben zur Ausgabe des letzten Befehls; beheben Sie das Problem und starten Sie start_de.cmd erneut."' ERR

# Setup-Fenster lesbar halten: ein Pro-Chunk-Download-Timeout (damit ein haengender
# Modell-Download abbricht und neu versucht, statt zu blockieren) und keine tqdm-Fortschrittsbalken.
export HF_HUB_DOWNLOAD_TIMEOUT=30
export HF_HUB_DISABLE_PROGRESS_BARS=1
# Den einfachen HTTPS-Download-Pfad verwenden, nicht Xet: das angepinnte (alte)
# huggingface_hub ruft weiterhin das veraltete hf_xet.download_files() auf, das bei jedem
# Modell-Download eine DeprecationWarning ausgibt. Xet zu deaktivieren vermeidet diesen Pfad.
# (Auch zentral in comsol_clippy/__init__.py gesetzt; hier exportiert, damit jeder direkte
# HF-Aufruf waehrend des Setups abgedeckt ist.)
export HF_HUB_DISABLE_XET=1

echo "=============================================="
echo " COMSOL Clippy Setup (Linux/WSL)"
echo " Projekt: $PROJECT_DIR"
echo "=============================================="

# --- Schritt 1: python3 sicherstellen ---
if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "[setup] python3 nicht gefunden; versuche apt-Installation..."
    sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-pip || {
      echo "[setup] FEHLER: python3 konnte nicht installiert werden. Installieren Sie es und starten Sie erneut." >&2; exit 1; }
  else
    echo "[setup] FEHLER: python3 fehlt und diese Linux-Distribution hat keinen apt-get-Fallback in setup_de.sh." >&2
    echo "[setup] Installieren Sie python3 + python3-venv und starten Sie start_de.cmd erneut." >&2
    exit 1
  fi
fi

# --- Schritt 2: venv + Abhaengigkeiten sicherstellen ---
HAVE_UV=0
if command -v uv >/dev/null 2>&1; then HAVE_UV=1; fi

create_venv() {
  echo "[setup] erstelle venv unter .venv ..."
  if [ "$HAVE_UV" = "1" ]; then uv venv "$VENV"; else python3 -m venv "$VENV"; fi
}

reset_venv() {
  echo "[setup] baue .venv neu auf ..."
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
    echo "[setup] python3-venv fehlt; versuche apt-Installation..."
    sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip || {
      echo "[setup] FEHLER: python3-venv konnte nicht installiert werden. Installieren Sie es und starten Sie erneut." >&2; exit 1; }
  else
    echo "[setup] FEHLER: python3 existiert, aber das venv-Modul ist nicht verfuegbar und es gibt keinen apt-get-Fallback." >&2
    echo "[setup] Installieren Sie python3-venv (oder verwenden Sie uv) und starten Sie start_de.cmd erneut." >&2
    exit 1
  fi
fi

if [ -d "$VENV" ] && ! venv_looks_usable; then
  echo "[setup] vorhandene .venv scheint defekt; baue sie vor der Installation neu auf ..."
  reset_venv
elif ! venv_looks_usable; then
  create_venv
fi

# CUDA erkennen, um das torch-Wheel zu waehlen (ein explizites --cpu/--gpu hat Vorrang vor der Erkennung).
TORCH_INDEX=""
TORCH_CHECK='import torch'
want_cuda=0
if [ "$DEVICE_OVERRIDE" = "gpu" ]; then
  want_cuda=1
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "[setup] --gpu angegeben, aber nvidia-smi nicht gefunden; installiere CUDA-torch trotzdem (faellt zur Laufzeit ggf. auf CPU zurueck)."
  fi
elif [ "$DEVICE_OVERRIDE" = "cpu" ]; then
  echo "[setup] --cpu angegeben - installiere CPU-torch."
elif command -v nvidia-smi >/dev/null 2>&1; then
  want_cuda=1
fi

if [ "$want_cuda" = "1" ]; then
  echo "[setup] installiere CUDA (cu121) torch."
  TORCH_INDEX="--index-url https://download.pytorch.org/whl/cu121"
  TORCH_CHECK='import sys, torch; sys.exit(0 if getattr(torch.version, "cuda", None) else 1)'
else
  echo "[setup] installiere CPU-torch."
fi

pip_install() {
  if [ "$HAVE_UV" = "1" ]; then uv pip install --python "$PY" "$@"; else "$PY" -m pip install "$@"; fi
}

install_runtime_stack() {
  if ! "$PY" -c "$TORCH_CHECK" >/dev/null 2>&1; then
    echo "[setup] installiere torch ..."
    # shellcheck disable=SC2086
    pip_install --upgrade pip
    pip_install --upgrade torch $TORCH_INDEX
  fi
  echo "[setup] installiere Projektabhaengigkeiten ..."
  pip_install -e .
}

install_runtime_stack

if RUNTIME_DEVICE="$(probe_runtime_device 2>/dev/null)"; then
  echo "[setup] fuer torch verfuegbares Laufzeitgeraet: $RUNTIME_DEVICE"
else
  echo "[setup] Umgebungs-Gesundheitstest nach Installation fehlgeschlagen; baue .venv einmal neu auf ..."
  reset_venv
  install_runtime_stack
  RUNTIME_DEVICE="$(probe_runtime_device)"
  echo "[setup] fuer torch verfuegbares Laufzeitgeraet: $RUNTIME_DEVICE"
fi

# --- Schritt 3: Ingest (inkrementell) ---
if ! supported_sources_present; then
  HAS_SOURCES=0
  echo ""
  echo "[setup] HINWEIS: der Ordner 'source/' ist leer."
  echo "[setup] Legen Sie Ihre COMSOL-Handbuecher (PDF) oder Notizen (.txt/.md) ab unter:"
  echo "[setup]   $PROJECT_DIR/source"
  echo "[setup] und starten Sie start_de.cmd erneut. Setup wird fortgesetzt, damit der Server trotzdem registriert wird."
elif [ "$SKIP_INGEST" = "1" ]; then
  echo "[setup] Ingest wird auf Wunsch uebersprungen (--skip-ingest)."
else
  echo "[setup] baue/repariere Vektorspeicher ..."
  if [ "$REBUILD" = "1" ]; then
    "$PY" main.py ingest --rebuild
  else
    "$PY" main.py ingest
  fi
fi

# --- Schritt 4: MCP-Server registrieren ---
echo "[setup] registriere MCP-Server in der/den Claude-Konfiguration(en) ..."
"$PY" scripts/register_mcp.py --command "$PY" --arg main.py --arg serve --cwd "$PROJECT_DIR"

if grep -qi microsoft /proc/version 2>/dev/null && command -v wslpath >/dev/null 2>&1; then
  DISTRO="${WSL_DISTRO_NAME:-}"
  WIN_APPDATA_WIN="$(cmd.exe /c 'echo %APPDATA%' 2>/dev/null | tr -d '\r\n' || true)"
  WIN_APPDATA="$(wslpath -u "$WIN_APPDATA_WIN" 2>/dev/null || true)"
  if [ -n "$DISTRO" ] && [ -n "$WIN_APPDATA" ]; then
    WIN_CFG="$WIN_APPDATA/Claude/claude_desktop_config.json"
    echo "[setup] registriere zusaetzlich den wsl.exe-Wrapper in Windows Claude Desktop ..."
    "$PY" scripts/register_mcp.py --command "wsl.exe" \
      --arg=-d --arg "$DISTRO" --arg=--cd --arg "$PROJECT_DIR" --arg "$PY" --arg main.py --arg serve \
      --target "$WIN_CFG"
  elif [ -n "$DISTRO" ]; then
    echo "[setup] konnte den Pfad zur Windows-Claude-Desktop-Konfiguration aus WSL nicht aufloesen; ueberspringe diese Registrierung."
  fi
fi

# --- Schritt 5: laufenden Daemon neu starten, damit Code/Speicher dieses Laufs wirksam werden ---
echo "[setup] starte Such-Daemon neu (falls er laeuft) ..."
"$PY" main.py restart-daemon || true

# --- Schritt 6: verifizieren ---
if [ "$HAS_SOURCES" = "1" ]; then
  echo "[setup] verifiziere ..."
  "$PY" main.py status
else
  echo "[setup] ueberspringe Vektorspeicher-Verifikation, bis source/ Dokumente enthaelt."
fi

# --- Schritt 7: Testabfrage + optionaler Live-MCP-Test ---
if [ "$HAS_SOURCES" = "1" ]; then
  echo ""
  echo "=============================================="
  echo " Testabfrage"
  echo "=============================================="
  "$PY" main.py query "How do I set up conjugate heat transfer?" --top-k 3 || true

  if [ "$SKIP_CLAUDE_TEST" = "1" ]; then
    echo "[setup] ueberspringe den einmaligen Claude-MCP-Test auf Wunsch (--skip-claude-test)."
  elif command -v claude >/dev/null 2>&1; then
    echo ""
    echo "[setup] starte einen einmaligen Claude-Chat, um das MCP-Tool zu testen ..."
    claude -p "Use the comsol-clippy MCP tool search_comsol_docs to find how to set up conjugate heat transfer in COMSOL, and cite the manual and page." \
      || echo "[setup] (einmaliger Claude-Test uebersprungen/fehlgeschlagen - nicht kritisch)"
  fi
else
  echo "[setup] ueberspringe Abfrage-Schnelltest, bis source/ Dokumente enthaelt."
fi

echo ""
echo "=============================================="
echo " Fertig - naechste Schritte"
echo "=============================================="
if [ "$HAS_SOURCES" = "0" ]; then
  echo " 1) DOKUMENTE HINZUFUEGEN: legen Sie Ihre COMSOL-Handbuecher (PDF) oder Notizen (.txt/.md) ab in:"
  echo "      $PROJECT_DIR/source"
  echo " 2) Starten Sie start_de.cmd erneut, um sie einzubetten."
else
  echo " Der MCP-Server ist registriert und der Vektorspeicher ist bereit."
fi
echo ""
echo " Interaktiv testen:"
echo "   cd \"$PROJECT_DIR\" && claude   # dann bitten Sie es, search_comsol_docs zu verwenden"
echo " Oder starten Sie Claude Desktop neu und bitten Sie es, search_comsol_docs zu verwenden."
echo ""
echo " Optionen zum erneuten Ausfuehren: start_de.cmd --help"
echo "=============================================="
