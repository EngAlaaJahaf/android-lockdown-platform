@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul || (echo [ALP] Python not found in PATH. & pause & exit /b 1)
python scripts\totp_live.py
pause