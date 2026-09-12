"""PHASE 3/4: deliver a REAL signed envelope to the on-device agent over ADB.

1. Builds the signed command envelope (backend.command.new_command) exactly as
   the Director would, for a reference policy on a target device.
2. Push es to /data/local/tmp/alp_envelope.json and broadcasts APPLY_POLICY.
3. Reads back the device-side state.json via `run-as` (real DPC evidence).

Usage: python scripts/deliver_command.py --device AVD-5554 --policy PHONE_ONLY
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
for sub in ("policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters"):
    sys.path.insert(0, os.path.join(ROOT, sub))

import backend.config as config
from backend.command import new_command
from backend.workflows import resolve_policy, adb


def _serial_of(device_id: str) -> str:
    from backend.db import connect
    with connect() as c:
        r = c.execute("SELECT serial FROM devices WHERE device_id=?", (device_id,)).fetchone()
    return r["serial"] if r else ""


def _snapshot_rows(policy_id: str) -> list[dict]:
    pol = resolve_policy(policy_id)
    if pol is None:
        raise SystemExit(f"unknown policy {policy_id}")
    subset = {s.strip().upper() for s in
              os.environ.get("ALP_LANE_SUBSET", "").split(",") if s.strip()}
    rows = []
    for r in pol.requirements:
        if subset and r.feature.upper() not in subset:
            continue
        rows.append({"feature": r.feature, "desired": r.desired_state,
                     "method": r.enforcement_method, "risk": r.risk})
    return rows


def main() -> int:
    device, policy = os.environ.get("ALP_DEVICE", "AVD-5554"), os.environ.get("ALP_POLICY", "PHONE_ONLY")
    serial = _serial_of(device) or "emulator-5554"
    env = new_command(0, device, "APPLY_POLICY",
                      {"policy_id": policy, "version": 1,
                       "snapshot": _snapshot_rows(policy)},
                      key=config.SIGNING_KEY or "alp-cli-dev-key-0001")
    local = os.path.join(ROOT, "reports", "phase3", env["cmd_id"] + ".json")
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w", encoding="utf-8") as fh:
        json.dump(env, fh, ensure_ascii=False, indent=2)
    remote = "/data/local/tmp/alp_envelope.json"

    def sh(*args):
        return subprocess.run([adb(), "-s", serial, *args],
                              capture_output=True, text=True, timeout=60)

    r = sh("push", local, remote)
    if r.returncode != 0:
        print("push failed:", r.stderr)
        return 1
    r = sh("shell", "am", "broadcast",
           "-n", "com.alp.agent/com.alp.agent.CommandReceiver",
           "-a", "com.alp.agent.APPLY_POLICY")
    print(r.stdout.strip())
    time.sleep(1)
    r = sh("shell", "run-as", "com.alp.agent", "cat", "files/state.json")
    if r.returncode != 0:
        print("run-as read failed:", r.stderr or r.stdout)
        return 1
    try:
        state = json.loads(r.stdout)
    except Exception:
        print("raw:", r.stdout)
        return 1
    print(json.dumps(state, indent=2, ensure_ascii=False))
    with open(os.path.join(os.path.dirname(local), "state.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())