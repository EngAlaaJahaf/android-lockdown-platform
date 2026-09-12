"""Director — the AD-4 orchestration service.

Sequence per approved AD-4 (§4/§35):
    Discover → Identify → Assess(capability) → Select Policy → Validate(snapshot)
    → Apply → Verify → Evidence → Compliance

Every step is audited. Nothing reports SUPPORTED without a snapshot that resolved
exceptions, and PASS is impossible without an evidence id (VerificationEngine law).
Channels are injected; the real ADB/agent channels are implemented at the CLI/API
layers; tests inject honest fakes.
"""
from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

from .db import connect
from .audit import AuditLog
from .command import new_command, verify_envelope, CommandRejected
from .state_machine import can_transition, transition
from . import rbac


class DirectorError(Exception):
    pass


class ApplyBlocked(DirectorError):
    """Snapshot carries un-resolvable exceptions; policy must not be applied."""


class PipelineResult:
    def __init__(self, device_id: str, policy_id: str):
        self.device_id = device_id
        self.policy_id = policy_id
        self.stage = "ABORT"
        self.snapshot = None
        self.command = None
        self.verification = None
        self.compliance = None
        self.evidence_id = ""
        self.audit_id = ""
        self.exceptions = []
        self.notes = []

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "policy_id": self.policy_id,
            "stage": self.stage,
            "exceptions": list(self.exceptions),
            "evidence_id": self.evidence_id,
            "audit_id": self.audit_id,
            "verification": self.verification.to_dict() if self.verification else None,
            "compliance": (self.compliance.result if self.compliance else None),
            "notes": list(self.notes),
        }


# Maps state-machine policy vocabulary onto the device table's
# enrollment_state vocabulary (health/management states).
_STATE_TO_DEVICE_VOCAB = {
    "PHONE_ONLY": "COMPLIANT", "FULL_LOCKDOWN": "COMPLIANT", "PARTIAL_LOCKDOWN": "COMPLIANT",
    "CORPORATE_STANDARD": "COMPLIANT", "ENROLLED": "ENROLLED",
    "MAINTENANCE": "MAINTENANCE", "QUARANTINE": "QUARANTINED",
    "RECOVERY": "RECOVERY", "RETIREMENT": "RETIRED",
}


class Director:
    def __init__(self, db_path: Optional[str] = None,
                 resolve_fn: Optional[Callable] = None,
                 verify_fn: Optional[Callable] = None,
                 channel_send: Optional[Callable] = None,
                 signing_key: Optional[str] = None,
                 audit: Optional[AuditLog] = None):
        """resolve_fn(policy, capability, compat_layer, vendor_adapter) -> PolicySnapshot
        verify_fn(command, device_id, expected, evidence_id, source) -> VerificationResult
        channel_send(envelope) -> dict{ok, error?}"""
        self.db_path = db_path
        self.resolve_fn = resolve_fn
        self.verify_fn = verify_fn
        self.channel_send = channel_send
        self.signing_key = signing_key
        self.audit = audit or AuditLog(db_path)

    # ------------------------------------------------------------------
    def apply(self, device_id: str, policy, capability,
              op_role: str = "SUPER_ADMIN", mfa_ok: bool = True,
              approval: Optional[dict] = None,
              compat_layer=None, vendor_adapter=None,
              force: bool = False, evidence_src: str = "SIMULATED",
              job_execution_id: int = 0) -> PipelineResult:
        """Full AD-4 pipeline for a single device. Returns result; raises on block."""
        res = PipelineResult(device_id, policy.policy_id)

        if policy.status in ("DRAFT", "REJECTED"):
            raise DirectorError(f"policy {policy.policy_id} is {policy.status}")

        # 1. Capability + snapshot (Validate)
        if self.resolve_fn is None:
            raise DirectorError("no resolve_fn configured")
        snap = self.resolve_fn(policy, capability, compat_layer, vendor_adapter)
        res.snapshot = snap
        res.exceptions = list(snap.exceptions)
        if snap.exceptions and not force:
            raise ApplyBlocked(
                f"policy {policy.policy_id} has {len(snap.exceptions)} unresolved "
                f"exceptions on {device_id}: {sorted(snap.exceptions)}")

        # 2. Authorization + approval gate
        rbac.authorize(op_role, "APPLY", require_mfa=True, mfa_ok=mfa_ok, approval=approval)
        if not can_transition("ENROLLED", "PHONE_ONLY") and capability.device_owner is not True:
            res.notes.append("device not yet Device-Owner; enrollment pending")

        # 3. Build signed command + send over channel
        expected = {}
        for r in snap.resolved:
            expected[r.feature] = "OFF" if r.desired == "BLOCK" else ("ON" if r.desired == "ALLOW" else "RESTRICT")
        env = new_command(job_execution_id, device_id, "APPLY_POLICY",
                          {"policy_id": policy.policy_id, "version": policy.version,
                           "snapshot": [r.__dict__ for r in snap.resolved]},
                          key=self.signing_key)
        res.command = env

        if self.channel_send is not None:
            outcome = self.channel_send(env)
            if not outcome.get("ok"):
                raise DirectorError(f"channel send failed: {outcome.get('error')}")
            res.notes.append("command delivered to channel")
        else:
            res.notes.append("no channel configured — command prepared only")

        # 4. Verify → evidence
        if self.verify_fn is None:
            raise DirectorError("no verify_fn configured")
        res.evidence_id = "EV-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8].upper()
        self._stamp_evidence(res.evidence_id, device_id, "PENDING")
        verdict = self.verify_fn("APPLY_POLICY", device_id, expected,
                                 evidence_id=res.evidence_id, source=evidence_src)
        verdict.evidence_id = res.evidence_id
        res.verification = verdict
        self._stamp_evidence(res.evidence_id, device_id, verdict.result)

        # 5. Compliance verdict (real engine: any violation → NON_COMPLIANT)
        from .compliance_forge import compliance_forge
        res.compliance = compliance_forge(device_id, policy.policy_id,
                                          expected, (verdict.observations or {}))

        # 6. State transition + persist + audit
        new_state = self._target_state(policy.category)
        try:
            new_state = transition("ENROLLED", new_state)
        except Exception:
            new_state = "ENROLLED"
        self._persist(device_id, policy.policy_id, verdict.result, res.evidence_id, new_state)
        res.stage = "COMPLETE"
        res.audit_id = self.audit.record(
            "cli", op_role, "AD4_APPLY", device_id=device_id,
            previous_state="ENROLLED", new_state=new_state,
            reason=f"AD-4 apply {policy.policy_id} v{policy.version}",
            result=verdict.result, evidence_ref=res.evidence_id,
            extra={"policy_id": policy.policy_id, "exceptions": len(snap.exceptions)})
        return res

    @staticmethod
    def _target_state(category: str) -> str:
        return {
            "PHONE_ONLY": "PHONE_ONLY", "FULL_LOCKDOWN": "FULL_LOCKDOWN",
            "PARTIAL_LOCKDOWN": "PARTIAL_LOCKDOWN",
            "CORPORATE_DEFAULT": "CORPORATE_STANDARD",
            "MAINTENANCE": "MAINTENANCE", "QUARANTINE": "QUARANTINE",
        }.get(category, "ENROLLED")

    def _persist(self, device_id: str, policy_id: str,
                 result: str, evidence_id: str, new_state: str):
        with connect(self.db_path) as c:
            row = c.execute("SELECT id, enrollment_state FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
            if row:
                comp = {"PASS": "COMPLIANT", "FAIL": "NON_COMPLIANT",
                        "PARTIAL": "PARTIAL", "UNKNOWN": "UNKNOWN"}.get(result, "UNKNOWN")
                # Enrollment never advances on a failed/unknown verification —
                # the policy-state vocabulary (COMPLIANT/QUARANTINED/…) is only
                # recorded once the device actually passed.
                dev_state = (_STATE_TO_DEVICE_VOCAB.get(new_state, "COMPLIANT")
                             if result == "PASS" else row["enrollment_state"])
                c.execute("UPDATE devices SET enrollment_state=?, compliance_state=?, "
                          "last_verification_at=datetime('now') WHERE device_id=?",
                          (dev_state, comp, device_id))

    def _stamp_evidence(self, evidence_id: str, device_id: str, result: str):
        with connect(self.db_path) as c:
            row = c.execute("SELECT id FROM devices WHERE device_id=?", (device_id,)).fetchone()
            dev_pk = row["id"] if row else None
            c.execute("INSERT OR IGNORE INTO evidence (evidence_id, device_id, kind, result, created_by) "
                      "VALUES (?,?,?,?,'director')",
                      (evidence_id, dev_pk, "VERIFY_RESULT", result))
            c.execute("UPDATE evidence SET result=? WHERE evidence_id=? AND result='PENDING'",
                      (result, evidence_id))


# ---------------------------------------------------------------------------
# Compliance mapping helper (kept here to avoid a circular import)
# ---------------------------------------------------------------------------

def _not_used():
    pass