"""Audit, Reports, Diagnostics, Jobs & Approvals Router for ALP FastAPI Core."""
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

from backend.db import connect  # noqa: E402
from backend import audit as audit_mod, approval as approval_mod  # noqa: E402
from backend.backup import create_backup  # noqa: E402
from backend.fastapi_core.security import get_current_session, authorize_action, check_mfa_ok  # noqa: E402
from backend.fastapi_core.routers.auth import get_controller  # noqa: E402

router = APIRouter(prefix="/api/v1", tags=["Audit & Reports"])


def fetch_jobs():
    with connect() as c:
        rows = c.execute(
            "SELECT j.job_id, j.job_type, j.status, j.priority, count(e.id) AS execs "
            "FROM jobs j LEFT JOIN job_executions e ON e.job_id=j.id "
            "GROUP BY j.id ORDER BY j.id DESC LIMIT 50"
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_approvals():
    with connect() as c:
        rows = c.execute(
            "SELECT approval_id, action, device_id, scope, requester, approver_1, approver_2, "
            "reason, decision, created_at FROM approvals ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return [dict(r) for r in rows]


class ApproveRequest(BaseModel):
    approval_id: str
    mfa: Optional[str] = ""


class BackupRequest(BaseModel):
    mfa: Optional[str] = ""


@router.get("/reports")
def get_reports_list(
    device_id: str = Query(""),
    sess: dict = Depends(get_current_session),
):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": get_controller().reports_list(device_id)}


@router.get("/reports/{did}")
def get_device_report(did: str, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": get_controller().generate_device_report(did)}


@router.get("/diagnostics")
def get_diagnostics(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": get_controller().diagnostics()}


@router.get("/jobs")
def get_jobs(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": fetch_jobs()}


@router.get("/approvals")
def get_approvals(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "VIEW", require_mfa=False)
    return {"ok": True, "data": fetch_approvals()}


@router.post("/approvals/approve")
def approve_request(req: ApproveRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "CREATE", mfa=req.mfa or "")
    out = approval_mod.approve(
        req.approval_id, sess["admin_id"], mfa_ok=check_mfa_ok(sess, req.mfa or "")
    )
    return {"ok": True, "data": out}


@router.get("/audit")
def get_audit_tail(
    tail: str = Query("100"),
    sess: dict = Depends(get_current_session),
):
    authorize_action(sess, "AUDIT", require_mfa=False)
    lg = audit_mod.AuditLog()
    try:
        limit = int(tail)
    except (ValueError, TypeError):
        limit = 100
    return {"ok": True, "data": lg.tail(limit)}


@router.get("/audit/tamper")
def get_audit_tamper_check(sess: dict = Depends(get_current_session)):
    authorize_action(sess, "AUDIT", require_mfa=False)
    return {"ok": True, "data": audit_mod.AuditLog().tamper_check()}


@router.post("/system/backup")
def trigger_backup(req: BackupRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "RESTORE", mfa=req.mfa or "")
    out = create_backup()
    if not out.get("ok"):
        raise HTTPException(status_code=500, detail=out.get("error", "backup failed"))
    return {"ok": True, "data": out}
