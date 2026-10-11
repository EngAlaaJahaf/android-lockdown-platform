"""Authentication & Authorization dependencies for ALP FastAPI Core.

Maintains 100% compatibility with backend.auth, backend.rbac, and existing session tokens.
"""
from __future__ import annotations

import os
import sys
from typing import Optional
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend import auth, rbac  # noqa: E402
from backend.config import MFA_REQUIRED  # noqa: E402
from backend.db import connect  # noqa: E402

http_bearer = HTTPBearer(auto_error=False)


def resolve_session_from_token(token: str) -> Optional[dict]:
    if not token:
        return None
    row = auth.resolve_session(token)
    return dict(row) if row else None


async def get_current_session(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
) -> dict:
    """Resolve active session from Bearer Header, Cookie, or Query parameter."""
    token = ""
    if creds and creds.credentials:
        token = creds.credentials
    elif "alp_token" in request.cookies:
        token = request.cookies.get("alp_token", "")
    elif "token" in request.query_params:
        token = request.query_params.get("token", "")

    if not token:
        raise HTTPException(status_code=401, detail="missing session token")

    sess = resolve_session_from_token(token)
    if not sess:
        raise HTTPException(status_code=401, detail="invalid or expired session token")

    return sess


def check_mfa_ok(sess: dict, code: str) -> bool:
    if not MFA_REQUIRED:
        return True
    with connect() as c:
        r = c.execute("SELECT mfa_secret FROM administrators WHERE id=?",
                      (sess.get("admin_id") or sess.get("id"),)).fetchone()
    return bool(r and r["mfa_secret"] and auth.totp_verify(r["mfa_secret"], code or ""))


def authorize_action(
    sess: dict,
    operation: str,
    mfa: str = "",
    require_mfa: bool = True,
    approval: Optional[dict] = None,
) -> str:
    """Check RBAC role permissions and MFA requirement."""
    try:
        return rbac.authorize(
            sess["role_code"],
            operation,
            require_mfa=require_mfa,
            mfa_ok=check_mfa_ok(sess, mfa),
            approval=approval,
        )
    except PermissionError as ex:
        raise HTTPException(status_code=403, detail=str(ex))
