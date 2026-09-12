"""Tests for the Vendor/Version Registry (device-agnostic classification)."""
from __future__ import annotations

import sys
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "vendor-adapters"))

from vendor_adapters.registry import classify, select_adapter  # noqa: E402
from vendor_adapters import SamsungAdapter, GenericAdapter  # noqa: E402


class RegistryClassify(unittest.TestCase):
    def test_samsung_j337p(self):
        dc = classify(manufacturer="samsung", model="SM-J337P",
                      android_version=9, api_level=28)
        self.assertEqual(dc.vendor_id, "samsung")
        self.assertTrue(dc.known_family)
        self.assertIn("J3", dc.family)
        self.assertEqual(dc.reference_tier, "LAB_REFERENCE")
        self.assertEqual(dc.android_version, 9)
        self.assertEqual(dc.api_level, 28)
        self.assertIn("wifi_block_restriction", dc.version_floors)

    def test_samsung_j320fn_floor(self):
        dc = classify("samsung", "SM-J320FN", 7, 24)
        self.assertEqual(dc.vendor_id, "samsung")
        self.assertIn("J3", dc.family)
        self.assertEqual(dc.reference_tier, "LAB_REFERENCE")

    def test_aosp_generic_model(self):
        dc = classify("google", "sdk_gphone64_x86_64", 16, 36)
        self.assertEqual(dc.vendor_id, "generic")
        self.assertEqual(dc.family, "aosp")
        self.assertTrue(dc.known_family)

    def test_unknown_vendor_falls_back_generic(self):
        dc = classify("acme", "MODEL-X", 9, 28)
        self.assertEqual(dc.vendor_id, "generic")
        self.assertEqual(dc.reference_tier, "UNKNOWN")

    def test_motorola_known_tier(self):
        dc = classify("motorola", "Moto G52", 12, 31)
        self.assertEqual(dc.vendor_id, "motorola")
        self.assertEqual(dc.reference_tier, "KNOWN_LIMIT")


class RegistryAdapterSelection(unittest.TestCase):
    def test_samsung_selects_samsung_adapter(self):
        dc = classify("samsung", "SM-J337P", 9, 28)
        ada = select_adapter(dc)
        self.assertIsInstance(ada, SamsungAdapter)
        self.assertIn("GATED", ada.status)      # honest: Knox not proven

    def test_samsung_knox_present_from_evidence(self):
        dc = classify("samsung", "SM-J337P", 9, 28)
        ada = select_adapter(dc, knox_sdk_present=True)
        self.assertIn("READY", ada.status)

    def test_generic_selects_generic(self):
        dc = classify("google", "sdk_gphone64_x86_64", 16, 36)
        ada = select_adapter(dc)
        self.assertIsInstance(ada, GenericAdapter)


if __name__ == "__main__":
    unittest.main()