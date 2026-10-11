"""ManageEngine MDM Plus restriction catalog — label-parity source of truth.

The section names, group labels and restriction labels below mirror the
ManageEngine MDM Plus "Device Profile" Android Restrictions payload. Labels
were cross-checked row-by-row against the *running* console
(build 11.2.2508.01) at
`webclient#/uems/mdm/manage/profile/android/<id>/restrictions`, and every
ManageEngine server key used here was confirmed present in the shipped
`android-restrictions-*.json` defaults. Our console and agent reuse these
labels so an administrator switching from ManageEngine finds the same
interface.

Tiers (mirroring capability-engine CapabilityState):
    SUPPORTED          — enforceable with the platform's Device-Owner DPM APIs
                          or real Settings writes from our agent over ADB.
    PARTIAL            — enforceable only in a degraded way, or requires
                          Device Owner + extra conditions (Play EMM / API gating).
    VENDOR_DEPENDENT   — requires Samsung / OEM (Knox, OneUI) APIs; unsafe or
                          absent on stock AOSP; reported honestly per device.
    NOT_FEASIBLE       — no public/known mechanism; we never fake it.

Methods are the enforcement channel names used by capability-engine / AlpOps.
"""
from __future__ import annotations

from typing import Iterator

# ---------------------------------------------------------------------------
# Groups (order = order in ManageEngine profile payload exporter)
# ---------------------------------------------------------------------------

RESTRICTION_GROUPS = [
    # (group_key, label, description)
    ("device_functionality", "Device Functionality", "Hardware capture and device-level capability toggles."),
    ("security", "Security", "Accounts, recovery, clipboard, developer and certificate controls."),
    ("sync_storage", "Sync and Storage", "Google sync, crash reporting, SD card and USB storage."),
    ("applications", "Applications", "App install / uninstall / approval scope and system app policy."),
    ("browser", "Browser Restriction", "On Core Android these apply to Google Chrome (per PDF note)."),
    ("network_roaming", "Network and Roaming", "Airplane mode, data, Wi-Fi, VPN and roaming controls."),
    ("device_connectivity", "Device Connectivity", "NFC, Bluetooth, printing and device-to-device links."),
    ("tethering", "Tethering", "All tethering flavors: Wi-Fi, Bluetooth, USB."),
    ("location_settings", "Location settings", "Location services, mock locations and Maps."),
    ("phone", "Phone", "Voice search, SMS/MMS and call directions."),
    ("date_time", "Date/Time Settings", "Device time, timezone and related date/time changes."),
    ("display", "Display Settings", "Screen timeout, brightness and ambient display."),
    ("miscellaneous", "Miscellaneous", "Power button, background processes and OEM extras."),
]


# (feature_key, label_ar, enforcement_method, tier, note)
def _r(label, feature, method, tier, note=""):
    return {"label": label, "feature": feature, "method": method,
            "tier": tier, "note": note}


RESTRICTIONS = {
    "device_functionality": [
        _r("Camera", "CAMERA", "DPM_RESTRICTION", "SUPPORTED",
           "DevicePolicyManager.setCameraDisabled(DO)."),
        _r("Allow camera in lock screen", "CAMERA_LOCKSCREEN", "DPM_RESTRICTION", "SUPPORTED",
           "keyguard feature KEYGUARD_DISABLE_SECURE_CAMERA."),
        _r("Video Recording", "CAMERA", "DPM_RESTRICTION", "PARTIAL",
           "Covered by Camera block on most builds; no separate stock API."),
        _r("Microphone", "MICROPHONE", "SETTINGS_GLOBAL", "PARTIAL",
           "global mic/audio capture disabled where the build exposes it."),
        _r("Audio Recording", "MICROPHONE", "SETTINGS_GLOBAL", "PARTIAL",
           "Routed with Microphone; recorder-app package control recommended."),
        _r("Firmware Recovery", "FIRMWARE_RECOVERY", "KNOX", "VENDOR_DEPENDENT",
           "Requires Samsung/Knox Download Mode policy."),
        _r("OS upgrade", "OS_UPGRADE", "DPM_SYSTEM_UPDATE", "PARTIAL",
           "setSystemUpdatePolicy can defer/freeze; denial is OEM-dependent."),
        _r("Screen Capture", "SCREEN_CAPTURE", "DPM_RESTRICTION", "SUPPORTED",
           "setScreenCaptureDisabled(DO)."),
        _r("Smart Clip Mode", "SMART_CLIP", "KNOX", "VENDOR_DEPENDENT", "Samsung-only."),
        _r("S Voice", "S_VOICE", "KNOX", "VENDOR_DEPENDENT", "Samsung-only."),
        _r("Enforce Storage encryption", "STORAGE_ENCRYPTION", "DPM_RESTRICTION", "PARTIAL",
           "Fully-managed encryption state varies by build; report from device."),
        _r("Enforce SD Card encryption", "SD_ENCRYPTION", "KNOX", "VENDOR_DEPENDENT",
           "Samsung SD encryption policy."),
    ],
    "security": [
        _r("Allow Adding or Removing Accounts on the Device", "ACCOUNTS",
           "DPM_RESTRICTION", "SUPPORTED", "addUserRestriction DISALLOW_MODIFY_ACCOUNTS."),
        _r("Restore Factory Settings", "FACTORY_RESET", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_FACTORY_RESET."),
        _r("Lock Screen Notification Preference", "NOTIFICATION_PREF", "DPM_RESTRICTION", "PARTIAL",
           "Keyguard/status-bar policy where the build honours it."),
        _r("Allow certificate based authentication for managed apps",
           "CERT_AUTH_APPS", "KNOX", "VENDOR_DEPENDENT", "Knox managed-certificate store."),
        _r("Allow users to install or modify certificates", "CERT_INSTALL",
           "DPM_RESTRICTION", "PARTIAL", "No public DO API; Knox addon."),
        _r("Clipboard", "CLIPBOARD", "DPM_RESTRICTION", "PARTIAL",
           "Stock Android lacks a global clipboard gate pre-13."),
        _r("Clipboard Share", "CLIPBOARD_SHARE", "KNOX", "VENDOR_DEPENDENT",
           "Samsung Smart Clip / clipboard share."),
        _r("Safe Mode", "SAFE_BOOT", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_SAFE_BOOT."),
        _r("Developer Mode", "DEVELOPER_OPTIONS", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_DEBUGGING_FEATURES + development_settings_enabled=0."),
        _r("\"Share via\" list", "SHARE_VIA", "PACKAGE_CTRL", "PARTIAL",
           "OEM-close list; stock has no resolver gate."),
        _r("Google Play Protect", "PLAY_PROTECT", "SETTINGS_GLOBAL", "SUPPORTED",
           "verifier_verify_adb_installs / package verifier enforcement."),
        _r("Auto fill", "AUTOFILL", "DPM_RESTRICTION", "PARTIAL",
           "Autofill service gating only on recent Android; otherwise OEM."),
    ],
    "sync_storage": [
        _r("Auto-sync Google accounts", "AUTO_SYNC", "SETTINGS_GLOBAL", "SUPPORTED",
           "global auto_time/auto_sync via Device Owner write."),
        _r("Report crash to Google", "REPORT_CRASH", "SETTINGS_GLOBAL", "SUPPORTED",
           "global send_action_app_error."),
        _r("SD Card", "SD_CARD", "STORAGE_POLICY", "SUPPORTED",
           "Master cascade over Store data in SD Card + Move apps to SD Card; "
           "no dedicated stock DO API, so the effective ceiling is those two lanes "
           "(PARTIAL / VENDOR_DEPENDENT)."),
        _r("Store data in SD Card", "SD_STORE", "STORAGE_POLICY", "PARTIAL",
           "Storage-manager scope for shared storage write."),
        _r("Move apps to SD Card", "SD_MOVE_APPS", "STORAGE_POLICY", "VENDOR_DEPENDENT",
           "OEM storage policies; not a stock DO API."),
        _r("USB", "USB_MASTER", "STORAGE_POLICY", "SUPPORTED",
           "Master cascade over Connections using USB + Connect a USB storage device; "
           "no dedicated stock DO API, so the effective ceiling is those two lanes "
           "(PARTIAL / VENDOR_DEPENDENT)."),
        _r("Connections using USB", "USB", "DPM_RESTRICTION", "PARTIAL",
           "USB tethering/file-transfer control, build-dependent."),
        _r("Connect a USB storage device", "USB_STORAGE", "STORAGE_POLICY", "VENDOR_DEPENDENT",
           "Auto-MTP disable is OEM-level."),
    ],
    "applications": [
        _r("Users can install only approved apps", "APP_INSTALLATION", "PACKAGE_CTRL", "PARTIAL",
           "App allowlist via setApplicationRestrictions/Play EMM."),
        _r("Allow access to all apps in Managed Google Play", "PLAY_STORE", "PACKAGE_CTRL", "PARTIAL",
           "Requires managed Play console."),
        _r("Allow accessing personal accounts in playstore", "PLAY_ACCOUNTS", "PACKAGE_CTRL", "PARTIAL",
           "Managed Google Play account policy."),
        _r("Gmail app", "GMAIL_APP", "PACKAGE_CTRL", "SUPPORTED",
           "Hide com.google.android.gm (setApplicationHidden, DO)."),
        _r("YouTube app", "YOUTUBE_APP", "PACKAGE_CTRL", "SUPPORTED",
           "Hide com.google.android.youtube (setApplicationHidden, DO)."),
        _r("Chrome browser app", "CHROME_APP", "PACKAGE_CTRL", "SUPPORTED",
           "Hide com.android.chrome (setApplicationHidden, DO). "
           "Vendor browsers stay under the Android Browser lane."),
        _r("Play Store app", "PLAYSTORE_APP", "PACKAGE_CTRL", "SUPPORTED",
           "Hide com.android.vending (setApplicationHidden, DO)."),
        _r("Allow installing non-market apps", "UNKNOWN_SOURCES", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_INSTALL_UNKNOWN_SOURCES."),
        _r("Uninstalling apps", "UNINSTALL_APPS", "DPM_RESTRICTION", "PARTIAL",
           "setUninstallBlocked per package."),
        _r("Stop system apps", "STOP_SYSTEM_APPS", "PACKAGE_CTRL", "PARTIAL",
           "Packages-suspend / system-app disables where permitted."),
        _r("Application Notification Mode", "NOTIFICATION_MODE", "PACKAGE_CTRL", "PARTIAL",
           "Notification channels gating."),
        _r("Global App Permission Policy", "APP_PERMISSIONS", "PACKAGE_CTRL", "PARTIAL",
           "Runtime-permission grants to managed apps."),
        _r("Restrict force stop and clear storage settings for the specified app(s)",
           "FORCE_STOP_LOCK", "PACKAGE_CTRL", "PARTIAL", "OEM/Play EMM."),
    ],
    "browser": [
        _r("Android Browser", "BROWSER", "PACKAGE_CTRL", "SUPPORTED",
           "Hide every browser on the handset (Chrome, Samsung Internet, "
           "vendor browsers resolved live) — links then have no handler."),
        _r("Fraud warning setting", "BROWSER_FRAUD_WARN", "APP_SETTINGS", "PARTIAL",
           "Chrome managed-config flag (Android Chrome note in PDF)."),
        _r("Pop-ups", "BROWSER_POPUPS", "APP_SETTINGS", "PARTIAL",
           "Chrome managed-config flag."),
        _r("JavaScript", "BROWSER_JAVASCRIPT", "APP_SETTINGS", "PARTIAL",
           "Chrome managed-config flag."),
        _r("Autofill", "BROWSER_AUTOFILL", "APP_SETTINGS", "PARTIAL",
           "Chrome managed-config flag."),
        _r("Cookies", "BROWSER_COOKIES", "APP_SETTINGS", "PARTIAL",
           "Chrome managed-config flag."),
    ],
    "network_roaming": [
        _r("Airplane Mode", "AIRPLANE_MODE", "SETTINGS_GLOBAL", "SUPPORTED",
           "global airplane_mode_on + radio toggles from our agent."),
        _r("Background data", "BACKGROUND_DATA", "SETTINGS_GLOBAL", "PARTIAL",
           "Data-saver umbrella covers most background traffic."),
        _r("Data Saver Mode", "DATA_SAVER", "SETTINGS_GLOBAL", "SUPPORTED",
           "global network_data_saver."),
        _r("Wi-Fi", "WIFI", "SETTINGS_GLOBAL", "SUPPORTED",
           "global wifi_on + QS-tile removal (agent ALP-Agent hardening)."),
        _r("Connect to Wi-Fi, only if distributed via MDM", "WIFI_CONFIG", "DPM_WIFI", "PARTIAL",
           "allowlist semantics via WifiSsidPolicy/equivalent on stock DO."),
        _r("Wi-fi Direct", "WIFI_DIRECT", "DPM_RESTRICTION", "PARTIAL",
           "No dedicated stock DO restriction; rely on Wi-Fi off."),
        _r("Allow users to connect to unsecure public Wi-Fi networks", "WIFI_UNSECURE",
           "DPM_WIFI", "PARTIAL", "SSID-level policy on capable builds."),
        _r("Allow users to configure VPN", "VPN", "DPM_RESTRICTION", "PARTIAL",
           "No stock DO restriction; builders ship Knox addon."),
        _r("Roaming data", "ROAMING_DATA", "SETTINGS_GLOBAL", "SUPPORTED",
           "global data_roaming=0 via Device Owner write."),
        _r("Sync data while roaming", "ROAMING_SYNC", "SETTINGS_GLOBAL", "PARTIAL",
           "Tied to roaming-data switch."),
        _r("Roaming push", "ROAMING_PUSH", "SETTINGS_GLOBAL", "PARTIAL",
           "OEM push channel; not standard."),
        _r("Voice call while roaming", "ROAMING_CALL", "SETTINGS_GLOBAL", "PARTIAL",
           "build-dependent radio policy."),
    ],
    "device_connectivity": [
        _r("NFC", "NFC", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_NEAR_FIELD_COMMUNICATION_RADIO (DO radio kill). "
           "Needs NFC hardware — refused on builds without it (proven on "
           "the V2352 bench unit, which has no nfc service)."),
        _r("Android Beam", "ANDROID_BEAM", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_OUTGOING_BEAM (DO) — proven in dumpsys on the bench unit."),
        _r("S Beam", "S_BEAM", "DPM_RESTRICTION", "SUPPORTED",
           "Enforced via the NFC radio kill (S-Beam rides on NFC); same "
           "hardware requirement as NFC."),
        _r("Bluetooth", "BLUETOOTH", "SETTINGS_GLOBAL", "SUPPORTED",
           "global bluetooth_on + adapter disable from agent."),
        _r("Bluetooth discovery", "BLUETOOTH_DISCOVERY", "KNOX", "VENDOR_DEPENDENT",
           "Ignores scanning-BT discovery on stock."),
        _r("Bluetooth pairing", "BLUETOOTH_PAIRING", "KNOX", "VENDOR_DEPENDENT",
           "Knox paring gate."),
        _r("Make outgoing calls using Bluetooth", "BLUETOOTH_CALL", "KNOX", "VENDOR_DEPENDENT",
           "Knox device-role policy."),
        _r("Connect to laptop/desktop via Bluetooth", "BLUETOOTH_PAN", "DPM_RESTRICTION", "SUPPORTED",
           "Tethering chain / PAN disable where DO grants."),
        _r("Bluetooth data transfer", "BLUETOOTH_TRANSFER", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_BLUETOOTH_SHARING (DO)."),
        _r("Printing", "PRINTING", "DPM_RESTRICTION", "NOT_FEASIBLE",
           "No stock DO printing restriction."),
    ],
    "tethering": [
        _r("Tethering", "TETHERING", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_TETHERING."),
        _r("Bluetooth tethering", "BLUETOOTH_TETHERING", "SETTINGS_GLOBAL", "SUPPORTED",
           "global tether_supported / BT PAN."),
        _r("Wi-Fi tethering", "HOTSPOT", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_TETHERING covers hotspot; media sharing off."),
        _r("USB tethering", "USB_NETWORKING", "SETTINGS_GLOBAL", "SUPPORTED",
           "global usb_tethering."),
    ],
    "location_settings": [
        _r("Location services", "LOCATION", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_SHARE_LOCATION."),
        _r("Mock locations", "MOCK_LOCATIONS", "DPM_RESTRICTION", "SUPPORTED",
           "DISALLOW_MOCK_LOCATION (DO)."),
        _r("Google Maps", "GOOGLE_MAPS", "PACKAGE_CTRL", "SUPPORTED",
           "Hide com.google.android.apps.maps (setApplicationHidden, DO)."),
        _r("All Google apps", "GOOGLE_APPS", "PACKAGE_CTRL", "SUPPORTED",
           "Hide internet-facing Google packages (Play, Gmail, YouTube, "
           "Chrome, …) via setApplicationHidden. Core services (GMS/GSF), "
           "keyboards, the dialer, and offline utilities (SMS, contacts, "
           "files, calendar, clock, calculator) are deliberately excluded "
           "so rollback stays reachable."),
    ],
    "phone": [
        _r("Google Voice search", "GOOGLE_VOICE", "PACKAGE_CTRL", "PARTIAL",
           "Suspend quicksearchbox."),
        _r("SMS", "SMS_MASTER", "PHONE_POLICY", "SUPPORTED",
           "Master cascade over Incoming SMS + Outgoing SMS; no stock DO SMS API, "
           "so the effective ceiling is those two lanes (both PARTIAL)."),
        _r("Incoming SMS", "SMS", "PHONE_POLICY", "PARTIAL",
           "No DO per-direction SMS API; Knox or app-level."),
        _r("Outgoing SMS", "SMS", "PHONE_POLICY", "PARTIAL",
           "No DO per-direction SMS API; Knox or app-level."),
        _r("MMS", "MMS", "PHONE_POLICY", "PARTIAL",
           "Routed with SMS; data required for MMS."),
        _r("Incoming MMS", "MMS", "PHONE_POLICY", "PARTIAL", "As MMS."),
        _r("Outgoing MMS", "MMS", "PHONE_POLICY", "PARTIAL", "As MMS."),
        _r("Call", "CALLS_MASTER", "PHONE_POLICY", "SUPPORTED",
           "Master cascade over Incoming calls + Outgoing calls; no stock DO call API, "
           "so the effective ceiling is those two lanes (both PARTIAL)."),
        _r("Incoming calls", "CALLS", "PHONE_POLICY", "PARTIAL",
           "No DO per-direction call API; Knox or app-level."),
        _r("Outgoing calls", "CALLS", "PHONE_POLICY", "PARTIAL",
           "No DO per-direction call API; Knox or app-level."),
    ],
    "date_time": [
        _r("Set device time", "SET_TIME", "SETTINGS_GLOBAL", "SUPPORTED",
           "global auto_time + DISALLOW_SET_TIME where exposed."),
        _r("Timezone", "SET_TIMEZONE", "SETTINGS_GLOBAL", "SUPPORTED",
           "global auto_time_zone."),
        _r("Modify date/time settings", "SET_TIME", "SETTINGS_GLOBAL", "SUPPORTED",
           "Lock auto-time provisioning to mitigate modification."),
        _r("Modify date/time", "SET_TIME_ZONE", "SETTINGS_GLOBAL", "SUPPORTED",
           "As above for timezone."),
    ],
    "display": [
        _r("Screen Timeout", "SCREEN_TIMEOUT", "SETTINGS_GLOBAL", "SUPPORTED",
           "global screen_off_timeout."),
        _r("Modifying Screen Timeout settings", "SCREEN_TIMEOUT_LOCK", "SETTINGS_GLOBAL", "PARTIAL",
           "Prevent the value from being changed by the user where supported."),
        _r("Set brightness", "SCREEN_BRIGHTNESS", "SETTINGS_GLOBAL", "SUPPORTED",
           "global screen_brightness."),
        _r("Adaptive brightness", "ADAPTIVE_BRIGHTNESS", "SETTINGS_GLOBAL", "SUPPORTED",
           "global screen_brightness_mode."),
        _r("Modifying brightness settings", "BRIGHTNESS_LOCK", "SETTINGS_GLOBAL", "PARTIAL",
           "As with timeout lock."),
        _r("Ambient display", "AMBIENT_DISPLAY", "SETTINGS_GLOBAL", "PARTIAL",
           "global doze_always_on where present."),
    ],
    "miscellaneous": [
        _r("Turn Off the device using Power Button", "POWER_OFF", "KNOX", "VENDOR_DEPENDENT",
           "No stock power-off restriction; Knox policy."),
        _r("Background process limit", "BACKGROUND_PROCESS_LIMIT", "SETTINGS_GLOBAL", "PARTIAL",
           "Developer-options service boundary, not a hard global."),
        _r("Terminate app on exiting", "TERMINATE_APP_ON_EXIT", "SETTINGS_GLOBAL", "PARTIAL",
           "always_finish_activities developer flag."),
        _r("Modify default device settings", "MODIFY_DEFAULT_SETTINGS", "SETTINGS_GLOBAL", "PARTIAL",
           "Umbrella for settings writes by user."),
        _r("Air command", "AIR_COMMAND", "KNOX", "VENDOR_DEPENDENT", "Samsung-only."),
        _r("Air view", "AIR_VIEW", "KNOX", "VENDOR_DEPENDENT", "Samsung-only."),
        _r("Wi-Fi", "WIFI", "SETTINGS_GLOBAL", "SUPPORTED",
           "Duplicate entry as it appears in the Misc. sheet of the PDF export."),
    ],
}


# Policy value vocabulary used by the ManageEngine console switches
# ("User Controlled" / "Always Off" radio controls, Allow/Restrict toggles).
VALUE_SET = {
    "toggle": ["Allow", "Restrict"],
    "radio_off": ["User Controlled", "Always Off"],
    "radio_allow": ["User Controlled", "Always Off", "Restricted"],
    "custom": ["User Controlled", "Restricted", "Allowed"],
}


def catalog() -> dict:
    """The full catalog: groups in UI order with their restrictions."""
    groups = []
    for gkey, label, desc in RESTRICTION_GROUPS:
        items = RESTRICTIONS.get(gkey, [])
        if not items:
            continue
        groups.append({"key": gkey, "label": label, "description": desc,
                       "restrictions": items})
    return {"source": "ManageEngine MDM Plus 11.2.2508.01 Android Restrictions "
                   "(verified against the running console)",
            "groups": groups}


def iter_restrictions() -> Iterator[dict]:
    """Flat view (used by policy maps / agent capability overlap)."""
    for gkey, _, _ in RESTRICTION_GROUPS:
        for r in RESTRICTIONS.get(gkey, []):
            yield {"group": gkey, **r}


def feature_union() -> set[str]:
    """Every feature key referenced by the catalog."""
    return {r["feature"] for r in iter_restrictions()}


ENFORCEABLE_TIERS = {"SUPPORTED", "PARTIAL"}


# Lanes that sever the very channel used to manage the device. Pushing one
# of these over a live ADB session kills that session (USB debugging off),
# after which rollback, recovery and re-verification are all unreachable.
# run_director_apply refuses real delivery of any profile containing them
# unless the caller explicitly passes allow_channel_risk=True — the console
# never sends that flag, so the button cannot orphan a phone by accident.
# ADB earned its place here the hard way: a test envelope carrying it cut a
# USB-only lab handset off mid-session (no rollback reachable).
CHANNEL_RISK_FEATURES = {"DEVELOPER_OPTIONS", "ADB"}


# ManageEngine section-header rows (SMS / Call / USB / SD Card) are aggregation
# containers: Android exposes no single stock DeviceOwner API for them, so there
# is no honest enforcement mechanism to attach to the header itself. Selecting a
# header therefore expands to the lanes it actually governs, and each leaf is
# then tiered on its own. Nothing is invented for the header row itself.
MASTER_CASCADE = {
    "SMS_MASTER": ("SMS",),
    "CALLS_MASTER": ("CALLS",),
    "USB_MASTER": ("USB", "USB_STORAGE"),
    "SD_CARD": ("SD_STORE", "SD_MOVE_APPS"),
}


def by_feature() -> dict[str, list[dict]]:
    """Map feature key -> catalog rows (multiple ManageEngine labels can share a
    feature; e.g. Camera + Video Recording both steer the CAMERA lane)."""
    out: dict[str, list[dict]] = {}
    for r in iter_restrictions():
        out.setdefault(r["feature"], []).append(r)
    return out


def policy_from_catalog(features, name: str = "السياسة القياسية", risk: str = "MEDIUM"):
    """Build a Policy (not yet persisted) from ManageEngine catalog feature keys.

    The admin picks ManageEngine labels in the console; we resolve them to the
    ALP feature lanes and BLOCK them. Honest split:
        applied   — lanes with an ENFORCEABLE tier (SUPPORTED/PARTIAL)
        excluded  — lanes only reachable via OEM/Knox (VENDOR_DEPENDENT) or with
                    no real mechanism (NOT_FEASIBLE); never silently dropped,
                    returned so the UI can show why each was left out.
    ManageEngine section headers listed in MASTER_CASCADE have no mechanism of
    their own, so they expand into the lanes they govern and are never emitted
    as requirements themselves.
    Raises ValueError when no enforceable feature is selected.
    """
    from policy_engine import Policy, FEATURES

    rows = by_feature()
    seen: dict[str, str] = {}          # feature -> best tier chosen
    excluded: dict[str, str] = {}      # feature -> why excluded
    queue: list[str] = []
    for raw in (x.strip().upper() for x in features if x and x.strip()):
        if raw in MASTER_CASCADE:
            # the header has no mechanism of its own, so it is never emitted as a
            # requirement; it is judged through the lanes it actually governs
            queue.extend(MASTER_CASCADE[raw])
        else:
            queue.append(raw)
    for f in queue:
        if f not in FEATURES:
            excluded[f] = "externo al vocabulario de la plataforma"
            continue
        cand = rows.get(f)
        if not cand:
            excluded[f] = "no en el catálogo ManageEngine"
            continue
        tiers = {c["tier"] for c in cand}
        if tiers & ENFORCEABLE_TIERS:
            seen[f] = next(c["tier"] for c in cand if c["tier"] in ENFORCEABLE_TIERS)
        elif "VENDOR_DEPENDENT" in tiers:
            excluded[f] = "requiere APIs OEM/Knox — no se puede garantizar"
        else:
            excluded[f] = "sin mecanismo real — no se falsifica cumplimiento"
    if not seen:
        raise ValueError(
            "no enforceable features selected; excluded: " + ", ".join(sorted(excluded)))
    from policy_engine import Policy as _P
    p = _P("POL-CUST-ME", name or "سياسة القيود", "CORPORATE_DEFAULT",
           version=1, status="DRAFT", change_reason="built from ManageEngine catalog")
    for f, tier in sorted(seen.items()):
        note = "catalog " + tier.lower()
        p.add(f, "BLOCK", risk, method=note, fallback=note)
    applied, dropped = sorted(seen), sorted(excluded)
    return p, applied, dropped