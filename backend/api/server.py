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

import base64
import hashlib
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
from backend.config import API_HOST, API_PORT, API_BIND, MFA_REQUIRED  # noqa: E402
from backend.db import connect, run_migrations  # noqa: E402
from backend.director import ApplyBlocked, DirectorError  # noqa: E402
from backend.pins import provision_pin as _provision_pin
from backend.groups import GroupError
from backend.profiles import ProfileConflict, ProfileError
from backend.workflows import (attached_serials, is_agent_installed,  # noqa: E402
                               is_device_owner_active, run_director_apply,
                               enroll_device, install_agent_app,
                               persist_reference_policies,
                               provision_device_owner)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHAN_DIR = os.path.join(PROJECT_ROOT, "reports", "phase1", "commands")
WEBUI_DIR = os.path.join(PROJECT_ROOT, "webui")

# Agent in-app branding (ManageEngine-style "rebranding" without rebuilding:
# the logo INSIDE the app, served here and fetched by the agent at Sync).
# The launcher icon itself can never change at runtime on stock Android.
BRANDING_DIR = os.path.join(WEBUI_DIR, "branding")
BRANDING_LOGO = os.path.join(BRANDING_DIR, "logo.png")
BRANDING_MAX_BYTES = 512 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _agent_policy(handler) -> dict:
    """Serve this handset's own signed policy envelope.

    `build` requests carry the signed envelope; a plain read answers with the
    state and fingerprint so the device can skip work it has already done.
    """
    from backend.agent_policy_pull import policy_for_device, build_apply_envelope
    from backend.config import signing_key as _key

    # A device has no session, and it may post a JSON body instead of query
    # parameters, so both are consulted.
    payload = handler.payload or {}
    q = handler._q("device_id") or payload.get("device_id") or ""
    serial = handler._q("serial") or payload.get("serial") or ""
    build = (handler.command or "GET") == "POST" or handler._q("build") == "1"
    if not q and not serial:
        raise ApiError(400, "device_id or serial is required")

    if build:
        return build_apply_envelope(q, serial, _key())
    return policy_for_device(q, serial)


def _branding_info() -> dict:
    """Public read-only branding descriptor for agents (no auth needed)."""
    try:
        with open(BRANDING_LOGO, "rb") as fh:
            data = fh.read()
    except OSError:
        return {"logo_url": None, "version": "", "updated_at": ""}
    import datetime
    ver = hashlib.sha1(data).hexdigest()[:16]
    updated = datetime.datetime.fromtimestamp(
        os.path.getmtime(BRANDING_LOGO),
        tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"logo_url": "/branding/logo.png", "version": ver,
            "updated_at": updated}


def _branding_store(png_b64: str) -> dict:
    """Replace the agent branding logo (callers must authorize EDIT first)."""
    if not png_b64 or not isinstance(png_b64, str):
        raise ApiError(400, "png_b64 (base64-encoded PNG) is required")
    try:
        data = base64.b64decode(png_b64, validate=True)
    except ValueError:
        raise ApiError(400, "png_b64 is not valid base64")
    if not data or len(data) > BRANDING_MAX_BYTES:
        raise ApiError(400, "logo must be a non-empty PNG of at most 512 KiB")
    if data[:8] != _PNG_MAGIC:
        raise ApiError(400, "only PNG images are accepted")
    if len(data) < 33:
        raise ApiError(400, "truncated PNG")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if not (1 <= width <= 1024 and 1 <= height <= 1024):
        raise ApiError(400, "logo dimensions must be within 1024x1024")
    os.makedirs(BRANDING_DIR, exist_ok=True)
    tmp = BRANDING_LOGO + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, BRANDING_LOGO)
    return _branding_info()

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
    if not MFA_REQUIRED:  # temporary delivery mode: username+password only
        return True
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
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self._serve_static(parsed.path)
        self._dispatch("GET", parsed.path, _body(self))

    def do_POST(self):
        self._dispatch("POST", urlparse(self.path).path, _body(self))

    def do_PUT(self):
        self._dispatch("PUT", urlparse(self.path).path, _body(self))

    def do_DELETE(self):
        self._dispatch("DELETE", urlparse(self.path).path, _body(self))

    def _q(self, name: str, default: str = "") -> str:
        values = parse_qs(urlparse(self.path).query).get(name)
        return (values[0] if values else default) or default

    # Set by _dispatch so helpers can see which verb and body produced this request.
    command = "GET"
    payload = None

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
        elif target.endswith(".png"):
            ctype = "image/png"
        elif target.endswith(".gif"):
            ctype = "image/gif"
        elif target.endswith(".jpg") or target.endswith(".jpeg"):
            ctype = "image/jpeg"
        elif target.endswith(".ico"):
            ctype = "image/x-icon"
        elif target.endswith(".webp"):
            ctype = "image/webp"
        with open(target, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method: str, path: str, body: dict):
        self.command = method
        self.payload = body
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
        except GroupError as ex:
            self._err(400, str(ex))
        except ProfileConflict as ex:
            # Well-formed request, wrong lifecycle state (e.g. editing a
            # published profile, deleting one that is still associated).
            self._err(409, str(ex))
        except ProfileError as ex:
            self._err(400, str(ex))
        except Exception as ex:
            self._err(500, f"{type(ex).__name__}: {ex}")

    def _handle(self, method: str, path: str, body: dict):
        if path.startswith("/api/v1/health"):
            return self._ok({"status": "UP", "service": "alp-control-plane",
                             "mfa_required": MFA_REQUIRED})

        # ---- agent self-service pull -------------------------------------
        # The agent has no operator session; it asks "what is my policy?" and
        # receives a signed envelope. There is no console credential in play and
        # nothing here can be used to read data: the answer is only ever the one
        # profile assigned to the asking device, and the envelope must still
        # pass the device's own signature check before it is applied.
        if path == "/api/v1/agent/policy" and method == "GET":
            return self._ok(_agent_policy(self))
        if path == "/api/v1/agent/policy" and method == "POST":
            return self._ok(_agent_policy(self))

        # ---- agent in-app branding (public read; EDIT-gated write) -------
        if path == "/api/v1/branding" and method == "GET":
            return self._ok(_branding_info())
        if path == "/api/v1/branding/logo" and method == "POST":
            sess = _auth(self)
            if not sess:
                raise ApiError(401, "missing or invalid session token")
            _route(sess, "EDIT", mfa=body.get("mfa", ""))
            return self._ok(_branding_store(body.get("png_b64", "")))

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

        if path == "/api/v1/devices/install-agent" and method == "POST":
            _route(sess, "APPLY", mfa=body.get("mfa", ""))
            info = install_agent_app(serial=body.get("serial", ""),
                                     device_id=body.get("device_id", ""),
                                     variant=body.get("variant", "auto"),
                                     launch=bool(body.get("launch", True)))
            if not info.get("installed"):
                raise ApiError(409, info.get("error") or "agent install failed")
            return self._ok(info)

        if path == "/api/v1/devices/provision-device-owner" and method == "POST":
            _route(sess, "APPLY", mfa=body.get("mfa", ""))
            try:
                info = provision_device_owner(
                    serial=body.get("serial", ""),
                    device_id=body.get("device_id", ""),
                    variant=body.get("variant", "auto"),
                    launch=bool(body.get("launch", True)))
            except ValueError as ex:
                raise ApiError(400, str(ex))
# device_owner_state in the DB is written from the dumpsys proof
            # inside provision_device_owner - this response reports what the
            # phone actually is, never what the console asked for.
            if not info.get("device_owner"):
                raise ApiError(409, info.get("error")
                               or info.get("hint")
                               or "device-owner provisioning did not complete")
            return self._ok(info)

        if path == "/api/v1/devices/detected" and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_controller().detected())

        if path == "/api/v1/devices/reset-policies" and method == "POST":
            # إلغاء كل القيود القديمة على جهاز وتنظيف قاعدة البيانات
            _route(sess, "APPLY", mfa=body.get("mfa", ""))
            did = body.get("device_id", "")
            if not did:
                raise ApiError(400, "device_id required")
            try:
                from backend.workflows import reset_device_policies
                result = reset_device_policies(did, serial=body.get("serial"))
                return self._ok(result)
            except ValueError as ex:
                raise ApiError(400, str(ex))

        if path.startswith("/api/v1/devices/") and path.endswith("/details") and method == "GET":
            _route(sess, "VIEW", require_mfa=False)
            did = path[len("/api/v1/devices/"): -len("/details")].strip("/")
            return self._ok(_device_details(did))

        if path.startswith("/api/v1/devices/") and method == "DELETE":
            # Delete ONE device record (only offered while its app is gone).
            # Same destructive gate as group deletion: RETIRE + approval.
            did = path[len("/api/v1/devices/"):].strip("/")
            if not did or "/" in did or did in (
                    "install-agent", "provision-device-owner", "enroll",
                    "detected", "reset-policies", "preflight",
                    "policy-preview", "capabilities"):
                raise ApiError(404, f"no route {method} {path}")
            _route(sess, "RETIRE", mfa=body.get("mfa", ""),
                   approval={"approved": bool(body.get("approver1"))
                             or bool(body.get("skip_approval")),
                             "reason": body.get("reason", "delete device"),
                             "dual": bool(body.get("approver1")
                                         and body.get("approver2"))})
            try:
                from backend.workflows import delete_device
                return self._ok(delete_device(did, force=bool(body.get("force", False))))
            except ValueError as ex:
                raise ApiError(409, str(ex))

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

        if path == "/api/v1/restrictions/catalog" and method == "GET":
            from backend import restrictions
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(restrictions.catalog())

        if path == "/api/v1/restrictions/policy" and method == "POST":
            _route(sess, "CREATE", mfa=body.get("mfa", ""))
            from backend.workflows import create_policy_from_catalog
            out = create_policy_from_catalog(
                body.get("features") or [], body.get("name") or "",
                risk=body.get("risk", "MEDIUM"))
            p = out["policy"]
            return self._ok({"policy_id": p.policy_id,
                             "display_name": p.display_name,
                             "applied": out["applied"],
                             "excluded": out["excluded"]})

        if path == "/api/v1/system/backup" and method == "POST":
            _route(sess, "RESTORE", mfa=body.get("mfa", ""))
            from backend.backup import create_backup
            out = create_backup()
            if not out.get("ok"):
                raise ApiError(500, out.get("error", "backup failed"))
            return self._ok(out)

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
                # resolved at call time: an import-time constant would freeze an
                # empty key and reject every command with "signing key not
                # configured" once ALP_SIGNING_KEY is set after boot.
                signing_key=_current_key(), chan_dir=CHAN_DIR,
                allow_channel_risk=bool(body.get("allow_channel_risk")))
            return self._ok(res)

        if path == "/api/v1/pin/provision" and method == "POST":
            device_id = body.get("device_id", "")
            if not device_id:
                raise ApiError(400, "device_id is required")
            _route(sess, "APPLY", mfa=body.get("mfa", ""))
            out = _provision_pin(device_id, body.get("pin", ""),
                                 serial=body.get("serial", ""),
                                 chan_dir=CHAN_DIR)
            return self._ok(out)

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

        # ---- emergency offline tokens (works with no cable, no network) --
        if path == "/api/v1/recovery/emergency/issue" and method == "POST":
            from backend import emergency as _emg
            _route(sess, "RECOVER", mfa=body.get("mfa", ""),
                   approval={"approved": bool(body.get("approver1"))
                             or bool(body.get("skip_approval")),
                             "reason": body.get("reason", "emergency token"),
                             "dual": bool(body.get("approver1")
                                         and body.get("approver2"))})
            try:
                return self._ok(_emg.issue_token(
                    body.get("device_id", ""), created_by=sess["username"],
                    label=body.get("label", ""),
                    ttl_hours=int(body.get("ttl_hours", 24) or 24),
                    purpose=body.get("purpose", "withdraw_uninstall") or
                    "withdraw_uninstall"))
            except ValueError as ex:
                raise ApiError(400, str(ex))

        if path == "/api/v1/recovery/emergency/provision" and method == "POST":
            from backend import emergency as _emg
            _route(sess, "RECOVER", mfa=body.get("mfa", ""),
                   approval={"approved": bool(body.get("approver1"))
                             or bool(body.get("skip_approval")),
                             "reason": body.get("reason", "provision token"),
                             "dual": bool(body.get("approver1")
                                         and body.get("approver2"))})
            try:
                return self._ok(_emg.provision_token(
                    body.get("device_id", ""), serial=body.get("serial", ""),
                    signing_key_=_current_key(), chan_dir=CHAN_DIR,
                    ttl_hours=int(body.get("ttl_hours", 24) or 24),
                    created_by=sess["username"],
                    purpose=body.get("purpose", "withdraw_uninstall") or
                    "withdraw_uninstall"))
            except ValueError as ex:
                raise ApiError(400, str(ex))

        if path == "/api/v1/recovery/emergency/offline-code" and method == "POST":
            from backend import emergency as _emg
            _route(sess, "RECOVER", mfa=body.get("mfa", ""),
                   approval={"approved": bool(body.get("approver1"))
                             or bool(body.get("skip_approval")),
                             "reason": body.get("reason", "offline code"),
                             "dual": bool(body.get("approver1")
                                         and body.get("approver2"))})
            try:
                return self._ok(_emg.offline_code(
                    body.get("device_id", ""),
                    body.get("purpose", "withdraw_uninstall") or
                    "withdraw_uninstall"))
            except ValueError as ex:
                raise ApiError(400, str(ex))

        if path == "/api/v1/recovery/emergency/revoke" and method == "POST":
            from backend import emergency as _emg
            _route(sess, "RECOVER", mfa=body.get("mfa", ""))
            try:
                return self._ok(_emg.revoke_token(body.get("token_id", ""),
                                                  by=sess["username"]))
            except ValueError as ex:
                raise ApiError(400, str(ex))

        if path == "/api/v1/recovery/emergency" and method == "GET":
            from backend import emergency as _emg
            _route(sess, "VIEW", require_mfa=False)
            return self._ok(_emg.list_tokens(self._q("device_id")))

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

        if path.startswith("/api/v1/groups") or path == "/api/v1/groups":
            return self._groups(method, path, body)

        if path == "/api/v1/profiles" or path.startswith("/api/v1/profiles/"):
            return self._profiles(method, path, body)

        raise ApiError(404, f"no route {method} {path}")

    # ------------------------------------------------------------------
    # Device Groups — see backend/api/groups_routes.py for the surface and the
    # RBAC rationale. Deployment outcomes come from backend.groups and are
    # derived from `assignments`; a staged apply is never reported as success.
    def _groups(self, method: str, path: str, body: dict):
        from backend import groups as G

        rest = path[len("/api/v1/groups"):].strip("/")
        parts = rest.split("/") if rest else []
        gid = None
        if parts and parts[0].isdigit():
            gid = int(parts[0])
            parts = parts[1:]
        elif parts and parts[0]:
            raise ApiError(404, f"no route {method} {path}")

        mfa = body.get("mfa", "")
        serial_for = _serial_for

        # ---- collection --------------------------------------------------
        # `gid is None` (not `not parts`) distinguishes /groups from /groups/{id}
        if gid is None:
            if method == "GET":
                _route(_auth(self), "VIEW", require_mfa=False)
                return self._ok(G.list_groups())
            if method == "POST":
                _route(sess := _auth(self), "CREATE", mfa=mfa)
                return self._ok(G.create_group(
                    body.get("name", ""), body.get("description", ""),
                    membership_type=body.get("membership_type", "STATIC"),
                    platform_type=body.get("platform_type", "ANDROID"),
                    created_by=sess["username"],
                    criteria_json=body.get("criteria_json")))

        if gid is None:
            raise ApiError(404, f"no route {method} {path}")

        # ---- /{id} -------------------------------------------------------
        if not parts:
            if method == "GET":
                _route(_auth(self), "VIEW", require_mfa=False)
                return self._ok(G.get_group(gid, with_members=True, with_profiles=True))
            if method == "PUT":
                _route(sess := _auth(self), "EDIT", mfa=mfa)
                return self._ok(G.update_group(
                    gid, name=body.get("name"), description=body.get("description"),
                    modified_by=sess["username"]))
            if method == "DELETE":
                # Deleting a group drops its members and every profile
                # association, so it sits behind the same destructive gate as
                # RETIRE rather than a plain EDIT, and needs that approval.
                _route(_auth(self), "RETIRE", mfa=mfa,
                       approval={"approved": bool(body.get("approver1"))
                                 or bool(body.get("skip_approval")),
                                 "reason": body.get("reason", "delete group"),
                                 "dual": bool(body.get("approver1")
                                              and body.get("approver2"))})
                return self._ok(G.delete_group(gid))

        # ---- /{id}/members ----------------------------------------------
        if parts[:1] == ["members"]:
            if method == "GET" and len(parts) == 1:
                _route(_auth(self), "VIEW", require_mfa=False)
                return self._ok(G.list_group_members(gid))
            if method == "POST" and len(parts) == 1:
                sess = _auth(self)
                ids = body.get("device_ids") or ([body["device_id"]]
                                                 if body.get("device_id") else [])
                if not ids:
                    raise ApiError(400, "device_ids is required")
                # Deploying to every member of a group is the reference's
                # "apply to all devices", so the caller may ask for the bulk
                # approval gate instead of the per-device one.
                op = "BULK_APPLY" if body.get("bulk") else "APPLY"
                _route(sess, op, mfa=mfa,
                       approval={"approved": bool(body.get("approver1"))
                                 or bool(body.get("skip_approval")),
                                 "reason": body.get("reason", "add members"),
                                 "dual": bool(body.get("approver1")
                                              and body.get("approver2"))})
                return self._ok(G.add_members(
                    gid, ids, op_role=sess["role_code"],
                    mfa_ok=_mfa_ok(sess, mfa), added_by=sess["username"],
                    serial_for=serial_for, signing_key=_current_key(),
                    chan_dir=CHAN_DIR, deploy=bool(body.get("deploy", True)),
                    real=bool(body.get("real")),
                    allow_channel_risk=bool(body.get("allow_channel_risk"))))
            if method == "DELETE" and len(parts) == 2:
                _route(_auth(self), "EDIT", mfa=mfa)
                return self._ok(G.remove_member(gid, parts[1]))

        # ---- /{id}/move --------------------------------------------------
        if parts == ["move"] and method == "POST":
            sess = _auth(self)
            if not body.get("to_group") or not body.get("device_id"):
                raise ApiError(400, "to_group and device_id are required")
            _route(sess, "EDIT", mfa=mfa)
            return self._ok(G.move_device(gid, body["to_group"], body["device_id"],
                                          moved_by=sess["username"]))

        # ---- /{id}/profiles ----------------------------------------------
        if parts[:1] == ["profiles"]:
            if method == "GET" and len(parts) == 1:
                _route(_auth(self), "VIEW", require_mfa=False)
                return self._ok(G.list_group_profiles(gid))
            if method == "POST" and len(parts) == 1:
                sess = _auth(self)
                ids = body.get("policy_ids") or ([body["policy_id"]]
                                                 if body.get("policy_id") else [])
                if not ids:
                    raise ApiError(400, "policy_ids is required")
                _route(sess, "APPLY", mfa=mfa,
                       approval={"approved": bool(body.get("approver1"))
                                 or bool(body.get("skip_approval")),
                                 "reason": body.get("reason", "associate profiles"),
                                 "dual": bool(body.get("approver1")
                                              and body.get("approver2"))})
                out = G.associate_profiles(
                    gid, ids, op_role=sess["role_code"],
                    mfa_ok=_mfa_ok(sess, mfa), assigned_by=sess["username"],
                    remarks=body.get("remarks", ""), serial_for=serial_for,
                    signing_key=_current_key(), chan_dir=CHAN_DIR,
                    deploy=bool(body.get("deploy", True)), real=bool(body.get("real")),
                    allow_channel_risk=bool(body.get("allow_channel_risk")))
                if out["rejected"]:
                    # Do not silently drop a profile the admin asked for.
                    raise ApiError(409, "profiles not eligible for association: "
                                          + json.dumps(out["rejected"], ensure_ascii=False))
                return self._ok(out)
            if method == "DELETE" and len(parts) == 2:
                _route(_auth(self), "EDIT", mfa=mfa)
                return self._ok(G.disassociate_profile(gid, parts[1]))

        # ---- /{id}/deploy ------------------------------------------------
        if parts == ["deploy"] and method == "POST":
            sess = _auth(self)
            _route(sess, "BULK_APPLY", mfa=mfa,
                   approval={"approved": bool(body.get("approver1"))
                             or bool(body.get("skip_approval")),
                             "reason": body.get("reason", "deploy group"),
                             "dual": bool(body.get("approver1")
                                          and body.get("approver2"))})
            return self._ok(G.deploy_group(
                gid, op_role=sess["role_code"], mfa_ok=_mfa_ok(sess, mfa),
                only_devices=body.get("device_ids"),
                only_policies=body.get("policy_ids"), serial_for=serial_for,
                signing_key=_current_key(), chan_dir=CHAN_DIR,
                real=bool(body.get("real")),
                allow_channel_risk=bool(body.get("allow_channel_risk"))))

        # ---- /{id}/status and /{id}/actions ------------------------------
        if parts == ["status"] and method == "GET":
            _route(_auth(self), "VIEW", require_mfa=False)
            return self._ok(G.group_status(gid))
        if parts == ["actions"] and method == "GET":
            _route(_auth(self), "VIEW", require_mfa=False)
            return self._ok(G.list_group_actions(gid))

        raise ApiError(404, f"no route {method} {path}")

    # ------------------------------------------------------------------
    # Profiles (console-managed `policies` rows) — draft lifecycle.
    #
    # A profile is not apply-able just because it exists: it has to be PUBLISHED
    # (ACTIVE or REVIEW) before a group may reference it, which is enforced in
    # backend.groups.associate_profiles. Publishing changes what every associated
    # device is expected to look like, so it sits behind the APPLY approval gate
    # rather than a plain EDIT.
    def _profiles(self, method: str, path: str, body: dict):
        from backend import profiles as P

        rest = path[len("/api/v1/profiles"):].strip("/")
        parts = rest.split("/") if rest else []
        mfa = body.get("mfa", "")

        if not parts:
            if method == "GET":
                _route(_auth(self), "VIEW", require_mfa=False)
                include_superseded = self._q("include_superseded", "false").lower() in ("true", "1")
                return self._ok(P.list_profiles(
                    status=self._q("status", ""),
                    search=self._q("search", ""),
                    include_superseded=include_superseded))
            if method == "POST":
                _route(sess := _auth(self), "CREATE", mfa=mfa)
                return self._ok(P.create_draft(
                    body.get("name", ""), category=body.get("category", "CORPORATE_DEFAULT"),
                    description=body.get("description", ""),
                    recovery_attempts=body.get("recovery_attempts"),
                    created_by=sess["username"]))

        pid = parts[0]
        sub = parts[1:]

        if not sub:
            if method == "GET":
                _route(_auth(self), "VIEW", require_mfa=False)
                return self._ok(P.get_profile(pid))
            if method == "PUT":
                _route(sess := _auth(self), "EDIT", mfa=mfa)
                save_kw = {}
                if "recovery_attempts" in body:
                    # Present-with-null disables the challenge; absent keeps it.
                    save_kw["recovery_attempts"] = body.get("recovery_attempts")
                return self._ok(P.save_draft(
                    pid, name=body.get("name"), description=body.get("description"),
                    category=body.get("category"),
                    requirements=body.get("requirements"),
                    changed_by=sess["username"],
                    change_reason=body.get("change_reason", ""), **save_kw))
            if method == "DELETE":
                _route(_auth(self), "RETIRE", mfa=mfa,
                       approval={"approved": bool(body.get("approver1"))
                                 or bool(body.get("skip_approval")),
                                 "reason": body.get("reason", "delete draft profile"),
                                 "dual": bool(body.get("approver1")
                                              and body.get("approver2"))})
                force = bool(body.get("force")) or self._q("force", "") in ("1", "true")
                return self._ok(P.delete_profile(pid, force=force))

        if sub == ["submit"] and method == "POST":
            _route(sess := _auth(self), "EDIT", mfa=mfa)
            return self._ok(P.submit_for_review(
                pid, changed_by=sess["username"],
                change_reason=body.get("change_reason", "")))

        if sub == ["reopen"] and method == "POST":
            _route(sess := _auth(self), "EDIT", mfa=mfa)
            return self._ok(P.reopen_rejected(
                pid, changed_by=sess["username"],
                change_reason=body.get("change_reason", "rework rejected profile")))

        if sub == ["revision"] and method == "POST":
            # Editing a published profile opens a new DRAFT revision instead of
            # mutating what the groups and devices already reference.
            _route(sess := _auth(self), "EDIT", mfa=mfa)
            return self._ok(P.create_revision(
                pid, changed_by=sess["username"],
                change_reason=body.get("change_reason", "new profile revision")))

        if sub == ["publish"] and method == "POST":
            _route(sess := _auth(self), "APPLY", mfa=mfa,
                   approval={"approved": bool(body.get("approver1"))
                             or bool(body.get("skip_approval")),
                             "reason": body.get("reason", "publish profile"),
                             "dual": bool(body.get("approver1")
                                          and body.get("approver2"))})
            return self._ok(P.publish_draft(
                pid, changed_by=sess["username"],
                change_reason=body.get("change_reason", "")))

        if sub == ["reject"] and method == "POST":
            _route(sess := _auth(self), "APPLY", mfa=mfa)
            return self._ok(P.reject_profile(
                pid, reason=body.get("reason", ""), changed_by=sess["username"]))

        if sub == ["retire"] and method == "POST":
            _route(sess := _auth(self), "RETIRE", mfa=mfa,
                   approval={"approved": bool(body.get("approver1"))
                             or bool(body.get("skip_approval")),
                             "reason": body.get("reason", "retire profile"),
                             "dual": bool(body.get("approver1")
                                          and body.get("approver2"))})
            return self._ok(P.retire_profile(
                pid, reason=body.get("reason", ""), changed_by=sess["username"]))

        raise ApiError(404, f"no route {method} {path}")

    # ------------------------------------------------------------------
    def _login(self, body: dict):
        user, pw, code = body.get("username", ""), body.get("password", ""), body.get("mfa", "")
        with connect() as c:
            row = c.execute("SELECT * FROM administrators WHERE username=? AND active=1",
                            (user,)).fetchone()
        if not row or not row["password_hash"] or not auth.verify_password(pw, row["password_hash"]):
            raise ApiError(401, "bad credentials")
        if MFA_REQUIRED and row["mfa_enabled"] and not auth.totp_verify(row["mfa_secret"] or "", code):
            raise ApiError(401, "bad MFA code")
        token = auth.create_session(row["id"])
        return self._ok({"token": token, "username": row["username"],
                         "role_id": row["role_id"], "display_name": row["display_name"],
                         "mfa_required": MFA_REQUIRED})


def _current_key():
    """Signing key resolved at call time (never a frozen import-time constant)."""
    from backend.config import signing_key
    return signing_key()


def _serial_for(member: dict):
    """Serial resolver handed to backend.groups for the ADB transport."""
    return member.get("serial") or None


def _devices():
    with connect() as c:
        rows = c.execute(
            "SELECT device_id, serial, manufacturer, model, android_version, api_level, "
            "enrollment_state, compliance_state, is_lab, last_verification_at "
            "FROM devices ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _device_details(did: str) -> dict:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM devices WHERE device_id=? OR serial=? OR id=?",
            (did, did, int(did) if did.isdigit() else -1)).fetchone()
        if not row:
            raise ApiError(404, f"device {did} not found")
        dev = dict(row)
        dev_id = dev["id"]

        group_rows = c.execute("""
            SELECT g.id, g.group_key, g.name, g.description, g.membership_type, g.platform_type,
                   dgm.added_at AS associated_time, dgm.added_by AS associated_by,
                   (SELECT COUNT(*) FROM device_group_members WHERE group_id=g.id) AS member_count,
                   'Applied' AS status
            FROM device_groups g
            JOIN device_group_members dgm ON dgm.group_id = g.id
            WHERE dgm.device_id = ?
            ORDER BY g.name
        """, (dev_id,)).fetchall()
        dev["groups"] = [dict(g) for g in group_rows]

        profile_rows = c.execute("""
            SELECT p.id, p.policy_id, p.display_name AS name, p.version, p.status,
                   gpa.assigned_at AS associated_time, gpa.assigned_by AS associated_by,
                   gpa.remarks, g.name AS group_name
            FROM policies p
            JOIN group_profile_assignments gpa ON gpa.policy_id = p.id
            JOIN device_group_members dgm ON dgm.group_id = gpa.group_id
            JOIN device_groups g ON g.id = gpa.group_id
            WHERE dgm.device_id = ?
            ORDER BY p.display_name
        """, (dev_id,)).fetchall()
        dev["profiles"] = [dict(p) for p in profile_rows]

        # Lanes the last apply could not enforce on THIS handset. They come from
        # the compliance snapshot written by the director, so the page can name
        # them instead of only showing a generic verdict.
        note_row = c.execute(
            "SELECT comp.result, comp.checked_at, comp.details, p.policy_id, "
            "       p.display_name "
            "FROM compliance comp "
            "LEFT JOIN policies p ON p.id = comp.policy_id "
            "WHERE comp.device_id=? "
            "ORDER BY comp.checked_at DESC, comp.rowid DESC LIMIT 1",
            (dev_id,)).fetchone()
        unresolved = []
        last_check = None
        last_policy = None
        last_result = None
        if note_row:
            last_check = note_row["checked_at"]
            last_policy = note_row["policy_id"]
            last_result = note_row["result"]
            try:
                details = json.loads(note_row["details"] or "{}")
            except (TypeError, ValueError):
                details = {}
            raw = details.get("__unresolved_lanes__") or []
            if isinstance(raw, str):
                raw = [raw]
            unresolved = [str(x) for x in raw]

        dev["last_checked_at"] = last_check
        dev["last_policy_id"] = last_policy
        dev["last_result"] = last_result
        dev["unresolved_lanes"] = unresolved

        # What the handset itself reports: rows it applied and rows it refused.
        # This is the part that stops a profile looking successful while the
        # agent silently ignored it.
        agent_skipped, agent_applied = [], []
        try:
            from backend.agent_state import read_last_apply, skipped_features
            st = read_last_apply(dev.get("serial") or "")
            if st:
                agent_skipped = skipped_features(st)
                agent_applied = list(st.get("applied") or [])
                dev["agent_cmd_id"] = st.get("cmd_id", "")
                dev["agent_applied_at"] = st.get("applied_at", "")
        except Exception:
            pass
        dev["agent_applied"] = agent_applied
        dev["agent_skipped"] = agent_skipped

        notes = []
        if unresolved:
            notes.append("هذه القيود لا يملك الجهاز آلية لفرضها: "
                         + "، ".join(unresolved))
        if agent_skipped:
            notes.append("الوكيل تجاهل هذه القيود على الجهاز: "
                         + "، ".join(agent_skipped))
        dev["enforcement_note"] = " | ".join(notes)

        # Live presence probe: the rows above are database truth and go stale
        # the moment the app is uninstalled from the phone, so the details
        # page re-probes on every open. One `adb devices` + one `pm path`
        # when attached; nothing is written, only reported.
        serial = (dev.get("serial") or "").strip()
        try:
            attached = bool(serial) and serial in attached_serials()
        except Exception:
            attached = False
        try:
            agent = bool(attached and is_agent_installed(serial))
        except Exception:
            agent = False
        # Ownership is re-read from the phone, not the column: removing the
        # admin grant on the handset leaves the DB saying ACTIVE while no
        # restriction can enforce. Unattached phones keep the stored value
        # (nothing was proven either way).
        owner_stored = ((dev.get("device_owner_state") or "NONE")
                        .upper() == "ACTIVE")
        if attached and agent:
            try:
                owner_active = bool(is_device_owner_active(serial))
            except Exception:
                owner_active = owner_stored
        else:
            owner_active = owner_stored if not attached else False
        dev["device_owner_live"] = owner_active if attached else None
        if not attached:
            step = ("offline",
                    "الجهاز غير متصل عبر USB الآن — البيانات المعروضة من آخر "
                    "مرة شوهد فيها")
        elif not agent:
            step = ("install",
                    "التطبيق غير مثبت على هذا الهاتف — ثبّته أولاً، فلن يصل "
                    "إليه أي شيء بدونه")
        elif not owner_active:
            step = ("provision_owner",
                    "التطبيق مثبت لكنه ليس مالك الجهاز — Android لن يطبّق أي "
                    "قيد قبل ذلك")
        else:
            step = ("group",
                    "الجهاز جاهز — أضفه إلى مجموعة لنشر ملفاتها عليه")
        dev["attached"] = attached
        dev["agent_installed"] = agent
        dev["next_step"] = step[0]
        dev["next_step_reason"] = step[1]
        return dev


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
    httpd = ThreadingHTTPServer((API_BIND, API_PORT), Handler)
    print(f"ALP control-plane listening on http://{API_BIND}:{API_PORT}")
    if API_BIND != API_HOST:
        print(f"  clients on this machine: http://{API_HOST}:{API_PORT}")
        print("  (gnirehtet maps 10.0.2.2 to host localhost)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
