# COMSOL Clippy - Setup fuer Windows (liegt in setup/, Projektwurzel ist das
# uebergeordnete Verzeichnis). Deutsche Ausgabe-Variante von setup.ps1.
# Bevorzugt den MCP-Server in WSL2 (GPU). Faellt auf natives Windows-Python zurueck,
# falls WSL nicht verfuegbar ist oder kein nutzbares Python hat. Idempotent und wiederholbar.
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

# --- Flag-Verarbeitung (vor dem Mutex / jeder schweren Arbeit, damit --help sofort kommt). ---
$SkipClaudeTest = $false
$SkipIngest = $false
$Rebuild = $false
$DeviceOverride = ""   # "", "cpu" oder "gpu"

function Show-Usage {
  Write-Host @"
COMSOL Clippy Setup (Windows)

Verwendung: start_de.cmd [Optionen]

Optionen:
  --skip-claude-test   Den einmaligen ``claude -p`` MCP-Schnelltest nicht starten.
  --skip-ingest        Registrieren/verifizieren ohne (erneutes) Einbetten der Quelldokumente.
  --rebuild            Erzwingt ein vollstaendiges Neu-Einbetten aller Dokumente.
  --cpu                CPU-torch verwenden (Standard auf nativem Windows; an WSL weitergereicht).
  --gpu                CUDA-torch in WSL verwenden (keine Wirkung auf dem nativen Windows-Pfad).
  -h, --help           Diese Hilfe anzeigen und beenden.

Wiederholbar und idempotent. Ohne Optionen wird die vollstaendige Setup-Pipeline ausgefuehrt.
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
      Write-Host "[setup] unbekannte Option: $a"
      Write-Host ""
      Show-Usage
      exit 2
    }
  }
}

# Flags, die unveraendert an setup_de.sh weitergereicht werden, wenn wir an WSL uebergeben.
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
  throw "[setup] In diesem Ordner laeuft bereits ein Setup. Warten Sie, bis es fertig ist, und starten Sie erneut."
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

    # Fallback fuer das uebliche Standard-Automount-Layout, falls direktes wslpath fehlschlaegt.
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
      Write-Host "$WarningMessage (Exit-Code $LASTEXITCODE)."
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
Write-Host " COMSOL Clippy Setup (Windows)"
Write-Host " Projekt: $ProjectDir"
Write-Host "=============================================="

# --- Laufzeitumgebung erkennen ---
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
      Write-Host "[setup] Verwende WSL-Laufzeit: Distribution '$distro'."
    } else {
      Write-Host "[setup] Verwende WSL-Laufzeit: Distribution '$distro' (python3 fehlt; setup_de.sh installiert oder erstellt es dort)."
    }

    if (Test-WslNvidiaSmi $distro) {
      Write-Host "[setup] NVIDIA-Tools sind in WSL sichtbar; setup_de.sh installiert dort CUDA-torch."
    } else {
      Write-Host "[setup] NVIDIA-Tools sind in WSL nicht sichtbar; setup_de.sh faellt dort auf CPU-torch zurueck."
    }
  } elseif ($candidates.Count -gt 0) {
    Write-Host "[setup] WSL ist installiert, aber keine gelistete Distribution konnte bash starten. Falle auf natives Windows-Python zurueck."
  } else {
    Write-Host "[setup] wsl.exe ist vorhanden, aber es sind keine WSL-Distributionen installiert/gelistet. Falle auf natives Windows-Python zurueck."
  }
}

if ($useWsl) {
  $wslProj = Get-WslPath $distro $ProjectDir
  if (-not $wslProj) {
    throw "Konnte '$ProjectDir' in der Distribution '$distro' nicht per wslpath in einen WSL-Pfad umwandeln."
  }
  Write-Host "[setup] Uebergabe an WSL: $wslProj/setup/setup_de.sh"
  $forward = ($ForwardFlags -join " ")
  & wsl.exe -d $distro --cd "$wslProj" -e bash -lc "chmod +x setup/setup_de.sh && ./setup/setup_de.sh $forward"
  if ($LASTEXITCODE -ne 0) { throw "WSL setup_de.sh fehlgeschlagen (Exit-Code $LASTEXITCODE)." }
  Write-Host "[setup] WSL-Setup abgeschlossen. Starten Sie Claude Desktop neu, um den MCP-Server zu laden."
  Release-SetupMutex
  exit 0
}

# --- Nativer Windows-Fallback ---
Write-Host "[setup] Kein nutzbares WSL -> nativer Windows-Python-Pfad (CPU)."
if ($DeviceOverride -eq "gpu") {
  Write-Host "[setup] der native Windows-Pfad ist nur CPU; ignoriere --gpu."
}
# Setup-Fenster lesbar und Downloads robust halten (Begruendung siehe setup_de.sh).
$env:HF_HUB_DOWNLOAD_TIMEOUT = "30"
$env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
# Einfacher HTTPS-Download-Pfad, nicht Xet - vermeidet die veraltete hf_xet-Warnung aus dem
# angepinnten alten huggingface_hub (siehe setup_de.sh / comsol_clippy/__init__.py).
$env:HF_HUB_DISABLE_XET = "1"
$Venv = Join-Path $ProjectDir ".venv-win"
$Py = Join-Path $Venv "Scripts\python.exe"
$HasSources = $true

# PowerShell kann native stderr-Ausgaben bei strikter Fehlerbehandlung in abbrechende Fehler
# umwandeln. Erwartete Probe-Fehlschlaege sollen normale False-Pruefungen bleiben.
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

# Strategie zur Beschaffung von Python, in bevorzugter Reihenfolge:
#   1. uv  -> laedt ein projekt-LOKALES Standalone-Python (nichts systemweit installiert).
#      uv selbst wird zuerst gebootstrappt, falls es fehlt (kleine exe, kein Admin).
#   2. winget -> systemweite Installation von Python 3.12.
#   3. vorhandenes System-Python (echt, nicht der Microsoft-Store-Stub).
#   4. mit Download-Link aufgeben.
# uv baut die venv direkt; die anderen Pfade nutzen `python -m venv`.

$script:UvPath = $null
$script:BasePython = $null

function New-ProjectVenv {
  if ($script:UvPath) {
    Write-Host "[setup] erstelle venv unter .venv-win mit einem uv-verwalteten Python 3.12 ..."
    & $script:UvPath venv --python 3.12 $Venv
    return
  }
  if ($script:BasePython) {
    Write-Host "[setup] erstelle venv unter .venv-win ..."
    & $script:BasePython -m venv $Venv
    return
  }
  throw "Es ist kein Python-Anbieter konfiguriert, um .venv-win zu erstellen."
}

function Reset-ProjectVenv([string]$reason) {
  Write-Host "[setup] $reason Baue .venv-win neu auf ..."
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
    # Der Microsoft-Store-"python.exe"-Stub macht nichts Nuetzliches; pruefen, ob er wirklich laeuft.
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

# uv beschaffen (bevorzugt: eigenstaendiges, projekt-lokales Python).
$uv = Find-Uv
if (-not $uv) {
  Write-Host "[setup] Bootstrappe uv (projekt-lokaler Python-Manager, kein Admin noetig) ..."
  try {
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $uv = Find-Uv
  } catch {
    Write-Host "[setup] uv-Bootstrap fehlgeschlagen: $($_.Exception.Message)"
  }
}

if ($uv) {
  $script:UvPath = $uv
  Write-Host "[setup] Verwende uv unter $uv"
  if ((Test-Path $Venv) -and -not (Test-VenvHealth $Py)) {
    Reset-ProjectVenv "vorhandene .venv-win scheint vor der Installation defekt."
  } elseif (-not (Test-VenvHealth $Py)) {
    New-ProjectVenv
  }
  function Pip-Install { & $uv pip install --python $Py @args }
} else {
  # --- Fallbacks: winget, dann vorhandenes System-Python ---
  $pyExe = Find-Python
  if (-not $pyExe) {
    Write-Host "[setup] uv nicht verfuegbar und kein Python gefunden. Versuche winget ..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
      & winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
      Write-Host "[setup] winget fertig; suche das neue Python (PATH in dieser Sitzung nicht aktualisiert) ..."
      $pyExe = Find-Python
    }
  }
  if (-not $pyExe) {
    throw @"
Python konnte nicht automatisch beschafft werden (uv-Bootstrap, winget und Systemsuche schlugen alle fehl).
Bitte installieren Sie Python 3.10+ von https://www.python.org/downloads/windows/
(waehlen Sie bei der Installation 'Add python.exe to PATH'), und doppelklicken Sie dann erneut auf start_de.cmd.
"@
  }
  Write-Host "[setup] Verwende Python unter $pyExe"
  $script:BasePython = $pyExe
  if ((Test-Path $Venv) -and -not (Test-VenvHealth $Py)) {
    Reset-ProjectVenv "vorhandene .venv-win scheint vor der Installation defekt."
  } elseif (-not (Test-VenvHealth $Py)) {
    New-ProjectVenv
  }
  function Pip-Install { & $Py -m pip install @args }
}

function Install-ProjectRuntime {
  if (-not (Test-PythonProbe $Py "import torch")) {
    Write-Host "[setup] installiere CPU-torch ..."
    Pip-Install --upgrade pip
    Pip-Install --upgrade torch
  }
  Write-Host "[setup] installiere Projektabhaengigkeiten ..."
  Pip-Install -e .
}

Install-ProjectRuntime

$runtimeDevice = Get-RuntimeDevice $Py
if (-not $runtimeDevice) {
  Reset-ProjectVenv "Umgebungs-Gesundheitstest nach Installation fehlgeschlagen."
  Install-ProjectRuntime
  $runtimeDevice = Get-RuntimeDevice $Py
  if (-not $runtimeDevice) {
    throw "[setup] Laufzeitgeraet-Probe nach Neuaufbau von .venv-win fehlgeschlagen."
  }
}
Write-Host "[setup] fuer torch verfuegbares Laufzeitgeraet: $runtimeDevice"

$SourceDir = Join-Path $ProjectDir "source"
if (-not (Test-SupportedSources $Py)) {
  $HasSources = $false
  Write-Host ""
  Write-Host "[setup] HINWEIS: der Ordner 'source/' ist leer."
  Write-Host "[setup] Legen Sie Ihre COMSOL-Handbuecher (PDF) oder Notizen (.txt/.md) ab unter:"
  Write-Host "[setup]   $SourceDir"
  Write-Host "[setup] und starten Sie start_de.cmd erneut. Wird fortgesetzt, damit der Server trotzdem registriert wird."
} elseif ($SkipIngest) {
  Write-Host "[setup] Ingest wird auf Wunsch uebersprungen (--skip-ingest)."
} else {
  Write-Host "[setup] baue/repariere Vektorspeicher ..."
  if ($Rebuild) { & $Py main.py ingest --rebuild } else { & $Py main.py ingest }
}

Write-Host "[setup] registriere MCP-Server ..."
& $Py scripts\register_mcp.py --command $Py --arg main.py --arg serve --cwd $ProjectDir

Write-Host "[setup] starte Such-Daemon neu (falls er laeuft) ..."
& $Py main.py restart-daemon

if ($HasSources) {
  Write-Host "[setup] verifiziere ..."
  & $Py main.py status

  Write-Host "=============================================="
  Write-Host " Testabfrage"
  Write-Host "=============================================="
  Invoke-OptionalNative { & $Py main.py query "How do I set up conjugate heat transfer?" --top-k 3 } "[setup] Abfrage-Schnelltest uebersprungen/fehlgeschlagen - nicht kritisch"

  if ($SkipClaudeTest) {
    Write-Host "[setup] ueberspringe den einmaligen Claude-MCP-Test auf Wunsch (--skip-claude-test)."
  } else {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
      Write-Host "[setup] starte einmaligen Claude-Chat, um das MCP-Tool zu testen ..."
      Invoke-OptionalNative { & claude -p "Use the comsol-clippy MCP tool search_comsol_docs to find how to set up conjugate heat transfer in COMSOL, and cite the manual and page." } "[setup] einmaliger Claude-Test uebersprungen/fehlgeschlagen - nicht kritisch"
    }
  }
} else {
  Write-Host "[setup] ueberspringe Vektorspeicher-Verifikation, bis source/ Dokumente enthaelt."
  Write-Host "[setup] ueberspringe Abfrage-Schnelltest, bis source/ Dokumente enthaelt."
}

Write-Host "=============================================="
Write-Host " Fertig - naechste Schritte"
Write-Host "=============================================="
if (-not $HasSources) {
  Write-Host " 1) DOKUMENTE HINZUFUEGEN: legen Sie Ihre COMSOL-Handbuecher (PDF) oder Notizen (.txt/.md) ab in:"
  Write-Host "      $SourceDir"
  Write-Host " 2) Starten Sie start_de.cmd erneut, um sie einzubetten."
} else {
  Write-Host " Der MCP-Server ist registriert und der Vektorspeicher ist bereit."
}
Write-Host ""
Write-Host " Interaktiv testen: fuehren Sie 'claude' in diesem Ordner aus oder starten Sie Claude Desktop neu,"
Write-Host " und bitten Sie es dann, search_comsol_docs zu verwenden."
Write-Host ""
Write-Host " Optionen zum erneuten Ausfuehren: start_de.cmd --help"
Write-Host "=============================================="

Release-SetupMutex
