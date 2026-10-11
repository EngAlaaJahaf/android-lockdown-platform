"""Device Groups Router for ALP FastAPI Core."""
from __future__ import annotations

import json
import os
import sys
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend import groups as G  # noqa: E402
from backend.groups import GroupError  # noqa: E402
from backend.fastapi_core.security import (  # noqa: E402
    get_current_session,
    authorize_action,
    check_mfa_ok,
)

CHAN_DIR = os.path.join(PROJECT_ROOT, "reports", "phase1", "commands")


def get_signing_key():
    from backend.config import signing_key
    return signing_key()


def serial_for_member(member: dict):
    return member.get("serial") or None


router = APIRouter(prefix="/api/v1/groups", tags=["Device Groups"])


# ---- Schemas ----
class CreateGroupRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    membership_type: Optional[str] = "STATIC"
    platform_type: Optional[str] = "ANDROID"
    criteria_json: Optional[Any] = None
    mfa: Optional[str] = ""


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mfa: Optional[str] = ""


class DeleteGroupRequest(BaseModel):
    mfa: Optional[str] = ""
    reason: Optional[str] = "delete group"
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False


class AddMembersRequest(BaseModel):
    device_ids: Optional[List[str]] = None
    device_id: Optional[str] = None
    bulk: Optional[bool] = False
    deploy: Optional[bool] = True
    real: Optional[bool] = False
    allow_channel_risk: Optional[bool] = False
    mfa: Optional[str] = ""
    reason: Optional[str] = "add members"
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False


class MoveMemberRequest(BaseModel):
    to_group: int
    device_id: str
    mfa: Optional[str] = ""


class AssociateProfilesRequest(BaseModel):
    policy_ids: Optional[List[str]] = None
    policy_id: Optional[str] = None
    remarks: Optional[str] = ""
    deploy: Optional[bool] = True
    real: Optional[bool] = False
    allow_channel_risk: Optional[bool] = False
    mfa: Optional[str] = ""
    reason: Optional[str] = "associate profiles"
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False


class DeployGroupRequest(BaseModel):
    device_ids: Optional[List[str]] = None
    policy_ids: Optional[List[str]] = None
    real: Optional[bool] = False
    allow_channel_risk: Optional[bool] = False
    mfa: Optional[str] = ""
    reason: Optional[str] = "deploy group"
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False


# ---- Endpoints ----
@router.get("")
def list_groups(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": G.list_groups()}


@router.post("")
def create_group(req: CreateGroupRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "CREATE", mfa=req.mfa or "")
    try:
        return {
            "ok": True,
            "data": G.create_group(
                req.name,
                req.description or "",
                membership_type=req.membership_type or "STATIC",
                platform_type=req.platform_type or "ANDROID",
                created_by=sess["username"],
                criteria_json=req.criteria_json,
            ),
        }
    except GroupError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.get("/{gid}")
def get_group(gid: int, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": G.get_group(gid, with_members=True, with_profiles=True)}


@router.put("/{gid}")
def update_group(gid: int, req: UpdateGroupRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT", mfa=req.mfa or "")
    try:
        return {
            "ok": True,
            "data": G.update_group(
                gid, name=req.name, description=req.description, modified_by=sess["username"]
            ),
        }
    except GroupError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.delete("/{gid}")
def delete_group(gid: int, req: DeleteGroupRequest, sess: dict = Depends(get_current_session)):
    authorize_action(
        sess,
        "RETIRE",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "delete group",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        return {"ok": True, "data": G.delete_group(gid)}
    except GroupError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.get("/{gid}/members")
def list_group_members(gid: int, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": G.list_group_members(gid)}


@router.post("/{gid}/members")
def add_group_members(gid: int, req: AddMembersRequest, sess: dict = Depends(get_current_session)):
    ids = req.device_ids or ([req.device_id] if req.device_id else [])
    if not ids:
        raise HTTPException(status_code=400, detail="device_ids is required")
    op = "BULK_APPLY" if req.bulk else "APPLY"
    authorize_action(
        sess,
        op,
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "add members",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        return {
            "ok": True,
            "data": G.add_members(
                gid,
                ids,
                op_role=sess["role_code"],
                mfa_ok=check_mfa_ok(sess, req.mfa or ""),
                added_by=sess["username"],
                serial_for=serial_for_member,
                signing_key=get_signing_key(),
                chan_dir=CHAN_DIR,
                deploy=bool(req.deploy),
                real=bool(req.real),
                allow_channel_risk=bool(req.allow_channel_risk),
            ),
        }
    except GroupError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.delete("/{gid}/members/{device_id}")
def remove_group_member(gid: int, device_id: str, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT")
    try:
        return {"ok": True, "data": G.remove_member(gid, device_id)}
    except GroupError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/{gid}/move")
def move_group_member(gid: int, req: MoveMemberRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT", mfa=req.mfa or "")
    try:
        return {
            "ok": True,
            "data": G.move_device(
                gid, req.to_group, req.device_id, moved_by=sess["username"]
            ),
        }
    except GroupError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.get("/{gid}/profiles")
def list_group_profiles(gid: int, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": G.list_group_profiles(gid)}


@router.post("/{gid}/profiles")
def associate_group_profiles(
    gid: int, req: AssociateProfilesRequest, sess: dict = Depends(get_current_session)
):
    ids = req.policy_ids or ([req.policy_id] if req.policy_id else [])
    if not ids:
        raise HTTPException(status_code=400, detail="policy_ids is required")
    authorize_action(
        sess,
        "APPLY",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "associate profiles",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    out = G.associate_profiles(
        gid,
        ids,
        op_role=sess["role_code"],
        mfa_ok=check_mfa_ok(sess, req.mfa or ""),
        assigned_by=sess["username"],
        remarks=req.remarks or "",
        serial_for=serial_for_member,
        signing_key=get_signing_key(),
        chan_dir=CHAN_DIR,
        deploy=bool(req.deploy),
        real=bool(req.real),
        allow_channel_risk=bool(req.allow_channel_risk),
    )
    if out.get("rejected"):
        raise HTTPException(
            status_code=409,
            detail="profiles not eligible for association: "
            + json.dumps(out["rejected"], ensure_ascii=False),
        )
    return {"ok": True, "data": out}


@router.delete("/{gid}/profiles/{policy_id}")
def disassociate_group_profile(
    gid: int, policy_id: str, sess: dict = Depends(get_current_session)
):
    authorize_action(sess, "EDIT")
    try:
        return {"ok": True, "data": G.disassociate_profile(gid, policy_id)}
    except GroupError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/{gid}/deploy")
def deploy_group(gid: int, req: DeployGroupRequest, sess: dict = Depends(get_current_session)):
    authorize_action(
        sess,
        "BULK_APPLY",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "deploy group",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    return {
        "ok": True,
        "data": G.deploy_group(
            gid,
            op_role=sess["role_code"],
            mfa_ok=check_mfa_ok(sess, req.mfa or ""),
            only_devices=req.device_ids,
            only_policies=req.policy_ids,
            serial_for=serial_for_member,
            signing_key=get_signing_key(),
            chan_dir=CHAN_DIR,
            real=bool(req.real),
            allow_channel_risk=bool(req.allow_channel_risk),
        ),
    }


@router.get("/{gid}/status")
def group_status(gid: int, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": G.group_status(gid)}


@router.get("/{gid}/actions")
def list_group_actions(gid: int, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": G.list_group_actions(gid)}
