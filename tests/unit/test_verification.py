"""VerificationEngine + ComplianceEngine tests — evidence gate is the core law."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for sub in ("verification-engine", "policy-engine", "capability-engine",
            "compatibility", "backend"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from verification_engine import VerificationEngine
from verification_engine.compliance import evaluate


class TestVerificationEngine(unittest.TestCase):
    def test_pass_impossible_without_evidence(self):
        eng = VerificationEngine(lambda dev: {"WIFI": "OFF"})
        r = eng.verify("LOCK", "D-1", {"WIFI": "OFF"}, evidence_id="")
        self.assertEqual(r.result, "UNKNOWN")
        self.assertFalse(r.is_pass)

    def test_simulated_source_is_never_pass(self):
        eng = VerificationEngine(lambda dev: {"WIFI": "OFF"})
        r = eng.verify("LOCK", "D-1", {"WIFI": "OFF"},
                       evidence_id="EV-LAB-0001", source="SIMULATED")
        self.assertEqual(r.result, "PASS", "value matches")
        self.assertFalse(r.is_pass, "honest=True forbids PASS verdict on sim")

    def test_real_device_with_evidence_can_pass(self):
        eng = VerificationEngine(lambda dev: {"WIFI": "OFF", "ADB": "OFF"})
        r = eng.verify("LOCK", "D-1", {"WIFI": "OFF", "ADB": "OFF"},
                       evidence_id="EV-LAB-0002", source="REAL_DEVICE")
        self.assertEqual(r.result, "PASS")
        self.assertTrue(r.is_pass)

    def test_mismatch_is_fail(self):
        eng = VerificationEngine(lambda dev: {"WIFI": "ON"})
        r = eng.verify("LOCK", "D-1", {"WIFI": "OFF"},
                       evidence_id="EV-1", source="REAL_DEVICE")
        self.assertEqual(r.result, "FAIL")

    def test_unknown_observation_is_not_fail(self):
        eng = VerificationEngine(lambda dev: {})
        r = eng.verify("LOCK", "D-1", {"WIFI": "OFF"},
                       evidence_id="EV-1", source="REAL_DEVICE")
        self.assertEqual(r.result, "UNKNOWN")

    def test_restricted_observation_satisfies_block_intent(self):
        """BLOCK/RESTRICT policy intents are proven by an ACTIVE restriction
        (RESTRICTED) even before the radio re-reports OFF after reboot."""
        eng = VerificationEngine(
            lambda dev: {"WIFI": "RESTRICTED", "ADB": "RESTRICTED"})
        r = eng.verify("LOCK", "D-1", {"WIFI": "BLOCK", "ADB": "BLOCK"},
                       evidence_id="EV-LAB-0003", source="REAL_DEVICE")
        self.assertEqual(r.result, "PASS")
        self.assertTrue(r.is_pass)


class TestComplianceEngine(unittest.TestCase):
    def test_full_match_compliant(self):
        v = evaluate("D-1", "POL-PHONE_ONLY",
                     {"WIFI": "OFF", "ADB": "OFF"}, {"WIFI": "OFF", "ADB": "OFF"})
        self.assertEqual(v.result, "COMPLIANT")

    def test_any_mismatch_makes_device_non_compliant(self):
        v = evaluate("D-1", "POL-PHONE_ONLY",
                     {"WIFI": "OFF", "ADB": "OFF"}, {"WIFI": "ON", "ADB": "OFF"})
        self.assertEqual(v.result, "NON_COMPLIANT")

    def test_missing_observation_is_unknown(self):
        v = evaluate("D-1", "POL-PHONE_ONLY", {"WIFI": "OFF"}, {})
        self.assertEqual(v.result, "UNKNOWN")
        self.assertFalse(v.details["WIFI"][2])

    def test_partial_verdict_only_with_mixed_observability(self):
        v = evaluate("D-1", "POL-PHONE_ONLY",
                     {"WIFI": "OFF", "ADB": "OFF", "CAMERA": "OFF"},
                     {"WIFI": "OFF"})           # no violation; two lanes unobservable
        self.assertEqual(v.result, "PARTIAL")

    def test_violation_beats_unknowns(self):
        v = evaluate("D-1", "POL-PHONE_ONLY",
                     {"WIFI": "OFF", "ADB": "OFF"},
                     {"WIFI": "ON", "ADB": "UNKNOWN"})
        self.assertEqual(v.result, "NON_COMPLIANT")


if __name__ == "__main__":
    unittest.main()