"""ALP Control-Plane HTTP API (PHASE 2) + Web Console (PHASE 3 web bridge).

Bearer session tokens come from `backend.auth.create_session` (same channel as
the Desktop CLI). Every endpoint calls `rbac.authorize(role_code, operation)`;
sensitive operations require an MFA code supplied in the request body.

The device transport stays the REAL local ADB/USB stack (backend.workflows /
backend.channel). The web console is a UI over the SAME engines the desktop
GUI uses — nothing is simulated: apply/recovery only ever touch ADB-attached
devices and report REAL_DEVICE evidence exactly like the desktop app.

Environment:
    ALP_API_HOST (127.0.0.1)  ALP_API_PORT (8765)  ALP_SIGNING_KEY  ALP_DB
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))  # PROJECT_ROOT for engine imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "desktop"))  # alp_manager package

from backend import auth, rbac, audit as audit_mod, approval as approval_mod, fleet  # noqa: E402
from backend.config import API_HOST, API_PORT, SIGNING_KEY  # noqa: E402
from backend.db import connect, run_migrations  # noqa: E402
from backend.director import ApplyBlocked, DirectorError  # noqa: E402
from backend.workflows import (attached_serials, run_director_apply,  # noqa: E402
                               enroll_device, persist_reference_policies)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHAN_DIR = os.path.join(PROJECT_ROOT, "reports", "phase1", "commands")
WEBUI_DIR = os.path.join(PROJECT_ROOT, "webui")

# The web console delegates to the same headless Controller the desktop GUI
# uses — same engines, same ADB channel, same honesty rules.
try:
    from alp_manager.controller import Controller  # noqa: E402
    _CONTROLLER = None

    def _controller():
        global _CONTROLLER
        if _CONTROLLER is None:
            _CONTROLLER = Controller(db_path="")
        return _CONTROLLER
except ImportError as _ex:  # pragma: no cover — desktop package must be runnable
    _CONTROLLER = None

    def _controller():
        raise RuntimeError(f"web console backend unavailable: {_ex}")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _body(req) -> dict:
    try:
        n = int(req.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(req.rfile.read(n).decode("utf-8"))
    except Exception as ex:
        raise ApiError(400, f"bad JSON body: {ex}")


def _auth(req) -> dict | None:
    h = req.headers.get("Authorization", "")
    if not h.lower().startswith("bearer "):
        return None
    token = h[7:].strip()
    row = auth.resolve_session(token)
    return dict(row) if row else None


def _mfa_ok(sess: dict, code: str) -> bool:
    with connect() as c:
        r = c.execute("SELECT mfa_secret FROM administrators WHERE id=?",
                      (sess.get("admin_id") or sess.get("id"),)).fetchone()
    return bool(r and r["mfa_secret"] and auth.totp_verify(r["mfa_secret"], code or ""))


def _route(sess, operation: str, mfa: str = "", require_mfa: bool = True,
           approval: Optional[dict] = None) -> str:
    """RBAC gate — raises ApiError(403) when denied or MFA missing."""
    try:
        return rbac.authorize(sess["role_code"], operation,
                              require_mfa=require_mfa, mfa_ok=_mfa_ok(sess, mfa),
                              approval=approval)
    except PermissionError as ex:
        raise ApiError(403, str(ex))


class Handler(BaseHTTPRequestHandler):
    server_version = "ALP-API/1.0"

    def log_message(self, fmt, *args):  # quieter stdlib logging
        pass

    # ------------------------------------------------------------------
    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data, status: int = 200):
        self._send(status, {"ok": True, "data": data})

    def _err(self, status: int, message: str):
        self._send(status, {"ok": False, "error": message})

    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self._serve_static(parsed.path)
        self._dispatch("GET", parsed.path, _body(self))

    def do_POST(self):
        self._dispatch("POST", urlparse(self.path).path, _body(self))

    def _q(self, name: str, default: str = "") -> str:
        values = parse_qs(urlparse(self.path).query).get(name)
        return (values[0] if values else default) or default

    def _serve_static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/")
        target = os.path.realpath(os.path.join(WEBUI_DIR, rel))
        if not target.startswith(os.path.realpath(WEBUI_DIR)) or not os.path.isfile(target):
            return self._err(404, "not found")
        ctype = "text/html; charset=utf-8"
        if target.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif target.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif target.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        elif target.endswith(".svg"):
            ctype = "image/svg+xml"
        with open(target, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method: str, path: str, body: dict):
        try:
            self._handle(method, path, body)
        except ApiError as ex:
            self._err(ex.status, ex.message)
        except ApplyBlocked as ex:
            self._err(409, f"apply blocked: {ex}")
        except DirectorError as ex:
            self._err(409, f"director: {ex}")
        except ValueError as ex:
            self._err(400, str(ex))
        except PermissionError as ex:
            self._err(403, str(ex))
        except Exception as ex:
            self._err(500, f"{type(ex).__name__}: {ex}")

    def _handle(self, method: str, path: str, body: dict):
        if path.startswith("/api/v1/health"):
            return self._ok({"status": "UP", "service": "alp-control-plane"})

        # ---- bootstrap (public, one-shot) ---------------------------------
        if path == "/api/v1/bootstrap" and method == "GET":
            return self._ok({"needs_bootstrap": _controller().needs_bootstrap()})
        if path == "/api/v1/bootstrap" and method == "POST":
            out = _controller().bootstrap(body.get("username", ""),
                                          body.get("password", ""))
            if not out.get("ok"):
                raise ApiError(409, out.get("error", "bootstrap refused"))
            return self._ok({"username": body.get("username", ""),
                             "totp_uri": out.get("totp_uri", ""),
                             "secret": out.get("secret", "")})

        if path == "/api/v1/auth/login":
            return self._login(body)
        if path == "/api/v1/auth/logout":
            sess = _auth(self)
            if sess:
                auth.revoke_session(sess["token"])
            return self._ok({"logged_out": True})

        sess = _auth(self)
        if not sess:
            raise ApiError(401, "missing or invalid session token")

        if path == "/api/v1/auth/whoami":
            return self._ok({"username": sess["username"],
                             "role_code": sess["role_code"],
                             "role_id": sess["role_id"]})

        if path == "/api/v1/devices" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_devices())

        if path == "/api/v1/devices/enroll" and method == "POST":
            _route(sess, "APPLY", mfa=body.get("mfa", ""))
            serial = body.get("serial") or (attached_serials() or [None])[0]
            if not serial:
                raise ApiError(400, "no serial given and no device attached via ADB")
            info = enroll_device(body.get("device_id"), serial,
                                 device_owner=bool(body.get("device_owner")),
                                 lab=bool(body.get("lab")))
            return self._ok(info)

        if path == "/api/v1/devices/detected" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().detected())

        if path == "/api/v1/adb/status" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().adb_status())

        if path == "/api/v1/devices/preflight" and method == "GET":
            _route(sess, "APPLY", require_mfa=False)
            return self._ok(_controller().preflight(
                self._q("device_id"), self._q("policy")))

        if path == "/api/v1/devices/policy-preview" and method == "GET":
            _route(sess, "APPLY", require_mfa=False)
            return self._ok(_controller().policy_preview(
                self._q("device_id"), self._q("policy")))

        if path == "/api/v1/devices/capabilities" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().capabilities(self._q("device_id")))

        if path == "/api/v1/policies" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_policies())

        if path == "/api/v1/policies/custom" and method == "POST":
            _route(sess, "CREATE", mfa=body.get("mfa", ""))
            out = _controller().create_policy(
                body.get("display_name", ""), body.get("category", ""),
                body.get("features", {}) or {}, body.get("risk", "MEDIUM"))
            if not out.get("ok"):
                raise ApiError(400, out.get("error", "policy create failed"))
            return self._ok(out)

        if path == "/api/v1/policies/sync" and method == "POST":
            _route(sess, "CREATE", mfa=body.get("mfa", ""))
            n = persist_reference_policies()
            return self._ok({"synced": n})

        if path == "/api/v1/apply" and method == "POST":
            device_id, policy_id = body.get("device_id"), body.get("policy")
            if not device_id or not policy_id:
                raise ApiError(400, "device_id and policy are required")
            _route(sess, "APPLY", mfa=body.get("mfa", ""))
            res = run_director_apply(
                device_id, policy_id,
                op_role=sess["role_code"], mfa_ok=_mfa_ok(sess, body.get("mfa", "")),
                serial=body.get("serial"), real=bool(body.get("real")),
                signing_key=SIGNING_KEY, chan_dir=CHAN_DIR)
            return self._ok(res)

        if path == "/api/v1/recovery" and method == "POST":
            approved = bool(body.get("skip_approval")) or bool(body.get("approver1"))
            _route(sess, "RECOVER", mfa=body.get("mfa", ""),
                   approval={"approved": approved,
                             "reason": body.get("reason", "web console"),
                             "dual": bool(body.get("approver1") and body.get("approver2"))})
            try:
                out = _controller().recover(
                    body.get("device_id", ""), body.get("mode", "R4_DIAGNOSTIC"),
                    approver1=body.get("approver1", ""),
                    approver2=body.get("approver2", ""),
                    reason=body.get("reason", ""),
                    skip_approval=bool(body.get("skip_approval")),
                    serial=body.get("serial", ""), exec_=bool(body.get("exec", False)))
                d = out if isinstance(out, dict) else {"result": str(out)}
                return self._ok(d)
            except ValueError as ex:
                raise ApiError(404, str(ex))

        if path == "/api/v1/recovery" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().recovery_status(self._q("device_id")))

        if path == "/api/v1/recovery/vault" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().recovery_vault_summary())

        if path == "/api/v1/recovery/vault" and method == "POST":
            action = body.get("action", "")
            dev = body.get("device_id", "")
            _route(sess, "RECOVER", mfa=body.get("mfa", ""),
                   approval={"approved": True, "reason": f"vault {action}", "dual": False})
            if action == "rotate":
                out = _controller().rotate_recovery(dev)
            elif action == "revoke":
                out = _controller().revoke_recovery(dev)
            elif action == "issue":
                out = _controller().issue_recovery(dev)
            else:
                raise ApiError(400, "vault action must be rotate|revoke|issue")
            return self._ok(out)

        if path == "/api/v1/reports" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().reports_list(self._q("device_id")))

        if path.startswith("/api/v1/reports/") and method == "GET":
            did = path[len("/api/v1/reports/"):].strip("/")
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().generate_device_report(did))

        if path == "/api/v1/diagnostics" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().diagnostics())

        if path == "/api/v1/jobs" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_jobs())

        if path == "/api/v1/approvals" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_approvals())

        if path == "/api/v1/audit" and method == "GET":
            _route(sess, "AUDIT", require_mfa=False)
            lg = audit_mod.AuditLog()
            return self._ok(_audit_rows(lg, self._q("tail", "100")))

        if path == "/api/v1/audit/tamper" and method == "GET":
            _route(sess, "AUDIT", require_mfa=False)
            return self._ok(audit_mod.AuditLog().tamper_check())

        if path == "/api/v1/approvals/approve" and method == "POST":
            _route(sess, "CREATE", mfa=body.get("mfa", ""))
            out = approval_mod.approve(body["approval_id"], sess["admin_id"],
                                       mfa_ok=_mfa_ok(sess, body.get("mfa", "")))
            return self._ok(out)

        raise ApiError(404, f"no route {method} {path}")

    # ------------------------------------------------------------------
    def _login(self, body: dict):
        user, pw, code = body.get("username", ""), body.get("password", ""), body.get("mfa", "")
        with connect() as c:
            row = c.execute("SELECT * FROM administrators WHERE username=? AND active=1",
                            (user,)).fetchone()
        if not row or not row["password_hash"] or not auth.verify_password(pw, row["password_hash"]):
            raise ApiError(401, "bad credentials")
        if row["mfa_enabled"] and not auth.totp_verify(row["mfa_secret"] or "", code):
            raise ApiError(401, "bad MFA code")
        token = auth.create_session(row["id"])
        return self._ok({"token": token, "username": row["username"],
                         "role_id": row["role_id"], "display_name": row["display_name"]})


def _devices():
    with connect() as c:
        rows = c.execute(
            "SELECT device_id, serial, manufacturer, model, android_version, api_level, "
            "enrollment_state, compliance_state, is_lab, last_verification_at "
            "FROM devices ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _policies():
    with connect() as c:
        rows = c.execute(
            "SELECT policy_id, display_name, category, version, status, checksum "
            "FROM policies ORDER BY category, policy_id").fetchall()
    return [dict(r) for r in rows]


def _jobs():
    with connect() as c:
        rows = c.execute(
            "SELECT j.job_id, j.job_type, j.status, j.priority, count(e.id) AS execs "
            "FROM jobs j LEFT JOIN job_executions e ON e.job_id=j.id "
            "GROUP BY j.id ORDER BY j.id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


def _approvals():
    with connect() as c:
        rows = c.execute(
            "SELECT approval_id, action, device_id, scope, requester, approver_1, approver_2, "
            "reason, decision, created_at FROM approvals ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


def _audit_rows(lg, tail):
    try:
        return lg.tail(int(tail))
    except (TypeError, ValueError):
        return lg.tail(100)


def main() -> None:
    run_migrations()
    os.makedirs(CHAN_DIR, exist_ok=True)
    httpd = ThreadingHTTPServer((API_HOST, API_PORT), Handler)
    print(f"ALP control-plane listening on http://{API_HOST}:{API_PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()