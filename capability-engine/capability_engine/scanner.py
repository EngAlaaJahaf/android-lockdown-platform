"""Capability scanning.

Two real sources:
  1. adb_scan():      reads live properties via `adb shell getprop` (real device/emulator).
  2. agent_report():  ingests the capability report supplied by the on-device DPC agent.

No value is invented. Anything not readable at scan time stays UNKNOWN.
"""
from __future__ import annotations

import subprocess
import re
import sys

from . import CapabilityProfile, CapabilityState, ClassTag

_NO_WINDOW = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
              if sys.platform == "win32" else 0)

ANDROID_VERSION_MAP = {
    "7": 7, "7.0": 7, "7.1": 7, "7.1.1": 7, "7.1.2": 7,
    "8": 8, "8.0": 8, "8.1": 8,
    "9": 9, "9.0": 9,
    "10": 10, "11": 11, "12": 12, "12L": 12, "13": 13, "14": 14, "15": 15,
    "16": 16,
}


def _version_to_api(android_version: Optional[int]) -> Optional[int]:
    if not android_version:
        return None
    map_api = {7: 24, 8: 26, 9: 28, 10: 29, 11: 30, 12: 31, 13: 33, 14: 34, 15: 35, 16: 36}
    return map_api.get(android_version)


def adb_scan(adb: str = "adb", serial: Optional[str] = None) -> CapabilityProfile:
    """Scan a connected device/emulator via `adb shell getprop`.

    Raises RuntimeError if no device is attached.
    """
    def run(*args: str) -> str:
        cmd = [adb] + (["-s", serial] if serial else []) + list(args)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           creationflags=_NO_WINDOW or 0)
        if r.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout.strip()

    props = {}
    for p in run("shell", "getprop").splitlines():
        m = re.match(r"^\[([^\]]+)\]: \[(.*)\]$", p)
        if m:
            props[m.group(1)] = m.group(2)

    def g(key: str, default: str = "") -> str:
        return props.get(key, default)

    ver_str = g("ro.build.version.release", "0")
    ver = _parse_version(ver_str)
    api = int(g("ro.build.version.sdk", "0") or 0) or _version_to_api(ver)
    br = g("ro.product.brand")
    md = g("ro.product.model")
    fp = g("ro.build.fingerprint")

    prof = CapabilityProfile(
        android_version=ver or 0,
        api_level=api or 0,
        manufacturer=br,
        model=md,
        build_fingerprint=fp,
        # Extended identity — only populated from real getprop values; anything
        # the device does not expose stays "" (honest: never guessed).
        security_patch=g("ro.build.version.security_patch"),
        kernel_version=_kernel_version(run),
        bootloader=g("ro.boot.bootloader"),
        verified_boot=g("ro.boot.verifiedbootstate"),
        encryption=g("ro.crypto.state"),
        baseband=g("gsm.version.baseband"),
    )

    # ---- Honest feature assessment from readable state (device owner NOT yet enforced) ----
    # The scan records the OS-level facts we can prove here. Policy support is
    # derived by the compatibility layer per API level; the scanner only adds
    # facts that are observable now.
    _apply_observable_os_facts(prof, props, api)
    return prof


def _parse_version(s: str) -> Optional[int]:
    m = re.match(r"\d+", s)
    if not m:
        return None
    n = int(m.group(0))
    return n if 6 <= n <= 16 else None


def _kernel_version(run) -> str:
    """`uname -r` -> kernel release string; '' if unreadable (honest)."""
    try:
        out = run("shell", "uname", "-r")
    except Exception:
        return ""
    return (out or "").strip()[:64]


def _apply_observable_os_facts(prof: CapabilityProfile, props: dict, api: Optional[int]):
    # These are OS-level, present per-API facts about enforcement feasibility.
    # They are VERSION-DEPENDENT, not "SUPPORTED": final support requires lab
    # evidence (assignments.verify_result) — see §78.
    if api is None:
        return
    if api >= 21:
        for feat in ("CAMERA", "MICROPHONE", "USB", "ADB", "DEVELOPER_OPTIONS",
                     "FACTORY_RESET", "APP_INSTALLATION", "UNKNOWN_SOURCES",
                     "TETHERING", "ACCOUNTS", "USER_MANAGEMENT", "SCREEN_CAPTURE",
                     "APPLICATIONS", "MOBILE_DATA"):
            prof.states[feat] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
            prof.methods[feat] = ["user_restriction_by_api", "dpm_device_owner"]
    if api >= 23:
        prof.states["SAFE_BOOT"] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
        prof.methods["SAFE_BOOT"] = ["user_restriction_disable_safe_boot"]
        prof.states["LOCATION"] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
        prof.methods["LOCATION"] = ["user_restriction_disable_location_services"]
    if api >= 26:
        prof.states["BLUETOOTH"] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
        prof.methods["BLUETOOTH"] = ["user_restriction_disable_bluetooth"]
    if api >= 28:
        prof.states["WIFI"] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
        prof.methods["WIFI"] = ["user_restriction_disable_wifi"]
        prof.states["VPN"] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
        prof.states["BLUETOOTH_PAN"] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
    if api >= 29:
        prof.states["ETHERNET"] = CapabilityState.ANDROID_VERSION_DEPENDENT.value
    # NOT FEASIBLE from an app/DPC layer — vendor/firmware layer only.
    prof.states["FACTORY_RESET_RECOVERY"] = CapabilityState.NOT_FEASIBLE.value
    prof.states["REFLAH_FIRMWARE"] = CapabilityState.NOT_FEASIBLE.value
    prof.class_tags.append(ClassTag.ANDROID_VERSION_DEPENDENT.value)
    # GPS raw hardware off is impossible to fully guarantee from app layer.
    prof.states["GPS"] = CapabilityState.PARTIAL.value
    prof.methods["GPS"] = ["user_restriction_location", "settings"]