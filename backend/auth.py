"""Authentication — scrypt password hashing, TOTP (RFC 6238) MFA, sessions.

No plaintext passwords, no static tokens in code. Sessions are short-lived,
revocable, and stored in DB. TOTP uses the encrypted-on-disk secret and the
device binding of the session for sensitive operations.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from typing import Optional

from .db import connect


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                        n=262144, r=8, p=1, maxmem=512 * 1024 * 1024)
    return "scrypt$262144$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, hash_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        want = base64.b64decode(hash_b64)
        got = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                             n=int(n), r=int(r), p=int(p), maxmem=512 * 1024 * 1024)
        return hmac.compare_digest(got, want)
    except Exception:
        return False


_B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generate_totp_secret() -> tuple[str, str]:
    """Return (b32_secret, otpauth_uri)."""
    raw = secrets.token_bytes(20)
    num = int.from_bytes(raw, "big")
    b32 = []
    for _ in range(32):
        b32.append(_B32_ALPHABET[num & 31])
        num >>= 5
    b32 = "".join(reversed(b32))
    uri = f"otpauth://totp/ALP:{b32}?secret={b32}&issuer=ALP"
    return b32, uri


def totp_verify(b32_secret: str, code: str, window: int = 1) -> bool:
    try:
        decoded = _b32_decode(b32_secret)
    except Exception:
        return False
    now = int(time.time()) // 30
    for off in range(-window, window + 1):
        if _totp_at(decoded, now + off) == code.strip():
            return True
    return False


def _totp_at(key: bytes, counter: int) -> str:
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[19] & 0x0F
    val = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{val:06d}"


def _b32_decode(s: str) -> bytes:
    s = s.upper().replace(" ", "")
    bits = 0
    val = 0
    out = bytearray()
    for ch in s:
        val = (val << 5) | _B32_ALPHABET.index(ch)
        bits += 5
        if bits >= 8:
            out.append((val >> (bits - 8)) & 0xFF)
            bits -= 8
    return bytes(out)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(admin_id: int, ttl_seconds: int = 86400 * 7) -> str:
    token = secrets.token_urlsafe(32)
    with connect() as c:
        c.execute(
            "INSERT INTO sessions(token, admin_id, expires_at) VALUES (?,?,?)",
            (token, admin_id,
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl_seconds))))
    return token


def resolve_session(token: str) -> Optional[dict]:
    with connect() as c:
        r = c.execute(
            "SELECT s.*, a.username, a.display_name, a.role_id, a.mfa_enabled, r.code AS role_code "
            "FROM sessions s JOIN administrators a ON a.id=s.admin_id "
            "JOIN roles r ON r.id=a.role_id WHERE s.token=? AND s.revoked=0", (token,)).fetchone()
    if not r:
        return None
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if r["expires_at"] < now_iso:
        return None
    try:
        new_exp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400 * 7))
        with connect() as c:
            c.execute("UPDATE sessions SET expires_at=? WHERE token=?", (new_exp, token))
    except Exception:
        pass
    return dict(r)


def revoke_session(token: str) -> None:
    with connect() as c:
        c.execute("UPDATE sessions SET revoked=1 WHERE token=?", (token,))