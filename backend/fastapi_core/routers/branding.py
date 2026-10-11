"""Branding router for ALP FastAPI Core."""
from __future__ import annotations

import base64
import datetime
import hashlib
import os
import sys
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.fastapi_core.security import get_current_session, authorize_action  # noqa: E402

WEBUI_DIR = os.path.join(PROJECT_ROOT, "webui")
BRANDING_DIR = os.path.join(WEBUI_DIR, "branding")
BRANDING_LOGO = os.path.join(BRANDING_DIR, "logo.png")
BRANDING_MAX_BYTES = 512 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

router = APIRouter(prefix="/api/v1/branding", tags=["Branding"])


def get_branding_info() -> dict:
    try:
        with open(BRANDING_LOGO, "rb") as fh:
            data = fh.read()
    except OSError:
        return {"logo_url": None, "version": "", "updated_at": ""}
    ver = hashlib.sha1(data).hexdigest()[:16]
    updated = datetime.datetime.fromtimestamp(
        os.path.getmtime(BRANDING_LOGO), tz=datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"logo_url": "/branding/logo.png", "version": ver, "updated_at": updated}


class StoreLogoRequest(BaseModel):
    png_b64: str
    mfa: Optional[str] = ""


@router.get("")
def read_branding():
    return {"ok": True, "data": get_branding_info()}


@router.post("/logo")
def store_logo(req: StoreLogoRequest, sess: dict = Depends(get_current_session)):
    authorize_action(sess, "EDIT", mfa=req.mfa or "")
    if not req.png_b64 or not isinstance(req.png_b64, str):
        raise HTTPException(status_code=400, detail="png_b64 (base64-encoded PNG) is required")
    try:
        data = base64.b64decode(req.png_b64, validate=True)
    except ValueError:
        raise HTTPException(status_code=400, detail="png_b64 is not valid base64")
    if not data or len(data) > BRANDING_MAX_BYTES:
        raise HTTPException(status_code=400, detail="logo must be a non-empty PNG of at most 512 KiB")
    if data[:8] != _PNG_MAGIC:
        raise HTTPException(status_code=400, detail="only PNG images are accepted")
    if len(data) < 33:
        raise HTTPException(status_code=400, detail="truncated PNG")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if not (1 <= width <= 1024 and 1 <= height <= 1024):
        raise HTTPException(status_code=400, detail="logo dimensions must be within 1024x1024")
    os.makedirs(BRANDING_DIR, exist_ok=True)
    tmp = BRANDING_LOGO + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, BRANDING_LOGO)
    return {"ok": True, "data": get_branding_info()}
