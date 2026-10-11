# -*- coding: utf-8 -*-
"""Smoke test for POST /api/v1/devices/provision-device-owner.

This is the endpoint the browser console calls when an operator grants device
ownership. It previously did not exist at all - the console's enroll button
merely wrote `device_owner=True` into the request body and the backend believed
it, so the UI could claim ownership it never proved.

The workflow itself is stubbed here so the test covers the HTTP contract only
(RBAC, field pass-through, and the 409 that stops a non-owner from being
reported as provisioned) without touching a real handset.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import config            # noqa: E402
from backend import db                # noqa: E402

PORT = 8791
TMP = os.path.join(tempfile.gettempdir(), "alp_provision_owner_smoke.db")
if os.path.exists(TMP):
    os.remove(TMP)

config.API_PORT = PORT
db.DBPATH = TMP
db.run_migrations()

from backend.db import connect                    # noqa: E402
from backend import auth as auth_mod              # noqa: E402
from backend.api import server as server_mod      # noqa: E402
from backend.api.server import Handler, CHAN_DIR  # noqa: E402

SUPER_PW = "po-smoke-super-pw-0001"
RO_PW = "po-smoke-ro-pw-0001"
with connect() as c:
    c.execute("DELETE FROM sessions WHERE token LIKE 'test%'")
    for user, pw, role_id in (("posmoke_super", SUPER_PW, 1),
                              ("posmoke_ro", RO_PW, 8)):
        c.execute("INSERT INTO administrators (username, password_hash, role_id, "
                  "active, mfa_enabled, display_name) VALUES (?,?,?,1,0,?) "
                  "ON CONFLICT(username) DO UPDATE SET "
                  "password_hash=excluded.password_hash, role_id=excluded.role_id, "
                  "active=1, mfa_enabled=0",
                  (user, auth_mod.hash_password(pw), role_id, user))

BASE = "http://127.0.0.1:%d" % PORT

# ------------------------------------------------------------------ stub
CALLS = []
STUB = {"owner": True, "error": None}


def fake_provision(serial="", device_id="", variant="auto", launch=True):
    CALLS.append({"serial": serial, "device_id": device_id,
                  "variant": variant, "launch": launch})
    out = {"serial": serial, "device_id": device_id,
           "package": "com.alp.agent", "installed": True,
           "device_owner": bool(STUB["owner"]), "verified": True}
    if STUB["error"]:
        out["error"] = STUB["error"]
    else:
        out["already_owner"] = bool(STUB["owner"])
    return out


server_mod.provision_device_owner = fake_provision


def _assert_port_free(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("port %d already in use - stop that server first" % port)
    finally:
        probe.close()


def section(name):
    print("\n=== %s ===" % name)


TOKEN = {"v": None}


def call(method, path, body=None, token=True, expect=None):
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token and TOKEN["v"]:
        req.add_header("Authorization", "Bearer " + TOKEN["v"])
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, payload = r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        status, payload = e.code, json.loads(e.read().decode())
    if expect is not None and status != expect:
        raise AssertionError("%s %s -> %s (want %s): %s"
                             % (method, path, status, expect, payload))
    return status, payload


_assert_port_free(PORT)
os.makedirs(CHAN_DIR, exist_ok=True)
httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.6)
FAILURES = []


def check(label, cond, detail=""):
    print("  %-62s %s" % (label, "OK" if cond else "FAIL " + str(detail)))
    if not cond:
        FAILURES.append(label)


try:
    section("auth")
    st, p = call("POST", "/api/v1/auth/login",
                 {"username": "posmoke_super", "password": SUPER_PW},
                 token=False, expect=200)
    TOKEN["v"] = p["data"]["token"]
    print("  logged in as", p["data"]["username"])

    section("route requires a session")
    call("POST", "/api/v1/devices/provision-device-owner",
         {"serial": "LT1", "device_id": "AVD-LT1"}, token=False, expect=401)
    print("  unauthenticated -> 401 OK")

    section("fields reach the workflow")
    st, p = call("POST", "/api/v1/devices/provision-device-owner",
                 {"serial": "LT8110260130351", "device_id": "AVD-LT8110260130351",
                  "variant": "auto", "launch": True}, expect=200)
    got = CALLS[-1]
    check("serial passed through", got["serial"] == "LT8110260130351", got)
    check("device_id passed through",
          got["device_id"] == "AVD-LT8110260130351", got)
    check("device_owner=True reported", p["data"]["device_owner"] is True, p)
    check("already_owner surfaced", p["data"].get("already_owner") is True, p)

    section("launch=false is honoured")
    call("POST", "/api/v1/devices/provision-device-owner",
         {"serial": "LT8110260130351", "device_id": "AVD-LT8110260130351",
          "launch": False}, expect=200)
    check("launch=False reached the workflow", CALLS[-1]["launch"] is False,
          CALLS[-1])

    section("a phone that is NOT the owner must not report success")
    STUB["owner"] = False
    STUB["error"] = "device-owner claim refused by the OS"
    st, p = call("POST", "/api/v1/devices/provision-device-owner",
                 {"serial": "LT8110260130351", "device_id": "AVD-LT8110260130351"})
    check("non-owner -> 409", st == 409, st)
    check("409 carries the OS reason",
          "refused" in json.dumps(p, ensure_ascii=False), p)
    STUB["owner"] = True
    STUB["error"] = None

    section("read-only role cannot grant ownership")
    TOKEN["v"] = None
    st, p = call("POST", "/api/v1/auth/login",
                 {"username": "posmoke_ro", "password": RO_PW},
                 token=False, expect=200)
    TOKEN["v"] = p["data"]["token"]
    before = len(CALLS)
    st, p = call("POST", "/api/v1/devices/provision-device-owner",
                 {"serial": "LT8110260130351", "device_id": "AVD-LT8110260130351"})
    check("READ_ONLY refused (403/401)", st in (401, 403), st)
    check("workflow never invoked", len(CALLS) == before, len(CALLS))

finally:
    httpd.shutdown()
    try:
        os.remove(TMP)
    except OSError:
        pass

print("\n" + ("FAILED: %s" % FAILURES if FAILURES else "ALL CHECKS PASSED"))
sys.exit(1 if FAILURES else 0)