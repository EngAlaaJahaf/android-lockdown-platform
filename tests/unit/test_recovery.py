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


class EmergencyTokenTests(unittest.TestCase):
    """Offline emergency uninstall tokens: issue-once, hash-only storage,
    single-use burn, expiry and revocation."""

    def setUp(self):
        self._prev_env = os.environ.get("ALP_DB")
        self.db = _fresh_db()
        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO devices (device_id, serial, model, "
                "android_version, api_level) VALUES (?,?,?,?,?)",
                ("DEV-EMG", "SEREMG1", "Pixel", 14, 34))

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev_env

    def test_issue_shows_plaintext_once_and_stores_hash_only(self):
        import hashlib
        from backend import emergency as emg
        out = emg.issue_token("DEV-EMG", created_by="pytest")
        self.assertTrue(out["token"].startswith("AE-"))
        self.assertTrue(out["token_id"].startswith("ET-"))
        with connect() as c:
            row = c.execute("SELECT * FROM emergency_tokens WHERE token_id=?",
                            (out["token_id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertNotIn(out["token"], dict(row).values())
        self.assertEqual(row["token_sha256"],
                         hashlib.sha256(out["token"].encode()).hexdigest())

    def test_verify_burns_single_use(self):
        from backend import emergency as emg
        tok = emg.issue_token("DEV-EMG")["token"]
        self.assertTrue(emg.verify_token("DEV-EMG", tok)["ok"])
        again = emg.verify_token("DEV-EMG", tok)
        self.assertFalse(again["ok"])
        self.assertIn("used", again["reason"])

    def test_unknown_device_and_token_refused(self):
        from backend import emergency as emg
        with self.assertRaises(ValueError):
            emg.issue_token("NOPE")
        bad = emg.verify_token("DEV-EMG", "AE-0000-0000")
        self.assertFalse(bad["ok"])

    def test_expired_and_revoked_refused(self):
        from backend import emergency as emg
        t1 = emg.issue_token("DEV-EMG")["token"]
        with connect() as c:
            c.execute("UPDATE emergency_tokens SET expires_at='2000-01-01 "
                      "00:00:00' WHERE token_sha256=?",
                      (__import__("hashlib").sha256(t1.encode()).hexdigest(),))
        self.assertIn("expired", emg.verify_token("DEV-EMG", t1)["reason"])
        t2 = emg.issue_token("DEV-EMG")
        emg.revoke_token(t2["token_id"])
        self.assertIn("revoked",
                      emg.verify_token("DEV-EMG", t2["token"])["reason"])
        with self.assertRaises(ValueError):
            emg.revoke_token("ET-deadbeef")

    def test_list_hides_hashes(self):
        from backend import emergency as emg
        emg.issue_token("DEV-EMG", label="spare")
        rows = emg.list_tokens("DEV-EMG")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("token_sha256", rows[0])
        self.assertEqual(rows[0]["label"], "spare")

    def test_purpose_scoping(self):
        from backend import emergency as emg
        out = emg.issue_token("DEV-EMG", purpose="rollback")
        self.assertEqual(out["purpose"], "rollback")
        ok = emg.verify_token("DEV-EMG", out["token"])
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["purpose"], "rollback")
        with self.assertRaises(ValueError):
            emg.issue_token("DEV-EMG", purpose="nuke-everything")

    def test_offline_codes_derive_and_verify(self):
        """memdm-style offline codes: deterministic per (secret, purpose,
        window), accepted ±1 step, rejected outside or for wrong purpose."""
        import time
        from backend import emergency as emg
        from backend.recovery_credentials import RecoveryVault
        RecoveryVault().ensure_for("DEV-EMG")
        now = time.time()
        a = emg.offline_code("DEV-EMG", "rollback", when=now)
        b = emg.offline_code("DEV-EMG", "rollback", when=now)
        self.assertEqual(a["code"], b["code"])
        self.assertRegex(a["code"], r"^\d{8}$")
        self.assertTrue(emg.verify_offline_code("DEV-EMG", "rollback",
                                                a["code"], when=now))
        # neighboring windows accepted (wrong phone clocks tolerated)
        self.assertTrue(emg.verify_offline_code(
            "DEV-EMG", "rollback", a["code"],
            when=now + emg.OFFLINE_STEP_SECONDS))
        # far window rejected
        self.assertFalse(emg.verify_offline_code(
            "DEV-EMG", "rollback", a["code"],
            when=now + 10 * emg.OFFLINE_STEP_SECONDS))
        # purpose separation: a rollback code never opens withdraw
        self.assertFalse(emg.verify_offline_code("DEV-EMG",
                                                 "withdraw_uninstall",
                                                 a["code"], when=now))
        self.assertFalse(emg.verify_offline_code("DEV-EMG", "rollback",
                                                 "00000000", when=now))
        with self.assertRaises(ValueError):
            emg.offline_code("DEV-EMG", "nuke-everything", when=now)
        with self.assertRaises(ValueError):
            emg.offline_code("NOPE", "rollback", when=now)

    def test_offline_vectors_stable_across_calls(self):
        """Pinned derivation: same secret+purpose+counter always yields the
        same code (the agent implements this byte-identically in
        EmergencyCodes.java; any drift breaks offline verification, so this
        test guards the formula)."""
        from backend import emergency as emg
        secret = bytes(range(32))
        c1 = emg._offline_code_for(secret, "rollback", 1000)
        c2 = emg._offline_code_for(secret, "rollback", 1000)
        c3 = emg._offline_code_for(secret, "rollback", 1001)
        c4 = emg._offline_code_for(secret, "withdraw_uninstall", 1000)
        self.assertEqual(c1, c2)
        self.assertRegex(c1, r"^\d{8}$")
        self.assertNotEqual(c1, c3)
        self.assertNotEqual(c1, c4)

    def test_offline_vectors_match_agent_implementation(self):
        """Cross-implementation vectors: these exact values were produced
        INDEPENDENTLY by the compiled Java EmergencyCodes.codeFor on the
        same secret (bytes 0..31). If either side drifts, offline codes die
        silently on the device — this test catches that."""
        from backend import emergency as emg
        secret = bytes(range(32))
        self.assertEqual(emg._offline_code_for(secret, "rollback", 1000),
                         "93239682")
        self.assertEqual(emg._offline_code_for(secret, "rollback", 1001),
                         "30152190")
        self.assertEqual(emg._offline_code_for(secret, "withdraw_uninstall",
                                               1000),
                         "57816768")
        # reset_password purpose produces dedicated valid 8-digit code
        reset_code = emg._offline_code_for(secret, "reset_password", 1000)
        self.assertRegex(reset_code, r"^\d{8}$")
        self.assertEqual(reset_code, emg._offline_code_for(secret, "reset_password", 1000))
        self.assertNotEqual(reset_code, "93239682")
        self.assertNotEqual(reset_code, "57816768")

    def test_passcode_recovery_profile_threshold_validation(self):
        """Profile creation and updates properly validate recovery_attempts."""
        from backend import profiles as P
        p = P.create_draft("Test Recov Profile", recovery_attempts=5)
        self.assertEqual(p["recovery_attempts"], 5)
        # update draft with new valid threshold
        p2 = P.save_draft(p["policy_id"], recovery_attempts=3)
        self.assertEqual(p2["recovery_attempts"], 3)
        # disable threshold with None
        p3 = P.save_draft(p["policy_id"], recovery_attempts=None)
        self.assertIsNone(p3["recovery_attempts"])
        # invalid threshold raises ProfileError
        with self.assertRaises(P.ProfileError):
            P.save_draft(p["policy_id"], recovery_attempts=15)
        with self.assertRaises(P.ProfileError):
            P.save_draft(p["policy_id"], recovery_attempts=0)


if __name__ == "__main__":
    unittest.main()