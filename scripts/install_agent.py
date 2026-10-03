"""PHASE 3/4: install the built ALP agent APK onto the attached device via ADB.

1. Resolves ADB (ALP_ADB -> ANDROID_HOME -> default SDK path) and lists
   attached devices.
2. Picks the device: explicit --serial/--device, else the first attached one.
3. `adb install -r -d` the APK (default: android-agent/alp-agent.apk).
4. Proves the install with `pm path com.alp.agent` + launches MainActivity.

Note: installing the APK does NOT claim Device Owner — that is done through the
console enroll flow (e.g. `adb shell dpm set-device-owner com.alp.agent/...`)
which this script prints as the documented follow-up.

Usage:
    python scripts/install_agent.py [--serial LT8110260130351] [--apk path]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PKG = "com.alp.agent"
DEFAULT_APK = os.path.join(ROOT, "android-agent", "alp-agent.apk")
_NO_WINDOW = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
              if sys.platform == "win32" else 0)


def adb_bin() -> str:
    adb = os.environ.get("ALP_ADB") or os.path.join(
        os.environ.get("ANDROID_HOME") or os.path.expandvars(
            r"%LOCALAPPDATA%\Android\Sdk"),
        "platform-tools", "adb.exe")
    return adb if os.path.exists(adb) else "adb"


def serials(adb: str) -> list[str]:
    r = subprocess.run([adb, "devices"], capture_output=True, text=True,
                       creationflags=_NO_WINDOW or 0)
    out = []
    for ln in r.stdout.splitlines()[1:]:
        if ln.strip() and "offline" not in ln:
            out.append(ln.split()[0])
    return out


def serial_of_device_id(device_id: str) -> str:
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    from backend.db import connect  # noqa: PLC0415
    with connect() as c:
        row = c.execute("SELECT serial FROM devices WHERE device_id=?",
                        (device_id,)).fetchone()
    return row["serial"] if row else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="install the ALP agent APK")
    ap.add_argument("--serial", default="", help="ADB serial (default: auto)")
    ap.add_argument("--device", default="", help="device_id to resolve serial")
    ap.add_argument("--apk", default=DEFAULT_APK,
                    help=f"path to the APK (default {DEFAULT_APK})")
    ap.add_argument("--no-launch", action="store_true",
                    help="skip launching MainActivity after install")
    args = ap.parse_args()

    adb = adb_bin()
    if not os.path.exists(adb):
        print(f"adb not found at {adb} (set ALP_ADB)")
        return 1
    if not os.path.exists(args.apk):
        print(f"APK not found: {args.apk} — run scripts/build_agent.py first")
        return 1

    devs = serials(adb)
    if not devs:
        print("NO DEVICES ATTACHED — nothing installed (honest: empty).")
        return 1
    serial = args.serial or (serial_of_device_id(args.device) if args.device else "")
    if not serial:
        if len(devs) == 1:
            serial = devs[0]
        else:
            print("multiple devices attached; pick one with --serial:")
            for d in devs:
                print("   ", d)
            return 1
    if serial not in devs:
        print(f"serial {serial} not attached (have: {', '.join(devs)})")
        return 1

    def sh(*argv):
        return subprocess.run([adb, "-s", serial, *argv],
                              capture_output=True, text=True, timeout=120,
                              creationflags=_NO_WINDOW or 0)

    print(f"installing {os.path.basename(args.apk)} -> {serial} ...")
    # -t: the debug-built APK carries the test-only flag; without it android
    # refuses with INSTALL_FAILED_TEST_ONLY.
    r = sh("install", "-r", "-d", "-t", args.apk)
    if r.returncode != 0:
        print("install failed:")
        print((r.stderr or r.stdout).strip())
        return 1
    print("install ok:", (r.stdout or r.stderr).strip()[-120:])

    p = sh("shell", "pm", "path", PKG)
    if p.returncode != 0 or PKG not in p.stdout:
        print(f"package {PKG} missing after install:")
        print((p.stderr or p.stdout).strip())
        return 1
    print("pm path:", p.stdout.strip())

    if not args.no_launch:
        sh("shell", "am", "start", "-n", f"{PKG}/.MainActivity",
           "--activity-no-history")
        print(f"launched {PKG}/.MainActivity")

    print(f"\ndevice owner follow-up (console enroll / manual):", end=" ")
    print(f"adb -s {serial} shell dpm set-device-owner {PKG}/.AlpDeviceAdminReceiver")
    return 0


if __name__ == "__main__":
    sys.exit(main())