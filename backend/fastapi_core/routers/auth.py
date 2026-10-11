"""Authentication & Bootstrap Router for ALP FastAPI Core."""
from __future__ import annotations

import os
import sys
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend import auth  # noqa: E402
from backend.config import MFA_REQUIRED  # noqa: E402
from backend.db import connect  # noqa: E402
from backend.fastapi_core.security import get_current_session  # noqa: E402

try:
    from alp_manager.controller import Controller
    _CONTROLLER = None

    def get_controller():
        global _CONTROLLER
        if _CONTROLLER is None:
            _CONTROLLER = Controller(db_path="")
        return _CONTROLLER
except ImportError as _ex:
    def get_controller():
        raise RuntimeError(f"web console backend unavailable: {_ex}")


router = APIRouter(prefix="/api/v1", tags=["Authentication & Bootstrap"])


class LoginRequest(BaseModel):
    username: str
    password: str
    mfa: Optional[str] = ""


class BootstrapRequest(BaseModel):
    username: str
    password: str


@router.get("/bootstrap")
def get_bootstrap_status():
    return {"ok": True, "data": {"needs_bootstrap": get_controller().needs_bootstrap()}}


@router.post("/bootstrap")
def execute_bootstrap(req: BootstrapRequest):
    out = get_controller().bootstrap(req.username, req.password)
    if not out.get("ok"):
        raise HTTPException(status_code=409, detail=out.get("error", "bootstrap refused"))
    return {
        "ok": True,
        "data": {
            "username": req.username,
            "totp_uri": out.get("totp_uri", ""),
            "secret": out.get("secret", ""),
        },
    }


@router.post("/auth/login")
def login(req: LoginRequest):
    with connect() as c:
        row = c.execute(
            "SELECT * FROM administrators WHERE username=? AND active=1",
            (req.username,),
        ).fetchone()

    if not row or not row["password_hash"] or not auth.verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="bad credentials")

    if MFA_REQUIRED and row["mfa_enabled"] and not auth.totp_verify(row["mfa_secret"] or "", req.mfa or ""):
        raise HTTPException(status_code=401, detail="bad MFA code")

    token = auth.create_session(row["id"])
    return {
        "ok": True,
        "data": {
            "token": token,
            "username": row["username"],
            "role_id": row["role_id"],
            "display_name": row["display_name"],
            "mfa_required": MFA_REQUIRED,
        },
    }


@router.post("/auth/logout")
async def logout(request: Request):
    # Optional auth logout
    h = request.headers.get("Authorization", "")
    token = h[7:].strip() if h.lower().startswith("bearer ") else request.cookies.get("alp_token", "")
    if token:
        sess = auth.resolve_session(token)
        if sess:
            auth.revoke_session(sess["token"])
    return {"ok": True, "data": {"logged_out": True}}


@router.get("/auth/whoami")
def whoami(sess: dict = Depends(get_current_session)):
    return {
        "ok": True,
        "data": {
            "username": sess["username"],
            "role_code": sess["role_code"],
            "role_id": sess["role_id"],
        },
    }
