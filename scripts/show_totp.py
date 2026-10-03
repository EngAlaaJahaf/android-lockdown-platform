"""Print the stored TOTP secrets (+ current 6-digit codes) from the ALP database.

Usage:  python scripts/show_totp.py
A secret is base32 — add it manually to Google Authenticator via
  نوع الحساب: Time-based (TOTP)  /  المفتاح: <BASE32>
"""
from __future__ import annotations

import sys
import time

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.auth import _b32_decode, _totp_at  # noqa: E402
from backend.db import connect  # noqa: E402

with connect() as c:
    rows = c.execute(
        "SELECT id, username, mfa_enabled, mfa_secret FROM administrators ORDER BY id"
    ).fetchall()

if not rows:
    print("No administrators yet — bootstrap first (first page shows the secret).")
    raise SystemExit(1)

now = time.localtime()
for r in rows:
    secret = r["mfa_secret"] or ""
    if not r["mfa_enabled"] or not secret:
        print(f"#{r['id']} {r['username']}: MFA disabled")
        continue
    code = _totp_at(_b32_decode(secret), int(time.time()) // 30)
    if not secret or secret.endswith("=0"):  # sanity guard only
        print(f"#{r['id']} {r['username']}: bad secret")
        continue
    print(f"#{r['id']} {r['username']}")
    print(f"   secret : {secret}")
    print(f"   add    : Google Authenticator / TOTP -> key {secret}")
    print(f"   now    : {code}  (current code, valid ~30s)")
    print(f"   otpauth: otpauth://totp/ALP:{r['username']}?secret={secret}&issuer=ALP")