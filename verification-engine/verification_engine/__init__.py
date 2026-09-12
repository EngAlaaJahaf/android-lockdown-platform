"""VerificationEngine — command → execute → observe → query actual → verify → evidence.

Per EXECUTE §35: a Command SENT is NOT success. Every action must be re-checked
against the ACTUAL device state and produce evidence with PASS/FAIL/PARTIAL/UNKNOWN.

honest=True tells the engine the observation source is not a real device yet —
callers must use it explicitly, never silently.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Observation:
    actual: dict = field(default_factory=dict)     # feature -> observed state
    source: str = "UNKNOWN"                        # REAL_DEVICE | AGENT_REPORT | SIMULATED


@dataclass
class VerificationResult:
    command: str
    device_id: str
    result: str = "UNKNOWN"                        # PASS|FAIL|PARTIAL|UNKNOWN
    observations: dict = field(default_factory=dict)
    evidence_id: str = ""
    honest: bool = True                            # True => not verified on real device
    timestamp: str = ""

    @property
    def is_pass(self) -> bool:
        return self.result == "PASS" and not self.honest

    def to_json(self) -> str:
        import json
        return json.dumps({
            "command": self.command, "device_id": self.device_id,
            "result": self.result, "observations": self.observations,
            "evidence_id": self.evidence_id, "honest": self.honest,
            "timestamp": self.timestamp}, indent=2)


class VerificationEngine:
    def __init__(self, observe: Optional[Callable[[str], dict]] = None):
        self.observe = observe or (lambda dev: {})

    def verify(self, command: str, device_id: str,
               expected: dict, evidence_id: str = "",
               source: str = "UNKNOWN") -> VerificationResult:
        """
        expected: {feature: desired} — the snapshot rows to prove.
        Returns a result; evidence_id is REQUIRED before ever reporting PASS.
        """
        t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        res = VerificationResult(command, device_id, timestamp=t, evidence_id=evidence_id)
        if not expected:
            res.result = "UNKNOWN"
            return res

        actual = self.observe(device_id) or {}
        res.observations = actual
        res.honest = source != "REAL_DEVICE"

        # Evidence gate: PASS is impossible without an evidence reference.
        if not evidence_id:
            res.result = "UNKNOWN"
            res.honest = True
            return res

        mismatches = []
        unknown = []
        for feat, want in expected.items():
            got = actual.get(feat)
            if got is None:
                unknown.append(feat)
            elif got != want:
                # A proven active restriction (RESTRICTED) satisfies an OFF or
                # RESTRICT expectation at the enforcement level (laid on top of
                # whatever the raw radio reports, which may lag until reboot).
                if got == "RESTRICTED" and want in ("OFF", "RESTRICT", "BLOCK"):
                    continue
                mismatches.append(feat)
            # else matches

        if mismatches:
            matched = len(expected) - len(mismatches) - len(unknown)
            res.result = "PARTIAL" if matched > 0 else "FAIL"
        elif unknown:
            res.result = "UNKNOWN"
        else:
            res.result = "PASS"
        return res