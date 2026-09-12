"""Security + backend integration tests. Uses an isolated temp DB (ALP_DB),
never the real database/alp.db."""

import os
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="alp_test_")
os.environ["ALP_DB"] = os.path.join(_TMP, "test.db")
os.environ["ALP_SIGNING_KEY"] = "test-only-signing-key-0123456789abcdef"

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from backend import db, audit, auth, rbac, approval, command, state_machine, fleet


class _Setup:
    @classmethod
    def setup(cls):
        db.run_migrations()
        with db.connect() as c:
            if c.execute("SELECT 1 FROM administrators LIMIT 1").fetchone():
                return  # idempotent — a prior discovery pass already seeded
            roles = {r["code"]: r["id"] for r in c.execute("SELECT id, code FROM roles")}
            for uname, dname, role in (("op_test", "Operator", "OPERATOR"),
                                       ("aprv_1", "Approver1", "FLEET_ADMIN"),
                                       ("aprv_2", "Approver2", "FLEET_ADMIN")):
                c.execute("INSERT INTO administrators (username, display_name, role_id, mfa_enabled) "
                          "VALUES (?,?,?,1)", (uname, dname, roles[role]))


_Setup.setup()


class TestAuditChain(unittest.TestCase):
    def test_chain_links_and_tamper_detection(self):
        lg = audit.AuditLog()
        lg.record("op_test", "OPERATOR", "POLICY_APPLY", device_id="D-1",
                  previous_state="ENROLLED", new_state="PHONE_ONLY", result="SUCCESS")
        id2 = lg.record("op_test", "OPERATOR", "LOCK", device_id="D-1",
                        previous_state="CORPORATE_STANDARD", new_state="FULL_LOCKDOWN", result="SUCCESS")
        checks = lg.tamper_check()
        self.assertEqual(checks["broken"], 0)

        with db.connect() as c:
            c.execute("UPDATE audit_logs SET new_state='QUARANTINE' WHERE entry_id=?", (id2,))
        checks = lg.tamper_check()
        self.assertGreaterEqual(checks["broken"], 1)

    def test_secrets_never_in_audit(self):
        lg = audit.AuditLog()
        lg.record("hacker", "SERVICE", "AUTH", reason="pw leak",
                  extra={"password": "hunter2", "token": "abc", "ok": 1})
        with db.connect() as c:
            row = c.execute("SELECT reason FROM audit_logs ORDER BY rowid DESC LIMIT 1").fetchone()
        self.assertNotIn("hunter2", row["reason"])


class TestAuth(unittest.TestCase):
    def test_password_hash_roundtrip(self):
        h = auth.hash_password("correct horse battery staple")
        self.assertTrue(auth.verify_password("correct horse battery staple", h))
        self.assertFalse(auth.verify_password("wrong", h))

    def test_totp_known_vector(self):
        import base64 as _b64
        # RFC 6238 test secret; counter 0 -> 755224
        key = _b64.b32decode("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
        self.assertEqual(auth._totp_at(key, 0), "755224")

    def test_totp_generate_verify(self):
        b32, _uri = auth.generate_totp_secret()
        code = auth._totp_at(auth._b32_decode(b32), int(os.popen("python -c \"import time; print(int(time.time())//30)\"").read().strip()))
        self.assertTrue(auth.totp_verify(b32, code))

    def test_session_lifecycle(self):
        tok = auth.create_session(1)
        resolved = auth.resolve_session(tok)
        self.assertEqual(resolved["username"], "op_test")
        auth.revoke_session(tok)
        self.assertIsNone(auth.resolve_session(tok))


class TestRBAC(unittest.TestCase):
    def test_super_admin_can_lock(self):
        self.assertEqual(rbac.decision_for("SUPER_ADMIN", "LOCK"), "ALLOW")

    def test_operator_may_lock_but_not_unlock(self):
        # reads back the approved matrix in migration 002
        self.assertEqual(rbac.decision_for("OPERATOR", "LOCK"), "ALLOW")
        self.assertEqual(rbac.decision_for("OPERATOR", "UNLOCK"), "DENY")
        self.assertEqual(rbac.decision_for("SUPER_ADMIN", "UNLOCK"), "REQUIRES_APPROVAL")

    def test_read_only_denied_bulk(self):
        self.assertEqual(rbac.decision_for("READ_ONLY", "BULK_APPLY"), "DENY")

    def test_factory_reset_requires_approval(self):
        d = rbac.decision_for("SUPER_ADMIN", "FACTORY_RESET")
        self.assertIn(d, ("REQUIRES_APPROVAL", "ALLOW"))
        self.assertTrue(rbac.requires_dual_approval("FACTORY_RESET"))

    def test_authorize_gate_mfa(self):
        with self.assertRaises(PermissionError):
            rbac.authorize("SUPER_ADMIN", "LOCK", require_mfa=True, mfa_ok=False)


class TestApprovalGate(unittest.TestCase):
    def test_dual_approval_flow_factory_reset(self):
        aid = approval.request_approval(1, "FACTORY_RESET", scope="single", reason="test")
        first = approval.approve(aid, 2, mfa_ok=True)
        self.assertTrue(first["needs_second"])
        self.assertFalse(approval.is_approved(aid))
        second = approval.approve(aid, 3, mfa_ok=True)
        self.assertTrue(second["approved"])
        self.assertTrue(approval.is_approved(aid))

    def test_dual_requires_distinct_approvers(self):
        aid = approval.request_approval(1, "RETIRE", scope="single", reason="test")
        approval.approve(aid, 2, mfa_ok=True)
        with self.assertRaises(ValueError):
            approval.approve(aid, 2, mfa_ok=True)  # same approver

    def test_mfa_required_to_approve(self):
        aid = approval.request_approval(1, "UNLOCK", scope="single", reason="test")
        with self.assertRaises(ValueError):
            approval.approve(aid, 2, mfa_ok=False)


class TestCommandChannel(unittest.TestCase):
    def test_sign_and_verify(self):
        env = command.new_command(1, "D-1", "LOCK", {"reason": "demo"})
        command.verify_envelope(env, "D-1")
        # idempotent second verify = replay
        with self.assertRaises(command.CommandRejected):
            command.verify_envelope(env, "D-1")

    def test_device_binding_mismatch(self):
        env = command.new_command(1, "D-1", "LOCK", {})
        with self.assertRaises(command.CommandRejected):
            command.verify_envelope(env, "D-2")

    def test_expired_command_rejected(self):
        import time as _t
        now = int(_t.time())
        payload = {"cmd_id": "C-X", "job_execution_id": 1, "device_id": "D-1",
                   "action": "LOCK", "nonce": "n1", "issued_at": now - 320,
                   "expires_at": now - 10, "body": {}}
        payload["signature"] = command.sign_command(payload)
        with self.assertRaises(command.CommandRejected):
            command.verify_envelope(payload, "D-1")


class TestStateMachine(unittest.TestCase):
    def test_canonical_enroll_path(self):
        self.assertEqual(state_machine.transition("UNMANAGED", "ENROLLMENT_PENDING"), "ENROLLMENT_PENDING")
        self.assertEqual(state_machine.transition("ENROLLMENT_PENDING", "ENROLLED",
                                                  also_target="CORPORATE_STANDARD"), "CORPORATE_STANDARD")

    def test_illegal_transition_rejected(self):
        with self.assertRaises(state_machine.StateTransitionError):
            state_machine.transition("UNMANAGED", "FULL_LOCKDOWN")

    def test_retirement_terminal(self):
        self.assertEqual(state_machine.transition("RECOVERY", "RETIREMENT"), "RETIREMENT")
        self.assertFalse(state_machine.can_transition("RETIREMENT", "ENROLLMENT_PENDING"))


class TestFleet(unittest.TestCase):
    def _run(self, ok: bool):
        return lambda dev, job: {"ok": ok}

    def test_job_wave_success(self):
        job = fleet.create_job("POLICY_UPDATE", "phone_only", 1, ["D-1", "D-2", "D-3"])
        res = fleet.run_wave(job, ["D-1", "D-2", "D-3"], self._run(True))
        self.assertEqual(res.succeeded, 3)
        self.assertFalse(res.stopped)

    def test_failure_threshold_stops_rollout(self):
        ids = [f"D-{i}" for i in range(10)]
        job = fleet.create_job("POLICY_UPDATE", "phone_only", 1, ids)
        with self.assertRaises(fleet.RolloutStopped):
            fleet.run_wave(job, ids, self._run(False))
        with db.connect() as c:
            status = c.execute("SELECT status FROM jobs WHERE job_id=?", (job,)).fetchone()["status"]
        self.assertEqual(status, "FAILURE_QUEUE")

    def test_emergency_stop(self):
        fleet.create_job("LOCK", "full_lockdown", 1, ["D-1"])
        stopped = fleet.emergency_stop_all("drill")
        self.assertGreaterEqual(stopped, 1)

    def test_simulate_bulk(self):
        result = fleet.simulate_bulk("full_lockdown", n=250)
        self.assertEqual(result["total_devices"], 250)
        self.assertIn(result["stage"], ("FULL", "STOPPED"))


if __name__ == "__main__":
    unittest.main()