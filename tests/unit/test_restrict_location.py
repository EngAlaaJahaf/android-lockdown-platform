# -*- coding: utf-8 -*-
"""Regression: RESTRICT lanes for GPS/LOCATION must resolve mechanisms on API>=23
devices (mirror of MOBILE_DATA RESTRICT). These already resolve the policy without
exceptions on the AM-28-pilot device SM-J337P (J3 2018 family)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for _sub in ("backend", "policy-engine", "capability-engine",
             "verification-engine", "vendor-adapters", "compatibility"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

from compatibility import AndroidCompatibilityLayer


class RestrictedLocationMechanismTests(unittest.TestCase):
    def test_location_restrict_has_mechanism_at_api28(self):
        cl = AndroidCompatibilityLayer(28)
        self.assertIsNotNone(cl.mechanism("LOCATION", "RESTRICT"))
        self.assertIn("user_restriction_disable_location_services",
                      cl.mechanism("LOCATION", "RESTRICT"))

    def test_gps_restrict_has_mechanism_at_api28(self):
        cl = AndroidCompatibilityLayer(28)
        self.assertIsNotNone(cl.mechanism("GPS", "RESTRICT"))
        self.assertIn("user_restriction_disable_location_services",
                      cl.mechanism("GPS", "RESTRICT"))

    def test_below_floor_restrict_is_infeasible(self):
        cl = AndroidCompatibilityLayer(22)
        self.assertIsNone(cl.mechanism("LOCATION", "RESTRICT"))
        self.assertIsNone(cl.mechanism("GPS", "RESTRICT"))

    def test_location_restrict_infeasible_below_api21(self):
        cl = AndroidCompatibilityLayer(19)
        self.assertIsNone(cl.mechanism("LOCATION", "RESTRICT"))

    def test_restrict_mirrors_block_mechanism(self):
        # PARITY: RESTRICT must never present FEWER candidates than BLOCK for
        # location lanes at a given api level.
        for api in (23, 28, 35):
            cl = AndroidCompatibilityLayer(api)
            blk = cl.mechanism("LOCATION", "BLOCK") or []
            rst = cl.mechanism("LOCATION", "RESTRICT") or []
            self.assertEqual(blk, rst, f"parity at api {api}")


if __name__ == "__main__":
    unittest.main()