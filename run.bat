@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (
  echo [ALP] Python not found in PATH. Install Python 3.11+ first.
  pause & exit /b 1
)

echo [ALP] Starting web console on http://127.0.0.1:8765 ...
echo [ALP] Press Ctrl+C to stop.

powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765'"

python scripts\alp_fastapi.py