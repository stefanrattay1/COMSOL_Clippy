:; # ---------------------------------------------------------------------------
:; # COMSOL Clippy launcher (polyglot: runs as Windows .cmd AND as a bash script).
:; # Double-click on Windows, or run `bash start.cmd` on Linux/WSL.
:; # It detects your operating system and runs the matching setup script.
:; # ---------------------------------------------------------------------------
:; # ===== Lines starting with ":;" are ignored by Windows but run by bash =====
:; DIR="$(cd "$(dirname "$0")" && pwd)"
:; echo "Detected Linux/WSL - starting setup..."
:; chmod +x "$DIR/setup/setup.sh" 2>/dev/null
:; exec bash "$DIR/setup/setup.sh" "$@"
:; exit $?
:; # bash never reaches past the exec above. The marker below hides the Windows
:; # section from bash's parser so `bash -n` stays happy.
:<<'WINDOWS_ONLY'
@echo off
REM ===== This section runs only on Windows (cmd.exe) =====
echo Detected Windows - starting setup...
where powershell >nul 2>&1
if errorlevel 1 (
echo PowerShell was not found on PATH. Install Windows PowerShell or PowerShell 7,
echo then run start.cmd again.
pause
exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\setup.ps1" %*
set "SETUP_EXIT=%ERRORLEVEL%"
echo.
if not "%SETUP_EXIT%"=="0" (
echo Setup failed with exit code %SETUP_EXIT%.
echo Scroll up for the error details, fix that, and run start.cmd again.
pause
exit /b %SETUP_EXIT%
)
echo Setup finished. You can close this window.
pause
WINDOWS_ONLY
