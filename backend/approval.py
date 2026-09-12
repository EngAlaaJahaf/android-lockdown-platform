"""Approval gate (§70) and two-person rule (§11) for destructive operations.

AUTHENTICATION_AND_RECOVERY_DESIGN.html §10: the old TOTP/MFA approver factor
is replaced by *named administrative confirmations*. The possession factor for
the sensitive device operation itself is the per-device recovery credential
(RecoveryVault), verified by the caller before execution.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from .db import connect
from .rbac import requires_dual_approval


class ApprovalRequired(Exception):
    def __init__(self, message: str, approval_id: str):
        super().__init__(message)
        self.approval_id = approval_id


def request_approval(requester_id: Optional[int], action: str, device_id: str = "",
                     scope: str = "single", reason: str = "") -> str:
    """Create a PENDING approval; returns approval_id.

    requester_id is informational (nullable — the open console has no mandate
    to force a login to file a request)."""
    aid = "APR-" + uuid.uuid4().hex[:10].upper()
    requester = requester_id if requester_id else None
    dev_pk = None
    if device_id:
        with connect() as c:
            r = c.execute("SELECT id FROM devices WHERE device_id=?",
                          (device_id,)).fetchone()
            dev_pk = r["id"] if r else None
    with connect() as c:
        c.execute(
            """INSERT INTO approvals (approval_id, action, device_id, scope,
                                      requester, reason, decision, mfa_verified)
               VALUES (?,?,?,?,?,?, 'PENDING', 0)""",
            (aid, action, dev_pk, scope, requester, reason))
    return aid


def confirm(approval_id: str, approver_name: str) -> dict:
    """Record one named human confirmation.

    Dual rule (destructive ops): two distinct named confirmations.
    Returns {'approved': bool, 'needs_second': bool}.
    """
    name = (approver_name or "").strip()
    if not name:
        raise ValueError("confirmation name required")
    with connect() as c:
        row = c.execute("SELECT * FROM approvals WHERE approval_id=?",
                        (approval_id,)).fetchone()
        if not row:
            raise ValueError(f"unknown approval {approval_id}")
        if row["decision"] != "PENDING":
            raise ValueError(f"approval {approval_id} already {row['decision']}")
        needed_dual = requires_dual_approval(row["action"])
        prior = c.execute(
            "SELECT approver_name FROM approval_confirmations "
            "WHERE approval_id=? ORDER BY seq", (approval_id,)).fetchall()
        names = [r["approver_name"] for r in prior]
        if names:
            if name == names[-1]:
                raise ValueError("same actor confirmed twice — "
                                 "self-confirmation not allowed")
            if names[0] == name:
                raise ValueError("same actor confirmed twice — "
                                 "self-confirmation not allowed")
        seq = len(names) + 1
        if needed_dual and seq > 2:
            raise ValueError("dual approval requires exactly two "
                             "distinct approvers")
        if not needed_dual and seq > 1:
            raise ValueError("single confirmation already recorded")
        c.execute(
            "INSERT INTO approval_confirmations (approval_id, seq, approver_name) "
            "VALUES (?,?,?)", (approval_id, seq, name))
        complete = (needed_dual and seq == 2) or (not needed_dual and seq == 1)
        if complete:
            c.execute("UPDATE approvals SET decision='APPROVED', decided_at=? "
                      "WHERE approval_id=?", (_now(), approval_id))
            return {"approved": True, "needs_second": False}
        return {"approved": False, "needs_second": True}


def approve(approval_id: str, approver_id: int, mfa_ok: bool = True) -> dict:
    """Legacy admin-account approver path (session + MFA factor).

    Kept for the old TOTP/session callers (CLI/API/tests). New consoles use
    `confirm()` (named human confirmations). Both feed the same confirmations
    table and enforce the same dual rule for destructive ops.
    """
    if not mfa_ok:
        raise ValueError("an MFA-verified actor is required to approve")
    with connect() as c:
        a = c.execute("SELECT username FROM administrators WHERE id=?",
                      (approver_id,)).fetchone()
    if not a:
        raise ValueError("unknown approver account")
    return confirm(approval_id, "admin:" + a["username"])


def deny(approval_id: str, approver_name: str) -> None:
    name = (approver_name or "").strip() or "unnamed"
    with connect() as c:
        c.execute("UPDATE approvals SET decision='DENIED', decided_at=? "
                  "WHERE approval_id=?", (_now(), approval_id))


def is_approved(approval_id: str) -> bool:
    with connect() as c:
        r = c.execute("SELECT decision FROM approvals WHERE approval_id=?",
                      (approval_id,)).fetchone()
    return bool(r and r["decision"] == "APPROVED")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())