@echo off
setlocal EnableExtensions
title ALP Wi-Fi Hard Block

rem ---------------------------------------------------------------
rem ALP Wi-Fi Hard Block / Unblock.
rem
rem LOCK (default):
rem   1. forget EVERY saved network  (kills the live connection and
rem      all auto-join/reconnect to any known network)
rem   2. turn the radio radio OFF     (cmd wifi set-wifi-enabled disabled)
rem   3. persist wifi_on=0            (survives reboot on most builds)
rem   4. remove shell network suggestions
rem   5. re-assert the hidden QS tile (no wifi tile in the pull-down)
rem   => the device cannot join ANY network while it stays applied.
rem
rem UNLOCK (arg "unlock"):
rem   re-enable the radio, restore wifi_on=1, restore default QS tiles.
rem   NOTE: forgotten networks are permanently deleted - re-add them
rem   manually from Settings once unlocked.
rem
rem Usage:
rem   wifi_block_any.cmd [lock|unlock] [serial]
rem
rem ADB resolution: ALP_ADB env var, then common SDK locations, then PATH.
rem ---------------------------------------------------------------

set "ACTION=lock"
if /i "%~1"=="unlock" set "ACTION=unlock"
set "SERIAL=%~2"

rem ---- resolve adb ----
set "ADB="
if defined ALP_ADB if exist "%ALP_ADB%" set "ADB=%ALP_ADB%"
if not defined ADB if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not defined ADB if defined ANDROID_HOME if exist "%ANDROID_HOME%\platform-tools\adb.exe" set "ADB=%ANDROID_HOME%\platform-tools\adb.exe"
if not defined ADB if exist "%ProgramFiles%\Android\platform-tools\adb.exe" set "ADB=%ProgramFiles%\Android\platform-tools\adb.exe"
if not defined ADB set "ADB=adb.exe"

echo [ADB]   %ADB%
echo [ACTION] %ACTION%

rem ---- resolve serial ----
if not defined SERIAL (
    for /f "tokens=1" %%s in ('"%ADB%" devices') do (
        if not defined SERIAL (
            if /i not "%%s"=="List" if /i not "%%s"=="of" if /i not "%%s"=="devices" if /i not "%%s"=="attached" (
                set "SERIAL=%%s"
            )
        )
    )
)
if not defined SERIAL (
    echo [ERROR] no device attached via ADB.
    exit /b 1
)
echo [DEVICE] %SERIAL%

if "%ACTION%"=="unlock" goto :unlock

rem ============================================================
rem LOCK
rem ============================================================
echo.
echo == 1/5  forget every saved network ==
set "NETLIST=%TEMP%\alp_netlist_%RANDOM%.txt"
"%ADB%" -s "%SERIAL%" shell cmd wifi list-networks > "%NETLIST%" 2>nul
rem for /f cannot run a quoted command (its leading quote is swallowed), so
rem the list is dumped to a temp file and IDs are parsed from the file.
for /f "tokens=1 delims= " %%n in ('findstr /R "[0-9]" "%NETLIST%"') do (
    echo      forgetting network %%n ...
    "%ADB%" -s "%SERIAL%" shell cmd wifi forget-network %%n
)
del "%NETLIST%" 2>nul
echo [OK] saved networks cleared.

echo.
echo == 2/5  power the radio OFF ==
"%ADB%" -s "%SERIAL%" shell cmd wifi set-wifi-enabled disabled
echo [OK] radio disable requested.

echo.
echo == 3/5  persist wifi_on=0 ==
"%ADB%" -s "%SERIAL%" shell settings put global wifi_on 0
echo [OK] wifi_on=0 persisted.

echo.
echo == 4/5  remove shell network suggestions ==
"%ADB%" -s "%SERIAL%" shell cmd wifi remove-all-suggestions
echo [OK] suggestions cleared.

echo.
echo == 5/5  re-assert hidden QS tile (no wifi toggle in shade) ==
"%ADB%" -s "%SERIAL%" shell settings put secure qs_tiles bt,rotation,cell,airplane,dnd
echo [OK] tile hidden.

echo.
echo == VERIFY ==
"%ADB%" -s "%SERIAL%" shell cmd wifi status | findstr /I /C:"Wifi is disabled" >nul
if errorlevel 1 (
    echo [WARN] wifi reported NOT disabled ^(check manually^)
) else (
    echo [OK] wifi is disabled.
)
"%ADB%" -s "%SERIAL%" shell settings get global wifi_on
echo.
echo [DONE] Wi-Fi is hard-blocked: no saved networks, radio off,
echo        no auto-join, no QS tile. Re-run with "unlock" to undo.
goto :eof

rem ============================================================
rem UNLOCK
rem ============================================================
:unlock
echo.
echo == 1/3  power the radio ON ==
"%ADB%" -s "%SERIAL%" shell cmd wifi set-wifi-enabled enabled
echo == 2/3  persist wifi_on=1 ==
"%ADB%" -s "%SERIAL%" shell settings put global wifi_on 1
echo == 3/3  restore default QS tiles ==
"%ADB%" -s "%SERIAL%" shell settings delete secure qs_tiles
echo.
echo [DONE] radio enabled + QS tiles restored. Remember: previously
echo        saved networks were deleted by the lock and are GONE.
endlocal