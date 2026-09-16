"""CapabilityEngine — device capability discovery and DeviceProfile model.

The capability engine NEVER asserts SUPPORTED without evidence. Every value is
classified with one of the ClassTag values. Values that cannot be verified at
scan time are UNKNOWN. (Approved plan: DeviceProfile-first; EXECUTE §7, §13.)

Execution plan references: EXECUTE §13, §57.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class ClassTag(str, Enum):
    """Honest capability classification (never pseudo-supported)."""
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    DEVICE_DEPENDENT = "DEVICE_DEPENDENT"
    VENDOR_DEPENDENT = "VENDOR_DEPENDENT"
    ANDROID_VERSION_DEPENDENT = "ANDROID_VERSION_DEPENDENT"
    PARTIAL = "PARTIAL"
    NOT_FEASIBLE = "NOT_FEASIBLE"


class CapabilityState(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    DEVICE_DEPENDENT = "DEVICE_DEPENDENT"
    VENDOR_DEPENDENT = "VENDOR_DEPENDENT"
    ANDROID_VERSION_DEPENDENT = "ANDROID_VERSION_DEPENDENT"
    NOT_FEASIBLE = "NOT_FEASIBLE"


# Feature names must match the vocabulary used by the policy engine.
FEATURES = (
    "WIFI", "BLUETOOTH", "MOBILE_DATA", "LOCATION", "GPS", "CAMERA", "MICROPHONE",
    "USB", "ADB", "DEVELOPER_OPTIONS", "SAFE_BOOT", "FACTORY_RESET",
    "APP_INSTALLATION", "UNKNOWN_SOURCES", "BROWSER", "PLAY_STORE", "HOTSPOT",
    "TETHERING", "ACCOUNTS", "USER_MANAGEMENT", "SCREEN_CAPTURE", "LOCK_TASK",
    "APPLICATIONS", "CALLS", "SMS", "CONTACTS", "ETHERNET", "USB_NETWORKING",
    "VPN", "BLUETOOTH_PAN", "FACTORY_RESET_RECOVERY", "REFLAH_FIRMWARE",
)


def capability_state_default() -> str:
    return CapabilityState.UNKNOWN.value


@dataclass
class CapabilityProfile:
    """One device, one capability assessment (per EXECUTE §13).

    states:  dict[feature, CapabilityState string]
    methods: dict[feature, list[str]] — candidate enforcement methods
    evidence: dict[feature, list[str]] — evidence refs proving state (empty = UNKNOWN)
    """
    device_id: str = ""
    android_version: int = 0
    api_level: int = 0
    manufacturer: str = ""
    model: str = ""
    build_fingerprint: str = ""
    security_patch: str = ""
    kernel_version: str = ""
    bootloader: str = ""
    verified_boot: str = ""
    encryption: str = ""
    baseband: str = ""
    device_owner: bool = False
    states: dict = field(default_factory=dict)
    methods: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    class_tags: list = field(default_factory=list)

    def __post_init__(self):
        for f in FEATURES:
            self.states.setdefault(f, capability_state_default())

    def is_supported(self, feature: str) -> bool:
        return self.states.get(feature) == CapabilityState.SUPPORTED.value

    def is_capable_of(self, feature: str) -> bool:
        """True when the device can meaningfully enforce a BLOCK for feature."""
        s = self.states.get(feature)
        return s in (CapabilityState.SUPPORTED.value, CapabilityState.PARTIAL.value)

    def ensure_evidence(self, feature: str):
        """UNKNOWN unless evidence exists; refuse silent promotion."""
        if not self.evidence.get(feature) and self.states.get(feature) in (
                CapabilityState.SUPPORTED.value, CapabilityState.PARTIAL.value):
            self.states[feature] = CapabilityState.UNKNOWN.value
            self.class_tags.append(ClassTag.UNKNOWN.value)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "CapabilityProfile":
        d = json.loads(raw)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})