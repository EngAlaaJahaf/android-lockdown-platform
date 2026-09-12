"""Bridges the VerificationEngine observations into the ComplianceEngine verdict.

Avoids a hard import chain between backend and verification-engine packages.
"""
from __future__ import annotations

import os
import sys


def compliance_forge(device_id: str, policy_id: str,
                     expected: dict, observations: dict) -> str:
    """Reuses system-installed verification-engine compliance evaluator (fallback)."""
    pkg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "verification-engine")
    if pkg not in sys.path:
        sys.path.insert(0, pkg)
    from verification_engine.compliance import evaluate
    return evaluate(device_id, policy_id, expected, observations).result