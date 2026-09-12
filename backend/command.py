"""Secure Command Channel (§48/§49) — authenticated, authorized, device-bound,
time-valid, non-replayable, signed commands with idempotency keys.

Signature scheme: HMAC-SHA256 over canonical command payload. The signing key
lives outside any code path that ships secrets (deployment-injected env var, or
an admin-provided key at first boot — never a constant).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Optional

from .config import SIGNING_KEY
from .db import connect


class CommandRejected(Exception):
    pass


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def sign_command(payload: dict, key: Optional[str] = None) -> str:
    key = key or SIGNING_KEY
    if not key:
        raise CommandRejected("signing key not configured")
    return hmac.new(key.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()


def new_command(job_execution_id: int, device_id: str, action: str,
                body: dict, ttl_seconds: int = 300,
                key: Optional[str] = None) -> dict:
    """Build a signed, non-replayable, time-valid command envelope."""
    now = int(time.time())
    payload = {
        "cmd_id": uuid.uuid4().hex[:14].upper(),
        "job_execution_id": job_execution_id,
        "device_id": device_id,
        "action": action,
        "nonce": uuid.uuid4().hex,
        "issued_at": now,
        "expires_at": now + ttl_seconds,
        "body": body,
    }
    payload["signature"] = sign_command(payload, key)
    return payload


def verify_envelope(envelope: dict, expected_device: str,
                    max_skew: int = 300,
                    key: Optional[str] = None) -> None:
    """Validate authenticity, freshness, device binding, replay-avoidance."""
    env = dict(envelope)                      # never mutate the caller's object
    key = key or SIGNING_KEY
    if not key:
        raise CommandRejected("signing key not configured")
    if env.get("device_id") != expected_device:
        raise CommandRejected("command device binding mismatch")
    sig = env.pop("signature", "")
    expected = sign_command(env, key)
    if not hmac.compare_digest(sig, expected):
        raise CommandRejected("bad signature")
    now = int(time.time())
    if env["issued_at"] > now + max_skew:
        raise CommandRejected("issued in the future (skew)")
    if env["expires_at"] < now:
        raise CommandRejected("command expired")
    _register_nonce(env["cmd_id"], env["nonce"])


def _register_nonce(cmd_id: str, nonce: str):
    """One-time use: reject a nonce seen before within the retention window."""
    with connect() as c:
        row = c.execute("SELECT 1 FROM command_nonces WHERE nonce=?", (nonce,)).fetchone()
        if row:
            raise CommandRejected("replay detected (nonce reused)")
        c.execute("INSERT INTO command_nonces (cmd_id, nonce) VALUES (?,?)", (cmd_id, nonce))
        c.execute("DELETE FROM command_nonces WHERE created_at < datetime('now','-15 minutes')")