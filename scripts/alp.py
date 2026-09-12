"""ALP Desktop Manager CLI (PHASE 1).

Pure-stdlib control plane over the backend services:

    bootstrap  create the first SUPER_ADMIN (TOTP provisioned)
    login      username + password + MFA code -> short-lived session
    logout / whoami
    devices    list Device Registry
    enroll     live ADB scan -> register device + profile + capabilities
    policies   persist reference policies (idempotent) and list them
    apply      run the full Director AD-4 pipeline for one device
    jobs       list fleet jobs
    approvals  list / approve (dual rule for destructive ops)
    audit      tail the hash-chained audit + tamper check
    sim        FleetSimulator staged rollout (1000 devices, synthetic)
    report     generate reports/phase1/PHASE1_REPORT.md

Honesty: `apply` without --real stages the command only; --real reads actual
state over ADB and reports only what it could observe. PASS requires a real
device observation (source=REAL_DEVICE) AND an evidence id — never invented.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
for sub in ("policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters"):
    sys.path.insert(0, os.path.join(ROOT, sub))

import backend.config as config                # noqa: E402
from backend.db import connect, run_migrations  # noqa: E402
from backend import auth, audit, fleet, approval as approval_mod  # noqa: E402
from backend.director import ApplyBlocked, DirectorError  # noqa: E402
from backend.workflows import (enroll_device, persist_reference_policies,  # noqa: E402
                               run_director_apply, attached_serials)

SESSION_FILE = os.path.join(ROOT, ".alp", "session.json")


def _session_dir() -> str:
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    return os.path.dirname(SESSION_FILE)


# ---------------------------------------------------------------------------
# Sessions / auth helpers
# ---------------------------------------------------------------------------

def save_session(session: dict) -> None:
    _session_dir()
    with open(SESSION_FILE, "w", encoding="utf-8") as fh:
        json.dump(session, fh, ensure_ascii=False, indent=2)


def load_session() -> dict | None:
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def require_session(mention_token: str = "") -> dict | None:
    sess = load_session()
    if not sess or not sess.get("token"):
        print("no session — run: python scripts/alp.py login")
        return None
    row = auth.resolve_session(sess["token"])
    if not row:
        print("session expired — run: python scripts/alp.py login")
        save_session({})
        return None
    return dict(row)


def owner(require: bool = True) -> dict | None:
    s = require_session()
    if require and not s:
        sys.exit(2)
    return s


def totp_ok(sess: dict, code: str) -> bool:
    with connect() as c:
        r = c.execute("SELECT mfa_secret FROM administrators WHERE id=?",
                      (sess.get("admin_id") or sess.get("id"),)).fetchone()
    return bool(r and r["mfa_secret"] and auth.totp_verify(r["mfa_secret"], code))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_bootstrap(args):
    run_migrations()
    with connect() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM administrators").fetchone()["n"]
        if n > 0:
            print(f"administrators already exist ({n}) — use `alp login`")
            return 1
        pw_hash = auth.hash_password(args.password)
        b32, uri = auth.generate_totp_secret()
        c.execute(
            "INSERT INTO administrators (username, display_name, role_id, password_hash, mfa_secret, mfa_enabled) "
            "VALUES (?,?,1,?,?,1)",
            (args.user, args.user, pw_hash, b32))
    print("bootstrap OK — save the TOTP secret now:")
    print(f"  uri : {uri}")
    print("Add it to an authenticator app, then `alp login` with a generated code.")


def cmd_login(args):
    run_migrations()
    with connect() as c:
        row = c.execute("SELECT * FROM administrators WHERE username=? AND active=1",
                        (args.user,)).fetchone()
    if not row or not row["password_hash"]:
        print("bad username or password")
        return 1
    if not auth.verify_password(args.password, row["password_hash"]):
        print("bad username or password")
        return 1
    if row["mfa_enabled"] and not auth.totp_verify(row["mfa_secret"] or "", args.code):
        print("bad MFA code")
        return 1
    token = auth.create_session(row["id"])
    save_session({"token": token})
    print(f"logged in as {row['username']} (role_id={row['role_id']}, session={token[:12]}…)")


def cmd_whoami(args):
    s = owner(require=False)
    if not s:
        return 1
    print(f"{s['username']}  role_code={s['role_code']}  token={s['token'][:12]}…")


def cmd_logout(args):
    s = load_session()
    if s and s.get("token"):
        try:
            auth.revoke_session(s["token"])
        except Exception:
            pass
    save_session({})
    print("logged out")


def cmd_devices(args):
    with connect() as c:
        rows = c.execute(
            "SELECT device_id, model, android_version, enrollment_state, compliance_state, is_lab "
            "FROM devices ORDER BY id").fetchall()
    if not rows:
        print("no devices registered — run `alp enroll` or seed_devices.py")
        return 0
    print(f"{'DEVICE':<12} {'MODEL':<10} {'OS':>3} {'STATE':<18} {'COMPLIANCE':<11} LAB")
    for r in rows:
        print(f"{r['device_id']:<12} {r['model'] or '-':<10} {r['android_version'] or 0:>3} "
              f"{r['enrollment_state']:<18} {r['compliance_state'] or 'UNKNOWN':<11} {r['is_lab']}")


def cmd_enroll(args):
    run_migrations()
    devs = attached_serials()
    if not devs:
        print("NO DEVICES ATTACHED — nothing scanned")
        return 1
    serial = args.serial or devs[0]
    info = enroll_device(args.device_id, serial,
                         device_owner=args.device_owner, lab=args.lab)
    print(f"enrolled {info['device_id']}: {info['manufacturer']} {info['model']} "
          f"android={info['android_version']} api={info['api_level']} "
          f"owner={info['device_owner']}")
    return 0


def cmd_policies(args):
    run_migrations()
    n = persist_reference_policies()
    with connect() as c:
        rows = c.execute(
            "SELECT policy_id, category, version, status FROM policies ORDER BY category, policy_id").fetchall()
    print(f"synced {n} reference policies from policy-engine:")
    for r in rows:
        print(f"  {r['policy_id']:<20} {r['category']:<18} v{r['version']} [{r['status']}]")


def cmd_apply(args):
    run_migrations()
    sess = owner()
    mfa_ok = bool(args.mfa) and totp_ok(sess, args.mfa)
    if not mfa_ok:
        print("MFA code required/incorrect — an MFA-verified actor is mandatory for APPLY.")
        return 1
    try:
        res = run_director_apply(
            args.device, args.policy, op_role=sess["role_code"], mfa_ok=mfa_ok,
            serial=args.serial or None, real=args.real, signing_key=config.SIGNING_KEY,
            chan_dir=os.path.join(ROOT, "reports", "phase1", "commands"))
    except ApplyBlocked as ex:
        print(f"APPLY BLOCKED: {ex}")
        return 1
    except DirectorError as ex:
        print(f"DIRECTOR ERROR: {ex}")
        return 1
    except ValueError as ex:
        print(f"ERROR: {ex}")
        return 1
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_jobs(args):
    with connect() as c:
        rows = c.execute(
            "SELECT j.job_id, j.job_type, j.status, j.priority, count(e.id) AS execs "
            "FROM jobs j LEFT JOIN job_executions e ON e.job_id=j.id "
            "GROUP BY j.id ORDER BY j.id DESC LIMIT 20").fetchall()
    if not rows:
        print("no jobs yet")
        return 0
    for r in rows:
        print(f"{r['job_id']:<22} {r['job_type']:<14} {r['status']:<14} prio={r['priority']} execs={r['execs']}")


def cmd_approve(args):
    sess = owner()
    with connect() as c:
        row = c.execute("SELECT * FROM approvals WHERE approval_id=?",
                        (args.approval_id,)).fetchone()
    if not row:
        print(f"no such approval {args.approval_id}")
        return 1
    print(f"action={row['action']} requester={row['requester']} decision={row['decision']} "
          f"reason={row['reason']}")
    mfa_ok = totp_ok(sess, args.mfa) if args.mfa else False
    if not mfa_ok:
        print("MFA required to approve")
        return 1
    try:
        out = approval_mod.approve(args.approval_id, sess["admin_id"], mfa_ok=mfa_ok)
        print("approved" if out.get("approved") else "first approver recorded — waiting for second")
    except ValueError as ex:
        print(f"approval failed: {ex}")
        return 1


def cmd_audit(args):
    lg = audit.AuditLog()
    if args.tamper:
        print(json.dumps(lg.tamper_check(), indent=2, ensure_ascii=False))
    for e in lg.tail(args.tail):
        print(f"{e['created_at']} [{e['role']}] {e['action']:<14} dev={e['device_id'] or '-':<11} "
              f"res={e['result'] or '-'}")


def cmd_sim(args):
    res = fleet.simulate_bulk(args.policy, n=args.n)
    for w in res["waves"]:
        print(f"wave {w['wave']}: devices={w['devices']} ok={w['ok']} failed={w['failed']}")
    print(f"stage={res['stage']}" + (f" why={res.get('why')}" if res.get("why") else ""))


def cmd_report(args):
    os.makedirs(os.path.join(ROOT, "reports", "phase1"), exist_ok=True)
    with connect() as c:
        devs = c.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"]
        pols = c.execute("SELECT COUNT(*) AS n FROM policies").fetchone()["n"]
        ev = c.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
        aud = c.execute("SELECT COUNT(*) AS n FROM audit_logs").fetchone()["n"]
        assign = c.execute("SELECT COUNT(*) AS n FROM assignments").fetchone()["n"]
    body = f"""# PHASE 1 REPORT — Control Plane (CLI)

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

## Registry
- devices: {devs}
- policies persisted: {pols}
- assignments recorded: {assign}
- evidence rows: {ev}
- audit entries (hash-chained): {aud}

## CLI surface (scripts/alp.py)
bootstrap · login · whoami · logout · devices · enroll · policies · apply ·
jobs · approvals · audit · sim · report

## Honesty invariants
- apply without --real: source=SIMULATED → PASS structurally impossible.
- apply --real: only ADB-observable lanes enter the actual map; missing lanes
  stay UNKNOWN (verdict UNKNOWN/PARTIAL, never fake PASS).
- evidence_id is minted by the Director before verification and stamped
  PENDING→result; PASS requires a real device observation.
"""
    path = os.path.join(ROOT, "reports", "phase1", "PHASE1_REPORT.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"written -> {path}")


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="alp", description="ALP Desktop Manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bootstrap", help="create first SUPER_ADMIN (TOTP provisioned)")
    b.add_argument("--user", default="admin")
    b.add_argument("--password", default="admin")
    b.set_defaults(func=cmd_bootstrap)

    li = sub.add_parser("login")
    li.add_argument("--user", default="admin")
    li.add_argument("--password", default="admin")
    li.add_argument("--code", default="")
    li.set_defaults(func=cmd_login)

    sub.add_parser("whoami").set_defaults(func=cmd_whoami)
    sub.add_parser("logout").set_defaults(func=cmd_logout)
    sub.add_parser("devices").set_defaults(func=cmd_devices)

    en = sub.add_parser("enroll", help="live ADB scan -> register device+profile")
    en.add_argument("--device-id", default="")
    en.add_argument("--serial", default="")
    en.add_argument("--device-owner", action="store_true")
    en.add_argument("--lab", action="store_true")
    en.set_defaults(func=cmd_enroll)

    po = sub.add_parser("policies", help="sync reference policies + list")
    po.set_defaults(func=cmd_policies)

    ap = sub.add_parser("apply", help="Director AD-4 pipeline for one device")
    ap.add_argument("--device", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--serial", default="", help="adb serial (defaults to device row)")
    ap.add_argument("--real", action="store_true", help="observe actual state over ADB")
    ap.add_argument("--mfa", default="", help="TOTP code (mandatory for APPLY)")
    ap.set_defaults(func=cmd_apply)

    sub.add_parser("jobs").set_defaults(func=cmd_jobs)

    ap2 = sub.add_parser("approvals", help="approve a request (dual rule enforced)")
    ap2.add_argument("--approval-id", required=True)
    ap2.add_argument("--mfa", default="")
    ap2.set_defaults(func=cmd_approve)

    au = sub.add_parser("audit")
    au.add_argument("--tail", type=int, default=20)
    au.add_argument("--tamper", action="store_true")
    au.set_defaults(func=cmd_audit)

    sm = sub.add_parser("sim", help="FleetSimulator staged rollout (synthetic)")
    sm.add_argument("--n", type=int, default=1000)
    sm.add_argument("--policy", default="POL-PHONE_ONLY")
    sm.set_defaults(func=cmd_sim)

    rp = sub.add_parser("report")
    rp.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args) if hasattr(args, "func") else p.print_help()


if __name__ == "__main__":
    sys.exit(main())