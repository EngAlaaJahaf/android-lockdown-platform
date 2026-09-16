"""ComplianceEngine — expected policy vs actual device state → verdict.

Verdicts: COMPLIANT | NON_COMPLIANT | PARTIAL | UNKNOWN (per EXECUTE §36).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ComplianceVerdict:
    device_id: str
    policy_id: str
    result: str = "UNKNOWN"
    details: dict = field(default_factory=dict)   # feature -> (expected, actual, ok)


def evaluate(device_id: str, policy_id: str,
             expected: dict, actual: dict) -> ComplianceVerdict:
    """expected/actual: feature -> value maps.

    Semantics (honest reporting, §36): one violated constraint makes the device
    NON_COMPLIANT; unobservable lanes never fabricate compliance (UNKNOWN/PARTIAL).
    """
    v = ComplianceVerdict(device_id, policy_id)
    RESTRICT_SATISFIES = {"OFF", "RESTRICT", "BLOCK"}
    diff = {}
    for feat, want in expected.items():
        got = actual.get(feat)
        ok = got is not None and (
            got == want
            or (got == "RESTRICTED" and want in RESTRICT_SATISFIES))
        diff[feat] = (want, got, ok)
    v.details = diff

    total = len(diff)
    if total == 0:
        v.result = "UNKNOWN"
        return v
    violations = [f for f, (_, got, ok) in diff.items() if got is not None and not ok]
    missing = [f for f, (_, got, _) in diff.items() if got is None]
    if violations:
        v.result = "NON_COMPLIANT"
    elif missing:
        v.result = "UNKNOWN" if len(missing) == total else "PARTIAL"
    else:
        v.result = "COMPLIANT"
    return v