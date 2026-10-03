@echo off
setlocal EnableExtensions
title ALP Manager

rem ---------------------------------------------------------------
rem Launch the ALP Manager desktop app on Windows (Qt, Tk fallback).
rem
rem   run_app.cmd                -> Qt UI (falls back to Tk automatically)
rem   run_app.cmd --tk           -> force the legacy Tk UI
rem
rem Any startup crash opens the console and pauses so the traceback
rem stays visible instead of the window silently closing.
rem ---------------------------------------------------------------

set "ROOT=%~dp0.."
pushd "%ROOT%"

rem ---- Python: prefer the py launcher, else python on PATH ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"

rem ---- engine + package import paths (same set run_tests.py uses) ----
set "PYTHONPATH=%ROOT%;%ROOT%\backend;%ROOT%\desktop;%ROOT%\policy-engine;%ROOT%\capability-engine;%ROOT%\verification-engine;%ROOT%\compatibility;%ROOT%\vendor-adapters"

rem ---- dev signing key default so apply/rollback flows are usable ----
if not defined ALP_SIGNING_KEY (
    set "ALP_SIGNING_KEY=alp-cli-dev-key-0001"
    echo [NOTE] ALP_SIGNING_KEY unset - using the dev default key.
)

echo [APP]   %PY% desktop\run_app.py %*
echo [ROOT]  %ROOT%
echo.
%PY% desktop\run_app.py %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [ERROR] ALP Manager exited with code %RC% - see the traceback above.
    pause
)
endlocal & exit /b %RC%