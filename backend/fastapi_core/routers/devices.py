"""Devices & ADB Router for ALP FastAPI Core."""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional, Any, Dict
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from pydantic import BaseModel

_CACHE_DETECTED = {"ts": 0.0, "data": []}
_CACHE_ADB_STATUS = {"ts": 0.0, "data": {}}
_CACHE_TTL = 2.0  # 2 seconds fast in-memory cache
_PROBED_ATTACHED: set[str] = set()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.db import connect  # noqa: E402
from backend.workflows import (  # noqa: E402
    attached_serials,
    enroll_device,
    install_agent_app,
    provision_device_owner,
    reset_device_policies,
    delete_device,
)
from backend.fastapi_core.security import get_current_session, authorize_action  # noqa: E402
from backend.fastapi_core.routers.auth import get_controller  # noqa: E402
from backend.fastapi_core.websocket_manager import ws_manager  # noqa: E402

router = APIRouter(prefix="/api/v1", tags=["Devices & ADB"])


def fetch_devices_list():
    with connect() as c:
        rows = c.execute(
            """
            SELECT d.device_id, d.serial, d.manufacturer, d.model, d.android_version, d.api_level,
                   d.enrollment_state, d.compliance_state, d.is_lab, d.last_verification_at,
                   m.device_capacity, m.available_device_capacity, m.os_version, m.product_name,
                   m.battery_level, m.total_ram_memory, m.available_ram_memory, m.device_type,
                   m.is_rooted, m.encryption_status,
                   n.wifi_mac, n.wifi_ip, n.bluetooth_mac
            FROM devices d
            LEFT JOIN mddeviceinfo m ON m.device_id = d.device_id
            LEFT JOIN mdnetworkinfo n ON n.device_id = d.device_id
            ORDER BY d.id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_device_details(did: str) -> dict:
    import json
    with connect() as c:
        row = c.execute(
            "SELECT * FROM devices WHERE device_id=? OR serial=? OR id=?",
            (did, did, int(did) if did.isdigit() else -1),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"device {did} not found")
        dev = dict(row)
        dev_id = dev["id"]

        group_rows = c.execute(
            """
            SELECT g.id, g.group_key, g.name, g.description, g.membership_type, g.platform_type,
                   dgm.added_at AS associated_time, dgm.added_by AS associated_by,
                   (SELECT COUNT(*) FROM device_group_members WHERE group_id=g.id) AS member_count,
                   'Applied' AS status
            FROM device_groups g
            JOIN device_group_members dgm ON dgm.group_id = g.id
            WHERE dgm.device_id = ?
            ORDER BY g.name
            """,
            (dev_id,),
        ).fetchall()
        dev["groups"] = [dict(g) for g in group_rows]

        profile_rows = c.execute(
            """
            SELECT p.id, p.policy_id, p.display_name AS name, p.version, p.status, p.requirements,
                   COALESCE(gpa.assigned_at, a.applied_at) AS associated_time,
                   COALESCE(gpa.assigned_by, 'admin') AS associated_by,
                   'Associated' AS association_status
            FROM policies p
            LEFT JOIN group_profile_assignments gpa ON gpa.policy_id = p.id
            LEFT JOIN device_group_members dgm ON dgm.group_id = gpa.group_id AND dgm.device_id = ?
            LEFT JOIN assignments a ON a.policy_id = p.id AND a.device_id = ?
            WHERE (dgm.device_id IS NOT NULL OR a.device_id IS NOT NULL)
            GROUP BY p.id
            ORDER BY p.display_name
            """,
            (dev_id, dev_id),
        ).fetchall()
        profiles = []
        for pr in profile_rows:
            p_dict = dict(pr)
            if p_dict.get("requirements"):
                try:
                    p_dict["requirements"] = json.loads(p_dict["requirements"])
                except Exception:
                    pass
            profiles.append(p_dict)
        dev["profiles"] = profiles

        # Compliance record with real feature state breakdown
        comp_row = c.execute(
            """
            SELECT result, details, checked_at
            FROM compliance
            WHERE device_id = ?
            ORDER BY checked_at DESC LIMIT 1
            """,
            (dev_id,),
        ).fetchone()
        if comp_row:
            cd = dict(comp_row)
            if cd.get("details"):
                try:
                    cd["details"] = json.loads(cd["details"])
                except Exception:
                    pass
            dev["compliance"] = cd
        else:
            dev["compliance"] = None

        # Recovery credentials
        rec_row = c.execute(
            """
            SELECT recovery_id, created_at, revoked
            FROM recovery_credentials
            WHERE device_id = ? OR device_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (dev["device_id"], str(dev["id"])),
        ).fetchone()
        dev["recovery"] = dict(rec_row) if rec_row else None

        # Audit logs
        audit_rows = c.execute(
            """
            SELECT entry_id, actor, role, action, result, previous_state, new_state, reason, created_at
            FROM audit_logs
            WHERE device_id = ? OR device_id = ? OR device_id = ?
            ORDER BY created_at DESC LIMIT 50
            """,
            (dev["device_id"], dev.get("serial") or "", str(dev["id"])),
        ).fetchall()
        dev["audit_logs"] = [dict(a) for a in audit_rows]

    from backend import device_inventory
    did = dev["device_id"]
    serial = dev.get("serial")

    # 1. ALWAYS retrieve stored inventory from SQLite immediately (0ms delay)
    inv = device_inventory.get_device_inventory(did)

    # 2. Only if device has never been inventoried before and is attached, probe once
    if not inv or not inv.get("mddeviceinfo"):
        from backend import workflows
        if serial and serial in workflows.attached_serials():
            try:
                inv = device_inventory.probe_and_persist_device_inventory(serial or did)
            except Exception:
                inv = device_inventory.get_device_inventory(did)
        if not inv:
            inv = device_inventory.get_device_inventory(did)

    if inv:
        dev["mddeviceinfo"] = inv.get("mddeviceinfo") or {}
        dev["mdnetworkinfo"] = inv.get("mdnetworkinfo") or {}
        dev["hardware"] = inv.get("hardware") or {}
        dev["network"] = inv.get("network") or {}
        if inv.get("installed_apps"):
            dev["apps"] = inv["installed_apps"]
            dev["installed_packages"] = {
                "third_party": [a["package_name"] for a in inv["installed_apps"] if a.get("app_type") == "Third-Party App"],
                "system": [a["package_name"] for a in inv["installed_apps"] if a.get("app_type") != "Third-Party App"]
            }

    # 3. Dynamic background refresh: check dynamic stats (free space, battery) in background
    # This NEVER blocks the HTTP response! Response returns in 3-5ms directly from SQLite!
    if serial:
        device_inventory.refresh_dynamic_stats_background(serial, did)

    return dev


# ---- Schemas ----
class EnrollRequest(BaseModel):
    serial: Optional[str] = None
    device_id: Optional[str] = None
    device_owner: Optional[bool] = False
    lab: Optional[bool] = False
    mfa: Optional[str] = ""


class InstallAgentRequest(BaseModel):
    serial: Optional[str] = ""
    device_id: Optional[str] = ""
    variant: Optional[str] = "auto"
    launch: Optional[bool] = True
    mfa: Optional[str] = ""


class ProvisionOwnerRequest(BaseModel):
    serial: Optional[str] = ""
    device_id: Optional[str] = ""
    variant: Optional[str] = "auto"
    launch: Optional[bool] = True
    mfa: Optional[str] = ""


class ResetPoliciesRequest(BaseModel):
    device_id: str
    serial: Optional[str] = None
    mfa: Optional[str] = ""


class DeleteDeviceRequest(BaseModel):
    reason: Optional[str] = "delete device"
    mfa: Optional[str] = ""
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False
    force: Optional[bool] = False


class DeviceActionRequest(BaseModel):
    action: str
    params: Optional[Dict[str, Any]] = None
    mfa: Optional[str] = ""


# ---- Endpoints ----
@router.get("/devices")
def list_devices(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": fetch_devices_list()}


@router.post("/devices/enroll")
def enroll(req: EnrollRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    serial = req.serial or (attached_serials() or [None])[0]
    if not serial:
        raise HTTPException(status_code=400, detail="no serial given and no device attached via ADB")
    info = enroll_device(req.device_id, serial, device_owner=bool(req.device_owner), lab=bool(req.lab))
    ws_manager.broadcast_from_thread("devices", {"device_id": req.device_id, "action": "enroll", "event": "enrolled"})
    return {"ok": True, "data": info}


@router.post("/devices/install-agent")
def install_agent(req: InstallAgentRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    info = install_agent_app(
        serial=req.serial,
        device_id=req.device_id,
        variant=req.variant,
        launch=bool(req.launch),
    )
    if not info.get("installed"):
        raise HTTPException(status_code=409, detail=info.get("error") or "agent install failed")
    ws_manager.broadcast_from_thread("devices", {"device_id": req.device_id or req.serial, "action": "install_agent", "event": "installed"})
    return {"ok": True, "data": info}


@router.post("/devices/provision-device-owner")
def provision_owner(req: ProvisionOwnerRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    try:
        info = provision_device_owner(
            serial=req.serial,
            device_id=req.device_id,
            variant=req.variant,
            launch=bool(req.launch),
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))

    if not info.get("device_owner"):
        raise HTTPException(
            status_code=409,
            detail=info.get("error") or info.get("hint") or "device-owner provisioning did not complete",
        )
    ws_manager.broadcast_from_thread("devices", {"device_id": req.device_id or req.serial, "action": "provision_owner", "event": "provisioned"})
    return {"ok": True, "data": info}


def _ensure_background_device_inventory(serial: str):
    if serial in _PROBED_ATTACHED:
        return
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM mddeviceinfo WHERE serial_number=? OR device_id=? LIMIT 1",
            (serial, f"AVD-{serial}")
        ).fetchone()
        if row:
            _PROBED_ATTACHED.add(serial)
            return

    # Device plugged in via USB and never inventoried: probe once in background!
    _PROBED_ATTACHED.add(serial)
    def _worker():
        try:
            from backend import device_inventory
            print(f"[devices] Auto-probing attached device inventory in background: {serial}")
            device_inventory.probe_and_persist_device_inventory(serial)
        except Exception as e:
            print(f"[devices] Background auto-probe error for {serial}: {e}")
    threading.Thread(target=_worker, daemon=True).start()


@router.get("/devices/detected")
def detected_devices(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    now = time.time()
    if now - _CACHE_DETECTED["ts"] < _CACHE_TTL:
        return {"ok": True, "data": _CACHE_DETECTED["data"]}
    data = get_controller().detected()
    _CACHE_DETECTED["ts"] = now
    _CACHE_DETECTED["data"] = data

    # Auto-seed inventory in background upon first connection if missing
    for d in data:
        s = d.get("serial")
        if s and d.get("ready"):
            _ensure_background_device_inventory(s)

    return {"ok": True, "data": data}


@router.post("/devices/reset-policies")
def reset_policies(req: ResetPoliciesRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    try:
        result = reset_device_policies(req.device_id, serial=req.serial)
        ws_manager.broadcast_from_thread("devices", {"device_id": req.device_id, "action": "reset_policies", "event": "reset"})
        return {"ok": True, "data": result}
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.get("/devices/{did}/details")
def device_details(did: str, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": fetch_device_details(did)}


@router.post("/devices/{did}/scan")
def scan_device_endpoint(did: str, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", require_mfa=False)
    from backend import device_inventory
    inv = device_inventory.probe_and_persist_device_inventory(did)
    ws_manager.broadcast_from_thread("devices", {"device_id": did, "action": "scan", "event": "scanned"})
    return {"ok": True, "data": inv}


@router.post("/devices/{did}/action")
def trigger_device_action(
    did: str,
    req: DeviceActionRequest,
    sess: dict = Depends(get_current_session)
):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    from backend import device_actions
    actor = sess.get("username") or "admin"
    role = sess.get("role") or "SUPER_ADMIN"
    result = device_actions.execute_device_action(
        device_id=did,
        action=req.action,
        params=req.params or {},
        actor=actor,
        role=role
    )
    ws_manager.broadcast_from_thread("devices", {"device_id": did, "action": req.action, "result": result, "event": "action_executed"})
    return {"ok": result.get("ok", True), "data": result}


@router.delete("/devices/{did}")
def delete_device_endpoint(did: str, req: DeleteDeviceRequest, sess: dict = Depends(get_current_session)):
    authorize_action(
        sess,
        "RETIRE",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "delete device",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        res = delete_device(did, force=bool(req.force))
        ws_manager.broadcast_from_thread("devices", {"device_id": did, "action": "delete", "event": "deleted"})
        return {"ok": True, "data": res}
    except ValueError as ex:
        raise HTTPException(status_code=409, detail=str(ex))


@router.get("/adb/status")
def adb_status(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    now = time.time()
    if now - _CACHE_ADB_STATUS["ts"] < _CACHE_TTL:
        return {"ok": True, "data": _CACHE_ADB_STATUS["data"]}
    data = get_controller().adb_status()
    _CACHE_ADB_STATUS["ts"] = now
    _CACHE_ADB_STATUS["data"] = data
    return {"ok": True, "data": data}


@router.get("/devices/preflight")
def device_preflight(
    device_id: str = Query(""),
    policy: str = Query(""),
    sess: dict = Depends(get_current_session),
):
    authorize_action(sess, "APPLY", require_mfa=False)
    return {"ok": True, "data": get_controller().preflight(device_id, policy)}


@router.get("/devices/policy-preview")
def device_policy_preview(
    device_id: str = Query(""),
    policy: str = Query(""),
    sess: dict = Depends(get_current_session),
):
    authorize_action(sess, "APPLY", require_mfa=False)
    return {"ok": True, "data": get_controller().policy_preview(device_id, policy)}


@router.get("/devices/capabilities")
def device_capabilities(
    device_id: str = Query(""),
    sess: dict = Depends(get_current_session),
):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": get_controller().capabilities(device_id)}


# ---- Agent Self-Service Pull ----
async def _handle_agent_policy(request: Request):
    from backend.agent_policy_pull import policy_for_device, build_apply_envelope
    from backend.config import signing_key as _key

    q = request.query_params.get("device_id", "")
    serial = request.query_params.get("serial", "")
    build_flag = request.method == "POST" or request.query_params.get("build") == "1"

    if request.method == "POST":
        try:
            body = await request.json()
            q = q or body.get("device_id", "")
            serial = serial or body.get("serial", "")
        except Exception:
            pass

    if not q and not serial:
        raise HTTPException(status_code=400, detail="device_id or serial is required")

    if build_flag:
        return {"ok": True, "data": build_apply_envelope(q, serial, _key())}
    return {"ok": True, "data": policy_for_device(q, serial)}


@router.get("/agent/policy")
async def get_agent_policy(request: Request):
    return await _handle_agent_policy(request)


@router.post("/agent/policy")
async def post_agent_policy(request: Request):
    return await _handle_agent_policy(request)
