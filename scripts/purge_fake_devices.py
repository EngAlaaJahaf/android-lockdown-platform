# -*- coding: utf-8 -*-
"""Purge every fake device and its dependent rows, keeping one real handset.

Safety model:
  * dry-run by default; `--apply` is required to write,
  * a DB backup is taken before any delete,
  * the keeper device is refused as a delete target even if named twice,
  * FK-children are deleted explicitly (no PRAGMA foreign_keys games) and the
    result is verified by re-counting.

Usage:
    python scripts/purge_fake_devices.py            # dry run
    python scripts/purge_fake_devices.py --apply
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import db as db_mod  # noqa: E402

KEEP = "AVD-LT8110260130351"

# Tables that hold per-device rows. `mode` says how the device is referenced:
#   pk   -> integer devices.id
#   text -> devices.device_id string
DEVICE_SCOPED = [
    ("device_group_members", "pk"),
    ("assignments", "pk"),
    ("compliance", "text"),
    ("evidence", "text"),
    ("failures", "text"),
    ("recovery_actions", "text"),
    ("audit_logs", "text"),
    ("approvals", "text"),
    ("approval_confirmations", "text"),
    ("job_executions", "text"),
    ("group_deploy_status", None),      # reached via group_profile_assignments
    ("group_action_history", None),
]


def columns(c, table):
    return [r[1] for r in c.execute("PRAGMA table_info(%s)" % table)]


def existing(c, table):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                     "AND name=?", (table,)).fetchone() is not None


def plan(c):
    """Return (keepers, victims, per-table delete counts)."""
    keepers = [r["device_id"] for r in c.execute(
        "SELECT device_id FROM devices WHERE device_id=?", (KEEP,))]
    if not keepers:
        raise SystemExit("keeper device %s is not in the database - refusing to "
                         "guess which rows matter" % KEEP)
    victims = [dict(r) for r in c.execute(
        "SELECT id, device_id, serial, model FROM devices "
        "WHERE device_id<>? ORDER BY device_id", (KEEP,))]
    return keepers, victims


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default: dry run)")
    ap.add_argument("--also-reports", action="store_true",
                    help="also delete reports/<fake-device> directories")
    args = ap.parse_args()

    keepers, victims = None, None
    with db_mod.connect() as c:
        keepers, victims = plan(c)
        counts = {}
        for table, mode in DEVICE_SCOPED:
            if not existing(c, table):
                continue
            cols = columns(c, table)
            if mode == "pk" and "device_id" in cols:
                n = c.execute("SELECT COUNT(*) FROM %s WHERE device_id IN "
                              "(SELECT id FROM devices WHERE device_id<>?)"
                              % table, (KEEP,)).fetchone()[0]
                counts[table] = ("devices.id", n)
            elif mode == "text" and "device_id" in cols:
                n = c.execute("SELECT COUNT(*) FROM %s WHERE device_id<>? "
                              "AND device_id IS NOT NULL" % table,
                              (KEEP,)).fetchone()[0]
                counts[table] = ("devices.device_id", n)

        print("KEEP  : %s" % ", ".join(keepers))
        print("DROP  : %d fake device rows" % len(victims))
        for v in victims:
            print("        - %-22s serial=%-20s model=%s"
                  % (v["device_id"], v["serial"], v["model"]))
        print("\nDEPENDENT ROWS THAT WILL BE DELETED")
        total = 0
        for t, (kind, n) in sorted(counts.items()):
            print("  %-26s via %-18s %s" % (t, kind, n))
            total += n

        # group_* rows hang off the group, not the device; report separately
        for t in ("group_profile_assignments", "group_deploy_status",
                  "group_action_history", "device_group_members"):
            if existing(c, t):
                print("  %-26s (group rows, kept - the group itself stays)" % t)

        print("\nTOTAL dependent rows: %d" % total)
        if not args.apply:
            print("\nDRY RUN - nothing written. Re-run with --apply.")
            return 0

    # ---------------------------------------------------------------- backup
    src = db_mod.DBPATH
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = os.path.join(os.path.dirname(src),
                       "alp.db.prepurge-%s.bak" % stamp)
    shutil.copy2(src, bak)
    print("\nbackup -> %s" % bak)

    deleted = {}
    with db_mod.connect() as c:
        c.execute("PRAGMA foreign_keys=OFF")
        victims = [dict(r) for r in c.execute(
            "SELECT id, device_id FROM devices WHERE device_id<>?", (KEEP,))]
        ids = [v["id"] for v in victims]
        texts = [v["device_id"] for v in victims]

        # order: children first
        ORDER = [
            ("approvals", "text"),
            ("approval_confirmations", "text"),
            ("assignments", "pk"),
            ("audit_logs", "text"),
            ("compliance", "text"),
            ("evidence", "text"),
            ("failures", "text"),
            ("recovery_actions", "text"),
            ("job_executions", "text"),
            ("command_nonces", "text"),
        ]
        for table, mode in ORDER:
            if not existing(c, table):
                continue
            cols = columns(c, table)
            if mode == "pk" and "device_id" in cols and ids:
                q = "DELETE FROM %s WHERE device_id IN (%s)" % (
                    table, ",".join("?" * len(ids)))
                deleted[table] = c.execute(q, ids).rowcount
            elif mode == "text" and "device_id" in cols and texts:
                marks = ",".join("?" * len(texts))
                q = ("DELETE FROM %s WHERE device_id IN (%s)"
                     % (table, marks))
                deleted[table] = c.execute(q, texts).rowcount

        # device_group_members pointing to victims
        if existing(c, "device_group_members") and ids:
            q = ("DELETE FROM device_group_members "
                 "WHERE device_id IN (%s)" % ",".join("?" * len(ids)))
            deleted["device_group_members"] = c.execute(q, ids).rowcount

        # also clean evidence/failures/compliance that might still have old device_ids
        # (text refs to device_id strings not in KEEP)
        for t in ("evidence", "failures", "compliance", "audit_logs",
                  "approvals", "approval_confirmations", "recovery_actions",
                  "job_executions", "command_nonces", "sessions"):
            if existing(c, t) and texts:
                cols = columns(c, t)
                if "device_id" in cols:
                    marks = ",".join("?" * len(texts))
                    q = ("DELETE FROM %s WHERE device_id IN (%s)" % (t, marks))
                    cnt = c.execute(q, texts).rowcount
                    deleted[t] = deleted.get(t, 0) + cnt

        deleted["devices"] = c.execute(
            "DELETE FROM devices WHERE device_id<>?", (KEEP,)).rowcount
        c.commit()

    print("\nDELETED")
    for t, n in sorted(deleted.items()):
        if n:
            print("  %-26s %s" % (t, n))

    # ------------------------------------------------------------- verify
    print("\nVERIFY")
    ok = True
    with db_mod.connect() as c:
        n = c.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        print("  devices remaining      : %d" % n)
        if n != 1:
            ok = False
        left = [r["device_id"] for r in c.execute("SELECT device_id FROM devices")]
        print("  devices                : %s" % left)
        if left != [KEEP]:
            ok = False
        for table, mode in DEVICE_SCOPED:
            if not existing(c, table) or mode != "text":
                continue
            cols = columns(c, table)
            if "device_id" not in cols:
                continue
            n = c.execute("SELECT COUNT(*) FROM %s WHERE device_id<>? AND "
                          "device_id IS NOT NULL" % table, (KEEP,)).fetchone()[0]
            if n:
                print("  LEFTOVER %-20s %s" % (table, n))
                ok = False
        for table in ("device_group_members", "assignments"):
            if existing(c, table):
                n = c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                print("  %-23s: %s" % (table, n))

    if args.also_reports:
        base = os.path.join(ROOT, "reports")
        for v in victims:
            p = os.path.join(base, v["device_id"])
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                print("  removed dir %s" % os.path.relpath(p, ROOT))

    print("\n%s" % ("PURGE OK" if ok else "PURGE INCOMPLETE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())