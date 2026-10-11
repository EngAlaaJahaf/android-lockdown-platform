"""ALP Manager Controller — headless desktop logic (testable without GUI).

Wraps the backends/engines behind one API used by the GUI and by tests:

    bootstrap / login / logout / whoami      (legacy admin/TOTP surface, CLI+API)
    adb_status / devices / enroll / probe
    apply (Director AD-4, real ADB channel) / verify are part of apply
    recover (RecoveryEngine R1..R4, approval-gated)
    recovery_status / recovery_vault_summary / rotate_recovery / revoke_recovery
    audit tail + tamper check
    generate_device_report (markdown)

OPEN-CONSOLE MODEL (AUTHENTICATION_AND_RECOVERY_DESIGN.html §4/§6/§9):
the console opens the dashboard directly — there is no interactive
Login/TOTP at startup. Sensitive device operations (APPLY / RECOVER /
FIRMWARE) are governed by:
    - a possession factor: the per-device system-generated recovery credential
      (RecoveryVault.verify_for), verified against THIS console's encrypted
      vault — the operator never types a secret and reports never expose one;
    - the approval gate (§11 dual rule): two distinct named human
      confirmations for destructive R1/R2 operations;
    - RBAC rules from the policy engine (roles still apply where sessions
      exist; local-operator console runs are gated by the credential factor).

Honesty is inherited from the engines: PASS requires a REAL_DEVICE observation
and an evidence id; SIMULATED never passes; recovery R3 always refuses.
"""
from __future__ import annotations

import json
import os
import time

from . import paths
from . import paths as _paths
from . import logger

paths.add_engine_paths()
paths.apply_runtime_env()

import backend.config as config                    # noqa: E402
from backend.db import connect, run_migrations     # noqa: E402
from backend import auth, audit as audit_mod       # noqa: E402
from backend import approval as approval_mod       # noqa: E402
from backend.recovery_credentials import RecoveryVault          # noqa: E402
from backend.workflows import (attached_serials, attached_detailed,           # noqa: E402
                               enroll_device, persist_reference_policies,
                               run_director_apply, resolve_policy, live_probe,
                               vendor_adapter_for_device, classify_device,
                               is_agent_installed, is_device_owner_active,
                               api_level_of,
                               apps as apps_inventory,
                               create_custom_policy)
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

    def _require_session(self, session_required: bool = True) -> dict | None:
        """Return the active legacy session row, or None when relaxed.

        With session_required=True this preserves the historic behavior
        (raise). With False, a missing session means the console is running
        as a local operator — the sensitive-op gate is then the per-device
        recovery credential, not a login session.
        """
        sess = self._load_session()
        if not sess or not sess.get("token"):
            if not session_required:
                return None
            raise PermissionError(
                "no session — the console runs in local-operator mode "
                "(no interactive login at startup); sensitive device "
                "operations use the per-device recovery credential")
        row = auth.resolve_session(sess["token"])
        if not row:
            self._save_session({})
            if not session_required:
                return None
            raise PermissionError(
                "session expired — reinstate a session or continue in "
                "local-operator mode")
        return dict(row)

    def _can_use_recovery(self, device_id: str) -> bool:
        """Possession factor (§9/§16): does THIS console hold a live,
        unrevoked, decryptable recovery credential for `device_id`?
        Never logs or exposes the secret itself."""
        try:
            return bool(RecoveryVault(self.db_path)
                        .verify_for(device_id).get("ok"))
        except Exception:  # noqa: BLE001
            return False

    def _operator_role(self) -> str:
        """Legacy session role when present; otherwise the local-operator
        console still binds sensitive ops to the device credential."""
        sess = self._require_session(session_required=False)
        return (sess or {}).get("role_code") or "SUPER_ADMIN"

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
        except PermissionError:
            return ("local operator (no session) — sensitive device ops use "
                    "the per-device recovery credential")

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

    def detected(self) -> list:
        """Live auto-detection: every ADB-attached device, enriched with its
        readiness state and whether it is already registered in the DB.

        Plug a phone in and the UI polls this (4 s timer) and shows it
        immediately — "يتعرّف عليه مباشرة" — ready to register in one click.
        """
        reg = {d["serial"]: d for d in self.devices()}
        out = []
        for d in attached_detailed():
            model = (d["model"] or "").replace("_", "-")   # SM_J337P -> SM-J337P
            ready = bool(d["ready"])
            row = reg.get(d["serial"])
            registered = row is not None
            # A device with no agent can never receive a policy: the New
            # Devices page gates every later step behind Install when this
            # is false, so the operator cannot silently skip it.
            agent = is_agent_installed(d["serial"]) if ready else False
            # API level decides WHICH build installs: Android 5-6 handsets
            # refuse the standard APK (INSTALL_FAILED_OLDER_SDK), so the UI
            # offers the guarded legacy build instead of a dead button.
            try:
                api = api_level_of(d["serial"]) if ready else 0
            except Exception:
                api = 0
            legacy = bool(ready and 0 < api < 24)
            # Ownership is read from the DB, and that column is only ever
            # written from a dumpsys proof (provision_device_owner). An
            # "ACTIVE" here therefore means the phone really is an owner —
            # which is exactly what every restriction needs.
            owner_state = ((row or {}).get("device_owner_state") or "NONE").upper()
            # ...unless the grant was removed on the handset afterwards (the
            # package stays — Android forbids uninstalling a device owner —
            # while dpm lists no owner). Re-read live for attached phones so
            # the Connected tab offers Make Owner instead of a blind Add.
            if ready and agent:
                try:
                    if not is_device_owner_active(d["serial"]):
                        owner_state = "NONE"
                except Exception:
                    pass
            owner_active = owner_state == "ACTIVE"
            # The single source of truth for "what now": any console — web or
            # desktop, current or future — renders exactly this step instead
            # of re-implementing the gating logic (and getting it wrong).
            if not ready:
                step = ("authorize",
                        "على الهاتف: اسمح بتصحيح USB لهذا الكمبيوتر ثم حدّث")
            elif not agent:
                step = ("install",
                        "التطبيق غير مثبت على هذا الهاتف — ثبّته أولاً، "
                        "فلن يصل إليه أي شيء بدونه")
            elif not registered:
                step = ("register",
                        "التطبيق مثبت — سجّل الجهاز لبدء إدارته")
            elif not owner_active:
                step = ("provision_owner",
                        "الجهاز مسجّل لكنه ليس مالك جهاز — Android لن يطبّق أي "
                        "قيد قبل ذلك. ثبّت التطبيق كمالك جهاز من الزر المجاور.")
            else:
                step = ("group",
                        "الجهاز جاهز — أضفه إلى مجموعة لنشر ملفاتها عليه")
            out.append({
                "serial": d["serial"],
                "state": d["state"],
                "model": model,
                "ready": ready,
                "registered": registered,
                "agent_installed": agent,
                "api_level": api,
                "legacy_build": legacy,
                "device_owner": owner_active,
                "device_owner_state": owner_state,
                "next_step": step[0],
                "next_step_reason": step[1],
            })
        return out

    def devices(self) -> list:
        with connect(self.db_path) as c:
            rows = c.execute(
                "SELECT device_id, serial, manufacturer, model, android_version, api_level, "
                "enrollment_state, compliance_state, device_owner_state, is_lab, "
                "last_verification_at FROM devices ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Active device context (per-console selection, no secrets stored)
    # ------------------------------------------------------------------
    def _active_state_file(self) -> str:
        return os.path.join(os.path.dirname(self.session_file) or ".", "active.json")

    def set_active_device(self, device_id: str = "", serial: str = "") -> dict:
        """Persist the operator's selected device for THIS console. Stored
        as plain device metadata only — never credentials."""
        with connect(self.db_path) as c:
            if device_id:
                dev = c.execute("SELECT * FROM devices WHERE device_id=?",
                                (device_id,)).fetchone()
            elif serial:
                dev = c.execute("SELECT * FROM devices WHERE serial=?",
                                (serial,)).fetchone()
            else:
                return {"ok": False, "error": "no device given"}
            if not dev:
                return {"ok": False,
                        "error": f"device {device_id or serial} not registered"}
            dev = dict(dev)
        payload = {"device_id": dev["device_id"], "serial": dev["serial"] or "",
                   "model": dev["model"] or "",
                   "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            with open(self._active_state_file(), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as ex:  # noqa: BLE001
            return {"ok": False, "error": str(ex)}
        logger.log_event("active_device", "set",
                         device_id=payload["device_id"], serial=payload["serial"])
        return {"ok": True, **payload}

    def active_device(self) -> dict:
        path = self._active_state_file()
        payload = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:  # noqa: BLE001
                payload = {}
        did = (payload or {}).get("device_id", "")
        if did:
            with connect(self.db_path) as c:
                dev = c.execute("SELECT device_id, serial, model FROM devices "
                                "WHERE device_id=?", (did,)).fetchone()
            if dev:
                return {"ok": True, "device_id": dev["device_id"],
                        "serial": dev["serial"] or "", "model": dev["model"] or ""}
        return {"ok": False, "error": "no active device"}

    def enroll(self, serial: str, device_id: str = "", lab: bool = False) -> dict:
        try:
            info = enroll_device(device_id or "", serial,
                                 device_owner=False, lab=lab)
            # Possession factor: the per-device recovery credential is
            # generated by the system at first registration on this console
            # (never shown to anyone, never stored in plaintext).
            try:
                RecoveryVault(self.db_path).ensure_for(info["device_id"])
            except Exception as ex:  # noqa: BLE001
                logger.log_error("vault", ex,
                                 f"credential-ensure failed device={info['device_id']}")
            logger.log_event("enroll", "ok", serial=serial,
                             device_id=info.get("device_id", ""),
                             model=info.get("model", ""))
            return {"ok": True, "device": info}
        except Exception as ex:
            logger.log_error("enroll", ex, f"serial={serial}")
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def probe(self, serial: str) -> dict:
        try:
            return {"ok": True, "bundle": live_probe(serial)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def apps(self, serial: str) -> dict:
        """Real installed-package inventory via ADB `pm list packages`."""
        try:
            return {"ok": True, "apps": apps_inventory(serial)}
        except Exception as ex:
            logger.log_error("apps", ex, serial=serial)
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def create_policy(self, name: str, category: str, features, risk: str = "MEDIUM",
                      recovery_attempts: int | None = None) -> dict:
        """Create a console-managed custom policy (checkbox builder / wizard)."""
        try:
            p = create_custom_policy(name, category, features, risk=risk,
                                     created_by="console",
                                     recovery_attempts=recovery_attempts)
            logger.log_event("policy", "created", policy_id=p.policy_id,
                             category=p.category, features=len(p.requirements))
            return {"ok": True, "policy_id": p.policy_id,
                    "display_name": p.display_name, "features": len(p.requirements)}
        except Exception as ex:
            logger.log_error("policy", ex, category=category)
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
    def apply(self, device_id: str, policy: str,
              real: bool = True, lane_subset: str = "") -> dict:
        """Director AD-4 for one device. Gated by the per-device recovery
        credential (possession factor) — no interactive Login/TOTP needed."""
        logger.log_event("apply", "start", device_id=device_id, policy=policy,
                         real=real)
        if not self._can_use_recovery(device_id):
            msg = (f"APPLY blocked — no active recovery credential for "
                   f"{device_id} on this console (possession factor). "
                   f"Issue the credential for the device first.")
            logger.log_event("apply", "blocked", device_id=device_id,
                             policy=policy, reason="no-recovery-credential")
            return {"ok": False, "error": msg}
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
                device_id, policy, op_role=self._operator_role(),
                mfa_ok=True, serial=serial if real else None,
                real=real, signing_key=config.signing_key(),
                channel_send=send)
            res["ok"] = True
            logger.log_event("apply", "ok", device_id=device_id,
                             policy=policy, stage=res.get("stage", ""),
                             evidence_id=res.get("evidence_id", ""),
                             verification=res.get("verification", ""))
            return res
        except Exception as ex:
            logger.log_error("apply", ex, device_id=device_id, policy=policy)
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ------------------------------------------------------------------
    # On-device rollback PIN (provisioned via a SIGNED envelope)
    # ------------------------------------------------------------------
    def provision_pin(self, device_id: str, pin: str = "", serial: str = "") -> dict:
        """Issue a PROVISION_PIN envelope through the REAL adb channel.

        Envelope is Ed25519-signed on THIS console; the embedded public key on
        the device is what accepts it. `pin` empty => a crypto-random 6-digit
        code is generated and returned once for the operator to hand to the
        user (the device itself can never set/reset its own rollback PIN).
        """
        try:
            from backend import pins as _pins  # noqa: PLC0415
            out = _pins.provision_pin(device_id, pin, serial=serial)
            out["ok"] = True
            logger.log_event("provision_pin", "issued",
                             device_id=device_id, cmd_id=out["envelope"]["cmd_id"],
                             action="PROVISION_PIN")
            if not out["delivery"].get("ok"):
                out["ok"] = False
                out["error"] = out["delivery"].get("error") or "adb delivery failed"
            return out
        except Exception as ex:  # noqa: BLE001
            logger.log_error("provision_pin", ex, device_id=device_id)
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ------------------------------------------------------------------
    # Recovery (R1..R4)
    # ------------------------------------------------------------------
    def recover(self, device_id: str, mode: str,
                serial: str = "", exec_: bool = False,
                approver1: str = "", approver2: str = "",
                reason: str = "", skip_approval: bool = False) -> dict:
        logger.log_event("recover", "start", device_id=device_id, mode=mode)
        if not self._can_use_recovery(device_id):
            return {"ok": False, "error":
                    f"{mode} blocked — no active recovery credential for "
                    f"{device_id} on this console (possession factor)"}
        if mode not in RECOVERY_MODES:
            return {"ok": False, "error": f"unknown recovery mode {mode!r}"}

        approval = {"approved": False}
        if mode == "R3_LAB_FLASH":
            # Governance gate: nothing executes. Approval is recorded as
            # satisfied so the engine emits its explicit REFUSED outcome.
            approval = {"approved": True,
                        "reason": "R3 governance refusal — Lab-Only, never "
                                  "executable from the management app"}
        elif mode in ("R0_WITHDRAW", "R1_RESTORE_POINT", "R2_REPROVISION"):
            if skip_approval:
                approval = {"approved": True,
                            "reason": "approval skipped (drill/test path)"}
            else:
                aid = approval_mod.request_approval(None, "RECOVER", device_id,
                                                    reason=reason or f"recovery {mode}")
                try:
                    if not approver1:
                        return {"ok": False, "approval_id": aid,
                                "error": "approval required — first named approver "
                                         "confirmation missing (dual rule: two "
                                         "distinct names)"}
                    first = approval_mod.confirm(aid, approver1)
                    if not first.get("approved"):
                        if not approver2:
                            return {"ok": False, "approval_id": aid,
                                    "error": "approval pending — second distinct "
                                             "approver confirmation required"}
                        second = approval_mod.confirm(aid, approver2)
                        if not second.get("approved"):
                            return {"ok": False, "approval_id": aid,
                                    "error": "approval not completed"}
                except ValueError as ex:
                    return {"ok": False, "approval_id": aid,
                            "error": f"approval failed: {ex}"}
                approval = {"approved": True,
                            "reason": f"{mode} approved by {approver1}"
                                      + (f" + {approver2}" if approver2 else "")}

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
                                 signing_key=config.signing_key(), probe=probe)
            res = eng.recover(device_id, mode, self._operator_role(), 0,
                              mfa_ok=True, approval=approval,
                              serial=dev_serial if dev_serial in attached_serials() else "",
                              exec_=exec_, restore_reason=reason)
            d = res.to_dict()
            d["ok"] = res.status in ("COMPLETE", "PARTIAL")
            if not d["ok"]:
                d["error"] = res.reason or res.status
            logger.log_event("recover", "done", device_id=device_id, mode=mode,
                             status=d.get("status", ""),
                             evidence_id=d.get("evidence_id", ""))
            return d
        except Exception as ex:
            logger.log_error("recover", ex, device_id=device_id, mode=mode)
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ------------------------------------------------------------------
    # Recovery vault — per-device credential status / rotation / revoke
    # Display-only: never exposes the secret, only `Recovery ID: XXXX-XXXX`.
    # ------------------------------------------------------------------
    def recovery_status(self, device_id: str) -> dict:
        """Display-only per-device status (Configured/Not Configured/Revoked/
        Mismatch) + the display-only Recovery ID."""
        try:
            st = RecoveryVault(self.db_path).status(device_id)
            st["ok"] = True
            return st
        except Exception as ex:  # noqa: BLE001
            return {"ok": False, "recovery": "Unavailable",
                    "recovery_id": "", "error": str(ex)}

    def recovery_vault_summary(self) -> dict:
        try:
            return {"ok": True,
                    "devices": RecoveryVault(self.db_path).summary()}
        except Exception as ex:  # noqa: BLE001
            return {"ok": False, "error": str(ex)}

    def rotate_recovery(self, device_id: str) -> dict:
        try:
            vault = RecoveryVault(self.db_path)
            st = vault.status(device_id)
            if st["recovery"] not in ("Configured", "Mismatch"):
                return {"ok": False,
                        "error": f"no active recovery credential for "
                                 f"{device_id} to rotate"}
            out = vault.rotate_for(device_id)
            out["ok"] = True
            return out
        except Exception as ex:  # noqa: BLE001
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def revoke_recovery(self, device_id: str) -> dict:
        try:
            out = RecoveryVault(self.db_path).revoke_for(device_id)
            out["ok"] = True
            return out
        except Exception as ex:  # noqa: BLE001
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def issue_recovery(self, device_id: str) -> dict:
        """(Re-)generate the display-only per-device credential. Automatically
        done at enrollment; exposed for Mismatch repair."""
        try:
            out = RecoveryVault(self.db_path).ensure_for(device_id)
            out["ok"] = True
            return out
        except Exception as ex:  # noqa: BLE001
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

    # ------------------------------------------------------------------
    # Capabilities + policy preview (honest, from real registry + live probe)
    # ------------------------------------------------------------------
    def capabilities(self, device_id: str) -> dict:
        from backend.workflows import capability_for_device
        with connect(self.db_path) as c:
            dev = c.execute("SELECT * FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
            if not dev:
                return {"ok": False, "error": f"no device {device_id}"}
            prof = capability_for_device(c, device_id)
        caps = {}
        if prof:
            for feat, capability in sorted(prof.states.items()):
                row = {"capability": capability,
                       "methods": prof.methods.get(feat, [])}
                if "observed" not in row:
                    row["observed"] = ""
                caps[feat] = row
        return {"ok": True, "device_id": device_id,
                "capability_profile": caps,
                "android_version": dev["android_version"] or 0,
                "api_level": dev["api_level"] or 0,
                "model": dev["model"] or "",
                "manufacturer": dev["manufacturer"] or ""}

    def policy_preview(self, device_id: str, policy: str) -> dict:
        from backend.workflows import resolve_policy
        pol = resolve_policy(policy)
        if not pol:
            return {"ok": False, "error": f"policy {policy} not found"}
        with connect(self.db_path) as c:
            dev = c.execute("SELECT serial FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
        if not dev:
            return {"ok": False, "error": f"device {device_id} not registered"}
        serial = dev["serial"]
        obs = {}
        if serial in attached_serials():
            try:
                b = live_probe(serial)
                obs = {f: v for f, v in (b.get("observed") or {}).items()}
                obs["_source"] = "REAL_DEVICE"
            except Exception as ex:
                obs["_source"] = f"error: {ex}"
        else:
            obs["_source"] = "DEVICE_NOT_ATTACHED"
        rows = []
        for r in pol.requirements:
            desired = r.desired_state
            current = obs.get(r.feature, "")
            rows.append({
                "feature": r.feature,
                "desired": desired,
                "current": current,
                "risk": r.risk,
                "source": obs.get("_source", ""),
            })
        return {"ok": True, "policy_id": pol.policy_id,
                "display_name": getattr(pol, "display_name", pol.policy_id),
                "device_id": device_id, "rows": rows}

    def preflight(self, device_id: str, policy: str) -> dict:
        """Honest pre-flight checklist before a policy apply (#21/#18).

        Reports only what is factually known RIGHT NOW: registration, ADB
        attach + authorization, device-policy readability, the management
        channel (Device Owner/DPC), the possession-factor credential, and
        whether the policy has any lane this device can actually implement.
        It never predicts verification success — that belongs to the
        verification engine after execution.

        verdict: PASS (all green) | CONDITIONAL (warnings/unknowns exist but
        the gate is not blocked) | FAIL (blocked). can_apply = PASS|CONDITIONAL.
        """
        from backend.workflows import capability_for_device
        checks: list[dict] = []

        def add(name, status, detail="", severity="FAIL"):
            checks.append({"name": name, "status": status,
                           "detail": detail, "severity": severity})

        with connect(self.db_path) as c:
            dev = c.execute("SELECT * FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
            dev = dict(dev) if dev else None
        if not dev:
            add("الجهاز مسجّل", "FAIL", f"الجهاز {device_id} غير موجود في السجل")
            return {"ok": True, "verdict": "FAIL", "can_apply": False,
                    "blocked": True, "checks": checks, "device_id": device_id,
                    "policy": policy, "reason": "الجهاز غير مسجّل"}

        pol = resolve_policy(policy)
        if not pol:
            add("السياسة معروفة", "FAIL", f"السياسة {policy} غير معروفة")
            return {"ok": True, "verdict": "FAIL", "can_apply": False,
                    "blocked": True, "checks": checks, "device_id": device_id,
                    "policy": policy, "reason": "سياسة غير معروفة"}
        add("السياسة معروفة", "PASS", getattr(pol, "display_name", pol.policy_id))

        serial = dev.get("serial") or ""
        state, attached, ready = "", False, False
        try:
            adb_list = attached_detailed()
        except Exception:  # noqa: BLE001 — adb missing/unavailable => not attached
            adb_list = []
        for d in adb_list:
            if d["serial"] == serial:
                state, attached, ready = d["state"], True, bool(d["ready"])
        if not serial:
            add("اتصال ADB وترخيص", "FAIL", "الجهاز بلا رقم تسلسلي مسجّل")
        elif attached and ready:
            add("اتصال ADB وترخيص", "PASS", f"{serial} بحالة {state}")
        elif attached:
            add("اتصال ADB وترخيص", "FAIL",
                f"{serial} متصل لكن الحالة {state} — فعّل تصحيح الأخطاء "
                "وأذِن للكمبيوتر")
        else:
            add("اتصال ADB وترخيص", "FAIL",
                "الجهاز غير متصل عبر ADB — لن يتم التطبيق الفعلي")

        obs, dpc_found = {}, None
        if attached and ready:
            try:
                b = live_probe(serial)
                obs = b.get("observed") or {}
                dpc_found = bool(b.get("dpc"))
                add("قراءة قيود الجهاز", "PASS" if (b.get("restrictions") or obs)
                    else "UNKNOWN",
                    "قراءة dumpsys/الإعدادات متاحة" if obs
                    else "لا قراءات متاحة بعد")
            except Exception as ex:  # noqa: BLE001
                add("قراءة قيود الجهاز", "UNKNOWN", f"تعذّرت القراءة: {ex}")
        else:
            add("قراءة قيود الجهاز", "UNKNOWN", "لا جهاز متصل لقراءته")

        owner = (dev.get("device_owner_state") or "").upper()
        if owner == "ACTIVE":
            add("قناة التطبيق (مالك الجهاز/DPM)", "PASS", "Device Owner مفعّل")
        elif attached and ready:
            if dpc_found:
                add("قناة التطبيق (مالك الجهاز/DPM)", "PASS",
                    "وكيل DPC موجود على الجهاز")
            else:
                add("قناة التطبيق (مالك الجهاز/DPM)", "WARN",
                    "لا يوجد Device Owner/DPC — المسارات المعتمدة على DPM "
                    "ستكون خطة فقط ولن تُطبَّق فعليًا على الجهاز", "WARN")
        else:
            add("قناة التطبيق (مالك الجهاز/DPM)", "FAIL",
                "الجهاز غير قابل للوصول الآن — لا يمكن التطبيق الفعلي")

        try:
            cred = bool(RecoveryVault(self.db_path)
                        .verify_for(device_id).get("ok"))
        except Exception:  # noqa: BLE001
            cred = False
        add("بيان الاسترداد (عامل الحيازة)", "PASS" if cred else "FAIL",
            "مُصدر وجاهز لهذا الجهاز" if cred
            else "لم يُصدر — لن يُسمح بالتطبيق")

        try:
            prof = capability_for_device(connect(self.db_path), device_id)
            states = dict(prof.states) if prof else {}
        except Exception:  # noqa: BLE001
            states = {}
        actionable, unsupported = [], []
        for r in getattr(pol, "requirements", []):
            feat = getattr(r, "feature", None) or (
                r.get("feature") if isinstance(r, dict) else "")
            st = (states.get(feat) or "").upper()
            if st and st not in ("NOT_FEASIBLE", "UNKNOWN"):
                actionable.append(feat)
            else:
                unsupported.append(feat)
        if actionable:
            add("نطاق القدرات للسياسة", "PASS",
                "مسارات قابلة للتطبيق: " + "، ".join(sorted(set(actionable))))
        elif unsupported:
            add("نطاق القدرات للسياسة", "WARN",
                "لا مسارات قابلة للتطبيق للسياسة على هذا الجهاز (غير مدفوع "
                "بدليل/غير مدعوم) — لن يُطبَّق شيء فعليًا", "WARN")
        else:
            add("نطاق القدرات للسياسة", "WARN", "لا متطلبات في هذه السياسة", "WARN")

        blocked = [c["name"] for c in checks if c["status"] == "FAIL"]
        if blocked:
            verdict, can = "FAIL", False
        elif any(c["status"] in ("WARN", "UNKNOWN") for c in checks):
            verdict, can = "CONDITIONAL", True
        else:
            verdict, can = "PASS", True
        reason = ("محظور: " + "؛ ".join(blocked) if blocked
                  else ("تحذيرات قائمة — يراجعها المسؤول قبل التنفيذ"
                        if verdict == "CONDITIONAL" else "جاهز للتطبيق"))
        logger.log_event("preflight", verdict, device_id=device_id,
                         policy=pol.policy_id, can_apply=can,
                         fails=len(blocked))
        return {"ok": True, "verdict": verdict, "can_apply": can,
                "blocked": bool(blocked), "checks": checks,
                "device_id": device_id, "policy": pol.policy_id,
                "reason": reason}

    def reports_list(self, device_id: str = "") -> list:
        base = os.path.join(config.REPORTS_DIR, device_id) if device_id \
            else config.REPORTS_DIR
        out = []
        if os.path.isdir(base):
            for root, _dirs, files in os.walk(base):
                for fn in sorted(files):
                    if fn.lower().endswith((".md", ".json", ".html")):
                        p = os.path.join(root, fn)
                        out.append({"path": p,
                                    "size": os.path.getsize(p),
                                    "mtime": time.strftime(
                                        "%Y-%m-%d %H:%M:%S",
                                        time.localtime(os.path.getmtime(p)))})
        return out

    def diagnostics(self) -> dict:
        from backend.workflows import adb
        adb_exe = adb()
        attached = attached_serials()
        db_ok = False
        tables = 0
        try:
            with connect(self.db_path) as c:
                tables = c.execute(
                    "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table'").fetchone()["n"]
            db_ok = True
        except Exception as ex:
            db_ok = str(ex)
        try:
            tamper = audit_mod.AuditLog(self.db_path).tamper_check()
        except Exception as ex:
            tamper = {"error": str(ex)}
        from .paths import is_frozen, persist_dir, project_root
        return {
            "frozen_mode": is_frozen(),
            "project_root": project_root() if not is_frozen() else persist_dir(),
            "db_path": self.db_path,
            "db_ok": db_ok,
            "db_tables": tables,
            "adb_exe": adb_exe,
            "adb_configured": os.path.exists(adb_exe) or adb_exe.lower() == "adb",
            "adb_devices": attached,
            "bootstrap_needed": self.needs_bootstrap(),
            "signed_in": bool((self._load_session() or {}).get("token")),
            "audit_chain": "OK" if (tamper.get("broken") is False) else "BROKEN",
        }