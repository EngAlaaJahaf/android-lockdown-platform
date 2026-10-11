"""Compatibility Layer — one mechanism table per Android generation (7→15).

Each mechanism lists the Android API (min) the mechanism is officially available
on (per DPM/UserManager/Settings.Global documentation). `mechanism()` returns
the candidate mechanisms for (feature, desired) on the device api_level — NOT a
"supported" verdict (evidence still required by the verification engine).

Execution plan reference: EXECUTE §21.
"""
from __future__ import annotations

_API = {
    # API level floors for official mechanisms (verified in approved plan §8/§13):
    # user_restriction_* (UserManager) API 21+
    # wifi disable restriction — user_restriction_disable_wifi API 28+ (before:
    #   only via DPM device owner wifi config control, partial)
    # bluetooth disable restriction API 26+
    # location services restriction API 23+
    # safe boot restriction API 23+
    # factory reset restrictions API 21+
    # debugging features restriction API 21+
    # usb file transfer restriction API 21+
    "user_restriction": 21,
    "disable_wifi_restriction": 28,
    "disable_bluetooth_restriction": 26,
    "disable_location_services": 23,
    "disable_safe_boot": 23,
    "disable_debugging_features": 21,
    "disable_usb_file_transfer": 21,
    "disable_tethering": 21,
    "disable_ethernet": 21,
    "wifi_lockdown_global_setting": 23,   # WIFI_DEVICE_OWNER_CONFIGS_LOCKDOWN (API 23) — Decided DEC-001
    "lock_task": 21,
}

_MAPPINGS = {
    "WIFI": {"BLOCK": ["user_restriction_disable_wifi"], "RESTRICT": ["user_restriction_disable_wifi"]},
    "HOTSPOT": {"BLOCK": ["user_restriction_disable_tethering"]},
    "TETHERING": {"BLOCK": ["user_restriction_disable_tethering"]},
    "BLUETOOTH_PAN": {"BLOCK": ["user_restriction_disable_bluetooth"]},
    "BLUETOOTH_TRANSFER": {"BLOCK": ["user_restriction_disable_bluetooth_sharing"]},
    "USB_NETWORKING": {"BLOCK": ["user_restriction_disable_usb_networking"]},
    "ETHERNET": {"BLOCK": ["user_restriction_disable_ethernet"]},
    "VPN": {"BLOCK": ["user_restriction_disable_vpn"]},
    "BLUETOOTH": {"BLOCK": ["user_restriction_disable_bluetooth"]},
    "MOBILE_DATA": {"RESTRICT": ["user_restriction_disable_background_data"],
                    "BLOCK": ["user_restriction_disable_background_data"]},
    "LOCATION": {"BLOCK": ["user_restriction_disable_location_services"],
                  "RESTRICT": ["user_restriction_disable_location_services"]},
    "GPS": {"BLOCK": ["user_restriction_disable_location_services"],
            "RESTRICT": ["user_restriction_disable_location_services"]},
    "CAMERA": {"BLOCK": ["dpm_camera_disabled"]},
    "MICROPHONE": {"BLOCK": ["user_restriction_disable_microphone"]},
    "USB": {"BLOCK": ["user_restriction_disable_usb_file_transfer"]},
    "ADB": {"BLOCK": ["user_restriction_disable_debugging_features"]},
    "DEVELOPER_OPTIONS": {"BLOCK": ["user_restriction_disable_debugging_features"]},
    "SAFE_BOOT": {"BLOCK": ["user_restriction_disable_safe_boot"]},
    "FACTORY_RESET": {"BLOCK": ["user_restriction_disable_factory_reset"]},
    "APP_INSTALLATION": {"BLOCK": ["user_restriction_block_install_unknown_sources"],
                         "RESTRICT": ["package_allowlist"]},
    "UNKNOWN_SOURCES": {"BLOCK": ["user_restriction_block_unknown_sources"]},
    "PLAY_STORE": {"BLOCK": ["package_hide_play_store"]},
    "GOOGLE_MAPS": {"BLOCK": ["package_hide_maps"]},
    "GMAIL_APP": {"BLOCK": ["package_hide_gmail"]},
    "YOUTUBE_APP": {"BLOCK": ["package_hide_youtube"]},
    "CHROME_APP": {"BLOCK": ["package_hide_chrome"]},
    "PLAYSTORE_APP": {"BLOCK": ["package_hide_play_store"]},
    "GOOGLE_APPS": {"BLOCK": ["package_hide_google_apps"]},
    "BROWSER": {"BLOCK": ["package_hide_browser"]},
    "SCREEN_CAPTURE": {"BLOCK": ["dpm_screen_capture_disabled"]},
    "ACCOUNTS": {"BLOCK": ["user_restriction_disable_add_user"]},
    "USER_MANAGEMENT": {"BLOCK": ["user_restriction_disable_add_user"]},
    "LOCK_TASK": {"RESTRICT": ["lock_task_kiosk"]},
    "APPLICATIONS": {"RESTRICT": ["package_allowlist"]},
    # Governed lanes — never "supported" by an app:
    "FACTORY_RESET_RECOVERY": {"BLOCK": [], "WARN_AUDIT": ["governance_lab_only"]},
    "REFLAH_FIRMWARE": {"BLOCK": [], "WARN_AUDIT": ["governance_lab_only"]},
    # Telephony (allow): no mechanisms required; verification-only.
    "CALLS": {"ALLOW": []}, "SMS": {"ALLOW": []}, "CONTACTS": {"ALLOW": []},
    # ---- ManageEngine catalog lanes (profile #904) ----
    # Device-Owner Settings.Global writes (official DO channel). The agent
    # implements these; until then verification honestly reports UNKNOWN/FAIL.
    "AIRPLANE_MODE": {"BLOCK": ["global_airplane_mode_off"]},
    "DATA_SAVER": {"BLOCK": ["global_data_saver_on"]},
    "ROAMING_DATA": {"BLOCK": ["global_data_roaming_off"]},
    "ROAMING_SYNC": {"BLOCK": ["global_data_roaming_off"]},
    "ROAMING_PUSH": {"BLOCK": ["global_data_roaming_off"]},
    "ROAMING_CALL": {"BLOCK": ["global_data_roaming_off"]},
    "NFC": {"BLOCK": ["user_restriction_disable_nfc_radio"]},
    "ANDROID_BEAM": {"BLOCK": ["user_restriction_disable_outgoing_beam"]},
    "S_BEAM": {"BLOCK": ["user_restriction_disable_nfc_radio"]},
    "BLUETOOTH_TETHERING": {"BLOCK": ["global_tether_off"]},
    "SET_TIME": {"BLOCK": ["global_auto_time_off"]},
    "SET_TIMEZONE": {"BLOCK": ["global_auto_timezone_off"]},
    "SET_TIME_ZONE": {"BLOCK": ["global_auto_timezone_off"]},
    "SCREEN_TIMEOUT": {"BLOCK": ["settings_screen_off_timeout"]},
    "SCREEN_BRIGHTNESS": {"BLOCK": ["settings_screen_brightness"]},
    "ADAPTIVE_BRIGHTNESS": {"BLOCK": ["settings_screen_brightness_mode"]},
    "BRIGHTNESS_LOCK": {"BLOCK": ["settings_write_lock_best_effort"]},
    "SCREEN_TIMEOUT_LOCK": {"BLOCK": ["settings_write_lock_best_effort"]},
    "AMBIENT_DISPLAY": {"BLOCK": ["settings_ambient_display"]},
    "BACKGROUND_PROCESS_LIMIT": {"BLOCK": ["global_background_process_limit"]},
    "TERMINATE_APP_ON_EXIT": {"BLOCK": ["global_always_finish_activities"]},
    "MODIFY_DEFAULT_SETTINGS": {"BLOCK": ["settings_write_lock_best_effort"]},
    "PLAY_PROTECT": {"BLOCK": ["global_package_verifier_enforce"]},
    "REPORT_CRASH": {"BLOCK": ["global_send_action_app_error"]},
    "AUTO_SYNC": {"BLOCK": ["global_auto_sync_off"]},
    "MOCK_LOCATIONS": {"BLOCK": ["user_restriction_disable_mock_location"]},
    "CAMERA_LOCKSCREEN": {"BLOCK": ["dpm_camera_disabled"]},
    "WIFI_CONFIG": {"BLOCK": ["user_restriction_disable_wifi"]},
    "UNINSTALL_APPS": {"BLOCK": ["user_restriction_disable_uninstall_apps"]},
    "OS_UPGRADE": {"BLOCK": ["dpm_system_update_freeze"]},
    "STORAGE_ENCRYPTION": {"BLOCK": ["dpm_storage_encryption"]},
}

# mechanisms that require a specific API floor beyond the generic 21
_MECH_API = {
    "user_restriction_disable_wifi": _API["disable_wifi_restriction"],
    "user_restriction_disable_bluetooth": _API["disable_bluetooth_restriction"],
    "user_restriction_disable_location_services": _API["disable_location_services"],
    "user_restriction_disable_safe_boot": _API["disable_safe_boot"],
    "user_restriction_disable_nfc_radio": 35,   # javap: absent on 27-34
    "wifi_lockdown_global_setting": _API["wifi_lockdown_global_setting"],
    "lock_task_kiosk": _API["lock_task"],
}


class AndroidCompatibilityLayer:
    """Resolves candidate mechanisms for (feature, desired) at a given api_level."""

    def __init__(self, api_level: int = 0):
        self.api_level = api_level

    def mechanism(self, feature: str, desired: str):
        """Return list of candidate enforcement mechanisms or None if infeasible."""
        table = _MAPPINGS.get(feature)
        if not table:
            return [] if desired == "ALLOW" else None
        cands = [m for m in table.get(desired, [])]
        if not cands and desired == "RESTRICT" and "BLOCK" in table:
            cands = [m for m in table.get("BLOCK", [])]
        if not cands and desired != "ALLOW" and desired not in table:
            # try WARN_AUDIT gate for governed features
            cands = [m for m in table.get("WARN_AUDIT", [])]
        out = []
        for m in cands:
            floor = _MECH_API.get(m, 21)
            if self.api_level and self.api_level < floor:
                continue
            out.append(m)
        if not out and desired != "ALLOW":
            # legacy partial: for wifi below 28 we still have DPM-level control
            if feature == "WIFI" and desired == "BLOCK" and 23 <= self.api_level < 28:
                out.append("wifi_lockdown_global_setting")
        return out or None