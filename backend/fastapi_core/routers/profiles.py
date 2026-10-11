"""Profiles, Policies & Restrictions Router for ALP FastAPI Core."""
from __future__ import annotations

import os
import sys
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.db import connect  # noqa: E402
from backend import restrictions, profiles as P  # noqa: E402
from backend.profiles import ProfileConflict, ProfileError  # noqa: E402
from backend.director import ApplyBlocked, DirectorError  # noqa: E402
from backend.workflows import (  # noqa: E402
    create_policy_from_catalog,
    persist_reference_policies,
    run_director_apply,
)
from backend.fastapi_core.security import (  # noqa: E402
    get_current_session,
    authorize_action,
    check_mfa_ok,
)
from backend.fastapi_core.routers.auth import get_controller  # noqa: E402

CHAN_DIR = os.path.join(PROJECT_ROOT, "reports", "phase1", "commands")


def get_signing_key():
    from backend.config import signing_key
    return signing_key()


router = APIRouter(prefix="/api/v1", tags=["Profiles & Restrictions"])


def fetch_policies_list():
    with connect() as c:
        rows = c.execute(
            "SELECT policy_id, display_name, category, version, status, checksum "
            "FROM policies ORDER BY category, policy_id"
        ).fetchall()
    return [dict(r) for r in rows]


# ---- Schemas ----
class RestrictionPolicyRequest(BaseModel):
    features: Optional[List[str]] = []
    name: Optional[str] = ""
    risk: Optional[str] = "MEDIUM"
    mfa: Optional[str] = ""


class CustomPolicyRequest(BaseModel):
    display_name: str
    category: str
    features: Optional[Dict[str, Any]] = {}
    risk: Optional[str] = "MEDIUM"
    mfa: Optional[str] = ""


class ApplyPolicyRequest(BaseModel):
    device_id: str
    policy: str
    mfa: Optional[str] = ""
    serial: Optional[str] = None
    real: Optional[bool] = False
    allow_channel_risk: Optional[bool] = False


class CreateProfileRequest(BaseModel):
    name: str
    category: Optional[str] = "CORPORATE_DEFAULT"
    description: Optional[str] = ""
    recovery_attempts: Optional[int] = None
    mfa: Optional[str] = ""


class SaveProfileRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    requirements: Optional[Any] = None
    change_reason: Optional[str] = ""
    recovery_attempts: Optional[Any] = ...  # Default ellipsis to detect presence
    mfa: Optional[str] = ""


class ProfileActionRequest(BaseModel):
    reason: Optional[str] = ""
    change_reason: Optional[str] = ""
    mfa: Optional[str] = ""
    approver1: Optional[str] = None
    approver2: Optional[str] = None
    skip_approval: Optional[bool] = False
    force: Optional[bool] = False


# ---- Endpoints ----
@router.get("/policies")
def list_policies(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": fetch_policies_list()}


@router.get("/restrictions/catalog")
def get_restrictions_catalog(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": restrictions.catalog()}


@router.post("/restrictions/policy")
def create_policy_catalog(req: RestrictionPolicyRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "CREATE", mfa=req.mfa or "")
    out = create_policy_from_catalog(req.features or [], req.name or "", risk=req.risk or "MEDIUM")
    p = out["policy"]
    return {
        "ok": True,
        "data": {
            "policy_id": p.policy_id,
            "display_name": p.display_name,
            "applied": out["applied"],
            "excluded": out["excluded"],
        },
    }


@router.post("/policies/custom")
def create_custom_policy(req: CustomPolicyRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "CREATE", mfa=req.mfa or "")
    out = get_controller().create_policy(
        req.display_name, req.category, req.features or {}, req.risk or "MEDIUM"
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error", "policy create failed"))
    return {"ok": True, "data": out}


@router.post("/policies/sync")
def sync_policies(req: Optional[Dict[str, Any]] = None, sess: dict = Depends(get_current_session)):
    mfa = (req or {}).get("mfa", "")
    authorize_action(sess, "CREATE", mfa=mfa)
    n = persist_reference_policies()
    return {"ok": True, "data": {"synced": n}}


@router.post("/apply")
def apply_policy(req: ApplyPolicyRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    try:
        res = run_director_apply(
            req.device_id,
            req.policy,
            op_role=sess["role_code"],
            mfa_ok=check_mfa_ok(sess, req.mfa or ""),
            serial=req.serial,
            real=bool(req.real),
            signing_key=get_signing_key(),
            chan_dir=CHAN_DIR,
            allow_channel_risk=bool(req.allow_channel_risk),
        )
        return {"ok": True, "data": res}
    except ApplyBlocked as ex:
        raise HTTPException(status_code=409, detail=f"apply blocked: {ex}")
    except DirectorError as ex:
        raise HTTPException(status_code=409, detail=f"director: {ex}")


# ---- Profiles Lifecycle ----
@router.get("/profiles")
def list_profiles(
    status: str = Query(""),
    search: str = Query(""),
    include_superseded: bool = Query(False),
    sess: dict = Depends(get_current_session),
):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {
        "ok": True,
        "data": P.list_profiles(
            status=status, search=search, include_superseded=include_superseded
        ),
    }


@router.post("/profiles")
def create_profile(req: CreateProfileRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "CREATE", mfa=req.mfa or "")
    return {
        "ok": True,
        "data": P.create_draft(
            req.name,
            category=req.category or "CORPORATE_DEFAULT",
            description=req.description or "",
            recovery_attempts=req.recovery_attempts,
            created_by=sess["username"],
        ),
    }


@router.get("/profiles/{pid}")
def get_profile_by_id(pid: str, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": P.get_profile(pid)}


@router.put("/profiles/{pid}")
def update_profile(pid: str, req: SaveProfileRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT", mfa=req.mfa or "")
    save_kw = {}
    if req.recovery_attempts is not ...:
        save_kw["recovery_attempts"] = req.recovery_attempts
    try:
        return {
            "ok": True,
            "data": P.save_draft(
                pid,
                name=req.name,
                description=req.description,
                category=req.category,
                requirements=req.requirements,
                changed_by=sess["username"],
                change_reason=req.change_reason or "",
                **save_kw,
            ),
        }
    except ProfileConflict as ex:
        raise HTTPException(status_code=409, detail=str(ex))
    except ProfileError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.delete("/profiles/{pid}")
def delete_profile(
    pid: str,
    req: ProfileActionRequest,
    force: bool = Query(False),
    sess: dict = Depends(get_current_session),
):
    authorize_action(
        sess,
        "RETIRE",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "delete draft profile",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    try:
        return {"ok": True, "data": P.delete_profile(pid, force=force or bool(req.force))}
    except ProfileConflict as ex:
        raise HTTPException(status_code=409, detail=str(ex))


@router.post("/profiles/{pid}/submit")
def submit_profile(pid: str, req: ProfileActionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT", mfa=req.mfa or "")
    return {
        "ok": True,
        "data": P.submit_for_review(
            pid, changed_by=sess["username"], change_reason=req.change_reason or ""
        ),
    }


@router.post("/profiles/{pid}/reopen")
def reopen_profile(pid: str, req: ProfileActionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT", mfa=req.mfa or "")
    return {
        "ok": True,
        "data": P.reopen_rejected(
            pid,
            changed_by=sess["username"],
            change_reason=req.change_reason or "rework rejected profile",
        ),
    }


@router.post("/profiles/{pid}/revision")
def revision_profile(pid: str, req: ProfileActionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT", mfa=req.mfa or "")
    return {
        "ok": True,
        "data": P.create_revision(
            pid,
            changed_by=sess["username"],
            change_reason=req.change_reason or "new profile revision",
        ),
    }


@router.post("/profiles/{pid}/publish")
def publish_profile(pid: str, req: ProfileActionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(
        sess,
        "APPLY",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "publish profile",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    return {
        "ok": True,
        "data": P.publish_draft(
            pid, changed_by=sess["username"], change_reason=req.change_reason or ""
        ),
    }


@router.post("/profiles/{pid}/reject")
def reject_profile(pid: str, req: ProfileActionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "APPLY", mfa=req.mfa or "")
    return {
        "ok": True,
        "data": P.reject_profile(
            pid, reason=req.reason or "", changed_by=sess["username"]
        ),
    }


@router.post("/profiles/{pid}/retire")
def retire_profile(pid: str, req: ProfileActionRequest, sess: dict = Depends(get_current_session)):
    authorize_action(
        sess,
        "RETIRE",
        mfa=req.mfa or "",
        approval={
            "approved": bool(req.approver1) or bool(req.skip_approval),
            "reason": req.reason or "retire profile",
            "dual": bool(req.approver1 and req.approver2),
        },
    )
    return {
        "ok": True,
        "data": P.retire_profile(
            pid, reason=req.reason or "", changed_by=sess["username"]
        ),
    }
