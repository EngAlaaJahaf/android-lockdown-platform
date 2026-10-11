"""Device Groups — group CRUD, membership, group->profile association, and the
automatic deployment triggered by either event.

Design source (read-only reference, never copied wholesale):
  design-ref/mdm-plus-groups-profiles.txt
  docs/reference/memdm/memdm-schema.sql  (ManageEngine MDM Plus 11.2.2508.01)

memdm table -> ALP table
  customgroup                -> device_groups
  customgroupmemberrel       -> device_group_members
  grouptoprofilehistory      -> group_profile_assignments
  groupcollnstatussummary    -> group_deploy_status
  groupactionhistory         -> group_action_history
  mdmresourcetoprofilehistory-> assignments

A ManageEngine "Profile" is a bundle of restrictions; in ALP that bundle is a
`policies` row, so group_profile_assignments.policy_id references policies(id).
`device_profiles` is NOT that concept -- it is the hardware model row
(manufacturer/model/api_level) that carries `capabilities`.

Honesty rules baked into this module:
  * Deployment outcomes are stored per (device, policy) in `assignments` and the
    summary counters are DERIVED from those rows. Nothing is written
    optimistically, so a profile can never look fully green because a column
    defaulted to 0.
  * With no device attached the pipeline only ever reaches STAGED. STAGED is
    reported as yet-to-apply, never as success. Only REAL_DEVICE evidence with a
    PASS/PartIAL verification counts as success.
  * A lane that is VENDOR_DEPENDENT / NOT_FEASIBLE makes the whole profile
    NOT_APPLICABLE for that device rather than silently deploying less than the
    admin asked for.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from .db import connect

# Outcome vocabulary written to assignments.verify_result.
OUT_APPLIED = "APPLIED"            # REAL_DEVICE evidence + PASS
OUT_PARTIAL = "PARTIAL"            # REAL_DEVICE evidence + PARTIAL
OUT_STAGED = "STAGED"              # prepared/delivered, NOT confirmed on device
OUT_FAILED = "FAILED"              # pipeline raised
OUT_NOT_APPLICABLE = "NOT_APPLICABLE"  # profile has no enforceable mechanism here

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class GroupError(Exception):
    """Bad group input (maps to HTTP 400 in the API layer)."""


# --------------------------------------------------------------------- helpers
def _slug(name: str) -> str:
    s = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return s or "group"


def _unique_key(c, name: str, exclude_id: int | None = None) -> str:
    base = _slug(name)
    key, n = base, 1
    while True:
        row = c.execute("SELECT id FROM device_groups WHERE group_key=?", (key,)).fetchone()
        if not row or (exclude_id is not None and row["id"] == exclude_id):
            return key
        n += 1
        key = "%s-%d" % (base, n)


def _device_pk(c, device_id: str) -> int:
    """Resolve the integer FK target; raises if the device is not registered.

    Deliberately NOT an INSERT OR IGNORE placeholder: group membership must never
    invent a device that no enrollment produced.
    """
    did_str = str(device_id)
    r = c.execute(
        "SELECT id FROM devices WHERE device_id=? OR serial=? OR id=?",
        (did_str, did_str, int(did_str) if did_str.isdigit() else -1)
    ).fetchone()
    if not r:
        raise GroupError("device %r is not registered" % device_id)
    return r["id"]


def _group_pk(c, group_id) -> int:
    r = None
    try:
        gid = int(group_id)
        r = c.execute("SELECT id FROM device_groups WHERE id=?", (gid,)).fetchone()
    except (ValueError, TypeError):
        pass
    if not r:
        r = c.execute(
            "SELECT id FROM device_groups WHERE name=? OR group_key=?",
            (str(group_id), str(group_id))
        ).fetchone()
    if not r:
        raise GroupError("group %r not found" % group_id)
    return r["id"]


def _policy_pk(c, policy_id: str) -> int:
    r = c.execute("SELECT id FROM policies WHERE policy_id=?", (policy_id,)).fetchone()
    if not r:
        r = c.execute("SELECT id FROM policies WHERE root_id=? ORDER BY (status='ACTIVE') DESC, version DESC LIMIT 1", (policy_id,)).fetchone()
    if not r:
        raise GroupError("profile %r not found" % policy_id)
    return r["id"]


# ------------------------------------------------------------------ group CRUD
def create_group(name: str, description: str = "", membership_type: str = "STATIC",
                 platform_type: str = "ANDROID", created_by: str = "",
                 criteria_json: str | None = None) -> dict:
    """Create a device group. Mirrors the ManageEngine 'Create New Group' form."""
    name = (name or "").strip()
    if not name:
        raise GroupError("group name is required")
    mt = (membership_type or "STATIC").strip().upper()
    if mt not in ("STATIC", "DYNAMIC"):
        raise GroupError("membership_type must be STATIC or DYNAMIC")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as c:
        key = _unique_key(c, name)
        cur = c.execute(
            "INSERT INTO device_groups (group_key, name, description, membership_type, "
            "platform_type, created_by, created_at, modified_by, modified_at, criteria_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key, name, description or "", mt, (platform_type or "ANDROID").upper(),
             created_by, now, created_by, now, criteria_json))
        gid = cur.lastrowid
    return get_group(gid)


def list_groups() -> list[dict]:
    """Groups with the same counters the reference list shows."""
    with connect() as c:
        rows = c.execute("SELECT * FROM device_groups ORDER BY name").fetchall()
        out = []
        for g in rows:
            out.append({
                "id": g["id"], "group_key": g["group_key"], "name": g["name"],
                "description": g["description"],
                "membership_type": g["membership_type"],
                "category": g["membership_type"].capitalize(),
                "platform_type": g["platform_type"],
                "created_by": g["created_by"], "created_at": g["created_at"],
                "modified_by": g["modified_by"], "modified_at": g["modified_at"],
                "members": _count_members(c, g["id"]),
                "profiles": _count_profiles(c, g["id"]),
            })
        return out


def _count_members(c, group_id: int) -> int:
    return c.execute("SELECT COUNT(*) n FROM device_group_members WHERE group_id=?",
                     (group_id,)).fetchone()["n"]


def _count_profiles(c, group_id: int) -> int:
    return c.execute("SELECT COUNT(*) n FROM group_profile_assignments WHERE group_id=?",
                     (group_id,)).fetchone()["n"]


def get_group(group_id, with_members: bool = False, with_profiles: bool = False) -> dict:
    with connect() as c:
        _group_pk(c, group_id)
        g = c.execute("SELECT * FROM device_groups WHERE id=?", (int(group_id),)).fetchone()
        out = {
            "id": g["id"], "group_key": g["group_key"], "name": g["name"],
            "description": g["description"],
            "membership_type": g["membership_type"],
            "category": g["membership_type"].capitalize(),
            "platform_type": g["platform_type"],
            "created_by": g["created_by"], "created_at": g["created_at"],
            "modified_by": g["modified_by"], "modified_at": g["modified_at"],
            "members": _count_members(c, g["id"]),
            "profiles": _count_profiles(c, g["id"]),
        }
        if with_members:
            out["member_list"] = list_group_members(group_id)
        if with_profiles:
            out["profile_list"] = list_group_profiles(group_id)
    return out


def update_group(group_id, name: str | None = None, description: str | None = None,
                 modified_by: str = "") -> dict:
    with connect() as c:
        gid = _group_pk(c, group_id)
        if name is not None and name.strip():
            c.execute("UPDATE device_groups SET name=?, group_key=?, modified_by=?, "
                      "modified_at=? WHERE id=?",
                      (name.strip(), _unique_key(c, name, exclude_id=gid), modified_by,
                       datetime.now().strftime("%Y-%m-%d %H:%M:%S"), gid))
        if description is not None:
            c.execute("UPDATE device_groups SET description=?, modified_by=?, modified_at=? "
                      "WHERE id=?", (description, modified_by,
                                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"), gid))
    return get_group(group_id)


def delete_group(group_id) -> dict:
    with connect() as c:
        gid = _group_pk(c, group_id)
        name = c.execute("SELECT name FROM device_groups WHERE id=?", (gid,)).fetchone()["name"]
        c.execute("DELETE FROM device_groups WHERE id=?", (gid,))   # cascades
    return {"deleted": True, "id": int(group_id), "name": name}


# ------------------------------------------------------------------ membership
def list_group_members(group_id) -> list[dict]:
    with connect() as c:
        gid = _group_pk(c, group_id)
        rows = c.execute(
            "SELECT m.added_by, m.added_at, d.device_id, d.manufacturer, d.model, "
            "d.android_version, d.api_level, d.enrollment_state, d.compliance_state, "
            "d.mode, d.serial FROM device_group_members m "
            "JOIN devices d ON d.id = m.device_id WHERE m.group_id=? "
            "ORDER BY d.device_id", (gid,)).fetchall()
        return [{
            "device_id": r["device_id"], "serial": r["serial"],
            "manufacturer": r["manufacturer"], "model": r["model"],
            "android_version": r["android_version"], "api_level": r["api_level"],
            "enrollment_state": r["enrollment_state"],
            "compliance_state": r["compliance_state"], "mode": r["mode"],
            "added_by": r["added_by"], "added_at": r["added_at"],
        } for r in rows]


def _action_id() -> str:
    return "GACT-" + uuid.uuid4().hex[:12].upper()


def _open_action(c, group_id: int, action_id: str, by: str, reason: str = "") -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO group_action_history (group_action_id, group_id, action_id, "
              "reason_message, action_status, initiated_by, initiated_at, last_modified_at) "
              "VALUES (?,?,?,?,'INITIATED',?,?,?)",
              (_action_id(), group_id, action_id, reason, by, now, now))


def _close_action(c, action_row_id: int, status: str, ok: int, bad: int) -> None:
    c.execute("UPDATE group_action_history SET action_status=?, success_count=?, "
              "failure_count=?, last_modified_at=? WHERE id=?",
              (status, ok, bad, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action_row_id))


def _last_action_id(c, group_id: int) -> int | None:
    r = c.execute("SELECT id FROM group_action_history WHERE group_id=? "
                  "ORDER BY id DESC LIMIT 1", (group_id,)).fetchone()
    return r["id"] if r else None


def add_members(group_id, device_ids: list[str], op_role: str, mfa_ok: bool,
                added_by: str = "", serial_for=None, signing_key: str = "",
                chan_dir=None, deploy: bool = True, real: bool = False,
                allow_channel_risk: bool = False) -> dict:
    """Add devices to a group. Adding a device DEPLOYS every profile already
    associated with the group -- the behaviour asked for: membership implies the
    group's profile applies to that device immediately.

    serial_for / signing_key / chan_dir are forwarded to run_director_apply so a
    real transport can be injected; otherwise the apply is staged as usual.
    """
    added, already, deploy_res = [], [], []
    with connect() as c:
        gid = _group_pk(c, group_id)
        for dev in dict.fromkeys(x for x in device_ids if x and x.strip()):
            dpid = _device_pk(c, dev)
            exists = c.execute("SELECT 1 FROM device_group_members WHERE group_id=? "
                               "AND device_id=?", (gid, dpid)).fetchone()
            if exists:
                already.append(dev)
                continue
            c.execute("INSERT INTO device_group_members (group_id, device_id, added_by, added_at) "
                      "VALUES (?,?,?,?)",
                      (gid, dpid, added_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            added.append(dev)
        if added:
            _open_action(c, gid, "ADD_DEVICE", added_by, ",".join(added))
        act = _last_action_id(c, gid) if added else None

    if added and deploy:
        deploy_res = deploy_group(group_id, op_role=op_role, mfa_ok=mfa_ok,
                                  only_devices=added, serial_for=serial_for,
                                  signing_key=signing_key, chan_dir=chan_dir,
                                  action_id="APPLY_ON_JOIN", real=real,
                                  allow_channel_risk=allow_channel_risk)

    if act is not None:
        with connect() as c:
            res = deploy_res.get("summary") if deploy_res else {}
            _close_action(c, act,
                          "COMPLETED" if not res.get("failed") else "PARTIAL",
                          res.get("success", 0), res.get("failed", 0))

    return {"group_id": int(group_id), "added": added, "already_present": already,
            "deploy": deploy_res}


def remove_member(group_id, device_id: str) -> dict:
    with connect() as c:
        gid = _group_pk(c, group_id)
        dpid = _device_pk(c, device_id)
        cur = c.execute("DELETE FROM device_group_members WHERE group_id=? AND device_id=?",
                        (gid, dpid))
    return {"group_id": int(group_id), "device_id": device_id,
            "removed": cur.rowcount > 0}


def move_device(from_group, to_group, device_id: str, moved_by: str = "") -> dict:
    """Reference action 'Move to Group'."""
    remove_member(from_group, device_id)
    return add_members(to_group, [device_id], op_role="", mfa_ok=False,
                       added_by=moved_by, deploy=False)


# ----------------------------------------------------- group -> profile assign
def list_group_profiles(group_id) -> list[dict]:
    """The reference 'Profiles' tab: name, platform, version, execution status."""
    with connect() as c:
        gid = _group_pk(c, group_id)
        rows = c.execute(
            "SELECT a.id, a.policy_id AS assignment_fk, a.distributed_version, "
            "a.assigned_by, a.assigned_at, a.last_modified_at, p.policy_id AS pid, "
            "p.display_name, p.category, p.version, p.status, g.platform_type "
            "FROM group_profile_assignments a "
            "JOIN policies p ON p.id = a.policy_id "
            "JOIN device_groups g ON g.id = a.group_id WHERE a.group_id=? "
            "ORDER BY p.display_name", (gid,)).fetchall()
        out = []
        for r in rows:
            st = deploy_status(c, gid, r["assignment_fk"])
            out.append({
                "assignment_id": r["id"],
                # the TEXT policy_id the console/API uses everywhere, never the
                # integer FK (group_profile_assignments.policy_id -> policies.id)
                "policy_id": r["pid"],
                "profile_name": r["display_name"],
                "profile_type": r["category"],
                "platform_type": r["platform_type"] or "ANDROID",
                "assigned_time": r["assigned_at"],
                "distributed_version": r["distributed_version"],
                "latest_version": r["version"],
                "profile_status": r["status"],
                "execution_status": st,
                "assigned_by": r["assigned_by"],
            })
        return out


def associate_profiles(group_id, policy_ids: list[str], op_role: str, mfa_ok: bool,
                       assigned_by: str = "", remarks: str = "", serial_for=None,
                       signing_key: str = "", chan_dir=None, deploy: bool = True,
                       real: bool = False,
                       allow_channel_risk: bool = False) -> dict:
    """Associate one or more profiles with a group, then deploy to current members.

    Only ACTIVE profiles can be associated: DRAFT has no enforced meaning yet, and
    REJECTED never will. Deploying one would either silently do nothing or ship a
    policy the reviewer refused, so it is refused up front.
    """
    associated, skipped, rejected = [], [], []
    with connect() as c:
        gid = _group_pk(c, group_id)
        for pid in dict.fromkeys(x for x in policy_ids if x and x.strip()):
            ppid = _policy_pk(c, pid)
            row = c.execute("SELECT display_name, version, status FROM policies WHERE id=?",
                            (ppid,)).fetchone()
            if (row["status"] or "").upper() not in ("ACTIVE", "REVIEW"):
                rejected.append({"policy_id": pid, "status": row["status"]})
                continue
            exists = c.execute("SELECT 1 FROM group_profile_assignments WHERE group_id=? "
                               "AND policy_id=?", (gid, ppid)).fetchone()
            if exists:
                skipped.append(pid)
                continue
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO group_profile_assignments (group_id, policy_id, "
                "distributed_version, assigned_by, assigned_at, last_modified_by, "
                "last_modified_at, remarks) VALUES (?,?,?,?,?,?,?,?)",
                (gid, ppid, row["version"], assigned_by, now, assigned_by, now, remarks))
            associated.append(pid)
        if associated:
            _open_action(c, gid, "ASSOCIATE_PROFILE", assigned_by, ",".join(associated))
        act = _last_action_id(c, gid) if associated else None

    deploy_res = {}
    if associated and deploy:
        deploy_res = deploy_group(group_id, op_role=op_role, mfa_ok=mfa_ok,
                                  only_policies=associated, serial_for=serial_for,
                                  signing_key=signing_key, chan_dir=chan_dir,
                                  action_id="APPLY_ON_ASSIGN", real=real,
                                  allow_channel_risk=allow_channel_risk)

    if act is not None:
        with connect() as c:
            res = deploy_res.get("summary") if deploy_res else {}
            _close_action(c, act,
                          "COMPLETED" if not res.get("failed") else "PARTIAL",
                          res.get("success", 0), res.get("failed", 0))

    return {"group_id": int(group_id), "associated": associated,
            "already_associated": skipped, "rejected": rejected,
            "deploy": deploy_res}


def disassociate_profile(group_id, policy_id: str) -> dict:
    """Remove a profile from ONE group.

    The `assignments` cleanup is scoped to devices that are still members of
    other groups carrying the same profile; an assignment row for a device that
    only ever had this profile through THIS group is dropped, because otherwise
    the group_deploy_status join would keep counting a device that no longer
    belongs here. An assignment is NOT touched for devices that remain members
    of another group that still has this profile associated.
    """
    with connect() as c:
        gid = _group_pk(c, group_id)
        ppid = _policy_pk(c, policy_id)
        keep = {
            r["device_id"] for r in c.execute(
                "SELECT m.device_id FROM device_group_members m "
                "JOIN group_profile_assignments ga ON ga.group_id = m.group_id "
                "WHERE ga.policy_id=? AND m.group_id<>? AND m.device_id IN "
                "(SELECT device_id FROM device_group_members WHERE group_id=?)",
                (ppid, gid, gid)).fetchall()
        }
        stale = [r["device_id"] for r in c.execute(
            "SELECT device_id FROM device_group_members WHERE group_id=?",
            (gid,)).fetchall() if r["device_id"] not in keep]
        if stale:
            c.executemany("DELETE FROM assignments WHERE policy_id=? AND device_id=?",
                          [(ppid, d) for d in stale])
        cur = c.execute(
            "DELETE FROM group_profile_assignments WHERE group_id=? AND policy_id=?",
            (gid, ppid))
        c.execute("DELETE FROM group_deploy_status WHERE assignment_id NOT IN "
                  "(SELECT id FROM group_profile_assignments)")
    reconciliation = []
    if cur.rowcount > 0:
        # Resolve AFTER removing the association: another group/profile may
        # still govern the handset. Offline devices receive the same signed
        # desired state on their next policy pull.
        from .agent_policy_pull import build_apply_envelope
        from .channel import adb_channel
        from .workflows import attached_serials
        from .config import signing_key
        with connect() as c:
            members = [dict(r) for r in c.execute(
                "SELECT d.device_id, d.serial FROM devices d "
                "JOIN device_group_members m ON m.device_id=d.id WHERE m.group_id=?",
                (gid,)).fetchall()]
        try:
            attached = set(attached_serials())
        except Exception:
            attached = set()
        for device in members:
            result = {"device_id": device["device_id"], "status": "pending_sync"}
            if device["serial"] in attached:
                try:
                    answer = build_apply_envelope(device["device_id"], signing_key=signing_key())
                    envelope = answer.get("envelope")
                    if envelope:
                        send, _ = adb_channel(device["serial"])
                        delivery = send(envelope, envelope["action"])
                        result.update(status="sent" if delivery.get("ok") else "pending_sync",
                                      action=envelope["action"], delivery=delivery)
                except Exception as ex:
                    result["error"] = str(ex)
            reconciliation.append(result)
    return {"group_id": int(group_id), "policy_id": policy_id,
            "disassociated": cur.rowcount > 0,
            "assignments_cleared": len(stale),
            "assignments_kept": len(keep), "reconciliation": reconciliation}


# ------------------------------------------------------------------- deployment
def _record_assignment(c, device_pk: int, policy_pk: int, policy_id: str,
                       snapshot: str, outcome: str, verified: bool) -> None:
    """Record the current deployment row for one (device, profile) pair.

    The table's unique key is (device_id, policy_id, snapshot), so an upsert on
    (device_id, policy_id) is not available. "Latest deployment wins" is the
    intended semantics, so the prior rows for this pair are deleted and one fresh
    row is written. An explicit DELETE is used rather than INSERT OR REPLACE
    because REPLACE would also try to delete rows in child tables that reference
    this one with ON DELETE NO ACTION.

    applied_at is only set once something actually reached the device; a STAGED
    or NOT_APPLICABLE row keeps it NULL and records the truth in verify_result.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    applied_at = now if outcome in (OUT_APPLIED, OUT_PARTIAL, OUT_FAILED) else None
    c.execute("DELETE FROM assignments WHERE device_id=? AND policy_id=?",
              (device_pk, policy_pk))
    c.execute(
        "INSERT INTO assignments (device_id, policy_id, snapshot, applied_at, "
        "verified_at, verified, verify_result) VALUES (?,?,?,?,?,?,?)",
        (device_pk, policy_pk, snapshot, applied_at,
         now if verified else None, 1 if verified else 0, outcome))


def _classify(result: dict) -> tuple[str, bool]:
    """Map a run_director_apply result to (outcome, verified_on_device)."""
    src = result.get("source")
    ver = (result.get("verification") or "").upper()
    if src == "REAL_DEVICE":
        if ver == "PASS":
            return OUT_APPLIED, True
        if ver == "PARTIAL":
            return OUT_PARTIAL, True
        if result.get("stage") == "COMPLETE":
            return OUT_PARTIAL, True
        return OUT_FAILED, False
    # SIMULATED, or a device that is not attached: prepared only.
    return OUT_STAGED, False


def deploy_group(group_id, op_role: str, mfa_ok: bool, only_devices=None,
                 only_policies=None, serial_for=None, signing_key: str = "",
                 chan_dir=None, action_id: str = "APPLY_PROFILE",
                 real: bool = False, allow_channel_risk: bool = False) -> dict:
    """Deploy every associated profile to every member device (or a subset).

    Per-device outcomes land in `assignments`; the returned summary is derived
    from those rows. A device where the profile has no enforceable mechanism is
    recorded NOT_APPLICABLE instead of being counted as a success.

    Lanes the handset has no mechanism for do not cancel the deployment: the
    enforceable subset is still applied (force=True) and the refused lanes are
    reported per device in `detail` / `unresolved_lanes` so the console can
    name them on the device page.
    """
    from .workflows import run_director_apply
    from .restrictions import by_feature, ENFORCEABLE_TIERS

    with connect() as c:
        gid = _group_pk(c, group_id)
        members = [dict(r) for r in c.execute(
            "SELECT d.id, d.device_id, d.serial FROM device_group_members m "
            "JOIN devices d ON d.id=m.device_id WHERE m.group_id=? ORDER BY d.device_id",
            (gid,)).fetchall()]
        assigns = [dict(r) for r in c.execute(
            "SELECT a.id, a.policy_id, p.policy_id AS pid, p.display_name, p.requirements "
            "FROM group_profile_assignments a JOIN policies p ON p.id=a.policy_id "
            "WHERE a.group_id=? ORDER BY p.display_name", (gid,)).fetchall()]

    if only_devices:
        want = {x.strip() for x in only_devices if x and x.strip()}
        members = [m for m in members if m["device_id"] in want]
    if only_policies:
        wantp = {x.strip() for x in only_policies if x and x.strip()}
        assigns = [a for a in assigns if a["pid"] in wantp]

    results = []
    pending = []      # (device_pk, policy_pk, policy_id, snapshot, outcome, verified)
    action_row = None
    if members and assigns:
        with connect() as c:
            _open_action(c, gid, action_id, op_role or "", "deploy")
            action_row = _last_action_id(c, gid)

    lanes = []
    for a in assigns:
        # Only a profile with NO enforceable lane at all is reported
        # NOT_APPLICABLE. A single unenforceable lane does not cancel the
        # deployment: the rest still applies and the gap is surfaced per device.
        enforceable, unsupported, unenforceable = profile_enforceable(
            a["requirements"], by_feature, ENFORCEABLE_TIERS)
        snapshot = json.dumps({"requirements": json.loads(a["requirements"] or "[]")},
                              ensure_ascii=False)
        gap = []
        if unenforceable:
            gap.extend(unenforceable)
        if unsupported:
            gap.append("no mechanism for: " + ",".join(unsupported))
        for m in members:
            outcome, verified, detail = OUT_STAGED, False, ""
            if not enforceable:
                outcome, detail = OUT_NOT_APPLICABLE, "; ".join(unenforceable)
            else:
                try:
                    res = run_director_apply(
                        m["device_id"], a["pid"], op_role=op_role, mfa_ok=mfa_ok,
                        serial=(serial_for(m) if callable(serial_for) else None),
                        real=real, signing_key=signing_key, chan_dir=chan_dir,
                        allow_channel_risk=allow_channel_risk,
                        # Deploy what this handset can actually enforce; the
                        # lanes it refuses are reported, never silently dropped.
                        force=True)
                    outcome, verified = _classify(res)
                    detail = res.get("stage") or ""
                    lanes = res.get("unresolved_lanes") or []
                    if lanes:
                        detail = ("%s%s" % (detail, " | " if detail else "")
                                  + "not enforceable here: " + ", ".join(lanes))
                        gap.extend("lane not enforceable on this device: %s" % ln
                                   for ln in lanes)
                except Exception as exc:                      # noqa: BLE001
                    outcome, detail = OUT_FAILED, "%s: %s" % (type(exc).__name__, exc)
            if outcome != OUT_NOT_APPLICABLE and gap:
                # deployed, but the admin should still see the partial gap
                detail = ("%s%s" % (detail, " | " if detail else "")) + "; ".join(gap)
            results.append({"device_id": m["device_id"], "policy_id": a["pid"],
                            "outcome": outcome, "detail": detail,
                            "unresolved_lanes": list(lanes) if outcome != OUT_FAILED else []})
            pending.append((m["id"], a["policy_id"], a["pid"], snapshot, outcome, verified))

    with connect() as c:
        for row in pending:
            _record_assignment(c, *row)

    summary = {"total": len(results),
               "success": sum(1 for r in results if r["outcome"] == OUT_APPLIED),
               "partial": sum(1 for r in results if r["outcome"] == OUT_PARTIAL),
               "yet_to_apply": sum(1 for r in results if r["outcome"] == OUT_STAGED),
               "failed": sum(1 for r in results if r["outcome"] == OUT_FAILED),
               "not_applicable": sum(1 for r in results if r["outcome"] == OUT_NOT_APPLICABLE)}
    _refresh_deploy_status(int(group_id))
    if action_row is not None:
        with connect() as c:
            bad = summary["failed"] + summary["not_applicable"]
            _close_action(c, action_row,
                          "COMPLETED" if not bad else "PARTIAL",
                          summary["success"] + summary["partial"], bad)
    return {"group_id": int(group_id), "summary": summary, "results": results}


def profile_enforceable(requirements_json: str, by_feature_fn=None,
                        tiers=None) -> tuple[bool, list[str], list[str]]:
    """Classify the lanes of one profile.

    Returns (enforceable, unsupported, unenforceable) so the caller can report
    the difference instead of collapsing it:

      enforceable     -- at least one lane has a real mechanism here
      unsupported     -- lanes with no catalog row (nothing to enforce or report)
      unenforceable   -- lanes that DO exist but are OEM-only / not feasible

    A profile is deployable when `enforceable` is true. `unimplemented` lanes are
    still a real gap, so the caller surfaces them; they are not silently dropped.
    """
    if by_feature_fn is None:
        from .restrictions import by_feature as by_feature_fn, ENFORCEABLE_TIERS as tiers
    if tiers is None:
        from .restrictions import ENFORCEABLE_TIERS as tiers
    try:
        reqs = json.loads(requirements_json or "[]")
    except (ValueError, TypeError):
        return True, [], []
    rows = by_feature_fn()
    try:
        from policy_engine import FEATURES as ENGINE_FEATURES
    except ImportError:                       # pragma: no cover
        ENGINE_FEATURES = set()
    unsupported, unenforceable = [], []
    for r in reqs:
        feat = (r.get("feature") or "").strip()
        if not feat:
            continue
        cand = rows.get(feat)
        if not cand:
            # A lane with no ManageEngine catalog row is NOT automatically a gap:
            # ALP's own engine lanes (MOBILE_DATA, GPS, ADB, ...) are enforced
            # fine, they just have no counterpart in the reference catalog.
            # Only report it when the engines cannot resolve it either.
            if feat not in ENGINE_FEATURES:
                unsupported.append(feat)
            continue
        tiers_here = {c["tier"] for c in cand}
        if not (tiers_here & tiers):
            unenforceable.append("%s (%s)" % (feat, "/".join(sorted(tiers_here))))
    # Overall deployable if there exists AT LEAST ONE enforceable lane; the
    # rest are reported as gaps (unsupported/unenforceable) but deployment still
    # proceeds for the enforceable subset.
    # This matches the comment at L513-529 that gaps are surfaced without
    # collapsing the whole profile to NOT_APPLICABLE.
    enforceable_cnt = 0
    for r in reqs:
        feat = (r.get("feature") or "").strip()
        if not feat:
            continue
        cand = rows.get(feat)
        if not cand:
            if feat in ENGINE_FEATURES:
                enforceable_cnt += 1
            continue
        tiers_here = {c["tier"] for c in cand}
        if tiers_here & tiers:
            enforceable_cnt += 1
    return enforceable_cnt > 0, unsupported, unenforceable


def _refresh_deploy_status(group_id: int) -> None:
    """Recompute group_deploy_status from the real assignment rows.

    Counts only members of THIS group, and treats a member with no assignment
    row as yet-to-apply so the counters always add up to total_target_count.
    """
    with connect() as c:
        gid = _group_pk(c, group_id)
        rows = c.execute(
            "SELECT a.id AS aid, COUNT(m.id) AS total,"
            " SUM(CASE WHEN s.verify_result IN (?,?) THEN 1 ELSE 0 END) AS ok,"
            " SUM(CASE WHEN s.verify_result=? OR s.id IS NULL THEN 1 ELSE 0 END) AS staged,"
            " SUM(CASE WHEN s.verify_result=? THEN 1 ELSE 0 END) AS bad,"
            " SUM(CASE WHEN s.verify_result=? THEN 1 ELSE 0 END) AS na"
            " FROM group_profile_assignments a"
            " JOIN device_group_members m ON m.group_id = a.group_id"
            " LEFT JOIN assignments s ON s.device_id = m.device_id"
            "      AND s.policy_id = a.policy_id"
            " WHERE a.group_id=? GROUP BY a.id",
            (OUT_APPLIED, OUT_PARTIAL, OUT_STAGED, OUT_FAILED, OUT_NOT_APPLICABLE, gid)
        ).fetchall()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in rows:
            c.execute(
                "INSERT INTO group_deploy_status (assignment_id, total_target_count, "
                "yet_to_apply_count, success_count, failed_count, not_applicable_count, "
                "updated_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(assignment_id) DO UPDATE SET total_target_count=excluded.total_target_count,"
                " yet_to_apply_count=excluded.yet_to_apply_count, success_count=excluded.success_count,"
                " failed_count=excluded.failed_count, not_applicable_count=excluded.not_applicable_count,"
                " updated_at=excluded.updated_at",
                (r["aid"], r["total"] or 0, r["staged"] or 0, r["ok"] or 0,
                 r["bad"] or 0, r["na"] or 0, now))


def group_status(group_id) -> dict:
    """Roll-up across every profile associated with the group.

    `pending` counts member/profile pairs that have no deployment row yet, so the
    total is the true number of outstanding work rather than only what has been
    attempted.
    """
    with connect() as c:
        gid = _group_pk(c, group_id)
        members = _count_members(c, gid)
        rows = [dict(r) for r in c.execute(
            "SELECT a.policy_id, p.policy_id AS pid, p.display_name FROM "
            "group_profile_assignments a JOIN policies p ON p.id=a.policy_id "
            "WHERE a.group_id=? ORDER BY p.display_name", (gid,)).fetchall()]
        profiles = []
        tot = {"total": 0, "success": 0, "yet_to_apply": 0,
               "failed": 0, "not_applicable": 0}
        for r in rows:
            st = deploy_status(c, gid, r["policy_id"])
            profiles.append({"policy_id": r["pid"], "profile_name": r["display_name"],
                             "status": st})
            tot["total"] += st["total_target_count"]
            tot["success"] += st["success_count"]
            tot["yet_to_apply"] += st["yet_to_apply_count"]
            tot["failed"] += st["failed_count"]
            tot["not_applicable"] += st["not_applicable_count"]
        expected = members * len(rows)
    labels = {p["status"]["label"] for p in profiles}
    if not profiles:
        label = "NOT_DEPLOYED"
    elif labels == {"NOT_DEPLOYED"}:
        # Associated but never deployed: do not present it as pending work that
        # is under way, and certainly not as applied.
        label = "NOT_DEPLOYED"
    elif "FAILED" in labels:
        label = "FAILED"
    elif tot["success"] == expected and expected:
        label = "APPLIED"
    elif tot["success"]:
        label = "PARTIAL"
    elif tot["not_applicable"] and not tot["yet_to_apply"]:
        label = "NOT_APPLICABLE"
    else:
        label = "STAGED"
    return {"group_id": int(group_id), "label": label, "members": members,
            "profiles": len(rows), "expected_targets": expected,
            "counts": tot, "detail": profiles}


def list_group_actions(group_id, limit: int = 50) -> list[dict]:
    """group_action_history — the reference 'Action Summary' tab."""
    with connect() as c:
        gid = _group_pk(c, group_id)
        rows = c.execute(
            "SELECT group_action_id, action_id, action_status, initiated_by, "
            "initiated_at, last_modified_at, reason_message, success_count, "
            "failure_count FROM group_action_history WHERE group_id=? "
            "ORDER BY id DESC LIMIT ?", (gid, int(limit))).fetchall()
        return [dict(r) for r in rows]


def deploy_status(c, group_id: int, policy_id: str) -> dict:
    """Counters for one group+profile, matching groupcollnstatussummary."""
    row = c.execute(
        "SELECT d.total_target_count, d.yet_to_apply_count, d.success_count, "
        "d.failed_count, d.not_applicable_count FROM group_deploy_status d "
        "JOIN group_profile_assignments a ON a.id = d.assignment_id "
        "WHERE a.group_id=? AND a.policy_id=?", (group_id, policy_id)).fetchone()
    members = _count_members(c, group_id)
    if not row:
        return {"total_target_count": members, "yet_to_apply_count": members,
                "success_count": 0, "failed_count": 0, "not_applicable_count": 0,
                "label": "NOT_DEPLOYED"}
    d = {k: row[k] for k in row.keys()}
    if d["failed_count"]:
        label = "FAILED"
    elif d["not_applicable_count"]:
        label = "PARTIAL"
    elif d["success_count"] == d["total_target_count"] and d["total_target_count"]:
        label = "APPLIED"
    elif d["success_count"]:
        label = "PARTIAL"
    else:
        label = "STAGED"
    d["label"] = label
    return d
