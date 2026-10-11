"""WebSocket Connection Manager for ALP Real-Time Events.

Provides real-time broadcasting to connected WebUI clients for:
- Device connection/disconnection (ADB auto-watcher)
- Live audit log events (Policy apply, enrollment, emergency unlock)
- Device status updates (sync, battery, policy state)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("alp.websocket")


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
        self.client_topics: Dict[WebSocket, Set[str]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket, topics: Set[str] | None = None) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        self.client_topics[websocket] = topics or {"devices", "audit", "system"}
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        self.client_topics.pop(websocket, None)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast_json(self, topic: str, data: dict) -> None:
        payload = {"topic": topic, "data": data}
        message = json.dumps(payload)
        dead = []
        for connection in list(self.active_connections):
            allowed = self.client_topics.get(connection, set())
            if "all" in allowed or topic in allowed:
                try:
                    await connection.send_text(message)
                except Exception as ex:
                    logger.debug(f"Failed to send to client: {ex}")
                    dead.append(connection)
        for d in dead:
            self.disconnect(d)

    def broadcast_from_thread(self, topic: str, data: dict) -> None:
        """Thread-safe broadcast callable from sync worker threads (e.g. ADB watcher)."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast_json(topic, data), self._loop)


ws_manager = ConnectionManager()
