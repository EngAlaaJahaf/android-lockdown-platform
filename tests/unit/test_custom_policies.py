# -*- coding: utf-8 -*-
"""Tests for console-created custom policies and the compliance snapshot table."""
import os
import sys
import unittest

# Mirror the repo-wide test bootstrap (each test module wires the engine dirs).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for _sub in ("backend", "policy-engine", "capability-engine",
             "verification-engine", "vendor-adapters", "compatibility"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

from backend.db import connect  # noqa: E402
from backend import workflows   # noqa: E402


class _FakeChannel:
    def send(self, envelope):
        return {"ok": True, "error": None}


class CustomPolicyTests(unittest.TestCase):
    def test_create_persists_and_resolves(self):
        p = workflows.create_custom_policy("تقييد بعثة", "PHONE_ONLY",
                                           ["WIFI", "CAMERA", "ADB"],
                                           risk="HIGH", created_by="test")
        self.assertTrue(p.policy_id.startswith("POL-CUST-"))
        with connect() as c:
            row = c.execute("SELECT * FROM policies WHERE policy_id=?",
                            (p.policy_id,)).fetchone()
        self.assertIsNotNone(row)
        resolved = workflows.resolve_policy(p.policy_id)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.policy_id, p.policy_id)
        self.assertEqual(resolved.desired("WIFI"), "BLOCK")
        self.assertEqual(resolved.desired("CAMERA"), "BLOCK")
        # non-selected features default ALLOW (Policy.desired default)
        self.assertEqual(resolved.desired("VPN"), "ALLOW")

    def test_create_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            workflows.create_custom_policy("x", "PHONE_ONLY", ["NOT_A_FEATURE"])
        with self.assertRaises(ValueError):
            workflows.create_custom_policy("x", "PHONE_ONLY", [])
        with self.assertRaises(ValueError):
            workflows.create_custom_policy("x", "BOGUS_CATEGORY", ["WIFI"])

    def test_unknown_custom_policy_resolves_none(self):
        self.assertIsNone(workflows.resolve_policy("POL-CUST-DOES-NOT-EXIST"))


class ComplianceSnapshotTests(unittest.TestCase):
    def test_compliance_row_written_on_apply(self):
        dev_id = "D-COMP-WRITE"
        with connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO devices (device_id, serial, manufacturer, model, "
                "android_version, api_level, is_lab) VALUES (?,?,?,?,?,?,1)",
                (dev_id, "SERCOMPW", "Samsung", "SM-A145P", 15, 35))
        chan = _FakeChannel()
        res = workflows.run_director_apply(
            dev_id, "POL-FULL_LOCKDOWN", op_role="FLEET_ADMIN",
            mfa_ok=True, serial="SERCOMPW", real=False, signing_key="k",
            channel_send=chan.send)
        self.assertEqual(res["stage"], "COMPLETE")
        with connect() as c:
            rows = c.execute(
                "SELECT c.result, c.details FROM compliance c "
                "JOIN devices d ON d.id = c.device_id WHERE d.device_id=?",
                (dev_id,)).fetchall()
        self.assertGreaterEqual(len(rows), 1,
                                "compliance snapshot must be persisted")
        self.assertIsNotNone(rows[0]["details"], "details diff must be stored")


class AppsInventoryTests(unittest.TestCase):
    def test_apps_missing_serial_is_honest(self):
        inv = workflows.apps("NO-SUCH-SERIAL-12345")
        self.assertEqual(inv["count"], 0)
        self.assertEqual(inv["third_party"], [])
        self.assertEqual(inv["system"], [])
        self.assertEqual(inv["serial"], "NO-SUCH-SERIAL-12345")


if __name__ == "__main__":
    unittest.main()