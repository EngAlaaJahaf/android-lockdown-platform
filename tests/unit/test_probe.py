"""Tests for the live device probe (verification_engine.probe) honesty rules."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "verification-engine"))

from verification_engine.probe import (  # noqa: E402
    _parse_restrictions, _read_settings, _read_dpc_state, probe_live_device,
    _parse_camera_disabled, RESTRICTION_FEATURES)


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

DUMP_API30 = """Current Device Policy Manager state:
  Device Owner:
    admin=ComponentInfo{com.alp.agent/com.alp.agent.AlpDeviceAdminReceiver}
    package=com.alp.agent
  Enabled Device Admins (User 0, provisioningState: 3):
    com.alp.agent/.AlpDeviceAdminReceiver:
      UserRestrictionPolicyKey userRestriction_no_config_wifi
      UserRestrictionPolicyKey userRestriction_no_bluetooth
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

    def test_api30_policy_key_presence(self):
        active = _parse_restrictions(DUMP_API30)
        self.assertEqual(active.get("WIFI"), "no_config_wifi")
        self.assertEqual(active.get("BLUETOOTH"), "no_bluetooth")
        self.assertNotIn("TETHERING", active)

    def test_catalog_tokens(self):
        dump = """User restrictions:
  no_mock_location=true
  no_uninstall_apps=true
  no_clear_app_data=true
"""
        active = _parse_restrictions(dump)
        self.assertEqual(active.get("MOCK_LOCATIONS"), "no_mock_location")
        self.assertEqual(active.get("UNINSTALL_APPS"), "no_uninstall_apps")
        self.assertEqual(active.get("CLEAR_APP_DATA"), "no_clear_app_data")

    def test_token_extra_reports_shared_lanes(self):
        dump = """User restrictions:
  no_config_wifi=true
  no_config_tethering=true
"""
        active = _parse_restrictions(dump)
        self.assertEqual(active.get("WIFI"), "no_config_wifi")
        self.assertEqual(active.get("WIFI_CONFIG"), "no_config_wifi")
        self.assertEqual(active.get("TETHERING"), "no_config_tethering")
        self.assertEqual(active.get("BLUETOOTH_TETHERING"), "no_config_tethering")

    def test_explicit_false_beats_token(self):
        dump = "User restrictions:\n  no_config_wifi=false\n"
        self.assertEqual(_parse_restrictions(dump), {})

    def test_camera_disabled_true(self):
        dump = """Current admin:
    mDeviceOwner: package com.alp.agent
  mCameraDisabled: true
"""
        self.assertTrue(_parse_camera_disabled(dump))

    def test_camera_disabled_only_literal_true(self):
        self.assertFalse(_parse_camera_disabled(
            "Current admin:\n  mDeviceOwner: package com.alp.agent\n  mCameraDisabled: false\n"))
        self.assertFalse(_parse_camera_disabled("Camera settings: some.dump\n  mCameraController: present\n"))


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


class ReadSettingsLanes(unittest.TestCase):
    """Settings-backed catalog lanes: RESTRICTED when the value equals the
    enforcement target, ON otherwise, unreadable skipped."""

    def _patch(self, values: dict):
        import verification_engine.probe as probe
        orig = probe._run

        def fake_run(serial, *args):
            key = args[-1] if len(args) >= 4 else ""
            return (0, values.get(key, ""))
        probe._run = fake_run
        self._orig = orig
        self._probe = probe

    def tearDown(self):
        self._probe._run = self._orig

    def test_target_value_reports_restricted(self):
        self._patch({"nfc_on": "0", "data_saver": "1", "screen_off_timeout": "30000"})
        s = self._probe._read_settings("LT123")
        self.assertEqual(s.get("NFC"), "RESTRICTED")
        self.assertEqual(s.get("DATA_SAVER"), "RESTRICTED")
        self.assertEqual(s.get("SCREEN_TIMEOUT"), "RESTRICTED")

    def test_open_value_reports_on(self):
        self._patch({"nfc_on": "1", "data_saver": "0", "auto_time_zone": "1"})
        s = self._probe._read_settings("LT123")
        self.assertEqual(s.get("NFC"), "ON")
        self.assertEqual(s.get("DATA_SAVER"), "ON")
        self.assertEqual(s.get("SET_TIMEZONE"), "ON")
        self.assertIsNone(s.get("PLAY_PROTECT"))  # unreadable -> skipped, honest

    def test_roaming_family_shared_key(self):
        self._patch({"data_roaming": "0"})
        s = self._probe._read_settings("LT123")
        for lane in ("ROAMING_DATA", "ROAMING_SYNC", "ROAMING_PUSH", "ROAMING_CALL"):
            self.assertEqual(s.get(lane), "RESTRICTED")


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