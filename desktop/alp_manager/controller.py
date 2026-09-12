"""ALP Manager Controller — headless desktop logic (testable without GUI).

Wraps the backends/engines behind one API used by the Tkinter UI and by tests:

    bootstrap / login / logout / whoami
    adb_status / devices / enroll / probe
    apply (Director AD-4, real ADB channel) / verify are part of apply
    recover (RecoveryEngine R1..R4, approval-gated)
    audit tail + tamper check
    generate_device_report (markdown)

Honesty is inherited from the engines: PASS requires a REAL_DEVICE observation
and an evidence id; SIMULATED never passes; recovery R3 always refusess.
"""
from __future__ import annotations

import json
import os
import time

from . import paths
from . import paths as _paths

paths.add_engine_paths()
paths.apply_runtime_env()

import backend.config as config                    # noqa: E402
from backend.db import connect, run_migrations     # noqa: E402
from backend import auth, audit as audit_mod       # noqa: E402
from backend import approval as approval_mod       # noqa: E402
from backend.workflows import (attached_serials, enroll_device,                # noqa: E402
                               persist_reference_policies, run_director_apply,
                               resolve_policy, live_probe,
                               vendor_adapter_for_device, classify_device)
from backend.channel import adb_channel            # noqa: E402
from backend.recovery import RecoveryEngine, RECOVERY_MODES  # noqa: E402


class Controller:
    def __init__(self, db_path: str = "", session_file: str = ""):
        paths.apply_runtime_env()
        self.db_path = db_path or config.DBPATH
        self.session_file = session_file or (paths.session_file()
                                             if paths.is_frozen()
                                             else os.path.join(
                                                 paths.project_root(), ".alp", "session.json"))
        if not paths.is_frozen():
            os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
        # Synchronize the module-level default connection with this controller's
        # database so every backend helper (workflows/fleet/audit/policies) talks
        # to the same store as the UI (no cross-store drift).
        config.DBPATH = self.db_path
        import backend.db as _dbmod
        _dbmod.DBPATH = self.db_path
        from backend import config as _stalecfg  # noqa: F401
        run_migrations(self.db_path)

    # ------------------------------------------------------------------
    # Sessions / auth
    # ------------------------------------------------------------------
    def _save_session(self, d: dict):
        with open(self.session_file, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)

    def _load_session(self) -> dict | None:
        if not os.path.exists(self.session_file):
            return None
        try:
            with open(self.session_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def _require_session(self) -> dict:
        sess = self._load_session()
        if not sess or not sess.get("token"):
            raise PermissionError("no session — run: login")
        row = auth.resolve_session(sess["token"])
        if not row:
            self._save_session({})
            raise PermissionError("session expired — login again")
        return dict(row)

    def _totp_ok(self, admin_id: int, code: str) -> bool:
        with connect(self.db_path) as c:
            r = c.execute("SELECT mfa_secret FROM administrators WHERE id=?",
                          (admin_id,)).fetchone()
        return bool(r and r["mfa_secret"] and auth.totp_verify(r["mfa_secret"], code or ""))

    def needs_bootstrap(self) -> bool:
        with connect(self.db_path) as c:
            n = c.execute("SELECT COUNT(*) AS n FROM administrators").fetchone()["n"]
        return n == 0

    def bootstrap(self, user: str, password: str) -> dict:
        with connect(self.db_path) as c:
            n = c.execute("SELECT COUNT(*) AS n FROM administrators").fetchone()["n"]
            if n > 0:
                return {"ok": False, "error": "administrators already exist — use login"}
            pw = auth.hash_password(password)
            b32, uri = auth.generate_totp_secret()
            c.execute("INSERT INTO administrators (username, display_name, role_id, "
                      "password_hash, mfa_secret, mfa_enabled) VALUES (?,?,1,?,?,1)",
                      (user, user, pw, b32))
            return {"ok": True, "totp_uri": uri, "secret": b32}

    def login(self, user: str, password: str, code: str) -> dict:
        run_migrations(self.db_path)
        with connect(self.db_path) as c:
            row = c.execute("SELECT * FROM administrators WHERE username=? AND active=1",
                            (user,)).fetchone()
        if not row or not row["password_hash"] or not auth.verify_password(password, row["password_hash"]):
            return {"ok": False, "error": "bad username or password"}
        if row["mfa_enabled"] and not auth.totp_verify(row["mfa_secret"] or "", code):
            return {"ok": False, "error": "bad MFA code"}
        token = auth.create_session(row["id"])
        self._save_session({"token": token})
        return {"ok": True, "token": token, "username": row["username"],
                "role_id": row["role_id"], "display_name": row["display_name"]}

    def whoami(self) -> str:
        try:
            s = self._require_session()
            return f"{s['username']}  role={s['role_code']}  token={s['token'][:8]}…"
        except PermissionError as ex:
            return str(ex)

    def logout(self) -> dict:
        sess = self._load_session()
        if sess and sess.get("token"):
            try:
                auth.revoke_session(sess["token"])
            except Exception:
                pass
        self._save_session({})
        return {"ok": True}

    # ------------------------------------------------------------------
    # ADB + registry
    # ------------------------------------------------------------------
    def adb_status(self) -> dict:
        return {"devices": attached_serials(), "configured": True}

    def devices(self) -> list:
        with connect(self.db_path) as c:
            rows = c.execute(
                "SELECT device_id, serial, manufacturer, model, android_version, api_level, "
                "enrollment_state, compliance_state, device_owner_state, is_lab, "
                "last_verification_at FROM devices ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def enroll(self, serial: str, device_id: str = "", lab: bool = False) -> dict:
        try:
            info = enroll_device(device_id or "", serial,
                                 device_owner=False, lab=lab)
            return {"ok": True, "device": info}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def probe(self, serial: str) -> dict:
        try:
            return {"ok": True, "bundle": live_probe(serial)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def classify(self, manufacturer="", model="", android_version=0,
                 api_level=0, build_fingerprint=""):
        dc = classify_device(manufacturer, model, android_version,
                             api_level, build_fingerprint)
        return dc.to_dict()

    def policies(self) -> list:
        persist_reference_policies()
        with connect(self.db_path) as c:
            rows = c.execute(
                "SELECT policy_id, display_name, category, version, status, checksum "
                "FROM policies ORDER BY category, policy_id").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Apply (Director AD-4) with a REAL adb channel
    # ------------------------------------------------------------------
    def apply(self, device_id: str, policy: str, mfa: str,
              real: bool = True, lane_subset: str = "") -> dict:
        try:
            sess = self._require_session()
        except PermissionError as ex:
            return {"ok": False, "error": str(ex)}
        if not self._totp_ok(sess["admin_id"], mfa):
            return {"ok": False, "error": "MFA code required/incorrect — an MFA-verified actor is mandatory for APPLY"}
        with connect(self.db_path) as c:
            dev = c.execute("SELECT * FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
        if not dev:
            return {"ok": False, "error": f"device {device_id} not registered"}
        serial = dev["serial"]
        if real and serial not in attached_serials():
            return {"ok": False, "error": f"device {serial} not attached via ADB — can't apply for real"}
        if lane_subset and lane_subset.strip():
            os.environ["ALP_LANE_SUBSET"] = lane_subset
        send, _state = adb_channel(serial, out_dir=os.path.join(
            config.REPORTS_DIR, "phase1", "commands")) if real else (None, {})
        try:
            res = run_director_apply(
                device_id, policy, op_role=sess["role_code"],
                mfa_ok=True, serial=serial if real else None,
                real=real, signing_key=config.SIGNING_KEY,
                channel_send=send)
            res["ok"] = True
            return res
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ------------------------------------------------------------------
    # Recovery (R1..R4)
    # ------------------------------------------------------------------
    def recover(self, device_id: str, mode: str, mfa: str,
                serial: str = "", exec_: bool = False,
                approver_user: str = "", approver_mfa: str = "",
                reason: str = "", skip_approval: bool = False) -> dict:
        try:
            sess = self._require_session()
            admin_id, role = sess["admin_id"], sess["role_code"]
            if not self._totp_ok(admin_id, mfa):
                return {"ok": False, "error": "MFA code required for recovery"}
        except PermissionError as ex:
            return {"ok": False, "error": str(ex)}

        approval = {"approved": False}
        if mode in ("R1_RESTORE_POINT", "R2_REPROVISION"):
            if skip_approval:
                approval = {"approved": True, "reason": "test-only bypass"}
            else:
                aid = approval_mod.request_approval(admin_id, "RECOVER", device_id,
                                                    reason=reason or f"recovery {mode}")
                if not approver_user:
                    return {"ok": False, "approval_id": aid,
                            "error": "approval required — a second (distinct) approver with MFA must approve"}
                with connect(self.db_path) as c:
                    arr = c.execute(
                        "SELECT id, mfa_secret FROM administrators WHERE username=? AND active=1",
                        (approver_user,)).fetchone()
                if not arr or arr["id"] == admin_id:
                    return {"ok": False, "approval_id": aid,
                            "error": "approver must be an active, distinct administrator"}
                if not (arr["mfa_secret"] and auth.totp_verify(arr["mfa_secret"], approver_mfa)):
                    return {"ok": False, "approval_id": aid, "error": "bad approver MFA code"}
                out = approval_mod.approve(aid, arr["id"], mfa_ok=True)
                if not out.get("approved") or not approval_mod.is_approved(aid):
                    return {"ok": False, "approval_id": aid, "error": "approval not completed"}
                approval = {"approved": True, "reason": f"recovery {mode} approved ({approver_user})"}

        with connect(self.db_path) as c:
            dev = c.execute("SELECT serial FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
        dev_serial = serial or (dev["serial"] if dev else "")

        def probe(serial_inner):
            try:
                b = live_probe(serial_inner)
                return b.get("observed")
            except Exception:
                return None

        try:
            send, _ = adb_channel(dev_serial, out_dir="") if dev_serial else (None, {})
            eng = RecoveryEngine(db_path=self.db_path, channel_send=send,
                                 signing_key=config.SIGNING_KEY, probe=probe)
            res = eng.recover(device_id, mode, role, admin_id,
                              mfa_ok=True, approval=approval,
                              serial=dev_serial if dev_serial in attached_serials() else "",
                              exec_=exec_, restore_reason=reason)
            res.ok = True
            return res.to_dict()
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def audit(self, tail: int = 50) -> list:
        return audit_mod.AuditLog(self.db_path).tail(tail)

    def tamper_check(self) -> dict:
        return audit_mod.AuditLog(self.db_path).tamper_check()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def generate_device_report(self, device_id: str) -> dict:
        with connect(self.db_path) as c:
            dev = c.execute("SELECT * FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
            if not dev:
                return {"ok": False, "error": f"no device {device_id}"}
            ev = c.execute("SELECT evidence_id, kind, result, created_at, created_by "
                           "FROM evidence WHERE device_id=? ORDER BY id DESC LIMIT 20",
                           (dev["id"],)).fetchall()
            aud = c.execute("SELECT entry_id, action, result, created_at FROM audit_logs "
                            "WHERE device_id=? ORDER BY rowid DESC LIMIT 30",
                            (device_id,)).fetchall()
        body = []
        body.append(f"# Device report — {device_id}")
        body.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        body.append("")
        body.append("## Identity")
        for k in ("serial", "manufacturer", "model", "android_version", "api_level",
                  "build_fingerprint", "enrollment_state", "compliance_state",
                  "device_owner_state", "control_channel", "is_lab"):
            body.append(f"- {k}: {dev[k] or '-'}")
        body.append("")
        dc = classify_device(dev["manufacturer"] or "", dev["model"] or "",
                             dev["android_version"] or 0, dev["api_level"] or 0,
                             dev["build_fingerprint"] or "")
        body.append("## Vendor / version classification (device-agnostic)")
        for k, v in dc.to_dict().items():
            body.append(f"- {k}: {v or '-'}")
        body.append("")
        body.append("## Evidence")
        if not ev:
            body.append("_none recorded_")
        for e in ev:
            body.append(f"- `{e['evidence_id']}` {e['kind']} -> {e['result']} ({e['created_at']})")
        body.append("")
        body.append("## Audit trail (recent)")
        for a in aud:
            body.append(f"- `{a['entry_id']}` {a['action']} -> {a['result'] or '-'} ({a['created_at']})")
        text = "\n".join(body)
        d = os.path.join(config.REPORTS_DIR, device_id)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"device-report-{time.strftime('%Y%m%d-%H%M%S')}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return {"ok": True, "path": path, "text": text}