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

    def test_catalog_policy_honest_tier_split(self):
        out = workflows.create_policy_from_catalog(
            ["NFC", "SCREEN_TIMEOUT", "S_VOICE", "NOT_A_CATALOG_FEATURE"],
            name="من الكتالوج", created_by="test")
        p = out["policy"]
        self.assertTrue(p.policy_id.startswith("POL-CUST-"))
        self.assertEqual(set(out["applied"]), {"NFC", "SCREEN_TIMEOUT"})
        self.assertIn("S_VOICE", out["excluded"], "VENDOR_DEPENDENT must be excluded")
        self.assertIn("NOT_A_CATALOG_FEATURE", out["excluded"],
                      "out-of-vocabulary must be excluded, not silently dropped")
        with connect() as c:
            row = c.execute("SELECT * FROM policies WHERE policy_id=?",
                            (p.policy_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["category"], "CORPORATE_DEFAULT")

    def test_catalog_policy_rejects_only_non_enforceable(self):
        with self.assertRaises(ValueError):
            workflows.create_policy_from_catalog(["S_VOICE"], created_by="test")
        with self.assertRaises(ValueError):
            workflows.create_policy_from_catalog([], created_by="test")


class CatalogVocabularyTests(unittest.TestCase):
    """The catalog must never emit a lane the engines cannot resolve."""

    def test_every_catalog_lane_is_resolvable(self):
        from backend.restrictions import feature_union, MASTER_CASCADE
        from policy_engine import FEATURES
        from capability_engine import FEATURES as CAP_FEATURES

        unresolvable = sorted(
            set(feature_union()) - set(FEATURES) - set(MASTER_CASCADE))
        self.assertEqual(
            unresolvable, [],
            "catalog lanes with neither a FEATURES slot nor a cascade rule "
            "would be silently dropped by policy_from_catalog: %s" % unresolvable)

    def test_engines_share_one_vocabulary(self):
        from policy_engine import FEATURES
        from capability_engine import FEATURES as CAP_FEATURES
        self.assertEqual(
            set(FEATURES), set(CAP_FEATURES),
            "policy_engine and capability_engine must expose the same lanes, "
            "otherwise resolve() silently defaults to UNKNOWN")

    def test_cascade_targets_exist_in_catalog_and_vocabulary(self):
        from backend.restrictions import MASTER_CASCADE, by_feature
        from policy_engine import FEATURES
        rows = by_feature()
        for master, children in MASTER_CASCADE.items():
            self.assertTrue(children, "cascade target list must not be empty")
            for child in children:
                self.assertIn(child, FEATURES,
                              "%s cascades to %s, which has no vocabulary slot"
                              % (master, child))
                self.assertIn(child, rows,
                              "%s cascades to %s, which has no catalog row"
                              % (master, child))

    def test_master_selection_expands_instead_of_being_dropped(self):
        from backend.restrictions import policy_from_catalog, MASTER_CASCADE
        for master, children in MASTER_CASCADE.items():
            pol, applied, excluded = policy_from_catalog([master])
            emitted = {r.feature for r in pol.requirements}
            self.assertNotIn(
                master, emitted,
                "%s is a container row with no mechanism; it must never be "
                "emitted as a requirement" % master)
            expected = {c for c in children
                        if c not in excluded}
            self.assertEqual(
                expected & emitted, expected,
                "%s must expand into its enforceable lanes, got applied=%s "
                "excluded=%s" % (master, applied, excluded))

    def test_cascade_does_not_duplicate_requirements(self):
        from backend.restrictions import policy_from_catalog
        pol, _, _ = policy_from_catalog(
            ["SMS_MASTER", "USB_MASTER", "SD_CARD", "SMS", "CAMERA"])
        features = [r.feature for r in pol.requirements]
        self.assertEqual(
            len(features), len(set(features)),
            "expanding a header alongside its own leaf must not duplicate rows")


class ComplianceSnapshotTests(unittest.TestCase):
    def test_compliance_row_written_on_apply(self):
        dev_id = "D-COMP-WRITE"
        with connect() as c:
            c.execute(
                "INSERT INTO devices (device_id, serial, manufacturer, model, "
                "android_version, api_level, is_lab) VALUES (?,?,?,?,?,?,1) "
                "ON CONFLICT(device_id) DO UPDATE SET serial=excluded.serial, "
                "manufacturer=excluded.manufacturer, model=excluded.model, "
                "android_version=excluded.android_version, api_level=excluded.api_level, "
                "is_lab=excluded.is_lab",
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