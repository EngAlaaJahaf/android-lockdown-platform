"""Tests for the RecoveryEngine (backend.recovery) R0..R4 + honesty invariants."""
from __future__ import annotations

import os
import tempfile
import unittest

import backend.recovery as rec
from backend.recovery import RecoveryEngine, RecoveryBlocked, RECOVERY_MODES
from backend.db import connect, run_migrations


def _fresh_db() -> str:
    fd, path = tempfile.mkstemp(prefix="alp_rec_", suffix=".db")
    os.close(fd)
    os.environ["ALP_DB"] = path
    run_migrations(path)
    return path


class RecoveryFlows(unittest.TestCase):
    def setUp(self):
        self._prev_env = os.environ.get("ALP_DB")
        self.db = _fresh_db()
        from backend.director import DirectorError  # noqa: F401
        from backend.state_machine import transition  # noqa: F401
        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO devices (device_id, serial, model, android_version, "
                "api_level, enrollment_state, device_owner_state, control_channel) "
                "VALUES ('DEV-1','emulator-5554','sdk_gphone64_x86_64',16,36,"
                "'UNMANAGED','ACTIVE','LOCAL_ADB')")

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev_env

    def test_modes_vocabulary(self):
        self.assertEqual(len(RECOVERY_MODES), 5)
        for m in ("R0_WITHDRAW", "R1_RESTORE_POINT", "R2_REPROVISION",
                  "R3_LAB_FLASH", "R4_DIAGNOSTIC"):
            self.assertIn(m, RECOVERY_MODES)

    def test_r0_blocked_without_approval(self):
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001")
        with self.assertRaises(RecoveryBlocked):
            eng.recover("DEV-1", "R0_WITHDRAW", "SUPER_ADMIN", admin_id=1,
                        mfa_ok=False, approval={}, serial="")

    def test_r0_plan_only_not_executed(self):
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001")
        res = eng.recover("DEV-1", "R0_WITHDRAW", "SUPER_ADMIN", admin_id=1,
                          mfa_ok=True, approval={"approved": True}, serial="")
        self.assertEqual(res.mode, "R0_WITHDRAW")
        self.assertEqual(res.status, "PLAN_ONLY")
        self.assertTrue(res.details["plan"])
        self.assertNotIn("executed", res.details)

    def test_r0_exec_complete_when_owner_absent(self):
        import unittest.mock as mock
        from types import SimpleNamespace

        def fake_run(args, timeout=40):
            cmd = " ".join(args)
            if "list-owners" in cmd:
                return SimpleNamespace(returncode=0, stdout="OWNERS:\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        fake_channel = lambda e, a: {"ok": True}
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001",
                             channel_send=fake_channel)
        with mock.patch.object(rec, "_run", side_effect=fake_run):
            res = eng.recover("DEV-1", "R0_WITHDRAW", "SUPER_ADMIN", admin_id=1,
                              mfa_ok=True, approval={"approved": True},
                              serial="emulator-5554", exec_=True)
        self.assertEqual(res.status, "COMPLETE")
        self.assertEqual(res.source, "REAL_DEVICE")
        self.assertEqual(res.details["owners"], "OWNERS:\n")
        with connect() as c:
            row = c.execute("SELECT device_owner_state FROM devices "
                            "WHERE device_id='DEV-1'").fetchone()
            self.assertEqual(row["device_owner_state"], "NONE")

    def test_r0_exec_partial_when_owner_remains(self):
        import unittest.mock as mock
        from types import SimpleNamespace

        def fake_run(args, timeout=40):
            cmd = " ".join(args)
            if "list-owners" in cmd:
                return SimpleNamespace(returncode=0,
                                       stdout="User 0: admin=com.alp.agent/."
                                              "AlpDeviceAdminReceiver\n",
                                       stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        fake_channel = lambda e, a: {"ok": True}
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001",
                             channel_send=fake_channel)
        with mock.patch.object(rec, "_run", side_effect=fake_run):
            res = eng.recover("DEV-1", "R0_WITHDRAW", "SUPER_ADMIN", admin_id=1,
                              mfa_ok=True, approval={"approved": True},
                              serial="emulator-5554", exec_=True)
        self.assertEqual(res.status, "PARTIAL")
        self.assertIn("still present", res.reason)
        with connect() as c:
            row = c.execute("SELECT device_owner_state FROM devices "
                            "WHERE device_id='DEV-1'").fetchone()
            self.assertNotEqual(row["device_owner_state"], "NONE")

    def test_r1_blocked_without_approval(self):
        eng = RecoveryEngine(db_path=self.db, channel_send=lambda e, a: {"ok": True},
                             signing_key="test-key-0001")
        with self.assertRaises(RecoveryBlocked):
            eng.recover("DEV-1", "R1_RESTORE_POINT", "SUPER_ADMIN", admin_id=1,
                        mfa_ok=False, approval={}, serial="")
        with self.assertRaises(RecoveryBlocked):
            eng.recover("DEV-1", "R1_RESTORE_POINT", "SUPER_ADMIN", admin_id=1,
                        mfa_ok=True, approval={}, serial="")

    def test_r1_plan_only_when_no_channel(self):
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001")
        res = eng.recover("DEV-1", "R1_RESTORE_POINT", "SUPER_ADMIN", admin_id=1,
                          mfa_ok=True, approval={"approved": True}, serial="")
        self.assertEqual(res.mode, "R1_RESTORE_POINT")
        self.assertIn(res.status, ("PLAN_ONLY", "COMPLETE", "PARTIAL"))
        self.assertIn("prepared", res.details)
        # honest: without a probe/serial the result cannot be a real PASS
        self.assertNotEqual(res.source, "REAL_DEVICE")

    def test_r1_real_channel_verifies_restrictions_cleared(self):
        def channel(env, action):
            self.assertEqual(action, "CLEAR_POLICY")
            self.assertEqual(env["action"], "CLEAR_POLICY")
            return {"ok": True, "error": None}

        def probe(serial):
            return {"WIFI": "OFF", "BLUETOOTH": "OFF", "TETHERING": "OFF",
                    "ADB": "OFF", "MOBILE_DATA": "OFF", "LOCATION": "OFF"}
        eng = RecoveryEngine(db_path=self.db, channel_send=channel,
                             signing_key="test-key-0001", probe=probe)
        res = eng.recover("DEV-1", "R1_RESTORE_POINT", "SUPER_ADMIN", admin_id=1,
                          mfa_ok=True, approval={"approved": True},
                          serial="emulator-5554")
        self.assertEqual(res.status, "COMPLETE")
        self.assertEqual(res.source, "REAL_DEVICE")
        self.assertTrue(res.evidence_id.startswith("REC-"))
        self.assertTrue(res.audit_id.startswith("AUD-"))

    def test_r1_partial_when_restriction_remains(self):
        def channel(env, action):
            return {"ok": True}
        def probe(serial):
            return {"WIFI": "RESTRICTED", "BLUETOOTH": "OFF"}
        eng = RecoveryEngine(db_path=self.db, channel_send=channel,
                             signing_key="test-key-0001", probe=probe)
        res = eng.recover("DEV-1", "R1_RESTORE_POINT", "SUPER_ADMIN", admin_id=1,
                          mfa_ok=True, approval={"approved": True},
                          serial="emulator-5554")
        self.assertEqual(res.status, "PARTIAL")
        self.assertIn("WIFI", res.reason)

    def test_r2_plan_only_not_executed(self):
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001")
        res = eng.recover("DEV-1", "R2_REPROVISION", "SUPER_ADMIN", admin_id=1,
                          mfa_ok=True, approval={"approved": True}, serial="")
        self.assertEqual(res.status, "PLAN_ONLY")
        self.assertTrue(res.details["plan"])
        self.assertNotIn("executed", res.details)

    def test_r3_never_executes(self):
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001")
        res = eng.recover("DEV-1", "R3_LAB_FLASH", "SUPER_ADMIN", admin_id=1,
                          mfa_ok=True, approval={"approved": True}, serial="emulator-5554")
        self.assertEqual(res.status, "REFUSED")
        self.assertIn("GOVERNANCE", res.reason.upper())
        self.assertNotIn("executed", res.details)

    def test_r4_readonly_writes_report(self):
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001")
        res = eng.recover("DEV-1", "R4_DIAGNOSTIC", "AUDITOR", admin_id=1,
                          mfa_ok=True, approval={}, serial="")
        self.assertEqual(res.status, "COMPLETE")
        self.assertTrue(res.details.get("report_file"))
        self.assertTrue(os.path.exists(res.details["report_file"]))

    def test_unknown_mode_rejected(self):
        eng = RecoveryEngine(db_path=self.db, signing_key="test-key-0001")
        with self.assertRaises(RecoveryBlocked):
            eng.recover("DEV-1", "R9_UNKNOWN", "SUPER_ADMIN", admin_id=1,
                        mfa_ok=True, approval={}, serial="")


if __name__ == "__main__":
    unittest.main()