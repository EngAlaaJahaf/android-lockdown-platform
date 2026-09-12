# -*- coding: utf-8 -*-
"""AndroidLockdownManager_Setup.exe — per-user installer for ALP Manager.

Hosted by PyInstaller onefile: this module shells out to the real setup flow:
copy ALPManager.exe into %LOCALAPPDATA%\\Programs, create a Start Menu
shortcut, register a per-user uninstall entry (no admin rights needed), and
optionally launch the application.

Usage:
    AndroidLockdownManager_Setup.exe              # install
    AndroidLockdownManager_Setup.exe --uninstall  # remove
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys


APP_NAME = "AndroidLockdownManager"
DISPLAY_NAME = "ALP Manager — نظام إدارة تقييد أجهزة Android"
VERSION = "1.0.0"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidLockdownManager"


def _bundle_exe() -> str:
    """Path of the bundled ALPManager.exe (extracted inside this onefile)."""
    meipass = getattr(sys, "_MEIPASS", os.getcwd())
    cand = os.path.join(meipass, "ALPManager.exe")
    return cand if os.path.exists(cand) else ""


def _install_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP_NAME)


def _shortcut_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu",
                        "Programs", "AndroidLockdownManager.lnk")


def _desktop_shortcut_path() -> str:
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(d, "AndroidLockdownManager.lnk")


def _make_shortcut(lnk: str, target: str, wd: str, args: str = "",
                   try_raise: bool = False) -> bool:
    """Create a .lnk via PowerShell WScript.Shell (COM, no deps)."""
    import tempfile
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$s = $ws.CreateShortcut('{lnk}');"
        f"$s.TargetPath = '{target}';"
        f"$s.Arguments = '{args}';"
        f"$s.WorkingDirectory = '{wd}';"
        f"$s.Save()"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", ps],
                           capture_output=True, timeout=30)
        return r.returncode == 0 and os.path.exists(lnk)
    except Exception:  # noqa: BLE001
        if try_raise:
            raise
        return False


def _set_uninstall_entry(installed: str) -> None:
    import winreg  # noqa: PLC0415
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, DISPLAY_NAME)
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "ALP")
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, installed)
        setup_exe = os.path.abspath(sys.argv[0])
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                          f'"{setup_exe}" --uninstall')
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def _clear_uninstall_entry() -> None:
    try:
        import winreg  # noqa: PLC0415
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


def _msg(text: str, title: str = "ALP Manager") -> int:
    if os.environ.get("ALP_INSTALLER_NONINTERACTIVE") == "1":
        print(f"[non-interactive] {title}: {text}")
        return 0
    return ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)  # MB_ICONINFORMATION


def install() -> int:
    src = _bundle_exe()
    if not src:
        _msg("ملف ALPManager.exe غير موجود داخل حزمة التثبيت.",
             "خطأ في التثبيت")
        return 1
    dest = _install_dir()
    os.makedirs(dest, exist_ok=True)
    target = os.path.join(dest, "ALPManager.exe")
    shutil.copy2(src, target)

    ok_sc = _make_shortcut(_shortcut_path(), target, dest)
    _make_shortcut(_desktop_shortcut_path(), target, dest)
    _set_uninstall_entry(dest)

    _msg(
        "تم تثبيت ALP Manager بنجاح.\n\n"
        "الموقع: " + dest + "\n"
        "اختصاران أُنشئا: قائمة ابدأ وسطح المكتب.\n"
        "للإزالة: إعدادات > التطبيقات > ALP Manager > إلغاء التثبيت، "
        "أو شغّل المثبّت مع الخيار --uninstall.",
        "ALP Manager — اكتمل التثبيت")
    run = 0
    if os.environ.get("ALP_INSTALLER_NONINTERACTIVE") != "1":
        run = ctypes.windll.user32.MessageBoxW(
            0, "هل تريد تشغيل ALP Manager الآن؟", "ALP Manager", 0x4 | 0x40)
    if run == 6:  # IDYES
        subprocess.Popen(["explorer.exe", target])
    return 0


def uninstall() -> int:
    dest = _install_dir()
    target = os.path.join(dest, "ALPManager.exe")
    removed = 0
    for p in (_shortcut_path(), _desktop_shortcut_path(), target):
        try:
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except OSError:
            pass
    try:
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
    except OSError:
        pass
    _clear_uninstall_entry()
    _msg("تمت إزالة ALP Manager. (بيانات التطبيق في %LOCALAPPDATA%\\ALPManager "
         "بقيت محفوظة للمراجعة.)", "ALP Manager — الإزالة")
    return 0


def main() -> int:
    if "--uninstall" in sys.argv:
        return uninstall()
    return install()


if __name__ == "__main__":
    raise SystemExit(main())