"""Real ADB control channel for the on-device DPC agent.

Delivers signed envelopes to the DPC over adb by FILE DROP + broadcast with NO
extras — `am --es` truncates long JSON on some builds ("End of input at
character 8" defect observed), so each action uploads its own envelope file
under /data/local/tmp and the agent reads it back from disk.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from .workflows import adb

_NO_WINDOW = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
              if sys.platform == "win32" else 0)

# action -> remote envelope file the DPC expects
REMOTE_FILES = {
    "APPLY_POLICY": "/data/local/tmp/alp_envelope.json",
    "CLEAR_POLICY": "/data/local/tmp/alp_rollback.json",
    "GET_STATE": "/data/local/tmp/alp_req_state.json",
    "WITHDRAW_DO": "/data/local/tmp/alp_withdraw.json",
    "PROVISION_PIN": "/data/local/tmp/alp_pin.json",
    "EMERGENCY_TOKEN": "/data/local/tmp/alp_emergency.json",
    "EMERGENCY_SECRET": "/data/local/tmp/alp_offline_secret.json",
}


def adb_channel(serial: str, out_dir: str = ""):
    """Return (send, state).

    send(envelope, action=None) -> dict{ok, error?, staged?}
    Every delivery writes the envelope locally under out_dir (audit trail) and,
    when the device is attached, pushes + broadcasts it.
    """
    state = {"delivered": []}

    def send(envelope, action=None):
        action = action or envelope.get("action", "APPLY_POLICY")
        local = None
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            local = os.path.join(out_dir, envelope.get("cmd_id", "env") + ".json")
            with open(local, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, ensure_ascii=False, indent=2)
        remote = REMOTE_FILES.get(action, REMOTE_FILES["APPLY_POLICY"])

        def sh(*args):
            return subprocess.run([adb(), "-s", serial, *args],
                                  capture_output=True, text=True, timeout=60,
                                  creationflags=_NO_WINDOW or 0)

        r = sh("push", local or _tmp_write(envelope), remote)
        if r.returncode != 0:
            err = {"ok": False, "error": f"adb push failed: {r.stderr.strip()[:200]}",
                   "action": action, "cmd_id": envelope.get("cmd_id", "")}
            state["delivered"].append(err)
            return err
        intent = f"com.alp.agent.{action}"
        # Wake + deliver. On builds that vault background broadcasts (standby
        # bucket RESTRICTED / app-freezer), broadcasting to a background app is
        # silently deferred forever, so we first foreground the launcher via
        # `am start`; while the app is foreground the broadcast dispatches
        # immediately. Both transports funnel into the same AlpOps pipeline,
        # deduped by cmd_id, so double-processing never happens.
        n = sh("shell", "am", "start", "-n", "com.alp.agent/.MainActivity",
               "--activity-no-history")
        b = sh("shell", "am", "broadcast", "-n",
               "com.alp.agent/.CommandReceiver", "-a", intent,
               "--receiver-foreground")
        time.sleep(1)
        out = {"ok": n.returncode == 0, "action": action,
               "cmd_id": envelope.get("cmd_id", ""), "intent": intent,
               "staged": local or True,
               "error": None if n.returncode == 0 else n.stderr.strip()[:200]}
        state["delivered"].append(out)
        return out

    return send, state


def _tmp_write(envelope: dict) -> str:
    import tempfile
    fd, path = tempfile.mkstemp(prefix="alp_env_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, ensure_ascii=False)
    return path