"""PHASE 0: live capability scan of the attached device via ADB.

Run:     python scripts/scan_live_device.py
Output:  reports/phase0/scan-<serial>.json + short console report
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("capability-engine",):
    sys.path.insert(0, os.path.join(ROOT, sub))

from capability_engine.scanner import adb_scan

out_dir = os.path.join(ROOT, "reports", "phase0")
os.makedirs(out_dir, exist_ok=True)

adb = os.environ.get("ALP_ADB") or os.path.join(
    os.environ.get("ANDROID_HOME") or os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk"),
    "platform-tools", "adb.exe")
if not os.path.exists(adb):
    adb = "adb"


def serials() -> list[str]:
    r = subprocess.run([adb, "devices"], capture_output=True, text=True)
    out = []
    for ln in r.stdout.splitlines()[1:]:
        if ln.strip() and "offline" not in ln:
            out.append(ln.split()[0])
    return out


def main() -> None:
    devs = serials()
    if not devs:
        print("NO DEVICES ATTACHED — nothing scanned (honest: empty).")
        return
    for s in devs:
        print(f"scanning {s} ...")
        prof = adb_scan(adb=adb, serial=s)
        fname = os.path.join(out_dir, f"scan-{s.replace('-', '')}.json")
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write(prof.to_json())
        observed = {f: st for f, st in prof.states.items()
                    if st in ("ANDROID_VERSION_DEPENDENT", "PARTIAL", "NOT_FEASIBLE")}
        print(f"  android={prof.android_version} api={prof.api_level} "
              f"model={prof.model} ({prof.manufacturer})")
        for f in sorted(observed):
            print(f"    {f:22s} {observed[f]}")
        print(f"  saved -> {fname}")


if __name__ == "__main__":
    main()