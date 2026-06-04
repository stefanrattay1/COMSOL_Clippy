:; # ---------------------------------------------------------------------------
:; # COMSOL Clippy Starter (deutsche Version, Polyglott: laeuft als Windows .cmd UND
:; # als Bash-Skript). Unter Windows doppelklicken oder `bash start_de.cmd` unter
:; # Linux/WSL ausfuehren. Erkennt das Betriebssystem und startet das passende
:; # Setup-Skript (deutsche Ausgabe).
:; # ---------------------------------------------------------------------------
:; # ===== Zeilen, die mit ":;" beginnen, ignoriert Windows, Bash fuehrt sie aus. =====
:; DIR="$(cd "$(dirname "$0")" && pwd)"
:; echo "Linux/WSL erkannt - Setup wird gestartet..."
:; chmod +x "$DIR/setup/setup_de.sh" 2>/dev/null
:; exec bash "$DIR/setup/setup_de.sh" "$@"
:; exit $?
:; # Bash erreicht nichts hinter dem exec oben. Der Marker darunter verbirgt den
:; # Windows-Abschnitt vor dem Bash-Parser, damit `bash -n` zufrieden bleibt.
:<<'WINDOWS_ONLY'
@echo off
REM ===== Dieser Abschnitt laeuft nur unter Windows (cmd.exe) =====
echo Windows erkannt - Setup wird gestartet...
where powershell >nul 2>&1
if errorlevel 1 (
echo PowerShell wurde nicht im PATH gefunden. Installieren Sie Windows PowerShell oder
echo PowerShell 7 und fuehren Sie start_de.cmd erneut aus.
pause
exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\setup_de.ps1" %*
set "SETUP_EXIT=%ERRORLEVEL%"
echo.
if not "%SETUP_EXIT%"=="0" (
echo Setup mit Fehlercode %SETUP_EXIT% fehlgeschlagen.
echo Scrollen Sie nach oben fuer die Fehlerdetails, beheben Sie das Problem und fuehren Sie start_de.cmd erneut aus.
pause
exit /b %SETUP_EXIT%
)
echo Setup abgeschlossen. Sie koennen dieses Fenster schliessen.
pause
WINDOWS_ONLY
