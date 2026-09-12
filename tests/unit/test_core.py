import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from capability_engine import CapabilityProfile, CapabilityState, FEATURES as CFEAT
from policy_engine import phone_only, corporate_default_v1, full_lockdown, FEATURES as PFEAT
from policy_engine.snapshot import resolve


class TestCapabilityModel(unittest.TestCase):
    def test_features_vocabulary_aligned(self):
        self.assertEqual(set(CFEAT), set(PFEAT))

    def test_default_state_is_unknown(self):
        p = CapabilityProfile()
        for f in CFEAT:
            self.assertEqual(p.states[f], CapabilityState.UNKNOWN.value)

    def test_no_silent_support(self):
        p = CapabilityProfile()
        p.states["WIFI"] = CapabilityState.SUPPORTED.value
        p.ensure_evidence("WIFI")          # no evidence -> downgraded to UNKNOWN
        self.assertEqual(p.states["WIFI"], CapabilityState.UNKNOWN.value)

    def test_evidence_keeps_support(self):
        p = CapabilityProfile()
        p.states["WIFI"] = CapabilityState.SUPPORTED.value
        p.evidence["WIFI"] = ["EV-LAB-0001"]
        p.ensure_evidence("WIFI")
        self.assertEqual(p.states["WIFI"], CapabilityState.SUPPORTED.value)

    def test_roundtrip_json(self):
        p = CapabilityProfile(device_id="DEV-1", android_version=14, api_level=34)
        q = CapabilityProfile.from_json(p.to_json())
        self.assertEqual(q.device_id, "DEV-1")
        self.assertEqual(q.android_version, 14)


class TestPolicyModel(unittest.TestCase):
    def test_only_valid_features_tracked(self):
        VALID = {"BLOCK", "ALLOW", "RESTRICT", "WARN_AUDIT"}
        for fn in (phone_only, corporate_default_v1, full_lockdown):
            pol = fn()
            fm = pol.feature_map()
            for f in fm:
                self.assertIn(f, PFEAT, f"{pol.policy_id} unknown feature {f}")
            for f in PFEAT:
                self.assertIn(pol.desired(f), VALID)

    def test_phone_only_governs_wifi_sharply(self):
        pol = phone_only()
        self.assertEqual(pol.desired("WIFI"), "BLOCK")

    def test_governed_features_surface_as_not_feasible(self):
        pol = full_lockdown()
        self.assertEqual(pol.desired("REFLAH_FIRMWARE"), "WARN_AUDIT")
        self.assertIn("NOT_FEASIBLE", pol.feature_map()["REFLAH_FIRMWARE"].fallback)

    def test_phone_only_allows_telephony(self):
        pol = phone_only()
        self.assertEqual(pol.desired("CALLS"), "ALLOW")
        self.assertEqual(pol.desired("SMS"), "ALLOW")
        self.assertEqual(pol.desired("WIFI"), "BLOCK")

    def test_governed_features_not_enforceable(self):
        pol = full_lockdown()
        self.assertEqual(pol.desired("REFLAH_FIRMWARE"), "WARN_AUDIT")

    def test_unknown_feature_rejected(self):
        with self.assertRaises(ValueError):
            full_lockdown().add("NOT_A_FEATURE", "BLOCK")


class TestSnapshotResolution(unittest.TestCase):
    def _compat(self, api):
        sys.path.insert(0, os.path.join(ROOT, "compatibility"))
        from compatibility import AndroidCompatibilityLayer
        return AndroidCompatibilityLayer(api)

    def test_wifi_block_api_28(self):
        from compatibility import AndroidCompatibilityLayer
        layer = AndroidCompatibilityLayer(28)
        cap = CapabilityProfile(device_id="D", android_version=9, api_level=28)
        snap = resolve(phone_only(), cap, layer)
        row = snap.feature_map()["WIFI"]
        self.assertFalse(row.exception)
        self.assertIn("user_restriction_disable_wifi", row.method)

    def test_wifi_block_api_24_partial(self):
        from compatibility import AndroidCompatibilityLayer
        layer = AndroidCompatibilityLayer(24)
        cap = CapabilityProfile(device_id="D", android_version=7, api_level=24)
        snap = resolve(phone_only(), cap, layer)
        row = snap.feature_map()["WIFI"]
        # below API 28 there is no user_restriction_disable_wifi; lockdown global still partial
        self.assertTrue("user_restriction_disable_wifi" not in row.method)

    def test_governed_features_tracked_with_fallback(self):
        from compatibility import AndroidCompatibilityLayer
        layer = AndroidCompatibilityLayer(35)
        cap = CapabilityProfile(device_id="D", android_version=15, api_level=35)
        snap = resolve(full_lockdown(), cap, layer)
        fm = snap.feature_map()
        self.assertIn("REFLAH_FIRMWARE", fm)
        self.assertIn("NOT_FEASIBLE", fm["REFLAH_FIRMWARE"].fallback)

    def test_not_feasible_capability_becomes_exception(self):
        from compatibility import AndroidCompatibilityLayer
        from capability_engine import CapabilityState
        layer = AndroidCompatibilityLayer(35)
        cap = CapabilityProfile(device_id="D", android_version=15, api_level=35)
        cap.states["REFLAH_FIRMWARE"] = CapabilityState.NOT_FEASIBLE.value
        snap = resolve(phone_only(), cap, layer)
        self.assertIn("REFLAH_FIRMWARE", snap.exceptions)

    def test_unavailable_block_mechanism_is_exception(self):
        from compatibility import AndroidCompatibilityLayer
        layer = AndroidCompatibilityLayer(22)   # below API 23: no wifi control path
        cap = CapabilityProfile(device_id="D", android_version=6, api_level=22)
        snap = resolve(phone_only(), cap, layer)
        self.assertIn("WIFI", snap.exceptions)

    def test_wifi_locked_down_via_global_on_api_23_28(self):
        from compatibility import AndroidCompatibilityLayer
        layer = AndroidCompatibilityLayer(23)
        cap = CapabilityProfile(device_id="D", android_version=8, api_level=23)
        snap = resolve(phone_only(), cap, layer)
        self.assertIn("wifi_lockdown_global_setting", snap.feature_map()["WIFI"].method)


if __name__ == "__main__":
    unittest.main()