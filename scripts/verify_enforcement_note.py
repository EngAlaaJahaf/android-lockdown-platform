# -*- coding: utf-8 -*-
"""Live proof through the real HTTP API.

Creates a throwaway admin in the scratch store the same way the API smoke does
(the production password is never used or guessed), then reads the device page
payload the console renders.
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend.db import connect          # noqa: E402
from backend import auth as auth_mod    # noqa: E402

USER, PW = "verify_note_admin", "verify-note-pw-0001"
with connect() as c:
    c.execute("INSERT INTO administrators (username, password_hash, role_id, "
              "active, mfa_enabled, display_name) VALUES (?,?,?,1,0,?) "
              "ON CONFLICT(username) DO UPDATE SET "
              "password_hash=excluded.password_hash, role_id=excluded.role_id, "
              "active=1, mfa_enabled=0",
              (USER, auth_mod.hash_password(PW), 1, USER))

BASE = "http://127.0.0.1:8765"


def call(method, path, body=None, token=None):
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


st, p = call("POST", "/api/v1/auth/login", {"username": USER, "password": PW})
if st != 200:
    raise SystemExit("login failed: %s %s" % (st, p))
tok = p["data"]["token"]
print("logged in as", p["data"]["username"], "| mfa_required =",
      p["data"].get("mfa_required"))

st, p = call("GET", "/api/v1/devices/AVD-LT8110260130351/details", token=tok)
print("\ndevice details HTTP", st)
d = p["data"]
print("  last_policy_id   :", d.get("last_policy_id"))
print("  last_result      :", d.get("last_result"))
print("  unresolved_lanes :", d.get("unresolved_lanes"))
print("  agent_applied    :", len(d.get("agent_applied") or []), "rows")
print("  agent_skipped    :", d.get("agent_skipped"))
print("  agent_cmd_id     :", d.get("agent_cmd_id"))
print("  enforcement_note :", d.get("enforcement_note"))

st, p = call("GET", "/api/v1/groups/1/status", token=tok)
print("\ngroup status HTTP", st)
g = p.get("data") or {}
print("  label  :", g.get("label"))
print("  counts :", g.get("counts"))

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
                c.execute("DELETE FROM %s WHERE %s=?" % (t, key), (USER,))
    c.execute("DELETE FROM administrators WHERE username=?", (USER,))
print("\nthrowaway admin removed")