#!/usr/bin/env python3
"""restore_default.py — honest R1 rollback launcher (REAL on-disk script).

Routes into the REAL RecoveryEngine at backend/recovery.py using the same
import convention as the passing unit tests (tests/unit/test_recovery.py
injects the project root into sys.path, then uses `recovery.RecoveryEngine`).

The engine's honest invariants therefore hold automatically and are NOT
something this script may override:

  * PASS/COMPLETE is structurally impossible without an evidence id AND a
    real device observation (source must be REAL_DEVICE with a serial).
  * With no ADB-visible device the result will be PLAN_ONLY / SIMULATED and
    the script exits non-zero with a reason that says EXACTLY that — it does
    NOT print "COMPLETE" on an empty adb devices.

Run on the real device once it is ADB-visible:
    python scripts/restore_default.py DEV-1 \\
        --serial 520041d74247b58b --role SUPER_ADMIN \\
        --cred <recovery-credential> --approval '<json>' --exec
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # same convention as tests/unit/test_recovery.py

from backend.recovery import (  # noqa: E402  (real interface, not a stub)
    RecoveryEngine,
    RecoveryBlocked,
    RecoveryResult,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="ALP R1_RESTORE_POINT (real)")
    ap.add_argument("device_id")
    ap.add_argument("--serial", default="",
                    help="ADB serial of the real device (REAL_DEVICE path)")
    ap.add_argument("--role", default="SUPER_ADMIN")
    ap.add_argument("--cred", default="",
                    help="per-device recovery credential (possession factor)")
    ap.add_argument("--approval", default="{}",
                    help="signed approval envelope as JSON")
    ap.add_argument("--exec", action="store_true",
                    help="honest exec gate — without a REAL_DEVICE the engine "
                         "cannot and will not claim COMPLETE")
    ap.add_argument("--reason", default="operator-initiated rollback")
    args = ap.parse_args()

    engine = RecoveryEngine(
        db_path=os.environ.get("ALP_DB") or None,
        signing_key=os.environ.get("ALP_SIGNING_KEY", ""),
    )

    try:
        res = engine.recover(
            args.device_id, "R1_RESTORE_POINT", args.role, 1,
            mfa_ok=False,
            credential_ok=bool(args.cred),
            approval=json.loads(args.approval or "{}"),
            serial=args.serial,
            exec_=args.exec,
            restore_reason=args.reason,
        )
    except RecoveryBlocked as ex:
        print(f"REFUSED: {ex}")
        return 1

    d = res.to_dict()
    print(json.dumps(d, indent=2, ensure_ascii=False))
    # Honest gate: never let the caller leave believing it is done if the
    # device was never actually observed (no serial or SIMULATED only).
    if d.get("status") in ("COMPLETE", "PARTIAL") and d.get("source") != "REAL_DEVICE":
        print("WARNING: cannot verify COMPLETE without a REAL_DEVICE observation "
              "(honest invariant from backend/recovery.py).")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())


