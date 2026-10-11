"""Main FastAPI Application for ALP Control Plane (Phase 2 & 3 Modernized)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.config import MFA_REQUIRED, API_HOST, API_PORT  # noqa: E402
from backend.db import run_migrations  # noqa: E402
from backend.workflows import attached_serials  # noqa: E402
from backend.fastapi_core.websocket_manager import ws_manager  # noqa: E402
from backend.fastapi_core.routers import (  # noqa: E402
    auth,
    branding,
    devices,
    profiles,
    groups,
    recovery,
    audit,
)

logger = logging.getLogger("alp.fastapi")
WEBUI_DIR = os.path.join(PROJECT_ROOT, "webui")
CHAN_DIR = os.path.join(PROJECT_ROOT, "reports", "phase1", "commands")

_LAST_SERIALS: list[str] = []


async def _adb_watcher_loop():
    """Background task to detect connected/disconnected USB devices and push live events."""
    global _LAST_SERIALS
    while True:
        try:
            current = attached_serials() or []
            if set(current) != set(_LAST_SERIALS):
                added = [s for s in current if s not in _LAST_SERIALS]
                removed = [s for s in _LAST_SERIALS if s not in current]
                logger.info(f"ADB devices changed: added={added}, removed={removed}, total={len(current)}")
                _LAST_SERIALS = current
                await ws_manager.broadcast_json(
                    "devices",
                    {
                        "event": "device_state_changed",
                        "serials": current,
                        "added": added,
                        "removed": removed,
                        "count": len(current),
                    },
                )
        except Exception as ex:
            logger.debug(f"ADB watcher error: {ex}")
        await asyncio.sleep(2.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing ALP FastAPI Core...")
    try:
        from scripts.build_webui import build_webui
        build_webui()
    except Exception as ex:
        logger.warning(f"Failed to auto-assemble webui: {ex}")
    run_migrations()
    os.makedirs(CHAN_DIR, exist_ok=True)
    ws_manager.set_loop(asyncio.get_running_loop())
    watcher_task = asyncio.create_task(_adb_watcher_loop())
    yield
    # Shutdown
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="ALP Control Plane (ManageEngine MDM Architecture)",
    description="Modernized High-Performance Control-Plane API with WebSockets for Android Lockdown Platform",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Standard Error Formatting (100% matched with ALP WebUI requirements)
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": f"{type(exc).__name__}: {exc}"},
    )


# Health check
@app.get("/api/v1/health", tags=["Health"])
def health_check():
    return {
        "ok": True,
        "data": {
            "status": "UP",
            "service": "alp-fastapi-control-plane",
            "mfa_required": MFA_REQUIRED,
            "version": "2.0.0",
        },
    }


# Include domain routers
app.include_router(auth.router)
app.include_router(branding.router)
app.include_router(devices.router)
app.include_router(profiles.router)
app.include_router(groups.router)
app.include_router(recovery.router)
app.include_router(audit.router)


# WebSocket live events endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            text = await websocket.receive_text()
            if text == "ping":
                await websocket.send_text('{"topic": "system", "data": {"pong": true}}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# Serve root index.html and static files from webui/
@app.get("/", include_in_schema=False)
def serve_root():
    return FileResponse(os.path.join(WEBUI_DIR, "index.html"), media_type="text/html")


if os.path.isdir(WEBUI_DIR):
    app.mount("/", StaticFiles(directory=WEBUI_DIR, html=True), name="webui")
