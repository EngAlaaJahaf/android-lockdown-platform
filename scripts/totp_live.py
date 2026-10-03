"""Live TOTP code display for the ALP console.

Reads the stored admin TOTP secret and shows the current 6-digit login code,
refreshing every second with a countdown. Run in a side terminal next to the
browser while logging in. Ctrl+C to stop.

Usage:  python scripts/totp_live.py
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.auth import _b32_decode, _totp_at  # noqa: E402
from backend.db import connect  # noqa: E402

WINDOW = 30


def main() -> int:
    with connect() as c:
        rows = c.execute(
            "SELECT id, username, mfa_secret FROM administrators WHERE mfa_enabled=1 "
            "ORDER BY id").fetchall()
    if not rows:
        print("No administrator with MFA enabled. Bootstrap or reset admin first.")
        return 1

    who = rows[0]["username"]
    secret = rows[0]["mfa_secret"]

    print(f"ALP login code for console  (user: {who})")
    print(f"secret kept: {secret}  -> add once in Google Authenticator if not yet")
    print("code refreshes every 30s. Press Ctrl+C to stop.")
    print("-" * 46)

    last_code = None
    try:
        while True:
            now = int(time.time())
            cnt = now // WINDOW
            left = WINDOW - (now % WINDOW)
            code = _totp_at(_b32_decode(secret), cnt)
            if code != last_code:
                sys.stdout.write("\n")
                last_code = code
            bar = "#" * (left * 20 // WINDOW) + "-" * (20 - left * 20 // WINDOW)
            sys.stdout.write(f"\r  CODE: {code}   expires in {left:2d}s  [{bar}]\033[K")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())