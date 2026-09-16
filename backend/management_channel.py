"""Management Channel Protection.

Before a REAL policy delivery may restrict lanes that can sever the ONLY
administrative uplink (ADB/USB/developer-tools lanes on Samsung-family
devices), the platform must prove that a separate, non-destructive recovery
path exists.  If it cannot, the delivery is BLOCKED with an explicit reason.

Design rule (emergency-recovery architecture):
    - CRITICAL_FEATURES: lanes whose enforcement can take down the uplink.
      * ADB / DEVELOPER_OPTIONS  -> DISALLOW_DEBUGGING_FEATURES (kills adb).
      * USB / USB_NETWORKING     -> DISALLOW_USB_FILE_TRANSFER; on Samsung
        builds also drops the adb USB function (observed on SM-J337P/A9).
    - A delivery that targets any of these is only allowed when a recovery
      channel is demonstrated available: (a) the live adb uplink is present
      and testable, (b) the on-device DPC exposes an in-app rollback, or
      (c) the per-device recovery credential exists AND the recovery engine
      can run independently of the disabled lane.
    - Absence of a recovery path => ApplyBlocked, prior to any command send.
"""
from __future__ import annotations

import os
from typing import List, Optional

from .db import connect
from .workflows import attached_serials  # noqa: F401  (re-exported for callers)


CRITICAL_FEATURES = frozenset({"ADB", "DEVELOPER_OPTIONS", "USB", "USB_NETWORKING"})


class RecoveryChannelError(Exception):
    """Recovery-channel gate failure (applies only when its strict flag is on)."""


def _attach_state(db_path, device_id, serial):
    """Read device row + recovery credential presence (honest, read-only).

    backend.db.connect() returns a raw sqlite3.Connection whose `with` block
    only scopes a transaction — the connection is closed explicitly here so
    Windows can release the file immediately (tests use temp dirs)."""
    serial_out = serial
    credential = False
    conn = connect(db_path)
    try:
        dev = conn.execute("SELECT serial, model, control_channel FROM devices "
                           "WHERE device_id=?", (device_id,)).fetchone()
        if dev and not serial_out:
            serial_out = dev["serial"]
        cred = conn.execute("SELECT revoked FROM recovery_credentials "
                            "WHERE device_id=? ", (device_id,)).fetchone()
        credential = bool(cred and not cred["revoked"])
    finally:
        conn.close()
    return {"serial": serial_out, "credential": bool(credential)}


def management_channel_status(device_id: str, *,
                              db_path: Optional[str] = None,
                              serial: Optional[str] = None,
                              attached: Optional[bool] = None,
                              dpc_in_app_rollback: bool = False) -> dict:
    """Assess which administrative/recovery uplinks are available right now."""
    info = _attach_state(db_path, device_id, serial)
    channel_alive = attached if attached is not None else (
        bool(info["serial"]) and info["serial"] in attached_serials())
    channels = {
        "adb_live": bool(channel_alive),
        "dpc_in_app_rollback": bool(dpc_in_app_rollback),
        "recovery_engine": bool(info["credential"]),
    }
    available = [k for k, v in channels.items() if v]
    return {
        "device_id": device_id,
        "serial": info["serial"],
        "credential_issued": info["credential"],
        "channels": channels,
        "available": available,
        "blocked": not available,
        "summary": "recovery channel available: "
                   + (", ".join(available) if available else "NONE"),
    }


def check_recovery_channel(device_id: str,
                           features: List[str], *,
                           db_path: Optional[str] = None,
                           serial: Optional[str] = None,
                           attached: Optional[bool] = None,
                           dpc_in_app_rollback: bool = False,
                           strict: bool = True) -> dict:
    """Gate that blocks REAL deliveries touching channel-critical lanes.

    Returns a dict (always, even when blocked).  When strict and blocked it
    raises RecoveryChannelError with the honest reason.
    """
    critical = sorted(set(features) & CRITICAL_FEATURES)
    result = management_channel_status(
        device_id, db_path=db_path, serial=serial,
        attached=attached, dpc_in_app_rollback=dpc_in_app_rollback)
    result["critical_lanes"] = critical
    result["allowed"] = True
    result["reason"] = ""
    if critical and result["blocked"]:
        result["allowed"] = False
        result["reason"] = (
            f"delivery targets channel-critical lane(s) {critical} but no "
            f"recovery channel is available: {result['summary']}")
        if strict:
            raise RecoveryChannelError(result["reason"])
    return result