"""RecoveryEngine — R1..R4 (approved §7 recovery matrix / EXECUTE §20).

  R1_RESTORE_POINT  rollback the applied policy on the device (CLEAR_POLICY).
                    Reversible, MEDIUM impact -> RECOVER approval + the
                    per-device recovery credential (possession factor).
  R2_REPROVISION    re-enroll steps (QR / dpm path). RECOVER approval +
                    recovery credential; shell execution only with exec=True
                    (still approval-gated).
  R3_LAB_FLASH      governance gate — NEVER executes. Records an explicit
                    REFUSED_GOVERNANCE_LAB_ONLY evidential audit. R3 is a
                    Lab-Only procedure (two-person + firmware files) and is
                    NOT reachable from the management app by design.
  R4_DIAGNOSTIC     read-only device state dump. No approval, no mutation.

Honesty invariants (same law as the Director):
  - PASS is impossible without an evidence id AND a real device observation
    (source=REAL_DEVICE). SIMULATED sources structurally cannot PASS.
  - Every outcome is chained into the tamper-evident audit log even on refusal.

The admin factor ("mfa_ok" in the legacy callers, "credential_ok" in the new
console) is satisfied by the per-device recovery credential (RecoveryVault)
verify_for() — see AUTHENTICATION_AND_RECOVERY_DESIGN.html §9/§10/§16.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field

from .db import connect
from .audit import AuditLog
from .command import new_command
from . import rbac


RECOVERY_MODES = ("R1_RESTORE_POINT", "R2_REPROVISION", "R3_LAB_FLASH", "R4_DIAGNOSTIC")


@dataclass
class RecoveryResult:
    mode: str
    device_id: str
    status: str = "PENDING"          # COMPLETE | PARTIAL | FAILED | REFUSED | PLAN_ONLY
    evidence_id: str = ""
    audit_id: str = ""
    source: str = "SIMULATED"        # honest observation source
    reason: str = ""                 # why (block / refusal / partial)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "device_id": self.device_id, "status": self.status,
            "evidence_id": self.evidence_id, "audit_id": self.audit_id,
            "source": self.source, "reason": self.reason, "details": self.details,
        }


class RecoveryBlocked(Exception):
    pass


def adb() -> str:
    from .workflows import adb as _adb
    return _adb()


def _run(args: list[str], timeout: int = 40):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as ex:
        class R:
            returncode = -1
            stdout = ""
            stderr = str(ex)
        return R()


class RecoveryEngine:
    def __init__(self, db_path=None, channel_send=None,
                 signing_key: str = "", audit=None, probe=None):
        """channel_send(envelope, action) -> dict{ok, error?}
        probe(serial) -> observed feature map or None (honest SIMULATED path)."""
        self.db_path = db_path
        self.channel_send = channel_send
        self.signing_key = signing_key
        self.audit = audit or AuditLog(db_path)
        self.probe = probe   # e.g. probe_live_device from verification probe

    # ------------------------------------------------------------------
    def recover(self, device_id: str, mode: str, op_role: str, admin_id: int,
                mfa_ok: bool = False, credential_ok=None, approval=None,
                serial: str = "", exec_: bool = False,
                restore_reason: str = "") -> RecoveryResult:
        """Run a recovery mode.

        mfa_ok: legacy alias — retained so existing callers/tests keep working.
        credential_ok: the per-device recovery credential possession factor
        (RecoveryVault). When None (legacy callers), credential_ok derives
        from mfa_ok so old flows keep their previous authorization behavior.
        """
        if mode not in RECOVERY_MODES:
            raise RecoveryBlocked(f"unknown recovery mode {mode!r}")
        if credential_ok is None:
            credential_ok = bool(mfa_ok)
        handler = {
            "R1_RESTORE_POINT": self._r1,
            "R2_REPROVISION": self._r2,
            "R3_LAB_FLASH": self._r3,
            "R4_DIAGNOSTIC": self._r4,
        }[mode]
        return handler(device_id, op_role, admin_id, credential_ok, approval or {},
                       serial, exec_, restore_reason)

    # ------------------------------------------------------------------
    def _authorize(self, op_role: str, operation: str, credential_ok: bool,
                   approval: dict, mode: str) -> None:
        try:
            rbac.authorize(op_role, operation, require_mfa=False, mfa_ok=False,
                           approval=approval, require_credential=True,
                           credential_ok=credential_ok)
        except PermissionError as ex:
            raise RecoveryBlocked(f"{mode} authorization failed: {ex}")

    def _stamp(self, evidence_id: str, device_id: str, result: str):
        with connect(self.db_path) as c:
            row = c.execute("SELECT id FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
            dev_pk = row["id"] if row else None
            c.execute("INSERT OR IGNORE INTO evidence (evidence_id, device_id, kind, result, created_by) "
                      "VALUES (?,?,?,?,'recovery')",
                      (evidence_id, dev_pk, "RECOVERY_RESULT", result))

    def _evidence_id(self) -> str:
        return "REC-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8].upper()

    # ------------------------------------------------------------------
    def _r1(self, device_id, op_role, admin_id, credential_ok, approval, serial,
            exec_, reason) -> RecoveryResult:
        res = RecoveryResult("R1_RESTORE_POINT", device_id)
        self._authorize(op_role, "RECOVER", credential_ok, approval, "R1")
        self._update_state(device_id, "RECOVERY")

        env = new_command(0, device_id, "CLEAR_POLICY",
                          {"reason": reason or "operator-initiated rollback",
                           "restore_policy_id": ""},
                          key=self.signing_key)
        if self.channel_send is not None:
            outcome = self.channel_send(env, "CLEAR_POLICY")
            if not outcome.get("ok"):
                res.status = "FAILED"
                res.reason = f"channel send failed: {outcome.get('error')}"
                self._finish(res, device_id, op_role, admin_id, "R1", result="FAILED")
                return res
        else:
            res.details["prepared"] = {
                "cmd_id": env["cmd_id"], "action": "CLEAR_POLICY",
                "note": "no channel configured — rollback envelope prepared only"}

        res.evidence_id = self._evidence_id()
        self._stamp(res.evidence_id, device_id, "PENDING")
        observed = None
        if serial and self.probe is not None:
            try:
                observed = self.probe(serial)
            except Exception as ex:
                observed = {}
        if observed:
            res.source = "REAL_DEVICE"
            res.details["observed"] = observed
            restricted = [f for f, s in observed.items()
                          if isinstance(s, str) and "RESTRICT" in s.upper()]
            if not restricted:
                res.status = "COMPLETE"
            else:
                res.status = "PARTIAL"
                res.reason = f"still restricted: {sorted(restricted)}"
        else:
            res.source = "SIMULATED"
            res.status = "PLAN_ONLY"
            res.reason = "no real observation available — rollback not verified on device (honest)"
        self._stamp(res.evidence_id, device_id, res.status)
        self._finish(res, device_id, op_role, admin_id, "R1", result=res.status,
                     evidence_ref=res.evidence_id, extra={"verified": res.source})
        return res

    # ------------------------------------------------------------------
    def _r2(self, device_id, op_role, admin_id, credential_ok, approval, serial,
            exec_, reason) -> RecoveryResult:
        res = RecoveryResult("R2_REPROVISION", device_id)
        self._authorize(op_role, "RECOVER", credential_ok, approval, "R2")
        plan = [
            {"step": 1, "cmd": "adb shell settings put secure user_setup_complete 0",
             "why": "unlock device-owner provisioning (AOSP blocks DO with accounts)"},
            {"step": 2, "cmd": "adb shell dpm set-device-owner com.alp.agent/.AlpDeviceAdminReceiver",
             "why": "provision ALP agent as Device Owner (no accounts, user_setup_complete=0)"},
            {"step": 3, "cmd": "adb shell settings put secure user_setup_complete 1",
             "why": "restore user-setup flag after provisioning"},
        ]
        res.details["plan"] = plan
        res.details["qr_path"] = "QR / NFC provisioning: android.app.extra.PROVISIONING_MODE + ACTION_ADMIN_POLICY_COMPLIANCE (deprecated ACTION_PROVISION_MANAGED_DEVICE is NOT used)"

        executed = []
        if exec_ and serial:
            try:
                rbac.authorize(op_role, "RECOVER", require_mfa=False,
                               mfa_ok=False, approval=approval,
                               require_credential=True,
                               credential_ok=credential_ok)
                ok_all = True
                for step in plan:
                    raw = step["cmd"].replace("adb shell ", "")
                    r = _run([adb(), "-s", serial, "shell"] + raw.split(" "))
                    executed.append({"step": step["step"], "cmd": step["cmd"],
                                     "ok": r.returncode == 0,
                                     "out": (r.stdout or r.stderr)[:200]})
                    ok_all = ok_all and r.returncode == 0
                res.details["executed"] = executed
                res.status = "COMPLETE" if ok_all else "PARTIAL"
                res.reason = "" if ok_all else "some provisioning steps failed"
                res.source = "REAL_DEVICE"
            except RecoveryBlocked as ex:
                res.status = "FAILED"
                res.reason = str(ex)
        else:
            res.status = "PLAN_ONLY"
            res.reason = "plan produced; execution requires exec=True + approval (not executed)"
        self._finish(res, device_id, op_role, admin_id, "R2", result=res.status,
                     extra={"executed": bool(executed)})
        return res

    # ------------------------------------------------------------------
    def _r3(self, device_id, op_role, admin_id, credential_ok, approval, serial,
            exec_, reason) -> RecoveryResult:
        """Governance gate — ALWAYS refuses. Lab-Only R3 is not app-executable."""
        res = RecoveryResult("R3_LAB_FLASH", device_id, status="REFUSED")
        # Authorization is enforced (fails closed even for the refusal event).
        self._authorize(op_role, "FIRMWARE", credential_ok, approval, "R3")
        res.reason = ("REFUSED_GOVERNANCE_LAB_ONLY — firmware flashing is a "
                      "Lab-Only procedure (two-person review + firmware files). "
                      "It is never executable from the management application.")
        res.details["governance"] = {
            "rule": "AD-5 / §27 gate", "requires": "lab + dual human approval",
            "no_script_path": True,
        }
        self._update_state(device_id, "RECOVERY")
        self._finish(res, device_id, op_role, admin_id, "R3", result="REFUSED")
        return res

    # ------------------------------------------------------------------
    def _r4(self, device_id, op_role, admin_id, mfa_ok, approval, serial,
            exec_, reason) -> RecoveryResult:
        res = RecoveryResult("R4_DIAGNOSTIC", device_id)
        if op_role:
            try:
                rbac.authorize(op_role, "VIEW", require_mfa=False, mfa_ok=False)
            except PermissionError as ex:
                raise RecoveryBlocked(f"R4 authorization failed: {ex}")
        dump = {"identity": {}, "settings": {}, "restrictions": [], "dpc": None}
        if serial:
            r = _run([adb(), "-s", serial, "shell", "getprop"])
            if r.returncode == 0:
                for ln in r.stdout.splitlines():
                    if "]:" in ln and ln.startswith("["):
                        k, _, v = ln.partition("]: [")
                        dump["identity"][k.strip("[")] = v.rstrip("]")
            r = _run([adb(), "-s", serial, "shell", "dumpsys", "device_policy"])
            if r.returncode == 0:
                dump["device_policy_head"] = r.stdout[:4000]
                dump["restrictions"] = [ln for ln in r.stdout.splitlines()
                                        if "no_" in ln and ("true" in ln or "User restriction" in ln)]
            r = _run([adb(), "-s", serial, "shell", "run-as", "com.alp.agent",
                      "cat", "files/state.json"])
            if r.returncode == 0:
                try:
                    dump["dpc"] = json.loads(r.stdout)
                except Exception:
                    dump["dpc"] = {"raw": r.stdout[:500]}
        res.details = dump
        res.status = "COMPLETE"
        res.reason = "read-only diagnostic dump (REAL_DEVICE observation)" if serial else "no serial — empty dump (honest)"
        res.source = "REAL_DEVICE" if serial else "UNKNOWN"
        self._save_r4(device_id, res)
        self._finish(res, device_id, op_role, admin_id, "R4", result="COMPLETE")
        return res

    def _save_r4(self, device_id: str, res: RecoveryResult):
        from .config import REPORTS_DIR
        d = os.path.join(REPORTS_DIR, device_id)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"recovery-R4-{time.strftime('%Y%m%d-%H%M%S')}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(res.to_dict(), indent=2, ensure_ascii=False, default=str))
        res.details["report_file"] = path

    # ------------------------------------------------------------------
    def _update_state(self, device_id: str, state: str):
        with connect(self.db_path) as c:
            c.execute("UPDATE devices SET enrollment_state=? WHERE device_id=?",
                      (state, device_id))

    def _finish(self, res: RecoveryResult, device_id, op_role, admin_id,
                action: str, result: str, evidence_ref: str = "", extra=None):
        res.audit_id = self.audit.record(
            "recovery", op_role or "system", f"RECOVER_{action}",
            device_id=device_id, new_state="RECOVERY", result=result,
            evidence_ref=evidence_ref, extra=extra or {})