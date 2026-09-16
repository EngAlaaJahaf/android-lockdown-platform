"""Tests for the desktop Controller (headless, no GUI)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import backend.config as _cfg  # noqa: E402
import backend.db as _dbmod   # noqa: E402
from alp_manager.controller import Controller  # noqa: E402


class ControllerFlows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alp_ctrl_")
        self.db = os.path.join(self.tmp, "ctl.db")
        self.sess = os.path.join(self.tmp, "session.json")
        # Save the suite's DB routing so this module (which permanently
        # re-points global DBPATH while running) never leaks into siblings.
        self._prev = {"env": os.environ.get("ALP_DB"),
                      "cfg": _cfg.DBPATH, "db": _dbmod.DBPATH,
                      "rpt": _cfg.REPORTS_DIR}
        os.environ["ALP_DB"] = self.db
        os.environ["ALP_SIGNING_KEY"] = "ctrl-test-key-0001"
        os.environ["ALP_AUDIT_SALT"] = "ctrl-test-salt"
        _cfg.REPORTS_DIR = os.path.join(self.tmp, "reports")
        self.ctl = Controller(db_path=self.db, session_file=self.sess)

    def tearDown(self):
        if self._prev["env"] is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev["env"]
        _cfg.DBPATH = self._prev["cfg"]
        _dbmod.DBPATH = self._prev["db"]
        _cfg.REPORTS_DIR = self._prev["rpt"]

    def test_needs_bootstrap_then_bootstrap(self):
        self.assertTrue(self.ctl.needs_bootstrap())
        b = self.ctl.bootstrap("tester", "pass")
        self.assertTrue(b["ok"])
        self.assertIn("totp_uri", b)
        self.assertFalse(self.ctl.needs_bootstrap())
        again = self.ctl.bootstrap("x", "y")
        self.assertFalse(again["ok"])

    def test_login_requires_mfa_code(self):
        self.ctl.bootstrap("tester", "pass")
        r = self.ctl.login("tester", "pass", "000000")
        self.assertFalse(r["ok"])               # bad TOTP must fail

    def test_apply_requires_recovery_credential(self):
        # Open console: APPLY is gated by the per-device recovery credential
        # (possession factor), NOT by an interactive login/TOTP session.
        from backend.recovery_credentials import RecoveryVault
        self._seed_device(self.ctl, "D-CTRL-1", "SERCTRL1")
        r = self.ctl.apply("D-CTRL-1", "PHONE_ONLY")
        self.assertFalse(r["ok"])
        self.assertIn("recovery credential", r["error"])
        # after issuing the device credential the gate passes
        RecoveryVault(self.db).generate_for("D-CTRL-1")
        stale = self.ctl.apply("D-CTRL-1", "PHONE_ONLY")
        self.assertNotIn("recovery credential", stale.get("error", ""))

    def test_apply_internal_error_not_masked_by_logger(self):
        # Regression: apply()'s error handler passed device_id/policy as
        # keywords to logger.log_error() which did not accept **data — so a
        # real engine failure had its message replaced by a logging TypeError
        # and the true cause was hidden.
        from unittest import mock
        from backend.recovery_credentials import RecoveryVault
        self._seed_device(self.ctl, "D-ERR-1", "SERERR1")
        RecoveryVault(self.db).generate_for("D-ERR-1")
        with mock.patch("alp_manager.controller.attached_serials",
                        return_value=["SERERR1"]), \
             mock.patch("alp_manager.controller.adb_channel",
                        return_value=(None, {})), \
             mock.patch("alp_manager.controller.run_director_apply",
                        side_effect=ValueError("boom")):
            r = self.ctl.apply("D-ERR-1", "POL-FULL_LOCKDOWN")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "ValueError: boom")

    def test_policies_synced(self):
        pols = self.ctl.policies()
        ids = {p["policy_id"] for p in pols}
        self.assertIn("POL-PHONE_ONLY", ids)
        self.assertIn("POL-FULL_LOCKDOWN", ids)

    def test_recover_r3_refused_regardless(self):
        from backend.recovery_credentials import RecoveryVault
        self._seed_device(self.ctl, "D-CTRL-5", "SERCTRL5")
        RecoveryVault(self.db).generate_for("D-CTRL-5")
        r = self.ctl.recover("D-CTRL-5", "R3_LAB_FLASH", skip_approval=True)
        self.assertFalse(r["ok"])
        self.assertIn("REFUSED", (r.get("error") or "").upper())

    def test_recover_r1_requires_credential_then_confirmation(self):
        from backend.recovery_credentials import RecoveryVault
        self._seed_device(self.ctl, "D-CTRL-6", "SERCTRL6")
        # possession factor blocks first
        r = self.ctl.recover("D-CTRL-6", "R1_RESTORE_POINT", reason="test")
        self.assertFalse(r["ok"])
        self.assertIn("recovery credential", r["error"])
        RecoveryVault(self.db).generate_for("D-CTRL-6")
        # now the dual-rule confirmation gate requires named approvers
        r2 = self.ctl.recover("D-CTRL-6", "R1_RESTORE_POINT", reason="test")
        self.assertFalse(r2["ok"])
        self.assertIn("approver", r2["error"])
        self.assertIn("approval_id", r2)

    def test_recovery_status_roundtrip(self):
        from backend.recovery_credentials import RecoveryVault
        self._seed_device(self.ctl, "D-CTRL-7", "SERCTRL7")
        st0 = self.ctl.recovery_status("D-CTRL-7")
        self.assertTrue(st0["ok"])
        self.assertEqual(st0["recovery"], "Not Configured")
        RecoveryVault(self.db).generate_for("D-CTRL-7")
        st1 = self.ctl.recovery_status("D-CTRL-7")
        self.assertEqual(st1["recovery"], "Configured")
        self.assertRegex(st1["recovery_id"], r"^[0-9A-F]{4}-[0-9A-F]{4}$")
        # display-only: status must never leak the 32-byte credential secret
        blob = json.dumps(st1)
        self.assertNotIn('"ok":"', blob.lower())

    def test_rotate_and_revoke_recovery(self):
        from backend.recovery_credentials import RecoveryVault
        self._seed_device(self.ctl, "D-CTRL-8", "SERCTRL8")
        first = RecoveryVault(self.db).generate_for("D-CTRL-8")
        rid1 = first["recovery_id"]
        rot = self.ctl.rotate_recovery("D-CTRL-8")
        self.assertTrue(rot["ok"])
        self.assertNotEqual(rot["recovery_id"], rid1)
        rev = self.ctl.revoke_recovery("D-CTRL-8")
        self.assertTrue(rev["ok"])
        st = self.ctl.recovery_status("D-CTRL-8")
        self.assertEqual(st["recovery"], "Revoked")
        # a revoked credential must no longer satisfy the possession gate
        r = self.ctl.recover("D-CTRL-8", "R4_DIAGNOSTIC", skip_approval=True)
        self.assertFalse(r["ok"])
        self.assertIn("recovery credential", r["error"])

    def test_audit_and_tamper(self):
        self.ctl.bootstrap("tester", "pass")
        rows = self.ctl.audit(tail=10)
        self.assertIsInstance(rows, list)
        t = self.ctl.tamper_check()
        self.assertEqual(t["broken"], 0)

    def test_generate_device_report_missing_device(self):
        r = self.ctl.generate_device_report("NOPE")
        self.assertFalse(r["ok"])

    def test_classify_roundtrip(self):
        d = self.ctl.classify("samsung", "SM-J337P", 9, 28)
        self.assertEqual(d["vendor_id"], "samsung")
        self.assertEqual(d["family"], "J3 (2018+)")

    # ------------------------------------------------------------------
    # Capabilities / policy preview / reports / diagnostics (honesty path)
    # ------------------------------------------------------------------
    @staticmethod
    def _seed_device(ctl, device_id="D-CTRL-1", serial="SERCTRL1") -> str:
        """Register a device row directly (enroll() requires a live ADB
        device, so pure-DB seeding keeps these tests hermetic)."""
        from backend.db import connect
        with connect(ctl.db_path) as c:
            c.execute(
                "INSERT INTO devices (device_id, serial, manufacturer, model, "
                "android_version, api_level, is_lab) "
                "VALUES (?,?,?,?,?,?,1)",
                (device_id, serial, "Samsung", "SM-A145P", 15, 35))
        return device_id

    def test_capabilities_unknown_device(self):
        r = self.ctl.capabilities("NOPE")
        self.assertFalse(r["ok"])
        self.assertIn("error", r)

    def test_capabilities_registered_device(self):
        self._seed_device(self.ctl, "D-CTRL-1", "SERCTRL1")
        r = self.ctl.capabilities("D-CTRL-1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["device_id"], "D-CTRL-1")
        self.assertIsInstance(r["capability_profile"], dict)
        for k in ("model", "manufacturer", "android_version", "api_level"):
            self.assertIn(k, r)
        for feat, entry in sorted(r["capability_profile"].items()):
            self.assertIn("capability", entry)     # honest registry value
            self.assertIsInstance(entry["methods"], list)   # per-vendor methods

    def test_policy_preview_honest_not_attached(self):
        self._seed_device(self.ctl, "D-CTRL-2", "SERCTRL2")
        r = self.ctl.policy_preview("D-CTRL-2", "POL-FULL_LOCKDOWN")
        self.assertTrue(r["ok"])
        self.assertTrue(r["rows"])
        sources = {row["source"] for row in r["rows"]}
        self.assertEqual(sources, {"DEVICE_NOT_ATTACHED"})
        self.assertIn("desired", r["rows"][0])

    def test_policy_preview_unknown_policy(self):
        self._seed_device(self.ctl, "D-CTRL-3", "SERCTRL3")
        r = self.ctl.policy_preview("D-CTRL-3", "POL-ZZZ")
        self.assertFalse(r["ok"])

    def test_policy_preview_unregistered_device(self):
        r = self.ctl.policy_preview("NOPE", "POL-PHONE_ONLY")
        self.assertFalse(r["ok"])

    def test_reports_list_after_generate(self):
        self._seed_device(self.ctl, "D-CTRL-4", "SERCTRL4")
        g = self.ctl.generate_device_report("D-CTRL-4")
        self.assertTrue(g["ok"])
        lst = self.ctl.reports_list("D-CTRL-4")
        self.assertTrue(lst)
        self.assertEqual(set(lst[0].keys()), {"path", "size", "mtime"})
        self.assertTrue(os.path.exists(lst[0]["path"]))

    def test_detected_lists_attached_state_and_registration(self):
        # Plug-in auto-detection: attached devices get state + model, and
        # registered ones are flagged so the UI can offer one-click enroll.
        from unittest import mock
        self._seed_device(self.ctl, "D-DET-1", "SERDET1")
        with mock.patch("alp_manager.controller.attached_detailed",
                        return_value=[
                            {"serial": "SERDET1", "state": "device",
                             "model": "SM-A145P", "ready": True},
                            {"serial": "SERNEW1", "state": "device",
                             "model": "SM-J337P", "ready": True},
                            {"serial": "XOFF1", "state": "offline",
                             "model": "", "ready": False},
                            {"serial": "XUNA-1", "state": "unauthorized",
                             "model": "", "ready": False},
                        ]) as m:
            det = self.ctl.detected()
        m.assert_called_once()
        self.assertEqual(len(det), 4)
        by = {d["serial"]: d for d in det}
        self.assertTrue(by["SERDET1"]["registered"])
        self.assertTrue(by["SERDET1"]["ready"])
        self.assertFalse(by["SERNEW1"]["registered"])
        self.assertTrue(by["SERNEW1"]["ready"])
        self.assertFalse(by["XOFF1"]["ready"])
        self.assertFalse(by["XUNA-1"]["ready"])
        self.assertEqual(by["SERNEW1"]["model"], "SM-J337P")

    def test_detected_normalizes_model_underscore(self):
        # adb -l reports SM_J337P (underscore); the UI must show SM-J337P.
        from unittest import mock
        with mock.patch("alp_manager.controller.attached_detailed",
                        return_value=[
                            {"serial": "SERN2", "state": "device",
                             "model": "SM_J337P", "ready": True}]):
            det = self.ctl.detected()
        self.assertEqual(det[0]["model"], "SM-J337P")

    # ------------------------------------------------------------------
    # Pre-flight (#21): honest checklist before a policy apply
    # ------------------------------------------------------------------
    def test_preflight_unregistered_device(self):
        r = self.ctl.preflight("NOPE", "POL-PHONE_ONLY")
        self.assertTrue(r["ok"])
        self.assertEqual(r["verdict"], "FAIL")
        self.assertFalse(r["can_apply"])
        self.assertTrue(r["blocked"])
        self.assertIn("الجهاز مسجّل",
                      [c["name"] for c in r["checks"] if c["status"] == "FAIL"])

    def test_preflight_unknown_policy(self):
        self._seed_device(self.ctl, "D-PF-1", "SERPF1")
        r = self.ctl.preflight("D-PF-1", "POL-ZZZ")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertFalse(r["can_apply"])

    def test_preflight_not_attached_blocks(self):
        self._seed_device(self.ctl, "D-PF-2", "SERPF2")
        r = self.ctl.preflight("D-PF-2", "POL-PHONE_ONLY")
        self.assertEqual(r["verdict"], "FAIL")
        names = [c["name"] for c in r["checks"] if c["status"] == "FAIL"]
        self.assertIn("اتصال ADB وترخيص", names)

    def test_preflight_requires_credential_even_when_attached(self):
        from unittest import mock
        self._seed_device(self.ctl, "D-PF-3", "SERPF3")
        with mock.patch("alp_manager.controller.attached_detailed",
                        return_value=[{"serial": "SERPF3", "state": "device",
                                       "model": "SM-A145P", "ready": True}]):
            with mock.patch("alp_manager.controller.live_probe",
                            return_value={"observed": {"WIFI": "ON"},
                                          "restrictions": {}, "dpc": None}):
                r = self.ctl.preflight("D-PF-3", "POL-PHONE_ONLY")
        self.assertEqual(r["verdict"], "FAIL")
        names = [c["name"] for c in r["checks"] if c["status"] == "FAIL"]
        self.assertIn("بيان الاسترداد (عامل الحيازة)", names)

    def test_preflight_ok_when_attached_and_credentialed(self):
        from unittest import mock
        from backend.db import connect
        from backend.recovery_credentials import RecoveryVault
        self._seed_device(self.ctl, "D-PF-4", "SERPF4")
        with connect(self.ctl.db_path) as c:
            c.execute("UPDATE devices SET device_owner_state='ACTIVE' "
                      "WHERE device_id='D-PF-4'")
        RecoveryVault(self.db).generate_for("D-PF-4")
        with mock.patch("alp_manager.controller.attached_detailed",
                        return_value=[{"serial": "SERPF4", "state": "device",
                                       "model": "SM-A145P", "ready": True}]):
            with mock.patch("alp_manager.controller.live_probe",
                            return_value={"observed": {"WIFI": "ON", "ADB": "ON"},
                                          "restrictions": {}, "dpc": None}):
                r = self.ctl.preflight("D-PF-4", "POL-PHONE_ONLY")
        self.assertTrue(r["ok"])
        self.assertIn(r["verdict"], ("PASS", "CONDITIONAL"))
        self.assertTrue(r["can_apply"])
        self.assertFalse(any(c["status"] == "FAIL" for c in r["checks"]))

    def test_active_device_roundtrip(self):
        self._seed_device(self.ctl, "D-ACT-1", "SERACT1")
        self.assertFalse(self.ctl.active_device()["ok"])
        r = self.ctl.set_active_device(device_id="D-ACT-1")
        self.assertTrue(r["ok"])
        a = self.ctl.active_device()
        self.assertTrue(a["ok"])
        self.assertEqual(a["device_id"], "D-ACT-1")
        self.assertEqual(a["serial"], "SERACT1")
        self.assertNotIn("secret", json.dumps(r))

    def test_diagnostics_flat_shape(self):
        d = self.ctl.diagnostics()
        self.assertFalse(d["frozen_mode"])
        for k in ("db_ok", "db_tables", "adb_exe", "adb_configured",
                  "adb_devices", "bootstrap_needed", "signed_in", "audit_chain"):
            self.assertIn(k, d)


if __name__ == "__main__":
    unittest.main()