# COMSOL Clippy - setup for Windows (lives in setup/, project root is the parent).
# Prefers running the MCP server inside WSL2 (GPU). Falls back to native Windows
# Python if WSL is unavailable or has no usable Python. Idempotent and re-runnable.
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

function Convert-ToWslPath([string]$winPath) {
  $p = $winPath -replace '\\','/'
  if ($p -match '^([A-Za-z]):(.*)$') {
    $drive = $Matches[1].ToLower()
    return "/mnt/$drive$($Matches[2])"
  }
  return $p
}

Write-Host "=============================================="
Write-Host " COMSOL Clippy setup (Windows)"
Write-Host " Project: $ProjectDir"
Write-Host "=============================================="

# --- Detect runtime ---
$useWsl = $false
$distro = $null
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($wsl) {
  $list = (& wsl.exe -l -v) 2>$null
  $default = $list | Where-Object { $_ -match '^\s*\*' }
  if ($default) {
    $distro = ($default -replace '^\s*\*\s*','' -split '\s+')[0]
    $distro = ($distro -replace "[^\x20-\x7E]", "").Trim()
    & wsl.exe -d $distro -e bash -lc "command -v python3" *> $null
    if ($LASTEXITCODE -eq 0) {
      $useWsl = $true
      Write-Host "[setup] Using WSL runtime: distro '$distro' (GPU-capable)."
    } else {
      Write-Host "[setup] WSL distro '$distro' has no python3 -> will create a venv there."
      $useWsl = $true
    }
  }
}

if ($useWsl) {
  $wslProj = Convert-ToWslPath $ProjectDir
  Write-Host "[setup] Handing off to WSL: $wslProj/setup/setup.sh"
  & wsl.exe -d $distro --cd "$wslProj" -e bash -lc "chmod +x setup/setup.sh && ./setup/setup.sh"
  if ($LASTEXITCODE -ne 0) { throw "WSL setup.sh failed (exit $LASTEXITCODE)." }
  Write-Host "[setup] WSL setup complete. Restart Claude Desktop to load the MCP server."
  exit 0
}

# --- Native Windows fallback ---
Write-Host "[setup] No usable WSL -> native Windows Python path (CPU)."
# Keep the setup window readable and downloads resilient (see setup.sh for rationale).
$env:HF_HUB_DOWNLOAD_TIMEOUT = "30"
$env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
$Venv = Join-Path $ProjectDir ".venv-win"
$Py = Join-Path $Venv "Scripts\python.exe"

# Strategy for getting Python, in order of preference:
#   1. uv  -> downloads a project-LOCAL standalone Python (nothing installed system-wide).
#      We bootstrap uv itself first if it's missing (small exe, no admin).
#   2. winget -> system-wide Python 3.12 install.
#   3. existing system Python (real, not the Microsoft Store stub).
#   4. give up with a download link.
# uv builds the venv directly; the other paths use `python -m venv`.

function Find-Uv {
  $cmd = Get-Command uv -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $cand = "$env:USERPROFILE\.local\bin\uv.exe"
  if (Test-Path $cand) { return $cand }
  return $null
}

function Find-Python {
  $cmd = (Get-Command python -ErrorAction SilentlyContinue)
  if ($cmd) {
    # The Microsoft Store "python.exe" stub does nothing useful; verify it really runs.
    & $cmd.Source -c "import sys; sys.exit(0)" 2>$null
    if ($LASTEXITCODE -eq 0) { return $cmd.Source }
  }
  $roots = @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles\Python", "${env:ProgramFiles(x86)}\Python")
  foreach ($root in $roots) {
    if (Test-Path $root) {
      $hit = Get-ChildItem -Path $root -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
      if ($hit) { return $hit.FullName }
    }
  }
  return $null
}

# Try to obtain uv (preferred: self-contained, project-local Python).
$uv = Find-Uv
if (-not $uv) {
  Write-Host "[setup] Bootstrapping uv (project-local Python manager, no admin needed) ..."
  try {
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $uv = Find-Uv
  } catch {
    Write-Host "[setup] uv bootstrap failed: $($_.Exception.Message)"
  }
}

if ($uv) {
  Write-Host "[setup] Using uv at $uv"
  if (-not (Test-Path $Py)) {
    Write-Host "[setup] creating venv at .venv-win with a uv-managed Python 3.12 ..."
    # --python 3.12 makes uv download a private standalone interpreter if none is present.
    & $uv venv --python 3.12 $Venv
  }
  function Pip-Install { & $uv pip install --python $Py @args }
} else {
  # --- Fallbacks: winget, then existing system Python ---
  $pyExe = Find-Python
  if (-not $pyExe) {
    Write-Host "[setup] uv unavailable and no Python found. Trying winget ..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
      & winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
      Write-Host "[setup] winget finished; locating the new Python (PATH not refreshed this session) ..."
      $pyExe = Find-Python
    }
  }
  if (-not $pyExe) {
    throw @"
Python could not be obtained automatically (uv bootstrap, winget, and system search all failed).
Please install Python 3.10+ from https://www.python.org/downloads/windows/
(check 'Add python.exe to PATH' during install), then double-click start.cmd again.
"@
  }
  Write-Host "[setup] Using Python at $pyExe"
  if (-not (Test-Path $Py)) {
    Write-Host "[setup] creating venv at .venv-win ..."
    & $pyExe -m venv $Venv
  }
  function Pip-Install { & $Py -m pip install @args }
}

& $Py -c "import torch" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "[setup] installing CPU torch ..."
  Pip-Install --upgrade pip
  Pip-Install torch
}
Write-Host "[setup] installing project dependencies ..."
Pip-Install -e .

$SourceDir = Join-Path $ProjectDir "source"
if (-not (Test-Path $SourceDir) -or -not (Get-ChildItem -Path $SourceDir -ErrorAction SilentlyContinue)) {
  Write-Host ""
  Write-Host "[setup] NOTE: the 'source/' folder is empty."
  Write-Host "[setup] Add your COMSOL manuals (PDF) or notes (.txt/.md) to:"
  Write-Host "[setup]   $SourceDir"
  Write-Host "[setup] then re-run start.cmd. Continuing so the server still registers."
}
Write-Host "[setup] building/repairing vectorstore ..."
& $Py main.py ingest

Write-Host "[setup] registering MCP server ..."
$argsJson = '["main.py","serve"]'
& $Py scripts\register_mcp.py --command $Py --args $argsJson --cwd $ProjectDir

Write-Host "[setup] restarting search daemon (if running) ..."
& $Py main.py restart-daemon

Write-Host "[setup] verifying ..."
& $Py main.py status

Write-Host "=============================================="
Write-Host " Test query"
Write-Host "=============================================="
& $Py main.py query "How do I set up conjugate heat transfer?" --top-k 3

$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
  Write-Host "[setup] launching one-shot Claude chat to exercise the MCP tool ..."
  & claude -p "Use the comsol-clippy MCP tool search_comsol_docs to find how to set up conjugate heat transfer in COMSOL, and cite the manual and page."
}

Write-Host "=============================================="
Write-Host " Done. Restart Claude Desktop and ask it to use search_comsol_docs,"
Write-Host " or run 'claude' in this folder to test interactively."
Write-Host "=============================================="
