# -*- coding: utf-8 -*-
"""Remove the throwaway admins the smoke/verify scripts create.

These are test-only accounts created directly in the DB (never the production
admin). Leftovers would widen the login surface, so they are cleaned here.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend.db import connect  # noqa: E402

LEFTOVERS = ("posmoke_super", "posmoke_ro", "verify_note_admin",
             "apitest_super", "apitest_ro")

with connect() as c:
    c.execute("PRAGMA foreign_keys=OFF")
    removed = 0
    for user in LEFTOVERS:
        n = c.execute("SELECT COUNT(*) FROM administrators WHERE username=?",
                      (user,)).fetchone()[0]
        if not n:
            continue
        for t in ("sessions", "audit_logs", "approvals",
                  "approval_confirmations", "command_nonces"):
            try:
                cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
            except Exception:
                continue
            for key in ("username", "user_id", "user_ref", "admin_id", "actor",
                        "actor_username", "requester", "approver_1",
                        "approver_2", "initiated_by", "created_by"):
                if key in cols:
                    try:
                        c.execute("DELETE FROM %s WHERE %s=?" % (t, key), (user,))
                    except Exception:
                        pass
        c.execute("DELETE FROM administrators WHERE username=?", (user,))
        removed += n
    c.commit()

print("removed %d throwaway admin(s)" % removed)
with connect() as c:
    print("remaining admins:", [r["username"] for r in
                               c.execute("SELECT username FROM administrators")])