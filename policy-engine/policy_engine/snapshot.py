"""Adaptive Policy Snapshot — resolve WHAT(desired) x HOW(per-device mechanism).

Resolution inputs: Policy + CapabilityProfile + CompatibilityLayer + VendorAdapter.
Output: a PolicySnapshot with per-feature resolved rows (desired, method,
supported_state, verification, risk, fallback) plus a list of documented
exceptions (features that the device cannot enforce as desired).

Nothing is reported as `SUPPORTED` here: that verdict belongs to the
verification engine with evidence. This layer only RESOLVES and EXPOSES gaps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from capability_engine import CapabilityProfile, CapabilityState

DESIRED_ORDER = {"BLOCK": 3, "RESTRICT": 2, "WARN_AUDIT": 1, "ALLOW": 0}


@dataclass
class ResolvedRow:
    feature: str
    desired: str
    method: str
    supported: str
    risk: str
    fallback: str
    exception: bool = False


@dataclass
class PolicySnapshot:
    policy_id: str
    policy_version: int
    device_id: str
    resolved: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)
    applied: bool = False
    applied_at: str = ""
    verified: str = "UNKNOWN"

    def feature_map(self) -> dict:
        return {r.feature: r for r in self.resolved}

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def resolve(policy, capability: CapabilityProfile, compat_layer,
            vendor_adapter=None) -> PolicySnapshot:
    """Build the snapshot for `policy` against `capability` using `compat_layer`.

    compat_layer: object with .mechanism(feature, desired) -> list[mechanism str]|None
    vendor_adapter: optional object with .enhance(resolved_row) hook.
    """
    snap = PolicySnapshot(policy.policy_id, policy.version, capability.device_id or "-")
    desired_map = policy.feature_map()
    for feature, req in desired_map.items():
        mechanism = compat_layer.mechanism(feature, req.desired_state)
        cap_state = capability.states.get(feature, CapabilityState.UNKNOWN.value)

        if not mechanism:
            exception = req.desired_state not in ("ALLOW", "WARN_AUDIT")
        elif cap_state == CapabilityState.NOT_FEASIBLE.value:
            exception = True
        else:
            exception = False

        row = ResolvedRow(
            feature=feature,
            desired=req.desired_state,
            method=";".join(mechanism) if mechanism else req.fallback,
            supported=cap_state,
            risk=req.risk,
            fallback=req.fallback,
            exception=exception,
        )
        if vendor_adapter is not None:
            vendor_adapter.enhance(row)
        snap.resolved.append(row)
        if exception:
            snap.exceptions.append(feature)
    return snap