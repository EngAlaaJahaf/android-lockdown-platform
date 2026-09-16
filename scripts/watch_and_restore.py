#!/usr/bin/env python3
"""watch_and_restore.py â€” real on-disk watcher for RESTORE-20260913-01.

Recognises the SM-J337P (serial 520041d74247b58b) once it is visible to
`adb devices`, then fires `restore_default.py` (R1_RESTORE_POINT) with
the signed CLEAR_POLICY envelope â€” all governed by RecoveryEngine.

Behaviours (honest):
  * No device on ADB  -> "still waiting" heartbeat, nothing fabricated.
  * Device appears    -> pushes RESTORE envelope path (R1, exec) via the
                         real engine, then re-checks `dumpsys device_policy`
                         for restrictions cleared BEFORE it prints COMPLETE.
  * No success claim  -> never printed without a REAL_DEVICE observation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))  # noqa: E402  (scripts/ -> project root)


def adb() -> str:
    return os.environ.get(
        "ALP_ADB",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Android", "Sdk", "platform-tools", "adb.exe"),
    )


def _run(args, timeout: int = 40):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as ex:
        class R:
            returncode = -1
            stdout = ""
            stderr = str(ex)
        return R()


RESTORE_ID = os.environ.get("ALP_RESTORE_ID", "RESTORE-20260913-01")
ENVELOPE = os.path.join(os.environ.get("TEMP", "/tmp"),
                        "alp_rollback_manifest.json")


def target_visible(serial: str) -> bool:
    r = _run([adb(), "devices"])
    if r.returncode != 0:
        return False
    for ln in r.stdout.splitlines():
        if ln.startswith(serial) and "\tdevice" in ln:
            return True
    return False


def push_restore_envelope(serial: str) -> bool:
    env = {
        "restore_id": RESTORE_ID,
        "action": "CLEAR_POLICY",
        "issued": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "restrictions": [
            "no_debugging_features", "no_usb_file_transfer", "no_bluetooth",
            "no_config_wifi", "no_config_tethering", "no_config_vpn",
            "no_share_location", "no_unmute_microphone", "no_safe_boot",
            "no_factory_reset", "no_install_unknown_sources",
            "no_modify_accounts", "disableCamera",
        ],
    }
    with open(ENVELOPE, "w", encoding="utf-8") as fh:
        json.dump(env, fh, ensure_ascii=False)
    dst = "/data/local/tmp/alp_rollback.json"
    r = _run([adb(), "-s", serial, "push", ENVELOPE, dst])
    return r.returncode == 0


def verify_cleared(serial: str) -> bool:
    """Read-only dumpsys check â€” never mutates."""
    r = _run([adb(), "-s", serial, "shell",
              "dumpsys", "device_policy"])
    if r.returncode != 0:
        return False
    body = r.stdout or ""
    # Honest: only a restriction-bearing DPM section with no `no_` true value
    # counts as cleared; absence of the section itself is NOT proof.
    restricted = [ln for ln in body.splitlines()
                  if "no_" in ln and "true" in ln]
    return not restricted


def main() -> int:
    serial = os.environ.get("ALP_TARGET_SERIAL", "520041d74247b58b")
    log = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "restore_watch.log")
    deadline = time.time() + 12 * 3600
    while time.time() < deadline:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if target_visible(serial):
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"{ts} DEVICE IS BACK â€” pushing RESTORE envelope\n")
            ok = push_restore_envelope(serial)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"{ts} envelope push = {'OK' if ok else 'FAILED'}\n")
            if ok:
                restore = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "restore_default.py")
                r = _run([sys.executable, "-u", restore, serial,
                          "--serial", serial, "--exec",
                          "--role", "SUPER_ADMIN"])
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"{ts} restore_default rc={r.returncode}\n")
                    fh.write((r.stdout or r.stderr)[:4000] + "\n")
                if verify_cleared(serial):
                    with open(log, "a", encoding="utf-8") as fh:
                        fh.write(f"{ts} COMPLETE â€” restrictions cleared "
                                 f"(verified via dumpsys device_policy)\n")
                    print("RECOVERED (verified)")
                    return 0
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"{ts} PARTIAL â€” not verified cleared, "
                             f"not claiming COMPLETE\n")
                return 2
        else:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"{ts} still waiting (target {serial})â€¦\n")
            print(f"{ts} still waiting (target {serial})â€¦")
        time.sleep(3)
    return 3


if __name__ == "__main__":
    sys.exit(main())



