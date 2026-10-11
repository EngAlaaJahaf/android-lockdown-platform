"""Secure Command Channel (§48/§49) — authenticated, authorized, device-bound,
time-valid, non-replayable, signed commands with idempotency keys.

Signature scheme: HMAC-SHA256 over canonical command payload (console-internal
integrity) PLUS, when an Ed25519 keypair is configured, an `sig_ed25519` field
that is the ONLY signature the on-device agent verifies. The agent ships just
the public key, so an unlock/rollback command cannot be forged even by a rooted
device. The signing key lives outside any code path that ships secrets
(deployment-injected env var, or a keyfile at first boot — never a constant).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Optional

from .config import SIGNING_KEY, signing_key as _current_key
from .db import connect
from .ed25519 import sign_hex as _ed_sign_hex

# Signature fields are excluded from the canonically-signed payload so both
# signature types cover exactly the same bytes.
_SIG_FIELDS = ("signature", "sig_ed25519")


class CommandRejected(Exception):
    pass


def _canonical(payload: dict) -> bytes:
    body = {k: v for k, v in payload.items() if k not in _SIG_FIELDS}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def sign_command(payload: dict, key: Optional[str] = None) -> str:
    key = key or _current_key() or SIGNING_KEY
    if not key:
        raise CommandRejected("signing key not configured")
    return hmac.new(key.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()


def _ed_sign(payload: dict, priv_hex: Optional[str] = None) -> str:
    """Ed25519 signature over the canonical payload (hex), or "" when no key."""
    if priv_hex is None:
        from .config import ed25519_private_hex as _priv
        priv_hex = _priv()
    if not priv_hex:
        return ""
    try:
        return _ed_sign_hex(priv_hex, _canonical(payload))
    except ValueError:
        return ""


def new_command(job_execution_id: int, device_id: str, action: str,
                body: dict, ttl_seconds: int = 300,
                key: Optional[str] = None,
                ed_key: Optional[str] = None) -> dict:
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
    ed = _ed_sign(payload, ed_key)
    if ed:
        payload["sig_ed25519"] = ed
    return payload


def verify_envelope(envelope: dict, expected_device: str,
                    max_skew: int = 300,
                    key: Optional[str] = None,
                    require_ed: bool = False) -> None:
    """Validate authenticity, freshness, device binding, replay-avoidance."""
    env = dict(envelope)                      # never mutate the caller's object
    key = key or _current_key() or SIGNING_KEY
    if not key:
        raise CommandRejected("signing key not configured")
    if env.get("device_id") != expected_device:
        raise CommandRejected("command device binding mismatch")
    sig = env.pop("signature", "")
    expected = sign_command(env, key)
    if not hmac.compare_digest(sig, expected):
        raise CommandRejected("bad signature")
    ed = env.pop("sig_ed25519", "")
    if ed or require_ed:
        if not _verify_ed(env, ed):
            raise CommandRejected("bad ed25519 signature")
    now = int(time.time())
    if env["issued_at"] > now + max_skew:
        raise CommandRejected("issued in the future (skew)")
    if env["expires_at"] < now:
        raise CommandRejected("command expired")
    _register_nonce(env["cmd_id"], env["nonce"])


def _verify_ed(env: dict, sig_hex: str) -> bool:
    if not sig_hex:
        return False
    from .config import ed25519_public_hex as _pub
    pub = _pub()
    if not pub:
        return False
    from .ed25519 import verify_hex as _verify
    try:
        return _verify(pub, sig_hex, _canonical(env))
    except ValueError:
        return False


def _register_nonce(cmd_id: str, nonce: str):
    """One-time use: reject a nonce seen before within the retention window."""
    with connect() as c:
        row = c.execute("SELECT 1 FROM command_nonces WHERE nonce=?", (nonce,)).fetchone()
        if row:
            raise CommandRejected("replay detected (nonce reused)")
        c.execute("INSERT INTO command_nonces (cmd_id, nonce) VALUES (?,?)", (cmd_id, nonce))
        c.execute("DELETE FROM command_nonces WHERE created_at < datetime('now','-15 minutes')")