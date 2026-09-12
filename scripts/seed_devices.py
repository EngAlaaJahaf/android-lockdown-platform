"""PHASE 0: seed the Device Registry from physical firmware evidence (Lab Only).

Sources (approved plan §5, ALP-BASE-001):
  OS15: F:\root phon\انظمه تفليش\A145PXXS8DYI2_A145POJM8DYI2_XSG\
  OS14: F:\root phon\انظمه تفليش\SAMFW.COM_SM-A145P_XSG_A145PXXS8CYB3_fac\

Honesty rule: only LAB_EVIDENCE / OFFICIAL_DOC become class tags other than
UNKNOWN. Devices with no firmware proof stay UNKNOWN and is_lab=0.
"""
from __future__ import annotations

import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.db import connect
from backend.config import DBPATH

EVIDENCE_OS15 = (r"F:\root phon\انظمه تفليش\A145PXXS8DYI2_A145POJM8DYI2_XSG"
                 r"\AP_A145PXXS8DYI2_A145PXXS8DYI2_MQB100972586_REV00_user_low_ship_MULTI_CERT_meta_OS15.tar.md5")
EVIDENCE_OS14 = (r"F:\root phon\انظمه تفليش\SAMFW.COM_SM-A145P_XSG_A145PXXS8CYB3_fac"
                 r"\AP_A145PXXS8CYB3_A145PXXS8CYB3_MQB92710432_REV00_user_low_ship_MULTI_CERT_meta_OS14.tar.md5")


def evidence_exists(path: str) -> bool:
    return os.path.exists(path)


DEVICES = [
    dict(device_id="LAB-0001", serial="R3CT70027B1", manufacturer="Samsung", model="SM-A145P",
         variant="XSG", build_fingerprint="samsung/a14m/m14:15/A145PXXS8DYI2/U1XBK5:user/release-keys",
         android_version=15, api_level=35, security_patch="2025-04-01",
         bootloader_state="LOCKED", verified_boot_state="GREEN",
         encryption_state="ACTIVE", device_owner_state="NONE", dpc_state="NONE",
         enrollment_state="UNMANAGED", is_lab=1, organization="ALP-Lab",
         firmware_source=EVIDENCE_OS15, os_label="Android 15 (One UI 7)"),
    dict(device_id="LAB-0002", serial="R3CT70027B2", manufacturer="Samsung", model="SM-A145P",
         variant="XSG", build_fingerprint="samsung/a14m/m14:14/A145PXXS8CYB3/U1XBK1:user/release-keys",
         android_version=14, api_level=34, security_patch="2024-06-01",
         bootloader_state="LOCKED", verified_boot_state="GREEN",
         encryption_state="ACTIVE", device_owner_state="NONE", dpc_state="NONE",
         enrollment_state="UNMANAGED", is_lab=1, organization="ALP-Lab",
         firmware_source=EVIDENCE_OS14, os_label="Android 14 (One UI 6)"),
    dict(device_id="DEV-0001", serial=None, manufacturer="Samsung", model="SM-J320FN",
         variant="AUT", build_fingerprint="", android_version=7, api_level=24,
         security_patch="", bootloader_state="UNKNOWN", verified_boot_state="UNKNOWN",
         encryption_state="UNKNOWN", device_owner_state="UNKNOWN", dpc_state="UNKNOWN",
         enrollment_state="UNMANAGED", is_lab=0, organization="Org",
         firmware_source=None, os_label="Android 7 — NO firmware evidence yet"),
]


def main() -> None:
    db_path = os.environ.get("ALP_DB", DBPATH)
    from backend.db import run_migrations
    run_migrations(db_path)
    inserted = 0
    with connect(db_path) as c:
        for d in DEVICES:
            ev = d.get("firmware_source")
            verified = bool(ev and evidence_exists(ev))
            unverified_check = ("<-- " + os.path.abspath(ev)) if ev and not verified else ""
            issq = c.execute("SELECT id FROM devices WHERE device_id=?", (d["device_id"],)).fetchone()
            if not issq:
                c.execute(
                    """INSERT INTO devices (device_id, serial, manufacturer, model, variant,
                       build_fingerprint, android_version, api_level, security_patch,
                       bootloader_state, verified_boot_state, encryption_state,
                       device_owner_state, dpc_state, enrollment_state, is_lab,
                       organization, last_seen_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))""",
                    (d["device_id"], d["serial"], d["manufacturer"], d["model"], d["variant"],
                     d["build_fingerprint"], d["android_version"], d["api_level"], d["security_patch"],
                     d["bootloader_state"], d["verified_boot_state"], d["encryption_state"],
                     d["device_owner_state"], d["dpc_state"], "ENROLLMENT_PENDING", d["is_lab"],
                     d["organization"]))
            else:
                print(f"device {d['device_id']} already registered")
            profile_key = f"{d['model']}|{d['android_version']}|{(d['build_fingerprint'] or '?')[:24]}"
            prof = c.execute("SELECT id FROM device_profiles WHERE profile_key=?",
                             (profile_key,)).fetchone()
            if not prof:
                cur = c.execute(
                    """INSERT INTO device_profiles (profile_key, manufacturer, model, variant,
                       android_version, api_level, build_id, firmware_source, source_of_record,
                       class_tags, verified_at, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (profile_key, d["manufacturer"], d["model"], d["variant"],
                     d["android_version"], d["api_level"],
                     (d.get("build_fingerprint") or "")[:24],
                     d.get("firmware_source"), "LAB_EVIDENCE" if verified else "UNKNOWN",
                     "VERIFIED" if verified else "UNKNOWN",
                     "datetime('now')" if verified else None,
                     d["os_label"]))
                pid = cur.lastrowid
            else:
                pid = prof["id"]
                if verified:
                    # idempotent upgrade when firmware evidence becomes available
                    c.execute(
                        "UPDATE device_profiles SET source_of_record='LAB_EVIDENCE', "
                        "class_tags='VERIFIED', firmware_source=?, verified_at=datetime('now') "
                        "WHERE id=?", (d.get("firmware_source"), pid))
                for feature in ("WIFI", "BLUETOOTH", "CAMERA", "GPS", "ADB", "SAFE_BOOT",
                                "FACTORY_RESET", "TETHERING", "SCREEN_CAPTURE", "USB_FILE",
                                "APP_INSTALLATION", "DEVELOPER_OPTIONS"):
                    c.execute("UPDATE capabilities SET capability=?, evidence_ref=? "
                              "WHERE profile_id=? AND feature=?",
                              ("SUPPORTED" if verified else "UNKNOWN",
                               d.get("firmware_source") or "", pid, feature))
                    print(f"  upgraded capability {feature} on {profile_key} -> "
                          f"{'SUPPORTED' if verified else 'UNKNOWN'}")
            if not prof:
                for feature in ("WIFI", "BLUETOOTH", "CAMERA", "GPS", "ADB", "SAFE_BOOT",
                                "FACTORY_RESET", "TETHERING", "SCREEN_CAPTURE", "USB_FILE",
                                "APP_INSTALLATION", "DEVELOPER_OPTIONS"):
                    cap = "SUPPORTED" if verified else "UNKNOWN"
                    method = "DPM_RESTRICTION|SETTINGS_GLOBAL"
                    c.execute("INSERT INTO capabilities (profile_id, feature, capability, method, evidence_ref) "
                              "VALUES (?,?,?,?,?)",
                              (pid, feature, cap, method, d.get("firmware_source") or ""))
                print(f"registered device profile {profile_key} ({'VERIFIED' if verified else 'UNKNOWN'})" + unverified_check)
            else:
                print(f"profile {profile_key} re-verified -> "
                      f"{'VERIFIED' if verified else 'UNKNOWN'}" + unverified_check)
            inserted += 1
    print(f"seeded {inserted} device rows")


if __name__ == "__main__":
    main()