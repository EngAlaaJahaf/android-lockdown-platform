"""Vendor / Version Registry — device-agnostic classification and adapter selection.

The manager platform must work on ANY Android device (device-agnostic, per the
release requirements). This registry converts raw identity (manufacturer, model,
android_version, api_level / fingerprint) into a DeviceClass that decides:

   1. which VendorAdapter applies (never guessed — name-based, with Generic fallback)
   2. the known product family / reference tier
   3. version floors that matter for enforcement mechanisms

ClassTag honesty is preserved: this registry never asserts SUPPORTED. It only
classifies; capability/verification engines keep their own evidence gates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import VendorAdapter, GenericAdapter, SamsungAdapter


# ---------------------------------------------------------------------------
# Known product families (name-based; additive, never exhaustive)
# ---------------------------------------------------------------------------
_SAMSUNG_FAMILIES = [
    {"family": "J3 (2018+)", "pattern": r"SM-J33", "lab_versions": [9],
     "notes": "Family reference member SM-J337P = Android 9 / Knox 3.3 targeted lab pilot"},
    {"family": "J3 (2017)", "pattern": r"SM-J32", "lab_versions": [7],
     "notes": "Android 7 floor reference member SM-J320FN"},
    {"family": "J5", "pattern": r"SM-J5", "notes": ""},
    {"family": "J7", "pattern": r"SM-J7", "notes": ""},
    {"family": "A", "pattern": r"SM-A[0-9]", "lab_versions": [14, 15],
     "notes": "Lab reference member SM-A145P dual-OS (14/15)"},
    {"family": "M", "pattern": r"SM-M[0-9]", "notes": ""},
    {"family": "S", "pattern": r"SM-S[0-9]", "notes": ""},
    {"family": "Note", "pattern": r"SM-N[0-9]", "notes": ""},
    {"family": "Tab", "pattern": r"SM-T[0-9]", "notes": ""},
    {"family": "XCover", "pattern": r"SM-G[0-9]*X", "notes": ""},
]

_GOOGLE_AOSP_PATTERNS = (r"^sdk_", r"^google_", r"^angler$", r"^marlin$", r"^walleye$",
                         r"^crosshatch$", r"^blueline$", r"^raven$", r"^oriole$",
                         r"^panther$", r"^cheetah$", r"^husky$", r"^shiba$", r"^akita$")


@dataclass
class DeviceClass:
    vendor_id: str = "generic"                       # samsung | google | motorola | ... | generic
    vendor_label: str = "AOSP / Unknown"
    model: str = ""
    family: str = "unknown"
    product_line: str = ""
    android_version: int = 0
    api_level: int = 0
    build_fingerprint: str = ""
    known_family: bool = False
    reference_tier: str = "UNKNOWN"                  # LAB_REFERENCE | GENERAL | KNOWN_LIMIT | UNKNOWN
    version_floors: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _normalize_model(m: str) -> str:
    return (m or "").strip().upper()


def _is_samsung(model: str, manufacturer: str) -> bool:
    m = _normalize_model(model)
    if m.startswith("SM-") or m.startswith("GT-") or m.startswith("SM "):
        return True
    return (manufacturer or "").strip().lower() in ("samsung", "samsung electronics")


def _is_google_aosp(model: str, manufacturer: str, fingerprint: str) -> bool:
    m = _normalize_model(model)
    man = (manufacturer or "").strip().lower()
    fp = (fingerprint or "").lower()
    if man in ("google", "aosp", "generic", "emulator") or "emulator" in fp or "aosp" in fp:
        return True
    for pat in _GOOGLE_AOSP_PATTERNS:
        if re.match(pat, m.lower()):
            return True
    return False


def classify(manufacturer: str = "", model: str = "", android_version: int = 0,
             api_level: int = 0, build_fingerprint: str = "") -> DeviceClass:
    m = _normalize_model(model)
    cls = DeviceClass(model=model, android_version=android_version,
                      api_level=api_level, build_fingerprint=build_fingerprint)

    if _is_samsung(model, manufacturer):
        cls.vendor_id = "samsung"
        cls.vendor_label = "Samsung"
        cls.known_family = True
        fam = None
        for f in _SAMSUNG_FAMILIES:
            if re.match(f["pattern"], m):
                fam = f
                break
        if fam:
            cls.family = fam["family"]
            cls.notes = fam["notes"]
        cls.product_line = "Galaxy"
        cls.reference_tier = "GENERAL"
        # LAB_REFERENCE is FAMILY-based, not model-based: an identical crew member
        # of a family whose lab evidence exists (on the same Android version)
        # inherits the family's reference tier. Never a single-device hardcode.
        if fam and cls.android_version in (fam.get("lab_versions") or []):
            cls.reference_tier = "LAB_REFERENCE"
            cls.notes = (cls.notes +
                         " — lab-reference family/version (evidence exists for a "
                         "device of this class on the same Android version)").strip()
    elif _is_google_aosp(model, manufacturer, build_fingerprint):
        cls.vendor_id = "generic"
        cls.vendor_label = "AOSP / Google"
        cls.family = "aosp"
        cls.known_family = True
        cls.reference_tier = "GENERAL"
    else:
        known = manufacturer and re.match(
            r"(motorola|xiaomi|oneplus|huawei|honor|oppo|vivo|realme|nokia|sony|lg|lenovo|zte|infinix|tecno|asus|htc)",
            (manufacturer or "").strip().lower())
        if known:
            cls.vendor_id = known.group(1)
            cls.vendor_label = known.group(1).title()
            cls.known_family = True
            cls.reference_tier = "KNOWN_LIMIT"
        else:
            cls.reference_tier = "UNKNOWN"
            cls.notes = "vendor not recognized — GenericAdapter applies"

    # Version floors that matter for official enforcement mechanisms.
    cls.version_floors = {
        "dpm_device_admin": 24,          # minSdk of the ALP agent
        "user_restrictions": 21,
        "wifi_lockdown_global": 23,      # DEC-001
        "wifi_block_restriction": 28,
        "bluetooth_block_restriction": 26,
        "data_roaming_restriction": 28,  # DISALLOW_DATA_ROAMING
        "location_restriction": 23,
        "safe_boot_restriction": 23,
        "knox_enterprise": 30,           # Knox SDK entitlement per-device (never assumed)
    }
    return cls


def select_adapter(device_class: DeviceClass,
                   knox_sdk_present: Optional[bool] = None) -> VendorAdapter:
    """Pick the vendor adapter for a classified device.

    knox_sdk_present must come from device evidence, never from guessing; when
    None the Samsung adapter stays GATED (base DPM only) — honest default.
    """
    if device_class.vendor_id == "samsung":
        ada = SamsungAdapter()
        if knox_sdk_present is True:
            ada.set_knox_present(True)
        return ada
    return GenericAdapter()