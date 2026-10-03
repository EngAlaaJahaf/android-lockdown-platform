@echo off
setlocal EnableExtensions
title ALP Agent Installer

rem ---------------------------------------------------------------
rem ALP agent installer (generic engine).
rem
rem Choose an entry point:
rem   install_agent_dev.cmd       -> alp-agent.apk           (dev:    drawer icon,
rem                                                           testOnly)
rem   install_agent_release.cmd   -> alp-agent-release.apk   (release: hidden from
rem                                                           drawer, can become
rem                                                           Device Owner)
rem   install_agent.cmd [apk] [serial]   -> custom APK
rem
rem The engine detects the mode automatically from the APK filename:
rem   dev     -> install -r -d -t, NO Device Owner attempt (testOnly DPC is
rem              refused by dpm set-device-owner)
rem   release -> install -r -d, then attempt Device Owner claim
rem
rem ADB resolution: ALP_ADB env var, then common SDK locations, then PATH.
rem ---------------------------------------------------------------

set "SCRIPT_DIR=%~dp0"
set "APK=%~1"
if "%APK%"=="" set "APK=%~dp0..\android-agent\alp-agent.apk"
set "SERIAL=%~2"

rem ---- resolve adb ----
set "ADB="
if defined ALP_ADB if exist "%ALP_ADB%" set "ADB=%ALP_ADB%"
if not defined ADB if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not defined ADB if defined ANDROID_HOME if exist "%ANDROID_HOME%\platform-tools\adb.exe" set "ADB=%ANDROID_HOME%\platform-tools\adb.exe"
if not defined ADB if exist "%ProgramFiles%\Android\platform-tools\adb.exe" set "ADB=%ProgramFiles%\Android\platform-tools\adb.exe"
if not defined ADB set "ADB=adb.exe"

if not exist "%APK%" (
    echo [ERROR] APK not found: %APK%
    echo         Run scripts\build_agent.py first, or pass a path as arg 1.
    exit /b 1
)

set "MODE=dev"
echo %APK% | findstr /I /C:"release" >nul && set "MODE=release"
echo [MODE]  %MODE%  ^(dev=visible+testOnly / release=hidden+DPC-capable^)

echo [ADB]   %ADB%
echo [APK]   %APK%

rem ---- list attached devices ----
"%ADB%" devices
for /f "tokens=1" %%s in ('"%ADB%" devices') do (
    if not defined SERIAL (
        if /i not "%%s"=="List" if /i not "%%s"=="of" if /i not "%%s"=="devices" if /i not "%%s"=="attached" (
            set "SERIAL=%%s"
        )
    )
)
if not defined SERIAL (
    echo [ERROR] no device attached via ADB.
    exit /b 1
)
echo [DEVICE] %SERIAL%

rem ---- install ----
echo.
echo Installing "%APK%" on %SERIAL% ...
if "%MODE%"=="release" (
    "%ADB%" -s "%SERIAL%" install -r -d "%APK%"
) else (
    "%ADB%" -s "%SERIAL%" install -r -d -t "%APK%"
)
if errorlevel 1 (
    echo [ERROR] install failed ^(see above^).
    exit /b 1
)
echo [OK] install success.

echo.
"%ADB%" -s "%SERIAL%" shell pm path com.alp.agent

if "%MODE%"=="dev" (
    echo.
    echo [DO] skipped: this is the dev APK ^(testOnly^). A testOnly app can
    echo      never be a Device Owner. Install via install_agent_release.cmd
    echo      to claim the Device Owner role.
    goto :eof
)

rem ---- attempt Device Owner claim (release only) ----
echo.
echo [DO] claiming Device Owner com.alp.agent/.AlpDeviceAdminReceiver ...
"%ADB%" -s "%SERIAL%" shell dpm set-device-owner com.alp.agent/.AlpDeviceAdminReceiver
echo.
"%ADB%" -s "%SERIAL%" shell dumpsys device_policy | findstr /C:"com.alp.agent" >nul
if errorlevel 1 (
    echo [DO] FAILED: com.alp.agent is NOT the device owner. Reasons:
    echo      1. the APK is still testOnly - rebuild with build_agent.py --release
    echo      2. another package already owns the device
    echo      3. device has user accounts / unprovisioned - factory reset may help
) else (
    echo [DO] OK: com.alp.agent is the Device Owner on %SERIAL%.
)
echo.
endlocal