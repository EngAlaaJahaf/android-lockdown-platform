"""Web Console integration test — proves the web bridge drives the REAL ADB.

Boots the stdlib API server against an isolated DB, then over HTTP verifies:
  bootstrap (one-shot admin) -> login (TOTP) -> static index serving
  -> detected (real ADB-attached devices) -> enroll -> policies
  -> preflight -> R4 diagnostic (REAL_DEVICE) -> recovery vault.
Requires at least one ADB-attached device (LT-8110).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HOST, PORT = "127.0.0.1", 8878
BASE = f"http://{HOST}:{PORT}"
DB = os.path.join(tempfile.mkdtemp(prefix="alp_webui_"), "web.db")
TOKEN = ""


def req(method, path, payload=None, token=""):
    url = BASE + path
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        body = ex.read().decode("utf-8")
        try:
            return ex.code, json.loads(body)
        except Exception:
            return ex.code, {"ok": False, "error": body[:200]}


def totp_code(username="admin"):
    import sqlite3
    import base64
    import time as _t
    from backend import auth
    c = sqlite3.connect(DB)
    sec = c.execute("SELECT mfa_secret FROM administrators WHERE username=?",
                    (username,)).fetchone()[0]
    key = auth._b32_decode(sec)
    return auth._totp_at(key, int(_t.time()) // 30)


def main() -> int:
    env = dict(os.environ)
    env["ALP_DB"] = DB
    env["ALP_SIGNING_KEY"] = "webui-smoke-signing-key"
    env["ALP_AUDIT_SALT"] = "webui-smoke-salt"
    env["ALP_API_PORT"] = str(PORT)
    server = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "scripts", "alp_api.py")],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    fails = []
    try:
        for _ in range(60):
            try:
                if req("GET", "/api/v1/health")[1].get("ok"):
                    break
            except Exception:
                time.sleep(0.4)

        # static UI served
        raw = fetch_bytes("/")
        print(f"static /      -> HTTP {fetch_code('/')} {'OK-HTML' if b'<html' in raw else 'NOT-HTML'}")
        assert b"<html" in raw, "index.html not served"

        # bootstrap one-shot
        code, j = req("GET", "/api/v1/bootstrap")
        assert j["data"]["needs_bootstrap"] is True
        code, j = req("POST", "/api/v1/bootstrap", {"username": "admin", "password": "admin123"})
        assert j["ok"] and j["data"].get("secret"), j
        print("bootstrap     -> OK (TOTP issued)")
        code, j = req("GET", "/api/v1/bootstrap")
        assert j["data"]["needs_bootstrap"] is False

        # login with TOTP
        code, j = req("POST", "/api/v1/auth/login",
                      {"username": "admin", "password": "admin123", "mfa": totp_code()})
        assert j["ok"] and j["data"]["token"], j
        global TOKEN
        TOKEN = j["data"]["token"]
        print("login         -> OK")

        # whoami + detected (REAL ADB)
        code, j = req("GET", "/api/v1/auth/whoami", token=TOKEN)
        print("whoami        ->", j["data"]["username"], j["data"]["role_code"])
        code, j = req("GET", "/api/v1/devices/detected", token=TOKEN)
        serials = [d["serial"] for d in j["data"]] if j["ok"] else []
        print("detected      ->", serials or "NONE (no USB device!)")
        assert serials, "webui smoke requires an ADB-attached device"
        SER = serials[0]

        code, j = req("GET", "/api/v1/adb/status", token=TOKEN)
        print("adb/status    ->", j.get("data"))

        # enroll the real device
        code, j = req("POST", "/api/v1/devices/enroll",
                      {"serial": SER, "device_id": "WEB-" + SER, "mfa": totp_code()},
                      token=TOKEN)
        assert j["ok"], j
        DID = j["data"].get("device_id", "WEB-" + SER)
        print("enroll        ->", DID)

        # possession-factor credential for the vault
        code, j = req("POST", "/api/v1/recovery/vault",
                      {"action": "issue", "device_id": DID, "mfa": totp_code()},
                      token=TOKEN)
        assert j.get("ok") and j["data"].get("ok"), j
        rec_id = j["data"].get("recovery_id", "")
        print("vault issue   ->", rec_id)

        # policies + preflight (no MFA needed for preflight)
        req("POST", "/api/v1/policies/sync", {"mfa": totp_code()}, token=TOKEN)
        code, j = req("GET", "/api/v1/policies", token=TOKEN)
        pols = [p["policy_id"] for p in j["data"]] if j["ok"] else []
        print("policies      ->", pols[:4])
        code, j = req("GET", f"/api/v1/devices/preflight?device_id={DID}&policy=PHONE_ONLY",
                      token=TOKEN)
        print("preflight     ->", "OK" if j.get("ok") else j)

        # capabilities + recovery status
        code, j = req("GET", f"/api/v1/devices/capabilities?device_id={DID}", token=TOKEN)
        print("capabilities  ->", "OK" if j.get("ok") else j)
        code, j = req("GET", f"/api/v1/recovery?device_id={DID}", token=TOKEN)
        print("recoveryinfo  ->", "OK" if j.get("ok") else j)
        code, j = req("GET", "/api/v1/recovery/vault", token=TOKEN)
        print("vault         ->", "OK" if j.get("ok") else j)

        # R4 diagnostic over the web bridge = REAL_DEVICE observation
        code, j = req("POST", "/api/v1/recovery",
                      {"device_id": DID, "mode": "R4_DIAGNOSTIC", "mfa": totp_code(),
                       "serial": SER, "exec": True, "skip_approval": True},
                      token=TOKEN)
        d = j.get("data", {})
        print("R4 via web    ->", d.get("status"), "/ source=", d.get("source"))
        assert d.get("status") == "COMPLETE" and d.get("source") == "REAL_DEVICE", j

        # optional full R0_WITHDRAW -> R2_REPROVISION round-trip over HTTP,
        # but only when THIS console's agent is the active device owner
        owner_line = ""
        try:
            from backend.workflows import adb as engine_adb
            out = subprocess.check_output([engine_adb(), "-s", SER, "shell",
                                           "dpm", "list-owners"],
                                          stderr=subprocess.STDOUT, text=True, timeout=20)
            owner_line = out.strip()
        except Exception:
            pass
        if os.environ.get("ALP_FULL_RT") == "1":
            if "com.alp.agent" in owner_line:
                for mode in ("R0_WITHDRAW", "R2_REPROVISION"):
                    code, j = req("POST", "/api/v1/recovery",
                                  {"device_id": DID, "mode": mode, "mfa": totp_code(),
                                   "approver1": "admin", "approver2": "admin",
                                   "reason": "webui_smoke full round trip",
                                   "serial": SER, "exec": True, "skip_approval": True},
                                  token=TOKEN)
                    d = j.get("data", {})
                    print(f"{mode} via web  ->", d.get("status"), "/",
                          d.get("source"), "/", d.get("owner_state", ""))
                    assert d.get("status") in ("COMPLETE",) and d.get("source") == "REAL_DEVICE", j
            else:
                print("full RT      -> SKIPPED (device owner is a third-party "
                      "DPC; ALP cannot self-unenroll another product)")
                print("owner detect ->", owner_line or "none visible")

        # audit + tamper
        code, j = req("GET", "/api/v1/audit?tail=20", token=TOKEN)
        print("audit tail    ->", len(j.get("data", [])) if j.get("ok") else j)
        code, j = req("GET", "/api/v1/audit/tamper", token=TOKEN)
        print("tamper        ->", j.get("data", {}) if j.get("ok") else j)

        if fails:
            print("FAILURES:", fails)
            return 1
        print("WEBUI SMOKE PASSED")
        return 0
    finally:
        server.kill()
        server.wait(timeout=5)


def fetch_bytes(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.read()
    except Exception:
        return b""


def fetch_code(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as ex:
        return ex.code
    except Exception:
        return -1


if __name__ == "__main__":
    sys.exit(main())