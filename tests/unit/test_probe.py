"""Tests for the live device probe (verification_engine.probe) honesty rules."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "verification-engine"))

from verification_engine.probe import (  # noqa: E402
    _parse_restrictions, _read_settings, _read_dpc_state, probe_live_device,
    RESTRICTION_FEATURES)


DUMP_MODERN = """Current admin:
    mDeviceOwner: package com.alp.agent
    Global User Restriction:
      no_config_tethering=true
    User restrictions:
      no_config_wifi=true
      no_debugging_features=true
      no_factory_reset: true
"""

DUMP_OLDER = """User restrictions for user 0:
  no_bluetooth: true
  no_install_unknown_sources: true
"""

DUMP_CLEAR = """Current admin:
    mDeviceOwner: package com.alp.agent
    User restrictions:
"""


class ParseRestrictions(unittest.TestCase):
    def test_modern_true_lines(self):
        active = _parse_restrictions(DUMP_MODERN)
        self.assertEqual(active.get("WIFI"), "no_config_wifi")
        self.assertEqual(active.get("ADB"), "no_debugging_features")
        self.assertEqual(active.get("TETHERING"), "no_config_tethering")
        self.assertEqual(active.get("FACTORY_RESET"), "no_factory_reset")

    def test_older_colon_true(self):
        active = _parse_restrictions(DUMP_OLDER)
        self.assertEqual(active.get("BLUETOOTH"), "no_bluetooth")
        self.assertEqual(active.get("APP_INSTALLATION"), "no_install_unknown_sources")

    def test_clean_dump_yields_nothing(self):
        self.assertEqual(_parse_restrictions(DUMP_CLEAR), {})

    def test_explicit_false_beats_token(self):
        dump = "User restrictions:\n  no_config_wifi=false\n"
        self.assertEqual(_parse_restrictions(dump), {})


class ProbeHonesty(unittest.TestCase):
    def setUp(self):
        self.saved = {}

    def _mock(self, responses: dict):
        import verification_engine.probe as probe
        orig_run = probe._run
        orig_read = probe._read_settings
        orig_dpc = probe._read_dpc_state

        def fake_run(serial, *args):
            key = args[0] if args else "?"
            return (0, responses.get(key, ""))

        def fake_settings(serial):
            return {"WIFI": "ON", "MOBILE_DATA": "OFF"}

        def fake_dpc(serial):
            return {"cmd_id": "ABC", "applied": ["WIFI"]}

        self.saved = {"run": orig_run, "settings": orig_read, "dpc": orig_dpc}
        probe._run = fake_run
        probe._read_settings = fake_settings
        probe._read_dpc_state = fake_dpc

    def tearDown(self):
        import verification_engine.probe as probe
        probe._run = self.saved["run"]
        probe._read_settings = self.saved["settings"]
        probe._read_dpc_state = self.saved["dpc"]

    def test_probe_bundle_source_and_evidence(self):
        self._mock({})
        import verification_engine.probe as probe
        bundle = probe.probe_live_device("emulator-5554")
        self.assertEqual(bundle["source"], "REAL_DEVICE")
        self.assertEqual(bundle["observed"].get("WIFI"), "ON")
        self.assertEqual(bundle["dpc"]["applied"], ["WIFI"])
        self.assertIn("identity", bundle)

    def test_restriction_overrides_stale_setting(self):
        self._mock({})
        import verification_engine.probe as probe
        with _patch_run_restricted():
            bundle = probe.probe_live_device("emulator-5554")
        # wifi_on setting said ON but a proven restriction must be reported RESTRICTED
        self.assertEqual(bundle["observed"].get("WIFI"), "RESTRICTED")
        self.assertIn("WIFI", bundle["restrictions"])


class _patch_run_restricted:
    """Canned dumpsys that proves no_config_wifi=true while settings say ON."""
    def __enter__(self):
        import verification_engine.probe as probe
        self.p = probe
        self.orig = probe._run

        def fake_run(serial, *args):
            if "dumpsys" in args:
                return (0, "User restrictions:\n  no_config_wifi=true\n")
            return (0, "")
        probe._run = fake_run

    def __exit__(self, *exc):
        self.p._run = self.orig
        return False


class RestrictedSatifiesOff(unittest.TestCase):
    def test_verification_accepts_restricted_as_off(self):
        from verification_engine import VerificationEngine
        eng = VerificationEngine(lambda dev: {"WIFI": "RESTRICTED"})
        res = eng.verify("APPLY_POLICY", "DEV-1",
                         expected={"WIFI": "OFF"}, evidence_id="EV-1-00000001",
                         source="REAL_DEVICE")
        self.assertEqual(res.result, "PASS")
        self.assertFalse(res.honest)
        self.assertTrue(res.evidence_id)

    def test_restricted_satisfies_restrict(self):
        from verification_engine import VerificationEngine
        eng = VerificationEngine(lambda dev: {"TETHERING": "RESTRICTED"})
        res = eng.verify("APPLY_POLICY", "DEV-1",
                         expected={"TETHERING": "RESTRICT"}, evidence_id="EV-1-00000002",
                         source="REAL_DEVICE")
        self.assertEqual(res.result, "PASS")


if __name__ == "__main__":
    unittest.main()