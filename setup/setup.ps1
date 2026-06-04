# COMSOL Clippy - setup for Windows (lives in setup/, project root is the parent).
# Prefers running the MCP server inside WSL2 (GPU). Falls back to native Windows
# Python if WSL is unavailable or has no usable Python. Idempotent and re-runnable.
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

# --- Flag surface (parsed before the mutex / any heavy work so --help is instant). ---
$SkipClaudeTest = $false
$SkipIngest = $false
$Rebuild = $false
$DeviceOverride = ""   # "", "cpu", or "gpu"

function Show-Usage {
  Write-Host @"
COMSOL Clippy setup (Windows)

Usage: start.cmd [options]

Options:
  --skip-claude-test   Don't launch the one-shot ``claude -p`` MCP smoke test.
  --skip-ingest        Register/verify without (re-)embedding source documents.
  --rebuild            Force a full re-embed of every document.
  --cpu                Use CPU torch (default on native Windows; forwarded to WSL).
  --gpu                Use CUDA torch in WSL (no effect on the native Windows path).
  -h, --help           Show this help and exit.

Re-runnable and idempotent. Without options, runs the full setup pipeline.
"@
}

foreach ($a in $args) {
  switch -Regex ($a) {
    '^(--skip-claude-test)$' { $SkipClaudeTest = $true }
    '^(--skip-ingest)$'      { $SkipIngest = $true }
    '^(--rebuild)$'          { $Rebuild = $true }
    '^(--cpu)$'              { $DeviceOverride = "cpu" }
    '^(--gpu)$'              { $DeviceOverride = "gpu" }
    '^(-h|-help|--help|/\?|-\?)$' { Show-Usage; exit 0 }
    default {
      Write-Host "[setup] unknown option: $a"
      Write-Host ""
      Show-Usage
      exit 2
    }
  }
}

# Flags to forward verbatim into setup.sh when we hand off to WSL.
$ForwardFlags = @()
if ($SkipClaudeTest) { $ForwardFlags += "--skip-claude-test" }
if ($SkipIngest)     { $ForwardFlags += "--skip-ingest" }
if ($Rebuild)        { $ForwardFlags += "--rebuild" }
if ($DeviceOverride) { $ForwardFlags += "--$DeviceOverride" }
$projectHashBytes = [System.Text.Encoding]::UTF8.GetBytes($ProjectDir.ToLowerInvariant())
$projectHash = [System.BitConverter]::ToString(
  [System.Security.Cryptography.SHA1]::Create().ComputeHash($projectHashBytes)
).Replace("-", "").ToLowerInvariant()
$SetupMutex = [System.Threading.Mutex]::new($false, "Local\comsol-clippy-setup-$projectHash")
$SetupMutexHeld = $false
try {
  $SetupMutexHeld = $SetupMutex.WaitOne(0)
} catch {
  $SetupMutexHeld = $false
}
if (-not $SetupMutexHeld) {
  throw "[setup] Another setup is already running in this folder. Wait for it to finish, then re-run."
}

function Release-SetupMutex {
  if ($SetupMutexHeld) {
    $SetupMutex.ReleaseMutex()
    $script:SetupMutexHeld = $false
  }
  if ($SetupMutex) {
    $SetupMutex.Dispose()
  }
}

function Get-WslPath([string]$distroName, [string]$winPath) {
  $nativePrefWasSet = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($nativePrefWasSet) {
    $savedNativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    $out = & wsl.exe -d $distroName -e wslpath -a $winPath 2>$null
    $converted = $null
    if ($LASTEXITCODE -eq 0) {
      $converted = (($out | Select-Object -First 1) -replace "[^\x20-\x7E]", "").Trim()
    }
    if ($converted) {
      return $converted
    }

    # Fallback for the common default automount layout if direct wslpath fails.
    $p = $winPath -replace '\\','/'
    if ($p -match '^([A-Za-z]):(.*)$') {
      $drive = $Matches[1].ToLower()
      return "/mnt/$drive$($Matches[2])"
    }
    return $null
  } catch {
    $p = $winPath -replace '\\','/'
    if ($p -match '^([A-Za-z]):(.*)$') {
      $drive = $Matches[1].ToLower()
      return "/mnt/$drive$($Matches[2])"
    }
    return $null
  } finally {
    if ($nativePrefWasSet) {
      $PSNativeCommandUseErrorActionPreference = $savedNativePref
    }
  }
}

function Get-WslDistroCandidates {
  $candidates = New-Object System.Collections.Generic.List[string]

  $listVerbose = (& wsl.exe -l -v) 2>$null
  $default = $listVerbose | Where-Object { $_ -match '^\s*\*' } | Select-Object -First 1
  if ($default) {
    $defaultName = ($default -replace '^\s*\*\s*','' -split '\s+')[0]
    $defaultName = ($defaultName -replace "[^\x20-\x7E]", "").Trim()
    if ($defaultName) {
      [void]$candidates.Add($defaultName)
    }
  }

  $listQuiet = (& wsl.exe -l -q) 2>$null
  foreach ($line in $listQuiet) {
    $name = ($line -replace "[^\x20-\x7E]", "").Trim()
    if ($name -and -not $candidates.Contains($name)) {
      [void]$candidates.Add($name)
    }
  }

  return $candidates
}

function Test-WslBash([string]$distroName) {
  $nativePrefWasSet = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($nativePrefWasSet) {
    $savedNativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    & wsl.exe -d $distroName -e bash -lc "exit 0" *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  } finally {
    if ($nativePrefWasSet) {
      $PSNativeCommandUseErrorActionPreference = $savedNativePref
    }
  }
}

function Test-WslPython3([string]$distroName) {
  $nativePrefWasSet = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($nativePrefWasSet) {
    $savedNativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    & wsl.exe -d $distroName -e bash -lc "command -v python3" *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  } finally {
    if ($nativePrefWasSet) {
      $PSNativeCommandUseErrorActionPreference = $savedNativePref
    }
  }
}

function Test-WslNvidiaSmi([string]$distroName) {
  $nativePrefWasSet = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($nativePrefWasSet) {
    $savedNativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    & wsl.exe -d $distroName -e bash -lc "command -v nvidia-smi" *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  } finally {
    if ($nativePrefWasSet) {
      $PSNativeCommandUseErrorActionPreference = $savedNativePref
    }
  }
}

function Invoke-OptionalNative([scriptblock]$Command, [string]$WarningMessage) {
  $nativePrefWasSet = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($nativePrefWasSet) {
    $savedNativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    & $Command
    if ($LASTEXITCODE -ne 0) {
      Write-Host "$WarningMessage (exit $LASTEXITCODE)."
    }
  } catch {
    Write-Host "$WarningMessage ($($_.Exception.Message))."
  } finally {
    if ($nativePrefWasSet) {
      $PSNativeCommandUseErrorActionPreference = $savedNativePref
    }
  }
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
  $candidates = Get-WslDistroCandidates
  foreach ($candidate in $candidates) {
    if (Test-WslBash $candidate) {
      $distro = $candidate
      $useWsl = $true
      break
    }
  }

  if ($useWsl) {
    if (Test-WslPython3 $distro) {
      Write-Host "[setup] Using WSL runtime: distro '$distro'."
    } else {
      Write-Host "[setup] Using WSL runtime: distro '$distro' (python3 missing; setup.sh will install or create it there)."
    }

    if (Test-WslNvidiaSmi $distro) {
      Write-Host "[setup] NVIDIA tools are visible inside WSL; setup.sh will install CUDA torch there."
    } else {
      Write-Host "[setup] NVIDIA tools are not visible inside WSL; setup.sh will fall back to CPU torch there."
    }
  } elseif ($candidates.Count -gt 0) {
    Write-Host "[setup] WSL is installed, but no listed distro could launch bash. Falling back to native Windows Python."
  } else {
    Write-Host "[setup] wsl.exe is present, but no WSL distros are installed/listed. Falling back to native Windows Python."
  }
}

if ($useWsl) {
  $wslProj = Get-WslPath $distro $ProjectDir
  if (-not $wslProj) {
    throw "Could not convert '$ProjectDir' to a WSL path via wslpath in distro '$distro'."
  }
  Write-Host "[setup] Handing off to WSL: $wslProj/setup/setup.sh"
  $forward = ($ForwardFlags -join " ")
  & wsl.exe -d $distro --cd "$wslProj" -e bash -lc "chmod +x setup/setup.sh && ./setup/setup.sh $forward"
  if ($LASTEXITCODE -ne 0) { throw "WSL setup.sh failed (exit $LASTEXITCODE)." }
  Write-Host "[setup] WSL setup complete. Restart Claude Desktop to load the MCP server."
  Release-SetupMutex
  exit 0
}

# --- Native Windows fallback ---
Write-Host "[setup] No usable WSL -> native Windows Python path (CPU)."
if ($DeviceOverride -eq "gpu") {
  Write-Host "[setup] native Windows path is CPU-only; ignoring --gpu."
}
# Keep the setup window readable and downloads resilient (see setup.sh for rationale).
$env:HF_HUB_DOWNLOAD_TIMEOUT = "30"
$env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
# Plain HTTPS download path, not Xet — avoids the deprecated hf_xet warning from the
# pinned old huggingface_hub (see setup.sh / comsol_clippy/__init__.py).
$env:HF_HUB_DISABLE_XET = "1"
$Venv = Join-Path $ProjectDir ".venv-win"
$Py = Join-Path $Venv "Scripts\python.exe"
$HasSources = $true

# PowerShell can promote native stderr into terminating errors when the script runs
# with strict error handling. Expected probe failures should stay regular false checks.
function Test-PythonProbe([string]$pythonExe, [string]$code) {
  $nativePrefWasSet = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($nativePrefWasSet) {
    $savedNativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    & $pythonExe -c $code *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  } finally {
    if ($nativePrefWasSet) {
      $PSNativeCommandUseErrorActionPreference = $savedNativePref
    }
  }
}

function Test-VenvHealth([string]$pythonExe) {
  return (Test-PythonProbe $pythonExe "import site, sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)")
}

function Test-SupportedSources([string]$pythonExe) {
  $prevProjectDirEnv = $env:PROJECT_DIR_ENV
  $env:PROJECT_DIR_ENV = $ProjectDir
  try {
    return (Test-PythonProbe $pythonExe "import os, sys; from pathlib import Path; from comsol_clippy.pdf import list_sources; sys.exit(0 if list_sources(Path(os.environ['PROJECT_DIR_ENV']) / 'source') else 1)")
  } finally {
    if ($null -eq $prevProjectDirEnv) {
      Remove-Item Env:PROJECT_DIR_ENV -ErrorAction SilentlyContinue
    } else {
      $env:PROJECT_DIR_ENV = $prevProjectDirEnv
    }
  }
}

function Get-RuntimeDevice([string]$pythonExe) {
  $nativePrefWasSet = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($nativePrefWasSet) {
    $savedNativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    $out = & $pythonExe -c "from comsol_clippy.embeddings import detect_device; print(detect_device())" 2>$null
    if ($LASTEXITCODE -ne 0) {
      return $null
    }
    $device = (($out | Select-Object -Last 1) -replace "[^\x20-\x7E]", "").Trim()
    if ($device) {
      return $device
    }
    return $null
  } catch {
    return $null
  } finally {
    if ($nativePrefWasSet) {
      $PSNativeCommandUseErrorActionPreference = $savedNativePref
    }
  }
}

# Strategy for getting Python, in order of preference:
#   1. uv  -> downloads a project-LOCAL standalone Python (nothing installed system-wide).
#      We bootstrap uv itself first if it's missing (small exe, no admin).
#   2. winget -> system-wide Python 3.12 install.
#   3. existing system Python (real, not the Microsoft Store stub).
#   4. give up with a download link.
# uv builds the venv directly; the other paths use `python -m venv`.

$script:UvPath = $null
$script:BasePython = $null

function New-ProjectVenv {
  if ($script:UvPath) {
    Write-Host "[setup] creating venv at .venv-win with a uv-managed Python 3.12 ..."
    & $script:UvPath venv --python 3.12 $Venv
    return
  }
  if ($script:BasePython) {
    Write-Host "[setup] creating venv at .venv-win ..."
    & $script:BasePython -m venv $Venv
    return
  }
  throw "No Python provider is configured to create .venv-win."
}

function Reset-ProjectVenv([string]$reason) {
  Write-Host "[setup] $reason Rebuilding .venv-win ..."
  if (Test-Path $Venv) {
    Remove-Item -Path $Venv -Recurse -Force
  }
  New-ProjectVenv
}

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
    if (Test-PythonProbe $cmd.Source "import sys; sys.exit(0)") { return $cmd.Source }
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
  $script:UvPath = $uv
  Write-Host "[setup] Using uv at $uv"
  if ((Test-Path $Venv) -and -not (Test-VenvHealth $Py)) {
    Reset-ProjectVenv "existing .venv-win looks broken before install."
  } elseif (-not (Test-VenvHealth $Py)) {
    New-ProjectVenv
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
  $script:BasePython = $pyExe
  if ((Test-Path $Venv) -and -not (Test-VenvHealth $Py)) {
    Reset-ProjectVenv "existing .venv-win looks broken before install."
  } elseif (-not (Test-VenvHealth $Py)) {
    New-ProjectVenv
  }
  function Pip-Install { & $Py -m pip install @args }
}

function Install-ProjectRuntime {
  if (-not (Test-PythonProbe $Py "import torch")) {
    Write-Host "[setup] installing CPU torch ..."
    Pip-Install --upgrade pip
    Pip-Install --upgrade torch
  }
  Write-Host "[setup] installing project dependencies ..."
  Pip-Install -e .
}

Install-ProjectRuntime

$runtimeDevice = Get-RuntimeDevice $Py
if (-not $runtimeDevice) {
  Reset-ProjectVenv "environment health probe failed after install."
  Install-ProjectRuntime
  $runtimeDevice = Get-RuntimeDevice $Py
  if (-not $runtimeDevice) {
    throw "[setup] runtime device probe failed after rebuilding .venv-win."
  }
}
Write-Host "[setup] runtime device available to torch: $runtimeDevice"

$SourceDir = Join-Path $ProjectDir "source"
if (-not (Test-SupportedSources $Py)) {
  $HasSources = $false
  Write-Host ""
  Write-Host "[setup] NOTE: the 'source/' folder is empty."
  Write-Host "[setup] Add your COMSOL manuals (PDF) or notes (.txt/.md) to:"
  Write-Host "[setup]   $SourceDir"
  Write-Host "[setup] then re-run start.cmd. Continuing so the server still registers."
} elseif ($SkipIngest) {
  Write-Host "[setup] skipping ingest by request (--skip-ingest)."
} else {
  Write-Host "[setup] building/repairing vectorstore ..."
  if ($Rebuild) { & $Py main.py ingest --rebuild } else { & $Py main.py ingest }
}

Write-Host "[setup] registering MCP server ..."
& $Py scripts\register_mcp.py --command $Py --arg main.py --arg serve --cwd $ProjectDir

Write-Host "[setup] restarting search daemon (if running) ..."
& $Py main.py restart-daemon

if ($HasSources) {
  Write-Host "[setup] verifying ..."
  & $Py main.py status

  Write-Host "=============================================="
  Write-Host " Test query"
  Write-Host "=============================================="
  Invoke-OptionalNative { & $Py main.py query "How do I set up conjugate heat transfer?" --top-k 3 } "[setup] query smoke test skipped/failed - not fatal"

  if ($SkipClaudeTest) {
    Write-Host "[setup] skipping the claude one-shot MCP test by request (--skip-claude-test)."
  } else {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
      Write-Host "[setup] launching one-shot Claude chat to exercise the MCP tool ..."
      Invoke-OptionalNative { & claude -p "Use the comsol-clippy MCP tool search_comsol_docs to find how to set up conjugate heat transfer in COMSOL, and cite the manual and page." } "[setup] Claude one-shot test skipped/failed - not fatal"
    }
  }
} else {
  Write-Host "[setup] skipping vectorstore verification until source/ has documents."
  Write-Host "[setup] skipping query smoke test until source/ has documents."
}

Write-Host "=============================================="
Write-Host " Done - next steps"
Write-Host "=============================================="
if (-not $HasSources) {
  Write-Host " 1) ADD DOCUMENTS: drop your COMSOL manuals (PDF) or notes (.txt/.md) into:"
  Write-Host "      $SourceDir"
  Write-Host " 2) Re-run start.cmd to embed them."
} else {
  Write-Host " The MCP server is registered and the vectorstore is ready."
}
Write-Host ""
Write-Host " Test interactively: run 'claude' in this folder, or restart Claude Desktop,"
Write-Host " then ask it to use search_comsol_docs."
Write-Host ""
Write-Host " Re-run options: start.cmd --help"
Write-Host "=============================================="

Release-SetupMutex
