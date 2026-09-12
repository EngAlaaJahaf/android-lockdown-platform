"""Approval gate (§70) and two-person rule (§11) for destructive operations."""
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


def request_approval(requester_id: int, action: str, device_id: str = "",
                     scope: str = "single", reason: str = "") -> str:
    """Create a PENDING approval; returns approval_id."""
    aid = "APR-" + uuid.uuid4().hex[:10].upper()
    with connect() as c:
        c.execute(
            """INSERT INTO approvals (approval_id, action, device_id, scope, requester,
                                      reason, decision, mfa_verified)
               VALUES (?,?,?,?,?,?, 'PENDING', 0)""",
            (aid, action, device_id or None, scope, requester_id, reason))
    return aid


def approve(approval_id: str, approver_id: int, mfa_ok: bool = False,
            is_second: bool = False, force_override: bool = False) -> dict:
    """Approve an approval. Destructive ops need a second independent approver."""
    with connect() as c:
        row = c.execute("SELECT * FROM approvals WHERE approval_id=?",
                        (approval_id,)).fetchone()
        if not row:
            raise ValueError(f"unknown approval {approval_id}")
        needed_dual = requires_dual_approval(row["action"]) and not force_override
        if not mfa_ok:
            raise ValueError("MFA required to approve")
        if row["decision"] != "PENDING":
            raise ValueError(f"approval {approval_id} already {row['decision']}")

        if needed_dual:
            if row["approver_1"] is None:
                c.execute("UPDATE approvals SET approver_1=? WHERE approval_id=?",
                          (approver_id, approval_id))
                return {"approved": False, "needs_second": True}
            elif row["approver_2"] is None and row["approver_1"] != approver_id:
                c.execute("UPDATE approvals SET approver_2=?, decision='APPROVED', decided_at=? "
                          "WHERE approval_id=?", (approver_id, _now(), approval_id))
            else:
                raise ValueError("dual approval requires two distinct approvers")
        else:
            if row["approver_1"] is None:
                c.execute("UPDATE approvals SET approver_1=?, decision='APPROVED', decided_at=? "
                          "WHERE approval_id=?", (approver_id, _now(), approval_id))
            elif row["approver_1"] == approver_id:
                raise ValueError("self-approval not allowed")
            else:
                c.execute("UPDATE approvals SET approver_2=?, decision='APPROVED', decided_at=? "
                          "WHERE approval_id=?", (approver_id, _now(), approval_id))
        return {"approved": True, "needs_second": False}


def deny(approval_id: str, approver_id: int) -> None:
    with connect() as c:
        c.execute("UPDATE approvals SET decision='DENIED', decided_at=? WHERE approval_id=?",
                  (_now(), approval_id))


def is_approved(approval_id: str) -> bool:
    with connect() as c:
        r = c.execute("SELECT decision FROM approvals WHERE approval_id=?",
                      (approval_id,)).fetchone()
    return bool(r and r["decision"] == "APPROVED")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())