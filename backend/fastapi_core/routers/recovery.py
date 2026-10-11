"""Recovery Vault, Emergency Offline PINs Router for ALP FastAPI Core."""
from __future__ import annotations

import os
import sys
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.pins import provision_pin as _provision_pin  # noqa: E402
from backend.fastapi_core.security import get_current_session, authorize_action  # noqa: E402
from backend.fastapi_core.routers.auth import get_controller  # noqa: E402

CHAN_DIR = os.path.join(PROJECT_ROOT, "reports", "phase1", "commands")


def get_signing_key():
    from backend.config import signing_key
    return signing_key()


router = APIRouter(prefix="/api/v1", tags=["Recovery & Emergency Tokens"])


# ---- Schemas ----
class PinProvisionRequest(BaseModel):
    device_id: str
    pin: Optional[str] = ""
    serial: Optional[str] = ""
    mfa: Optional[str] = ""


class RecoveryRequest(BaseModel):
    device_id: str
    mode: Optional[str] = "R4_DIAGNOSTIC"
    approver1: Optional[str] = ""
    approver2: Optional[str] = ""
    reason: Optional[str] = ""
    skip_approval: Optional[bool] = False
    serial: Optional[str] = ""
    exec: Optional[bool] = False
    mfa: Optional[str] = ""


class VaultActionRequest(BaseModel):
    action: str  # rotate | revoke | issue
    device_id: str
    mfa: Optional[str] = ""


class EmergencyIssueRequest(BaseModel):
    device_id: str
    label: Optional[str] = ""
    ttl_hours: Optional[int] = 24
    purpose: Optional[str] = "withdraw_uninstall"
    reason: Optional[str] = "emergency token"
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False
    mfa: Optional[str] = ""


class EmergencyProvisionRequest(BaseModel):
    device_id: str
    serial: Optional[str] = ""
    ttl_hours: Optional[int] = 24
    purpose: Optional[str] = "withdraw_uninstall"
    reason: Optional[str] = "provision token"
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False
    mfa: Optional[str] = ""


class EmergencyOfflineCodeRequest(BaseModel):
    device_id: str
    purpose: Optional[str] = "withdraw_uninstall"
    reason: Optional[str] = "offline code"
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False
    mfa: Optional[str] = ""


class EmergencyRevokeRequest(BaseModel):
    token_id: str
    mfa: Optional[str] = ""


# ---- Endpoints ----
@router.post("/pin/provision")
def provision_pin_endpoint(req: PinProvisionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    out = _provision_pin(req.device_id, req.pin or "", serial=req.serial or "", chan_dir=CHAN_DIR)
    return {"ok": True, "data": out}


@router.get("/recovery")
def get_recovery_status(
    device_id: str = Query(""),
    sess: dict = Depends(get_current_session),
):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": get_controller().recovery_status(device_id)}


@router.post("/recovery")
def trigger_recovery(req: RecoveryRequest, sess: dict = Depends(get_current_session)):
    approved = bool(req.skip_approval) or bool(req.approver1)
    authorize_action(
        sess,
        "RECOVER",
        mfa=req.mfa or "",
        approval={
            "approved": approved,
            "reason": req.reason or "web console",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        out = get_controller().recover(
            req.device_id,
            req.mode or "R4_DIAGNOSTIC",
            approver1=req.approver1 or "",
            approver2=req.approver2 or "",
            reason=req.reason or "",
            skip_approval=bool(req.skip_approval),
            serial=req.serial or "",
            exec_=bool(req.exec),
        )
        d = out if isinstance(out, dict) else {"result": str(out)}
        return {"ok": True, "data": d}
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))


@router.get("/recovery/vault")
def recovery_vault_summary(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": get_controller().recovery_vault_summary()}


@router.post("/recovery/vault")
def recovery_vault_action(req: VaultActionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(
        sess,
        "RECOVER",
        mfa=req.mfa or "",
        approval={"approved": True, "reason": f"vault {req.action}", "dual": False},
    )
    if req.action == "rotate":
        out = get_controller().rotate_recovery(req.device_id)
    elif req.action == "revoke":
        out = get_controller().revoke_recovery(req.device_id)
    elif req.action == "issue":
        out = get_controller().issue_recovery(req.device_id)
    else:
        raise HTTPException(status_code=400, detail="vault action must be rotate|revoke|issue")
    return {"ok": True, "data": out}


# ---- Emergency Offline Tokens ----
@router.post("/recovery/emergency/issue")
def issue_emergency_token(req: EmergencyIssueRequest, sess: dict = Depends(get_current_session)):
    from backend import emergency as _emg

    authorize_action(
        sess,
        "RECOVER",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "emergency token",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        return {
            "ok": True,
            "data": _emg.issue_token(
                req.device_id,
                created_by=sess["username"],
                label=req.label or "",
                ttl_hours=int(req.ttl_hours or 24),
                purpose=req.purpose or "withdraw_uninstall",
            ),
        }
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/recovery/emergency/provision")
def provision_emergency_token(
    req: EmergencyProvisionRequest, sess: dict = Depends(get_current_session)
):
    from backend import emergency as _emg

    authorize_action(
        sess,
        "RECOVER",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "provision token",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        return {
            "ok": True,
            "data": _emg.provision_token(
                req.device_id,
                serial=req.serial or "",
                signing_key_=get_signing_key(),
                chan_dir=CHAN_DIR,
                ttl_hours=int(req.ttl_hours or 24),
                created_by=sess["username"],
                purpose=req.purpose or "withdraw_uninstall",
            ),
        }
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/recovery/emergency/offline-code")
def offline_code_token(
    req: EmergencyOfflineCodeRequest, sess: dict = Depends(get_current_session)
):
    from backend import emergency as _emg

    authorize_action(
        sess,
        "RECOVER",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "offline code",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        return {
            "ok": True,
            "data": _emg.offline_code(
                req.device_id, req.purpose or "withdraw_uninstall"
            ),
        }
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/recovery/emergency/revoke")
def revoke_emergency_token(
    req: EmergencyRevokeRequest, sess: dict = Depends(get_current_session)
):
    from backend import emergency as _emg

    authorize_action(sess, "RECOVER", mfa=req.mfa or "")
    try:
        return {
            "ok": True,
            "data": _emg.revoke_token(req.token_id, by=sess["username"]),
        }
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.get("/recovery/emergency")
def list_emergency_tokens(
    device_id: str = Query(""),
    sess: dict = Depends(get_current_session),
):
    from backend import emergency as _emg

    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": _emg.list_tokens(device_id)}
