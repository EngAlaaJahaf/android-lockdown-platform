"""PolicyEngine — policy model, Policy Schema (what), enforcement selection (how).

Separates WHAT (desired states per feature) from HOW (enforcement method, chosen
by Capability/Compatibility/Vendor layers per device). Per approved AD-2 the HOW
is always the official Android path (DPM, restrictions, Settings.Global, LockTask).

Execution plan references: EXECUTE §14, §15, §16, §73, §74, §75.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---- Feature vocabulary (single source; must match capability FEATURES) ----
# Base lanes (AD-2) + the ManageEngine MDM Plus restriction catalog (profile #904
# export). Feature keys beyond the base lanes come from backend.restrictions and
# carry honest tiers there; adding them to the vocabulary lets catalog-derived
# custom policies flow through creation/apply without silent filtering. Devices
# whose capability proves a lane NOT_FEASIBLE still refuse that lane at apply.
FEATURES = (
    "WIFI", "BLUETOOTH", "MOBILE_DATA", "LOCATION", "GPS", "CAMERA", "MICROPHONE",
    "USB", "ADB", "DEVELOPER_OPTIONS", "SAFE_BOOT", "FACTORY_RESET",
    "APP_INSTALLATION", "UNKNOWN_SOURCES", "BROWSER", "PLAY_STORE", "HOTSPOT",
    "TETHERING", "ACCOUNTS", "USER_MANAGEMENT", "SCREEN_CAPTURE", "LOCK_TASK",
    "APPLICATIONS", "CALLS", "SMS", "CONTACTS", "ETHERNET", "USB_NETWORKING",
    "VPN", "BLUETOOTH_PAN", "FACTORY_RESET_RECOVERY", "REFLAH_FIRMWARE",
    # ---- ManageEngine MDM Plus restriction catalog (profile #904 export) ----
    "ADAPTIVE_BRIGHTNESS", "AIRPLANE_MODE", "AIR_COMMAND", "AIR_VIEW",
    "AMBIENT_DISPLAY", "ANDROID_BEAM", "APP_PERMISSIONS", "AUTOFILL",
    "AUTO_SYNC", "BACKGROUND_DATA", "BACKGROUND_PROCESS_LIMIT",
    "BLUETOOTH_CALL", "BLUETOOTH_DISCOVERY", "BLUETOOTH_PAIRING",
    "BLUETOOTH_TETHERING", "BLUETOOTH_TRANSFER", "BRIGHTNESS_LOCK",
    "BROWSER_AUTOFILL", "BROWSER_COOKIES", "BROWSER_FRAUD_WARN",
    "BROWSER_JAVASCRIPT", "BROWSER_POPUPS", "CAMERA_LOCKSCREEN",
    "CERT_AUTH_APPS", "CERT_INSTALL", "CLIPBOARD", "CLIPBOARD_SHARE",
    "DATA_SAVER", "FIRMWARE_RECOVERY", "FORCE_STOP_LOCK", "GOOGLE_APPS",
    "GOOGLE_MAPS", "GMAIL_APP", "YOUTUBE_APP", "CHROME_APP", "PLAYSTORE_APP",
    "GOOGLE_VOICE", "MMS", "MOCK_LOCATIONS", "MODIFY_DEFAULT_SETTINGS",
    "NFC", "NOTIFICATION_MODE", "NOTIFICATION_PREF", "OS_UPGRADE",
    "PLAY_ACCOUNTS", "PLAY_PROTECT", "POWER_OFF", "PRINTING", "REPORT_CRASH",
    "ROAMING_CALL", "ROAMING_DATA", "ROAMING_PUSH", "ROAMING_SYNC",
    "SCREEN_BRIGHTNESS", "SCREEN_TIMEOUT", "SCREEN_TIMEOUT_LOCK",
    "SD_ENCRYPTION", "SD_MOVE_APPS", "SD_STORE", "SET_TIME", "SET_TIMEZONE",
    "SET_TIME_ZONE", "SHARE_VIA", "SMART_CLIP", "STOP_SYSTEM_APPS",
    "STORAGE_ENCRYPTION", "S_BEAM", "S_VOICE", "TERMINATE_APP_ON_EXIT",
    "UNINSTALL_APPS", "USB_STORAGE", "WIFI_CONFIG", "WIFI_DIRECT",
    "WIFI_UNSECURE",
)


class DesiredState(str):
    __slots__ = ()


@dataclass
class PolicyRequirement:
    """One feature row of a policy (matches §15 matrix columns)."""
    feature: str
    desired_state: str            # BLOCK | ALLOW | RESTRICT | WARN_AUDIT
    supported_state: str = "UNKNOWN"      # how the target device supports it
    enforcement_method: str = ""          # HOW — set by the resolution layer
    verification_method: str = ""         # how the verification engine checks it
    risk: str = "LOW"                     # LOW | MEDIUM | HIGH | CRITICAL
    fallback: str = ""                    # documented fallback / exception


@dataclass
class Policy:
    policy_id: str
    display_name: str
    category: str                # CORPORATE_DEFAULT | PHONE_ONLY | FULL_LOCKDOWN | PARTIAL_LOCKDOWN | MAINTENANCE | QUARANTINE
    version: int = 1
    status: str = "DRAFT"        # DRAFT|REVIEW|ACTIVE|RETIRED|REJECTED
    requirements: list = field(default_factory=list)   # list[PolicyRequirement]
    created_by: str = ""
    created_at: str = ""
    change_reason: str = ""
    recovery_attempts: Optional[int] = None

    def feature_map(self) -> dict:
        return {r.feature: r for r in self.requirements}

    def checksum(self) -> str:
        canon = json.dumps(
            [asdict(r) for r in sorted(self.requirements, key=lambda r: r.feature)],
            sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def desired(self, feature: str) -> str:
        r = self.feature_map().get(feature)
        return r.desired_state if r else "ALLOW"

    def add(self, feature: str, desired: str, risk: str = "LOW",
            method: str = "", verify: str = "", fallback: str = "") -> "Policy":
        if feature not in FEATURES:
            raise ValueError(f"unknown feature: {feature}")
        self.requirements.append(PolicyRequirement(
            feature=feature, desired_state=desired, risk=risk,
            enforcement_method=method, verification_method=verify, fallback=fallback))
        return self

    def to_json(self) -> str:
        d = asdict(self)
        d["checksum"] = self.checksum()
        return json.dumps(d, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Approved reference policies (versioned; Corporate Default is versionable §73)
# ---------------------------------------------------------------------------

def phone_only() -> Policy:
    """PHONE_ONLY (§16): keep the mission — calls/SMS/contacts — block the rest."""
    p = Policy("POL-PHONE_ONLY", "هاتف فقط", "PHONE_ONLY", version=1,
               status="REVIEW", change_reason="REV1 defined in approved plan §16")
    # ALLOW: required telephony
    for f in ("CALLS", "SMS", "CONTACTS"):
        p.add(f, "ALLOW", "HIGH" if f == "CALLS" else "LOW",
              method="dpm_policy_allow_implicit", verify="telephony_active")
    # BLOCK (user restrictions / package control per compat layer)
    p.add("WIFI", "BLOCK", "CRITICAL", method="user_restriction_disable_wifi",
          verify="wifi_state", fallback="AV_DEP: partially enforced below API 28")
    p.add("BLUETOOTH", "BLOCK", "HIGH", method="user_restriction_disable_bluetooth",
          verify="bluetooth_state")
    p.add("HOTSPOT", "BLOCK", "HIGH", method="user_restriction_disable_tethering", verify="tether_state")
    p.add("TETHERING", "BLOCK", "HIGH", method="user_restriction_disable_tethering", verify="tether_state")
    p.add("USB_NETWORKING", "BLOCK", "HIGH", method="user_restriction_disable_usb_networking", verify="usb_net_stats")
    p.add("BLUETOOTH_PAN", "BLOCK", "MEDIUM", method="user_restriction_disable_bluetooth_pan", verify="bt_pan_stats")
    p.add("VPN", "BLOCK", "MEDIUM", method="user_restriction_disable_metered_vpn", verify="vpn_state")
    p.add("ETHERNET", "BLOCK", "MEDIUM", method="user_restriction_disable_ethernet", verify="ethernet_state")
    p.add("CAMERA", "BLOCK", "CRITICAL", method="dpm_camera_disabled", verify="camera_intent")
    p.add("MICROPHONE", "BLOCK", "HIGH", method="user_restriction_disable_microphone", verify="mic_permission")
    p.add("GPS", "BLOCK", "HIGH", method="location_off", verify="provider_state", fallback="PARTIAL: HW RAW off not guaranteed")
    p.add("LOCATION", "BLOCK", "HIGH", method="user_restriction_disable_location_services", verify="location_mode")
    p.add("BROWSER", "BLOCK", "HIGH", method="package_hide_browser", verify="browser_absent")
    p.add("PLAY_STORE", "BLOCK", "HIGH", method="package_hide_play_store", verify="store_absent")
    p.add("APP_INSTALLATION", "BLOCK", "CRITICAL", method="user_restriction_block_install_unknown_sources", verify="install_blocked")
    p.add("UNKNOWN_SOURCES", "BLOCK", "CRITICAL", method="user_restriction_block_unknown_sources", verify="unknown_src_blocked")
    p.add("DEVELOPER_OPTIONS", "BLOCK", "CRITICAL", method="user_restriction_disable_debugging_features", verify="devopts_state")
    p.add("ADB", "BLOCK", "CRITICAL", method="user_restriction_disable_debugging_features", verify="adb_state")
    p.add("USB", "BLOCK", "HIGH", method="user_restriction_disable_usb_file_transfer", verify="usb_ft_state")
    p.add("SCREEN_CAPTURE", "BLOCK", "MEDIUM", method="dpm_screen_capture_disabled", verify="screencap_blocked")
    p.add("ACCOUNTS", "BLOCK", "MEDIUM", method="user_restriction_disable_add_user", verify="add_account_blocked")
    p.add("USER_MANAGEMENT", "BLOCK", "HIGH", method="user_restriction_disable_add_user", verify="user_mgmt_blocked")
    p.add("APPLICATIONS", "RESTRICT", "HIGH", method="package_allowlist", verify="allowlist_effective",
          fallback="allowlist defined by org; not enforced on legacy 7.x fully")
    p.add("LOCK_TASK", "RESTRICT", "MEDIUM", method="lock_task_kiosk", verify="kiosk_active",
          fallback="AV_DEP on OEM builds")
    p.add("MOBILE_DATA", "RESTRICT", "MEDIUM", method="background_data_off", verify="bg_data_state",
          fallback="PARTIAL: full data cut shares semantics with SMS for operators")
    p.add("SAFE_BOOT", "BLOCK", "HIGH", method="user_restriction_disable_safe_boot", verify="safe_boot_blocked")
    p.add("FACTORY_RESET", "BLOCK", "CRITICAL", method="user_restriction_disable_factory_reset", verify="fr_settings_blocked")
    # Governed, not enforceable from app layer:
    p.add("FACTORY_RESET_RECOVERY", "WARN_AUDIT", "CRITICAL",
          method="governance_lab_only", verify="audit_gate", fallback="NOT_FEASIBLE from DPC — recovery/ODIN")
    p.add("REFLAH_FIRMWARE", "WARN_AUDIT", "CRITICAL",
          method="governance_lab_only", verify="audit_gate", fallback="NOT_FEASIBLE from DPC — firmware layer")
    return p


def corporate_default_v1() -> Policy:
    """Corporate Default v1 (§73): balanced baseline, versioned."""
    p = Policy("POL-CORP_DEFAULT", "السياسة القياسية", "CORPORATE_DEFAULT", version=1,
               status="REVIEW", change_reason="v1 defined at EXECUTE baseline")
    p.add("CALLS", "ALLOW", "LOW").add("SMS", "ALLOW", "LOW").add("CONTACTS", "ALLOW", "LOW")
    p.add("CAMERA", "WARN_AUDIT", "MEDIUM").add("MICROPHONE", "WARN_AUDIT", "MEDIUM")
    p.add("GPS", "RESTRICT", "MEDIUM").add("LOCATION", "RESTRICT", "MEDIUM")
    p.add("ADB", "BLOCK", "HIGH").add("DEVELOPER_OPTIONS", "BLOCK", "HIGH")
    p.add("UNKNOWN_SOURCES", "BLOCK", "HIGH").add("APP_INSTALLATION", "RESTRICT", "HIGH")
    p.add("SCREEN_CAPTURE", "WARN_AUDIT", "MEDIUM")
    p.add("SAFE_BOOT", "BLOCK", "HIGH")
    p.add("TETHERING", "BLOCK", "MEDIUM").add("HOTSPOT", "BLOCK", "MEDIUM")
    p.add("USB", "WARN_AUDIT", "MEDIUM")
    p.add("ACCOUNTS", "ALLOW", "LOW").add("USER_MANAGEMENT", "BLOCK", "HIGH")
    p.add("APPLICATIONS", "RESTRICT", "LOW")
    p.add("FACTORY_RESET", "WARN_AUDIT", "CRITICAL")
    p.add("FACTORY_RESET_RECOVERY", "WARN_AUDIT", "CRITICAL",
          method="governance_lab_only", fallback="NOT_FEASIBLE from DPC")
    p.add("REFLAH_FIRMWARE", "WARN_AUDIT", "CRITICAL",
          method="governance_lab_only", fallback="NOT_FEASIBLE from DPC")
    return p


def full_lockdown() -> Policy:
    """FULL_LOCKDOWN: hardest enforceable config; honest about NOT FEASIBLE lanes."""
    p = Policy("POL-FULL_LOCKDOWN", "إغلاق كامل", "FULL_LOCKDOWN", version=1,
               status="REVIEW", change_reason="REV1")
    for f in ("WIFI", "BLUETOOTH", "MOBILE_DATA", "LOCATION", "GPS", "CAMERA", "MICROPHONE",
              "USB", "ADB", "DEVELOPER_OPTIONS", "SAFE_BOOT", "FACTORY_RESET",
              "APP_INSTALLATION", "UNKNOWN_SOURCES", "BROWSER", "PLAY_STORE", "HOTSPOT",
              "TETHERING", "ACCOUNTS", "USER_MANAGEMENT", "SCREEN_CAPTURE", "VPN",
              "ETHERNET", "USB_NETWORKING", "BLUETOOTH_PAN"):
        risk = "CRITICAL" if f in ("WIFI", "CAMERA", "ADB", "FACTORY_RESET") else "HIGH"
        p.add(f, "BLOCK", risk)
    p.add("CALLS", "ALLOW", "MEDIUM").add("SMS", "ALLOW", "MEDIUM").add("CONTACTS", "ALLOW", "LOW")
    p.add("APPLICATIONS", "RESTRICT", "CRITICAL", method="package_allowlist")
    p.add("LOCK_TASK", "RESTRICT", "HIGH", method="lock_task_kiosk")
    p.add("FACTORY_RESET_RECOVERY", "WARN_AUDIT", "CRITICAL", method="governance_lab_only", fallback="NOT_FEASIBLE from DPC")
    p.add("REFLAH_FIRMWARE", "WARN_AUDIT", "CRITICAL", method="governance_lab_only", fallback="NOT_FEASIBLE from DPC")
    return p


def partial_lockdown() -> Policy:
    """PARTIAL_LOCKDOWN: configurable mix (baseline kept close to corporate default)."""
    p = corporate_default_v1()
    p.policy_id = "POL-PARTIAL"
    p.display_name = "تقليص جزئي"
    p.category = "PARTIAL_LOCKDOWN"
    p.version = 1
    p.status = "REVIEW"
    p.change_reason = "REV1 baseline"
    return p


def maintenance() -> Policy:
    p = Policy("POL-MAINTENANCE", "صيانة", "MAINTENANCE", version=1, status="REVIEW")
    p.add("WIFI", "ALLOW", "MEDIUM").add("BLUETOOTH", "ALLOW", "MEDIUM")
    p.add("ADB", "ALLOW", "HIGH").add("DEVELOPER_OPTIONS", "ALLOW", "MEDIUM")
    p.add("APPLICATIONS", "ALLOW", "LOW")
    p.add("FACTORY_RESET", "WARN_AUDIT", "CRITICAL")
    return p


def quarantine() -> Policy:
    p = Policy("POL-QUARANTINE", "عزل", "QUARANTINE", version=1, status="REVIEW")
    for f in ("WIFI", "BLUETOOTH", "CAMERA", "MICROPHONE", "ADB", "GPS", "LOCATION",
              "APP_INSTALLATION", "UNKNOWN_SOURCES", "TETHERING", "HOTSPOT"):
        p.add(f, "BLOCK", "HIGH")
    p.add("APPLICATIONS", "RESTRICT", "CRITICAL", method="package_allowlist")
    return p


ALL_REFERENCE_POLICIES = {
    "PHONE_ONLY": phone_only,
    "CORPORATE_DEFAULT": corporate_default_v1,
    "FULL_LOCKDOWN": full_lockdown,
    "PARTIAL_LOCKDOWN": partial_lockdown,
    "MAINTENANCE": maintenance,
    "QUARANTINE": quarantine,
}