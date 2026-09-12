# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AndroidLockdownManager_Setup.exe (onefile, windowed).

Build:
    python -m PyInstaller deployment/AndroidLockdownManager_Setup.spec --noconfirm

Requires: dist/ALPManager.exe built first (this spec embeds it as data).
Output: dist/AndroidLockdownManager_Setup.exe
"""
import os

ROOT = os.getcwd()

app_exe = os.path.join(ROOT, "dist", "ALPManager.exe")

a = Analysis(
    [os.path.join(ROOT, "deployment", "installer_app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(app_exe, ".")] if os.path.exists(app_exe) else [],
    hiddenimports=["winreg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "tkinter", "PyQt5", "PyQt6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AndroidLockdownManager_Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)