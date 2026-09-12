"""PHASE 2 smoke/integration check for the HTTP control-plane API.

Boots the stdlib server as a child process, then exercises the token-auth +
RBAC + director surfaces over HTTP, then shuts it down. Uses an isolated DB.
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
sys.path.insert(0, os.path.join(ROOT, "backend"))

HOST, PORT = "127.0.0.1", 8877
BASE = f"http://{HOST}:{PORT}/api/v1"
DB = os.path.join(tempfile.mkdtemp(prefix="alp_api_"), "api.db")


def req(method: str, path: str, payload: dict | None = None, token: str = "") -> dict:
    url = BASE + path
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        return json.loads(ex.read().decode("utf-8"))


def wait_health(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = req("GET", "/health")
            if r.get("ok"):
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def main() -> int:
    env = dict(os.environ)
    env["ALP_DB"] = DB
    env["ALP_SIGNING_KEY"] = "api-smoke-signing-key"
    env["ALP_API_PORT"] = str(PORT)
    server = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "scripts", "alp_api.py")],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        if not wait_health():
            out = server.stdout.read().decode(errors="replace") if server.stdout else ""
            print("server failed to boot:\n", out)
            return 1

        # seed admin + device directly in the isolated DB
        from backend.db import run_migrations, connect
        from backend import auth as a
        run_migrations(DB)
        with connect(DB) as c:
            if c.execute("SELECT COUNT(*) AS n FROM administrators").fetchone()["n"] == 0:
                h = a.hash_password("admin")
                sec, _ = a.generate_totp_secret()
                c.execute("INSERT INTO administrators (username, role_id, password_hash, mfa_secret, mfa_enabled) "
                          "VALUES ('admin',1,?,?,1)", (h, sec))
                lastid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            else:
                lastid = c.execute("SELECT id FROM administrators ORDER BY id LIMIT 1").fetchone()["id"]
        from backend import auth as _auth
        import base64, hashlib  # noqa
        otp = _totp_code(DB, "admin")

        r = req("POST", "/auth/login", {"username": "admin", "password": "admin", "mfa": otp})
        if not r.get("ok"):
            print("login FAILED:", r)
            return 1
        token = r["data"]["token"]
        print("login        -> OK")

        r = req("GET", "/devices", token=token)
        print("devices      ->", "OK" if r.get("ok") else r)
        r = req("POST", "/policies/sync", {"mfa": otp}, token=token)
        print("policies/sync ->", json.dumps(r)[:200])
        r = req("GET", "/policies", token=token)
        print("policies     ->", json.dumps(r)[:200])

        # RBAC negative: bogus token must be rejected
        r = req("GET", "/devices", token="bogus")
        print("rbac(neg)    ->", "OK 401" if r.get("ok") is False and r.get("error") else r)

        # apply must fail without MFA (actor gate)
        r = req("POST", "/apply", {"device_id": "AVD-5554", "policy": "PHONE_ONLY"}, token=token)
        print("apply(no mfa) ->", "403" if r.get("ok") is False else r)
        # apply with valid MFA but unknown device -> clean 400
        r = req("POST", "/apply", {"device_id": "NOPE-1", "policy": "PHONE_ONLY", "mfa": otp}, token=token)
        print("apply(unknown) ->", "400" if r.get("ok") is False else r)
        return 0
    finally:
        server.kill()
        server.wait(timeout=5)


def _totp_code(db: str, username: str) -> str:
    import time as _t
    from backend import auth
    import sqlite3
    c = sqlite3.connect(db)
    sec = c.execute("SELECT mfa_secret FROM administrators WHERE username=?", (username,)).fetchone()[0]
    key = auth._b32_decode(sec)
    return auth._totp_at(key, int(_t.time()) // 30)


if __name__ == "__main__":
    sys.exit(main())