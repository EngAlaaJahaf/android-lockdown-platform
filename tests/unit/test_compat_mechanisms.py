# -*- coding: utf-8 -*-
"""Compatibility mechanisms for newly-enforceable lanes.

The agent enforces these through stock Device Owner APIs, so the backend
must declare a mechanism instead of reporting "no enforcement mechanism":
  * GOOGLE_MAPS  -> package hiding (setApplicationHidden)
  * BLUETOOTH_TRANSFER -> DISALLOW_BLUETOOTH_SHARING user restriction
(BLUETOOTH_PAN and OS_UPGRADE already had declared mechanisms; the agent
just learned to actually carry them out.)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "compatibility"))
sys.path.insert(0, os.path.join(ROOT, "policy-engine"))
sys.path.insert(0, os.path.join(ROOT, "capability-engine"))

from compatibility import AndroidCompatibilityLayer  # noqa: E402


class NewMechanismsTests(unittest.TestCase):
    def test_maps_and_transfer_have_mechanisms_on_api_35(self):
        layer = AndroidCompatibilityLayer(35)
        maps = layer.mechanism("GOOGLE_MAPS", "BLOCK")
        self.assertTrue(maps, "GOOGLE_MAPS/BLOCK must resolve a mechanism")
        self.assertIn("package_hide_maps", maps)
        # RESTRICT inherits the BLOCK mechanism.
        self.assertTrue(layer.mechanism("GOOGLE_MAPS", "RESTRICT"))
        transfer = layer.mechanism("BLUETOOTH_TRANSFER", "BLOCK")
        self.assertTrue(transfer, "BLUETOOTH_TRANSFER/BLOCK must resolve")
        self.assertIn("user_restriction_disable_bluetooth_sharing", transfer)
        self.assertTrue(layer.mechanism("BLUETOOTH_TRANSFER", "RESTRICT"))

    def test_google_apps_switch_has_mechanism(self):
        from policy_engine import FEATURES as POLICY_FEATURES
        from capability_engine import FEATURES as CAP_FEATURES
        for lane in ("GOOGLE_APPS", "GMAIL_APP", "YOUTUBE_APP", "CHROME_APP",
                     "PLAYSTORE_APP"):
            self.assertIn(lane, POLICY_FEATURES, lane + " must be selectable")
            self.assertIn(lane, CAP_FEATURES, lane + " must share vocabulary")
            layer = AndroidCompatibilityLayer(35)
            mechs = layer.mechanism(lane, "BLOCK")
            self.assertTrue(mechs, lane + "/BLOCK must resolve a mechanism")
            self.assertTrue(layer.mechanism(lane, "RESTRICT"),
                            lane + "/RESTRICT must inherit it")

    def test_nfc_and_beam_have_stock_restrictions_on_api_35(self):
        # Correction of the earlier "impossible" verdict: android-35 exposes
        # DISALLOW_NEAR_FIELD_COMMUNICATION_RADIO and DISALLOW_OUTGOING_BEAM
        # (verified via javap), and the agent enforces them. S_BEAM rides on
        # the NFC radio, so it shares the radio mechanism.
        layer = AndroidCompatibilityLayer(35)
        nfc = layer.mechanism("NFC", "BLOCK")
        self.assertIn("user_restriction_disable_nfc_radio", nfc or [])
        beam = layer.mechanism("ANDROID_BEAM", "BLOCK")
        self.assertIn("user_restriction_disable_outgoing_beam", beam or [])
        sbeam = layer.mechanism("S_BEAM", "BLOCK")
        self.assertIn("user_restriction_disable_nfc_radio", sbeam or [])
        for lane in ("NFC", "ANDROID_BEAM", "S_BEAM"):
            self.assertTrue(layer.mechanism(lane, "RESTRICT"))

    def test_nfc_radio_is_new_enough_to_gate_old_devices(self):
        # javap across platforms/ proves DISALLOW_NEAR_FIELD_COMMUNICATION_RADIO
        # is absent on 27-34: on an API-22 handset the backend must report NFC
        # and S_BEAM as exceptions instead of promising enforcement.
        old = AndroidCompatibilityLayer(22)
        self.assertIsNone(old.mechanism("NFC", "BLOCK"))
        self.assertIsNone(old.mechanism("S_BEAM", "BLOCK"))
        # Beam's send block is old (present since at least API 27).
        self.assertTrue(old.mechanism("ANDROID_BEAM", "BLOCK"))

    def test_truly_impossible_lanes_stay_mechanismless(self):
        layer = AndroidCompatibilityLayer(35)
        for feature in ("BLUETOOTH_PAIRING", "BLUETOOTH_DISCOVERY",
                        "BLUETOOTH_CALL", "FIRMWARE_RECOVERY",
                        "BROWSER_AUTOFILL", "BROWSER_FRAUD_WARN"):
            self.assertIsNone(layer.mechanism(feature, "BLOCK"),
                              "%s must stay an honest exception" % feature)


if __name__ == "__main__":
    unittest.main()
