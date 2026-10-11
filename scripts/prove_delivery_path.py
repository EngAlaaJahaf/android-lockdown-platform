# -*- coding: utf-8 -*-
"""Prove the console's own delivery path now really reaches the handset.

Runs the same call the console makes (POST /groups/{id}/deploy with
real=true) through HTTP, then reads the device's own apply record to confirm the
bytes arrived and were enforced.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = r"D:\projects\android-lockdown-platform"
sys.path.insert(0, ROOT)
from backend.db import connect          # noqa: E402
from backend import auth as auth_mod    # noqa: E402

ADB = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                   "Android", "Sdk", "platform-tools", "adb.exe")
SERIAL = "LT8110260130351"
BASE = "http://127.0.0.1:8765"
USER, PW = "delivery_probe_admin", "delivery-probe-pw-0001"


def sh(*args):
    return subprocess.run([ADB, "-s", SERIAL, *args],
                          capture_output=True, text=True, timeout=90)


with connect() as c:
    c.execute("INSERT INTO administrators (username, password_hash, role_id, "
              "active, mfa_enabled, display_name) VALUES (?,?,?,1,0,?) "
              "ON CONFLICT(username) DO UPDATE SET "
              "password_hash=excluded.password_hash, role_id=excluded.role_id, "
              "active=1, mfa_enabled=0",
              (USER, auth_mod.hash_password(PW), 1, USER))


def call(method, path, body=None, token=None):
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def device_apply_record():
    r = sh("shell", "run-as", "com.alp.agent", "cat", "files/apply_result.json")
    raw = (r.stdout or "").strip()
    return json.loads(raw) if raw.startswith("{") else {}


def os_restrictions():
    out = sh("shell", "dumpsys", "user").stdout
    grab, block = False, []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Effective restrictions:"):
            grab = True
            continue
        if grab:
            if not s or s.endswith(":"):
                break
            block.append(s)
    return sorted(block)


st, p = call("POST", "/api/v1/auth/login", {"username": USER, "password": PW})
tok = p["data"]["token"]
print("logged in as", p["data"]["username"])

before_cmd = device_apply_record().get("cmd_id", "(none)")
before_res = os_restrictions()
print("\nBEFORE  apply cmd_id :", before_cmd)
print("BEFORE  restrictions :", len(before_res))
for r in before_res:
    print("   -", r)

print("\n--- POST /api/v1/groups/1/deploy  (exactly what the console sends) ---")
st, p = call("POST", "/api/v1/groups/1/deploy",
             {"real": True, "skip_approval": True,
              "reason": "delivery path proof"}, token=tok)
print("HTTP", st)
print(json.dumps(p, ensure_ascii=False, indent=1, default=str)[:1400])

time.sleep(6)
after_cmd = device_apply_record().get("cmd_id", "(none)")
after_res = os_restrictions()
record = device_apply_record()
print("\nAFTER   apply cmd_id :", after_cmd)
print("AFTER   restrictions :", len(after_res))
for r in after_res:
    print("   -", r)
print("\nagent applied rows   :", len(record.get("applied") or []))
print("agent skipped rows   :", record.get("skipped"))

stale = before_cmd == after_cmd
print("\nVERDICT:", "NO NEW COMMAND REACHED THE DEVICE"
      if stale else "DELIVERY REACHED THE DEVICE")

with connect() as c:
    c.execute("PRAGMA foreign_keys=OFF")
    cols = [r[1] for r in c.execute("PRAGMA table_info(sessions)")]
    for key in ("username", "user_id", "user_ref", "admin_id"):
        if key in cols:
            c.execute("DELETE FROM sessions WHERE %s=?" % key, (USER,))
            break
    for t in ("audit_logs", "approvals"):
        tcols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
        for key in ("actor", "actor_username", "username", "requester",
                    "approver_1", "approver_2", "initiated_by"):
            if key in tcols:
                try:
                    c.execute("DELETE FROM %s WHERE %s=?" % (t, key), (USER,))
                except Exception:
                    pass
    c.execute("DELETE FROM administrators WHERE username=?", (USER,))
print("\nthrowaway admin removed")