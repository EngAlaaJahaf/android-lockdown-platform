"""Tests for the desktop Controller (headless, no GUI)."""
from __future__ import annotations

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

    def test_apply_requires_session(self):
        from alp_manager.controller import Controller
        fresh = Controller(db_path=self.db, session_file=os.path.join(self.tmp, "s2.json"))
        r = fresh.apply("DEV-1", "PHONE_ONLY", mfa="123456")
        self.assertFalse(r["ok"])
        self.assertIn("no session", r["error"])

    def test_policies_synced(self):
        pols = self.ctl.policies()
        ids = {p["policy_id"] for p in pols}
        self.assertIn("POL-PHONE_ONLY", ids)
        self.assertIn("POL-FULL_LOCKDOWN", ids)

    def test_recover_r3_refused_regardless(self):
        r = self.ctl.recover("DEV-1", "R3_LAB_FLASH", mfa="123456", skip_approval=True)
        self.assertFalse(r["ok"])
        self.assertIn("no session", r["error"])

    def test_recover_r1_needs_second_approver(self):
        self.ctl.bootstrap("tester", "pass")
        from backend import auth
        from backend.db import connect
        with connect(self.db) as c:
            row = c.execute("SELECT id FROM administrators LIMIT 1").fetchone()
            token = auth.create_session(row["id"])
            self.ctl._save_session({"token": token})
        r = self.ctl.recover("DEV-1", "R1_RESTORE_POINT", mfa="000000",
                             skip_approval=False, reason="test")
        self.assertFalse(r["ok"])
        self.assertIn("MFA", r["error"])

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

    def test_diagnostics_flat_shape(self):
        d = self.ctl.diagnostics()
        self.assertFalse(d["frozen_mode"])
        for k in ("db_ok", "db_tables", "adb_exe", "adb_configured",
                  "adb_devices", "bootstrap_needed", "signed_in", "audit_chain"):
            self.assertIn(k, d)


if __name__ == "__main__":
    unittest.main()