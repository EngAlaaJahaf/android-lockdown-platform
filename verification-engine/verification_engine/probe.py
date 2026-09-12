"""Live device probe — collect REAL, observable device state over ADB.

Used by the VerificationEngine (source=REAL_DEVICE) and by Recovery R4/R1.
The probe only records what ADB could actually observe:

  identity      getprop (brand / model / version / api / fingerprint)
  settings      settings get global|secure for readable radio flags
  restrictions  active UserManager restrictions parsed from dumpsys device_policy
  dpc           the DPC's own state.json via run-as (applied lanes, last cmd)

"observed" normalizes the facts into a {feature: value} map with values
ON | OFF | RESTRICTED, where RESTRICTED means an enforcement restriction is
currently ACTIVE on the device (proof available). Missing lanes are simply
absent — the verification engine must treat them as UNKNOWN, never as PASS.

Honesty rule: a lane is only reported as RESTRICTED when `dumpsys device_policy`
literally lists the restriction; settings values only when readable.
"""
from __future__ import annotations

import json
import os
import subprocess

from . import VerificationResult  # noqa: F401  (re-exported convenience)


# UserManager restriction constant -> feature vocabulary used by ALP.
RESTRICTION_FEATURES = {
    "no_config_wifi": "WIFI",
    "no_bluetooth": "BLUETOOTH",
    "no_config_tethering": "TETHERING",
    "no_usb_file_transfer": "USB",
    "no_config_vpn": "VPN",
    "no_unmute_microphone": "MICROPHONE",
    "no_debugging_features": "ADB",
    "no_safe_boot": "SAFE_BOOT",
    "no_factory_reset": "FACTORY_RESET",
    "no_install_unknown_sources": "APP_INSTALLATION",
    "no_modify_accounts": "ACCOUNTS",
    "no_share_location": "LOCATION",
    "no_background_data": "MOBILE_DATA",
    "no_data_roaming": "MOBILE_DATA",
    "no_ethernet": "ETHERNET",
    "no_config_credentials": "VPN",
}


def _adb(serial: str):
    a = os.environ.get("ALP_ADB")
    if a:
        return a
    home = os.environ.get("ANDROID_HOME") or os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk")
    candidate = os.path.join(home, "platform-tools", "adb.exe")
    return candidate if os.path.exists(candidate) else "adb"


def _run(serial: str, *args: str):
    try:
        r = subprocess.run([_adb(serial), "-s", serial, *args],
                           capture_output=True, text=True, timeout=25)
        return (r.returncode, r.stdout)
    except Exception:
        return (-1, "")


def _parse_restrictions(dumpsys: str) -> dict:
    """Extract ACTIVE restrictions -> {feature: restriction_key} (only proven ones).

    dumpsys device_policy lists active restrictions as lines such as:
        no_config_wifi=true        (modern, 'User restrictions:' section)
        no_config_wifi: true       (older dump formats)
    A restriction is reported active ONLY when the token is observed with a
    true value in the dump. It is never inferred from absence.
    """
    active = {}
    lines = dumpsys.splitlines()
    for tok, feat in RESTRICTION_FEATURES.items():
        proven = False
        for ln in lines:
            if tok not in ln:
                continue
            after = ln.split(tok, 1)[1]
            if "false" in after.split("true", 1)[0]:
                continue                     # explicitly false line wins
            if "true" in after:
                proven = True
                break
            stripped = after.strip().lstrip("=: \t")
            if stripped == "true" or after.strip().startswith("="):
                if after.strip().startswith("="):
                    proven = "true" in after
                    break
        if proven:
            active.setdefault(feat, tok)
    return active


def _read_settings(serial: str) -> dict:
    settings = {}
    probes = [("global", "wifi_on", "WIFI"), ("global", "airplane_mode_on", "MOBILE_DATA"),
              ("secure", "location_mode", "LOCATION"), ("secure", "adb_enabled", "ADB")]
    for scope, key, feat in probes:
        rc, out = _run(serial, "shell", "settings", "get", scope, key)
        v = out.strip()
        if rc == 0 and v in ("1", "0"):
            settings[feat] = "ON" if v == "1" else "OFF"
    return settings


def _read_dpc_state(serial: str) -> dict | None:
    rc, out = _run(serial, "shell", "run-as", "com.alp.agent", "cat", "files/state.json")
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except Exception:
        return {"raw": out[:500]}
    return data if isinstance(data, dict) else {"raw": out[:500]}


def probe_live_device(serial: str) -> dict:
    """Full honest observation bundle for a single attached device."""
    rc, prop_out = _run(serial, "shell", "getprop")
    props = {}
    if rc == 0:
        for ln in prop_out.splitlines():
            if ln.startswith("[") and "]: [" in ln:
                k, _, v = ln[1:].partition("]: [")
                props[k] = v.rstrip("]")

    rc, dp_out = _run(serial, "shell", "dumpsys", "device_policy")
    restrictions = _parse_restrictions(dp_out) if rc == 0 else {}

    settings = _read_settings(serial)
    dpc = _read_dpc_state(serial)

    observed = dict(settings)
    for feat in restrictions:
        observed[feat] = "RESTRICTED"          # enforcement restriction proven active
    # A restriction overrides a stale settings read (restriction is the stronger proof).
    for feat in restrictions:
        if feat in ("WIFI", "ADB"):
            observed[feat] = "RESTRICTED"

    return {
        "identity": {
            "serial": serial,
            "manufacturer": props.get("ro.product.brand", ""),
            "model": props.get("ro.product.model", ""),
            "android_version": props.get("ro.build.version.release", ""),
            "api_level": props.get("ro.build.version.sdk", ""),
            "build_fingerprint": props.get("ro.build.fingerprint", ""),
            "device_owner": ("Device Owner" in dp_out or "device owner" in (dp_out or "").lower()),
        },
        "restrictions": restrictions,
        "observed": observed,
        "dpc": dpc,
        "source": "REAL_DEVICE",
    }