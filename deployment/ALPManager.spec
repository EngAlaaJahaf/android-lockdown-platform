# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ALP Manager desktop application (onefile, windowed).

Build:
    python -m PyInstaller deployment/ALPManager.spec --noconfirm

Output: dist/ALPManager.exe
"""
import os
import sys

ROOT = os.getcwd()

a = Analysis(
    [os.path.join(ROOT, "desktop", "run_app.py")],
    pathex=[ROOT,
            os.path.join(ROOT, "policy-engine"),
            os.path.join(ROOT, "capability-engine"),
            os.path.join(ROOT, "verification-engine"),
            os.path.join(ROOT, "compatibility"),
            os.path.join(ROOT, "vendor-adapters")],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "database", "schema.sql"), "database"),
        (os.path.join(ROOT, "database", "migrations"), "database/migrations"),
    ],
    hiddenimports=[
        "alp_manager.app",
        "alp_manager.app_qt",
        "alp_manager.logger",
        "alp_manager.controller",
        "policy_engine",
        "capability_engine",
        "verification_engine",
        "verification_engine.probe",
        "compatibility",
        "vendor_adapters",
        "vendor_adapters.registry",
        "backend.recovery",
        "backend.recovery_credentials",
        "backend.channel",
        "backend.workflows",
        "backend.director",
        "backend.audit",
        "backend.auth",
        "backend.approval",
        "backend.command",
        "backend.fleet",
        "backend.rbac",
        "backend.db",
        "backend.config",
        "backend.api",
        "backend.state_machine",
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        "PySide6.QtCore",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ALPManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)