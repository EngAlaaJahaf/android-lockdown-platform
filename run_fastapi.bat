@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (
  echo [ALP] Python not found in PATH. Install Python 3.11+ first.
  pause & exit /b 1
)

echo ======================================================================
echo [ALP FastAPI] Starting Modern Control-Plane on http://127.0.0.1:8765 ...
echo [ALP FastAPI] Press Ctrl+C to stop.
echo ======================================================================

:: Launch browser in background after 2 seconds while Python starts immediately
start "" powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765'"

python scripts\alp_fastapi.py
if errorlevel 1 (
  echo.
  echo [ALP FastAPI] Server stopped with error.
  pause
)
