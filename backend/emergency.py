"""Offline emergency uninstall tokens (the answer to "I killed the channel").

Scenario: an admin pushes a channel-killing restriction (or any bug orphans
a phone). USB delivery of CLEAR/WITHDRAW envelopes is gone, so nothing the
console sends can ever arrive. The way back that needs no cable:

  1. Console issues a high-entropy one-time token NOW and shows it ONCE.
     Only SHA256(token) is stored — the plaintext lives nowhere.
  2. Earlier (while USB worked) the same hash was provisioned into the
     agent inside a SIGNED envelope, exactly like the rollback PIN.
  3. The holder opens the agent with the dialer secret code, types the
     token into the Emergency screen; the agent compares hashes locally.
     Match -> full local rollback + Device-Owner self-withdraw + Android
     uninstall prompt. No network, no USB, no forged commands (an attacker
     without the token learns nothing; 5 wrong tries lock the screen with
     the same backoff as the PIN).

Bounds, stated honestly: single-use is enforced on the device; here a
successful console-side verify also burns the token. Revocation only bites
BEFORE the phone goes offline (after that the device cannot know), so every
token carries an expiry (default 24 h) and the console refuses expired ones.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import os
import secrets
from datetime import datetime, timedelta

from .db import connect

TOKEN_TTL_HOURS = 24
TOKEN_BYTES = 15  # 120 bits

# One token, one door — mirroring the reference recovery-key types
# (unlock / pause kiosk / revoke management). The agent enforces the scope
# offline together with the hash check, so a rollback token can never
# withdraw management and an uninstall token can never just lift a lock.
# "reset_password" opens only the lock-screen recovery challenge: after N
# wrong lock attempts the holder types the console-derived code and the
# agent opens the system set-new-password screen. It can neither lift
# restrictions nor withdraw management.
PURPOSES = {"rollback", "withdraw_uninstall", "pause_kiosk", "reset_password"}

# Offline (memdm-style) codes: derived, not stored. At enrollment-time trust
# (USB/provisioning) both sides learn one random per-device secret; afterwards
# either side derives the same time-bound code with no channel at all:
#   code = truncate(HMAC-SHA256(secret, "ALP-EMG-V1" || purpose || counter))
# counter = floor(unix_time / STEP), RFC-4226-style dynamic truncation,
# 8 digits. The phone accepts counter ±1 (15-minute tolerance for wrong
# phone clocks) and burns each (purpose, counter) after first use, so a
# shoulder-surfed code cannot be replayed later in its window.
OFFLINE_STEP_SECONDS = 300
OFFLINE_DIGITS = 8
OFFLINE_WINDOW = 1
OFFLINE_DOMAIN = b"ALP-EMG-V1"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_token() -> str:
    raw = base64.b32encode(secrets.token_bytes(TOKEN_BYTES)).decode("ascii")
    groups = [raw[i:i + 4] for i in range(0, len(raw), 4)]
    return "AE-" + "-".join(groups)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(device_id: str, created_by: str = "", label: str = "",
                ttl_hours: int = TOKEN_TTL_HOURS,
                purpose: str = "withdraw_uninstall") -> dict:
    """Create a one-time emergency token. The plaintext is returned ONCE."""
    device_id = (device_id or "").strip()
    if not device_id:
        raise ValueError("device_id is required")
    if purpose not in PURPOSES:
        raise ValueError("purpose must be one of: " + ", ".join(sorted(PURPOSES)))
    if not (1 <= int(ttl_hours) <= 24 * 30):
        raise ValueError("ttl_hours must be 1..720")
    with connect() as c:
        dev = c.execute("SELECT id FROM devices WHERE device_id=?",
                        (device_id,)).fetchone()
        if not dev:
            raise ValueError(f"device {device_id!r} is not registered")
        token, token_id = _new_token(), "ET-" + secrets.token_hex(4)
        now = datetime.now()
        exp = now + timedelta(hours=int(ttl_hours))
        c.execute(
            "INSERT INTO emergency_tokens (token_id, device_id, token_sha256,"
            " label, created_at, created_by, expires_at, purpose) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (token_id, device_id, _digest(token), label or "",
             now.strftime("%Y-%m-%d %H:%M:%S"), created_by or "",
             exp.strftime("%Y-%m-%d %H:%M:%S"), purpose))
    return {"token_id": token_id, "token": token, "device_id": device_id,
            "label": label or "", "purpose": purpose,
            "expires_at": exp.strftime("%Y-%m-%d %H:%M:%S"),
            "warning": "copy it now — it is never shown or stored again"}


def verify_token(device_id: str, token: str) -> dict:
    """Check a token (single-use: success burns it). Returns {ok, reason}."""
    digest = _digest(token or "")
    with connect() as c:
        row = c.execute(
            "SELECT * FROM emergency_tokens WHERE device_id=? AND "
            "token_sha256=? ORDER BY id DESC LIMIT 1",
            ((device_id or "").strip(), digest)).fetchone()
        if not row or not hmac_mod.compare_digest(row["token_sha256"], digest):
            return {"ok": False, "reason": "unknown token for this device"}
        if row["revoked_at"]:
            return {"ok": False, "reason": "token was revoked"}
        if row["used_at"]:
            return {"ok": False, "reason": "token already used"}
        if (row["expires_at"] or "") < _now():
            return {"ok": False, "reason": "token expired"}
        c.execute("UPDATE emergency_tokens SET used_at=? WHERE id=?",
                  (_now(), row["id"]))
    return {"ok": True, "token_id": row["token_id"],
            "purpose": row["purpose"] or "withdraw_uninstall"}


def revoke_token(token_id: str, by: str = "") -> dict:
    with connect() as c:
        cur = c.execute("UPDATE emergency_tokens SET revoked_at=? "
                        "WHERE token_id=? AND revoked_at IS NULL",
                        (_now(), (token_id or "").strip()))
        _ = by
    if not cur.rowcount:
        raise ValueError(f"no live token {token_id!r}")
    return {"token_id": token_id, "revoked": True}


def list_tokens(device_id: str) -> list:
    """Audit view: handles and state, never hashes."""
    with connect() as c:
        rows = c.execute(
            "SELECT token_id, device_id, label, purpose, created_at, "
            "created_by, expires_at, used_at, revoked_at FROM emergency_tokens "
            "WHERE device_id=? ORDER BY id DESC LIMIT 50",
            ((device_id or "").strip(),)).fetchall()
    return [dict(r) for r in rows]


def provision_token(device_id: str, serial: str = "", signing_key_: str = "",
                    chan_dir: str = "", ttl_hours: int = TOKEN_TTL_HOURS,
                    created_by: str = "",
                    purpose: str = "withdraw_uninstall") -> dict:
    """Issue a token AND deliver its hash to the agent in a signed envelope.

    Must run while USB works (that is the whole point: provision early, use
    late). Returns the plaintext token ONCE plus the channel delivery record.
    """
    from . import command
    from .channel import adb_channel
    from .config import PROJECT_ROOT, ed25519_private_hex, signing_key
    os.environ.setdefault("ALP_SIGNING_KEY",
                          signing_key_ or signing_key())
    if not serial:
        with connect() as c:
            row = c.execute("SELECT serial FROM devices WHERE device_id=?",
                            ((device_id or "").strip(),)).fetchone()
        serial = row["serial"] if row else (device_id or "").strip()
    pk = ed25519_private_hex()
    if not pk:
        raise RuntimeError(
            "Ed25519 private key not configured — run scripts/gen_agent_key.py "
            "or set ALP_ED_PRIV (the embedded APK key must match)")
    issued = issue_token(device_id, created_by=created_by,
                         label="device-provisioned", ttl_hours=ttl_hours,
                         purpose=purpose)
    env = command.new_command(1, device_id, "EMERGENCY_TOKEN",
                              {"token_sha256": _digest(issued["token"]),
                               "token_id": issued["token_id"],
                               "purpose": issued["purpose"],
                               "expires_at": issued["expires_at"]}, ed_key=pk)
    out_dir = chan_dir or os.path.join(PROJECT_ROOT, "reports", "phase1",
                                       "commands")
    send, _state = adb_channel(serial or device_id, out_dir=out_dir)
    delivery = send(env, "EMERGENCY_TOKEN")
    return {"token_id": issued["token_id"], "token": issued["token"],
            "device_id": device_id, "purpose": issued["purpose"],
            "expires_at": issued["expires_at"],
            "delivery": delivery,
            "warning": issued["warning"]}


def _offline_counter(when=None) -> int:
    import time as _time
    ts = _time.time() if when is None else float(when)
    return int(ts // OFFLINE_STEP_SECONDS)


def _offline_code_for(secret: bytes, purpose: str, counter: int) -> str:
    """Pure derivation both sides implement byte-identically (agent mirrors
    this in EmergencyCodes.java; any drift breaks offline verification, so
    the cross-implementation vector test below pins it)."""
    import hmac as _hmac
    import struct as _struct
    msg = OFFLINE_DOMAIN + purpose.encode("utf-8") + _struct.pack(">Q", counter)
    digest = _hmac.new(secret, msg, digestmod=__import__("hashlib").sha256).digest()
    offset = digest[-1] & 0x0F
    code = _struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** OFFLINE_DIGITS)).zfill(OFFLINE_DIGITS)


def _offline_secret(device_id: str) -> bytes:
    from .recovery_credentials import RecoveryVault
    device_id = (device_id or "").strip()
    vault = RecoveryVault()
    # Never auto-create here: deriving must fail closed for unknown devices.
    # Secrets come into being only through explicit provisioning
    # (enrollment / provision_offline_secret), while a channel exists.
    if vault.status(device_id).get("recovery") != "Configured":
        raise ValueError("no recovery credential for %r — enroll/provision "
                         "it first (the offline secret is exchanged while "
                         "the channel is alive)" % device_id)
    return vault.offline_secret(device_id)


def offline_code(device_id: str, purpose: str, when=None) -> dict:
    """Derive the current offline emergency code. Needs no channel — only
    the console (which guards the vault root key) and the device (which was
    provisioned the same secret) can produce it."""
    if purpose not in PURPOSES:
        raise ValueError("purpose must be one of: " + ", ".join(sorted(PURPOSES)))
    secret = _offline_secret(device_id)
    counter = _offline_counter(when)
    import datetime as _dt
    valid_until = _dt.datetime.fromtimestamp(
        (counter + 1) * OFFLINE_STEP_SECONDS,
        tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"device_id": (device_id or "").strip(), "purpose": purpose,
            "code": _offline_code_for(secret, purpose, counter),
            "counter": counter, "step_seconds": OFFLINE_STEP_SECONDS,
            "valid_until": valid_until,
            "warning": "read it to the holder over a trusted channel; "
                       "it expires with its time window"}


def verify_offline_code(device_id: str, purpose: str, code: str,
                        when=None, window: int = OFFLINE_WINDOW) -> bool:
    """Console-side check (same math as the agent). Single-use is enforced
    on the DEVICE (it burns purpose+counter); here only the window matches."""
    import hmac as _hmac
    if purpose not in PURPOSES:
        return False
    try:
        secret = _offline_secret(device_id)
    except ValueError:
        return False
    counter = _offline_counter(when)
    want = (code or "").strip()
    for c in range(counter - window, counter + 1 + window):
        if _hmac.compare_digest(_offline_code_for(secret, purpose, c), want):
            return True
    return False


def provision_offline_secret(device_id: str, serial: str = "",
                             signing_key_: str = "",
                             chan_dir: str = "") -> dict:
    """Push the per-device offline secret into the agent inside a SIGNED
    envelope (same pipeline as the rollback PIN). Must run while USB works;
    afterwards codes verify with no channel at all. Returns delivery record
    (the secret itself is never returned — it already lives in the vault)."""
    import base64 as _b64
    from . import command
    from .channel import adb_channel
    from .config import PROJECT_ROOT, ed25519_private_hex, signing_key
    os.environ.setdefault("ALP_SIGNING_KEY",
                          signing_key_ or signing_key())
    if not serial:
        with connect() as c:
            row = c.execute("SELECT serial FROM devices WHERE device_id=?",
                            ((device_id or "").strip(),)).fetchone()
        serial = row["serial"] if row else (device_id or "").strip()
    pk = ed25519_private_hex()
    if not pk:
        raise RuntimeError(
            "Ed25519 private key not configured — run scripts/gen_agent_key.py "
            "or set ALP_ED_PRIV (the embedded APK key must match)")
    secret = _offline_secret(device_id)
    env = command.new_command(1, device_id, "EMERGENCY_SECRET",
                              {"secret_b64": _b64.b64encode(secret).decode("ascii")},
                              ed_key=pk)
    out_dir = chan_dir or os.path.join(PROJECT_ROOT, "reports", "phase1",
                                       "commands")
    send, _state = adb_channel(serial or device_id, out_dir=out_dir)
    delivery = send(env, "EMERGENCY_SECRET")
    return {"device_id": (device_id or "").strip(), "delivery": delivery,
            "provisioned": bool(delivery and delivery.get("ok")),
            "note": "derive codes with /recovery/emergency/offline-code"}
