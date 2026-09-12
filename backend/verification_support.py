"""Tiny compliance mapping from a VerificationResult (§36 verdicts)."""
from __future__ import annotations


def compliance_from_verification(verdict) -> str:
    """PASS→COMPLIANT, FAIL→NON_COMPLIANT, PARTIAL→PARTIAL, UNKNOWN→UNKNOWN."""
    return {
        "PASS": "COMPLIANT",
        "FAIL": "NON_COMPLIANT",
        "PARTIAL": "PARTIAL",
        "UNKNOWN": "UNKNOWN",
    }.get(getattr(verdict, "result", "UNKNOWN"), "UNKNOWN")