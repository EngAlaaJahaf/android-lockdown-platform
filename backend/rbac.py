"""RBAC authorization — decision per (role, operation): ALLOW | DENY | REQUIRES_APPROVAL.

Since a role can have at most one decision per operation, operations marked
REQUIRES_APPROVAL must pass the approval gate before the backend executes them.
Authorization failures are always logged by the caller.

Execution plan references: EXECUTE §28, §29, §30, §70.
"""
from __future__ import annotations

from typing import Optional

from .db import connect


class AuthorizationError(PermissionError):
    pass


def decision_for(role_code: str, operation: str) -> Optional[str]:
    with connect() as c:
        r = c.execute(
            """SELECT p.decision FROM permissions p
               JOIN roles r ON r.id = p.role_id
               WHERE r.code=? AND p.operation=?""", (role_code, operation)).fetchone()
    return r["decision"] if r else None


def authorize(role_code: str, operation: str, require_mfa: bool = True,
              mfa_ok: bool = False, approval: Optional[dict] = None,
              require_credential: bool = False,
              credential_ok: bool = False) -> str:
    """Returns 'ALLOW' or 'APPROVED'; raises AuthorizationError otherwise.

    approval: {'approved': bool, 'reason': str, 'dual': bool} for REQUIRES_APPROVAL
    or dual-approval sensitive operations.

    credential_ok: device possession factor. Sensitive device operations use
    the per-device recovery credential (RecoveryVault) instead of an MFA/TOTP
    code — see AUTHENTICATION_AND_RECOVERY_DESIGN.html §9/§10/§16.
    """
    decision = decision_for(role_code, operation)
    if decision is None:
        raise AuthorizationError(f"no rule for {role_code}:{operation}")
    if decision == "DENY":
        raise AuthorizationError(f"{role_code} denied for {operation}")
    if decision == "REQUIRES_APPROVAL":
        if not (approval and approval.get("approved")):
            raise AuthorizationError(f"{operation} requires approval gate")
    if require_credential and not credential_ok:
        raise AuthorizationError(
            f"{operation} requires the device recovery credential "
            f"(possession factor) for role {role_code}")
    if require_mfa and not mfa_ok:
        raise AuthorizationError(f"{operation} requires MFA for role {role_code}")
    return "APPROVED" if decision == "REQUIRES_APPROVAL" else "ALLOW"


SENSITIVE_OPERATIONS = {
    "UNLOCK", "PARTIAL_UNLOCK", "RECOVER", "UNENROLL", "RETIRE",
    "FACTORY_RESET", "FIRMWARE", "KEY_MANAGEMENT", "BULK_APPLY",
}


def requires_dual_approval(operation: str) -> bool:
    """Destructive operations per §11/§70 need two independent approvers."""
    return operation in ("FACTORY_RESET", "RETIRE", "FIRMWARE", "UNENROLL")