"""Reset an administrator's password (keeps TOTP by default).

Usage:
  python scripts/reset_admin.py admin newpass
  python scripts/reset_admin.py admin newpass --new-mfa    # fresh TOTP secret
  python scripts/reset_admin.py admin newpass --no-mfa     # disable 2nd factor

Prints the TOTP secret and a *current* 6-digit login code. Add the secret to
Google Authenticator once, then log the console in with:
  username : <user>
  password : <newpass>
  TOTP     : the 6-digit code from the app (renews every 30s)
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.auth import (_b32_decode, _totp_at,  # noqa: E402
                         generate_totp_secret, hash_password)
from backend.db import connect  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if len(args) not in (2, 3) or "--help" in args or "-h" in args:
        print(__doc__)
        return 2
    username, password = args[0], args[1]
    flag = args[2] if len(args) == 3 else ""

    if len(password) < 6:
        print("password must be at least 6 characters")
        return 2

    with connect() as c:
        row = c.execute("SELECT id, mfa_secret FROM administrators WHERE username=?",
                        (username,)).fetchone()
        if not row:
            print(f"no administrator named {username!r}")
            return 1
        admin_id = row["id"]

        secret, otpauth = generate_totp_secret() if flag == "--new-mfa" else (row["mfa_secret"], "")
        mfa_enabled = 0 if flag == "--no-mfa" else 1
        c.execute("UPDATE administrators SET password_hash=?, mfa_secret=?, mfa_enabled=? WHERE id=?",
                  (hash_password(password), secret, mfa_enabled, admin_id))
        tag = {"--new-mfa": "TOTP secret regenerated",
               "--no-mfa": "MFA disabled", "": "password reset, TOTP secret kept"}.get(flag, flag)

    print(f"#id {admin_id} {username}: {tag}")
    if not mfa_enabled:
        print("login: username + password only")
        return 0

    code = _totp_at(_b32_decode(secret), int(time.time()) // 30)
    print(f"username : {username}")
    print(f"password : {password}")
    print(f"TOTP key : {secret}")
    print(f"now code : {code}   (6 digits, renews ~every 30s)")
    print(f"otpauth  : otpauth://totp/ALP:{username}?secret={secret}&issuer=ALP")
    print("Add the TOTP key in Google Authenticator, then use 'now code' to log in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())