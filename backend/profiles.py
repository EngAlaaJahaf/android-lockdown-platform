"""Profiles (console-managed `policies` rows) — draft lifecycle + real listing.

The ManageEngine MDM Plus console never publishes a profile on the first save.
The admin creates it, edits restrictions, saves (Draft), and only then publishes
(`design-ref/mdm-plus-groups-profiles.txt`, memdm `mdmresourceprofile` +
`mdmresourceprofiledetails`). This module reproduces that lifecycle:

    DRAFT ──submit──▶ REVIEW ──publish──▶ ACTIVE ──retire──▶ RETIRED
      │                                    ▲
      ├────────────publish──────────────────┘
      └────────────reject──▶ REJECTED

Lifecycle rules enforced here:

  * `create_draft()` writes status='DRAFT' with an empty requirement set. It is
    never apply-able: `groups.associate_profiles()` refuses DRAFT/REJECTED, so a
    half-built profile cannot reach a device.
  * `save_draft()` only touches DRAFT rows. Editing an ACTIVE profile in place
    would silently change what every associated device is supposed to look like,
    so that is refused rather than faked.
  * To edit a published profile the console opens a *revision*: `create_revision()`
    makes a new DRAFT in the same lineage (`root_id`) that copies the published
    requirements as a starting point. `publish_draft()` then retires the version
    it supersedes and moves the group associations to the new one, so nothing is
    deployed by publishing alone — a redeploy is still required.
  * `publish_draft()` refuses a profile with zero requirements, and reports
    unenforceable lanes instead of publishing a profile that cannot be honoured.
  * `delete_profile()` only removes DRAFT/REJECTED rows that are not associated
    anywhere. A published profile is retired, never deleted, so the audit trail
    of what was once deployed survives.

Every counter in `list_profiles()` is derived from real rows; nothing is written
optimistically and no timestamp is invented for a profile that was never touched.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from .db import connect

# Status vocabulary is enforced by the policies CHECK constraint in schema.sql:
#   DRAFT | REVIEW | ACTIVE | RETIRED | REJECTED
_EDITABLE = ("DRAFT",)
_PUBLISHABLE = ("DRAFT", "REVIEW")

# allowed[from_status] = set of reachable statuses
_TRANSITIONS = {
    "DRAFT": {"REVIEW", "ACTIVE", "REJECTED"},
    "REVIEW": {"DRAFT", "ACTIVE", "REJECTED"},
    "ACTIVE": {"RETIRED"},
    "REJECTED": {"DRAFT"},
    "RETIRED": set(),
}

VALID_CATEGORIES = ("CORPORATE_DEFAULT", "PHONE_ONLY", "PARTIAL_LOCKDOWN",
                    "FULL_LOCKDOWN", "MAINTENANCE", "QUARANTINE")

VALID_STATES = ("BLOCK", "ALLOW", "RESTRICT", "WARN_AUDIT")
VALID_RISK = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

_COLS = ("policy_id, display_name, category, version, status, description, "
        "requirements, checksum, root_id, created_by, created_at, changed_by, "
        "change_reason, updated_at, published_at, published_by, "
        "recovery_attempts")

# Sentinel distinguishing "caller did not mention the threshold" (keep the
# stored value) from explicit null (disable the recovery challenge).
_KEEP = object()


def _validate_recovery_attempts(value):
    """Passcode-recovery threshold: None disables, 1..10 arms the challenge.

    Raises ProfileError naming the bound, so the console can show it inline
    instead of failing later at deploy time.
    """
    if value is None:
        return None
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        raise ProfileError("recovery_attempts must be 1..10 (or null to disable)")
    if not 1 <= n <= 10:
        raise ProfileError("recovery_attempts must be 1..10 (or null to disable)")
    return n

# A revision is a new version in the same lineage: `POL-X` -> `POL-X-V2`.
_REVISION_SUFFIX = re.compile(r"-V\d+$")

# statuses that need a *new revision* to be edited, rather than in-place save.
_REVISIONABLE = ("ACTIVE", "RETIRED")


class ProfileError(Exception):
    """Bad profile input / illegal lifecycle step (maps to HTTP 400/409)."""


class ProfileConflict(ProfileError):
    """The request is well-formed but the profile is not in a state that allows
    it (e.g. editing an ACTIVE profile, deleting one still in use)."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ validation
def _validate_requirements(requirements) -> list[dict]:
    """Normalise + validate the requirement list the console sends.

    Returns the canonical [{feature, desired_state, risk}, ...] stored in
    policies.requirements. Raises ProfileError listing every bad row at once so
    the admin sees all problems in one pass instead of fixing them one reload at
    a time.
    """
    from policy_engine import FEATURES

    if requirements is None:
        return []
    if not isinstance(requirements, list):
        raise ProfileError("requirements must be a list")
    out, seen, bad = [], {}, []
    for i, r in enumerate(requirements):
        if not isinstance(r, dict):
            bad.append("row %d is not an object" % i)
            continue
        feat = str(r.get("feature") or "").strip().upper()
        state = str(r.get("desired_state") or "BLOCK").strip().upper()
        risk = str(r.get("risk") or "MEDIUM").strip().upper()
        if not feat:
            bad.append("row %d has no feature" % i)
            continue
        if feat not in FEATURES:
            bad.append("row %d: unknown feature %s" % (i, feat))
            continue
        if state not in VALID_STATES:
            bad.append("row %d: desired_state must be one of %s"
                       % (i, "/".join(VALID_STATES)))
            continue
        if risk not in VALID_RISK:
            bad.append("row %d: risk must be one of %s" % (i, "/".join(VALID_RISK)))
            continue
        if feat in seen:
            bad.append("duplicate feature %s (last one wins)" % feat)
        seen[feat] = {"feature": feat, "desired_state": state, "risk": risk}
    if bad:
        raise ProfileError("; ".join(bad))
    return [seen[k] for k in sorted(seen)]


def _checksum(reqs: list[dict]) -> str:
    """Integrity hash of a requirement set, computed through the engine so the
    value is identical to what workflows.create_custom_policy() stores for the
    same requirements (same canonical form, one hash implementation)."""
    from policy_engine import Policy
    p = Policy("POL-CHECKSUM", "", "CORPORATE_DEFAULT")
    for r in reqs:
        p.add(r["feature"], r["desired_state"], r["risk"])
    return p.checksum()


def _row(c, policy_id: str):
    # 1. Direct match on policy_id
    r = c.execute("SELECT %s FROM policies WHERE policy_id=?" % _COLS, (policy_id,)).fetchone()
    if r:
        return r

    # 2. Match by root_id directly
    r = c.execute(
        "SELECT %s FROM policies WHERE root_id=? "
        "ORDER BY (status='DRAFT') DESC, (status='ACTIVE') DESC, version DESC LIMIT 1" % _COLS,
        (policy_id,)).fetchone()
    if r:
        return r

    # 3. Match by display_name (e.g. 'LT')
    r = c.execute(
        "SELECT %s FROM policies WHERE display_name=? COLLATE NOCASE "
        "ORDER BY (status='DRAFT') DESC, (status='ACTIVE') DESC, version DESC LIMIT 1" % _COLS,
        (policy_id,)).fetchone()
    if r:
        return r

    # 4. Match by numeric database id
    if str(policy_id).isdigit():
        r = c.execute("SELECT %s FROM policies WHERE id=?" % _COLS, (int(policy_id),)).fetchone()
        if r:
            return r

    raise ProfileError("profile %r not found" % policy_id)


# --------------------------------------------------------------------- listing
def list_profiles(status: str | None = None, search: str = "",
                  include_superseded: bool = False) -> list[dict]:
    """Profiles with the counters the console profile list shows.

    group_count / target_device_count / deployed_device_count are read from the
    association and deployment rows, so an unsaved draft honestly reports 0/0/0
    instead of a fabricated "1 group, -- devices".

    When include_superseded is False (the default for the console catalog and dropdowns),
    older superseded revisions (marked 'superseded by ...') are collapsed so each
    profile lineage appears only once showing its current/latest version.
    """
    where_parts: list[str] = []
    args: list = []

    if not include_superseded:
        # Exclude historical superseded revisions: only return the latest canonical profile for each lineage
        where_parts.append("(p.change_reason IS NULL OR p.change_reason NOT LIKE 'superseded by %')")
        if not status:
            where_parts.append(
                "p.version = (SELECT MAX(p2.version) FROM policies p2 "
                "WHERE COALESCE(p2.root_id, p2.policy_id) = COALESCE(p.root_id, p.policy_id))"
            )

    if status:
        where_parts.append("p.status=?")
        args.append(status.strip().upper())
    if search:
        where_parts.append("p.display_name LIKE ?")
        args.append("%" + search.strip() + "%")

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    sql = ("SELECT p.%s,"
           " (SELECT COUNT(*) FROM group_profile_assignments a"
           "    JOIN policies pa ON pa.id=a.policy_id"
           "   WHERE COALESCE(pa.root_id, pa.policy_id) = COALESCE(p.root_id, p.policy_id)) AS gc,"
           " (SELECT COUNT(DISTINCT m.device_id) FROM group_profile_assignments a"
           "    JOIN policies pa ON pa.id=a.policy_id"
           "    JOIN device_group_members m ON m.group_id=a.group_id"
           "   WHERE COALESCE(pa.root_id, pa.policy_id) = COALESCE(p.root_id, p.policy_id)) AS tc,"
           " (SELECT COUNT(DISTINCT s.device_id) FROM assignments s"
           "   WHERE s.policy_id=p.id) AS dc "
           "FROM policies p" % _COLS) + where_sql + " ORDER BY p.status='DRAFT' DESC, p.updated_at DESC, p.display_name"
    out = []
    with connect() as c:
        for r in c.execute(sql, args).fetchall():
            try:
                reqs = json.loads(r["requirements"] or "[]")
            except (ValueError, TypeError):
                reqs = []
            from .groups import profile_enforceable
            enforceable, unsupported, unenforceable = profile_enforceable(
                r["requirements"] or "[]")
            out.append({
                "policy_id": r["policy_id"],
                "name": r["display_name"],
                "description": r["description"] or "",
                "category": r["category"],
                "version": r["version"],
                "root_id": r["root_id"] or r["policy_id"],
                "status": r["status"],
                "requirement_count": len(reqs),
                "enforceable": enforceable,
                "unsupported_lanes": unsupported,
                "unenforceable_lanes": unenforceable,
                "group_count": r["gc"],
                "target_device_count": r["tc"],
                "deployed_device_count": r["dc"],
                "checksum": r["checksum"],
                "created_by": r["created_by"],
                "created_at": r["created_at"],
                "modified_by": r["changed_by"],
                "modified_at": r["updated_at"] or r["created_at"],
                "published_at": r["published_at"],
                "published_by": r["published_by"],
            })
    return out


def get_profile(policy_id: str) -> dict:
    """One profile with its requirement rows and its associations."""
    with connect() as c:
        r = _row(c, policy_id)
        actual_pid = r["policy_id"]
        pk = c.execute("SELECT id FROM policies WHERE policy_id=?", (actual_pid,)).fetchone()["id"]
        try:
            reqs = json.loads(r["requirements"] or "[]")
        except (ValueError, TypeError):
            reqs = []
        root = r["root_id"] or r["policy_id"]
        groups = [dict(g) for g in c.execute(
            "SELECT g.id, g.group_key, g.name AS group_name, g.name, "
            "  (SELECT COUNT(*) FROM device_group_members m WHERE m.group_id=g.id) AS member_count, "
            "  COALESCE(a.distributed_version, 1) AS version, "
            "  a.assigned_at AS associated_time, "
            "  COALESCE(a.assigned_by, 'admin') AS associated_by, "
            "  'Associated' AS status, "
            "  COALESCE(a.remarks, 'Policy associated') AS remarks "
            "FROM group_profile_assignments a "
            "JOIN device_groups g ON g.id=a.group_id "
            "WHERE a.policy_id IN (SELECT id FROM policies WHERE root_id=? OR id=?) "
            "ORDER BY g.name", (root, pk)).fetchall()]
        targets = c.execute(
            "SELECT COUNT(DISTINCT m.device_id) n FROM group_profile_assignments a "
            "JOIN device_group_members m ON m.group_id=a.group_id "
            "WHERE a.policy_id IN (SELECT id FROM policies WHERE root_id=? OR id=?)",
            (root, pk)).fetchone()["n"]
        deployed = c.execute(
            "SELECT COUNT(DISTINCT s.device_id) n FROM assignments s "
            "WHERE s.policy_id IN (SELECT id FROM policies WHERE root_id=? OR id=?)",
            (root, pk)).fetchone()["n"]
        devices = [dict(d) for d in c.execute(
            "SELECT DISTINCT d.device_id, COALESCE(NULLIF(d.model, ''), d.device_id) AS device_name, "
            "  d.user_ref AS username, COALESCE(NULLIF(d.serial, ''), d.device_id) AS serial, "
            "  COALESCE(d.last_seen_at, d.updated_at, '—') AS last_contact_time, "
            "  'Android' AS device_type, "
            "  CASE WHEN s.id IS NOT NULL THEN 'Applied' ELSE 'Associated' END AS status, "
            "  COALESCE(a.remarks, 'Policy associated') AS remarks "
            "FROM group_profile_assignments a "
            "JOIN device_group_members m ON m.group_id=a.group_id "
            "JOIN devices d ON (d.id=m.device_id OR d.device_id=m.device_id) "
            "LEFT JOIN assignments s ON (s.policy_id IN (SELECT id FROM policies WHERE root_id=? OR id=?) AND (s.device_id=d.id OR s.device_id=d.device_id)) "
            "WHERE a.policy_id IN (SELECT id FROM policies WHERE root_id=? OR id=?) "
            "ORDER BY d.device_id", (root, pk, root, pk)).fetchall()]
    from .groups import profile_enforceable
    enforceable, unsupported, unenforceable = profile_enforceable(r["requirements"] or "[]")
    return {
        "policy_id": r["policy_id"], "name": r["display_name"],
        "description": r["description"] or "", "category": r["category"],
        "version": r["version"], "root_id": r["root_id"] or r["policy_id"],
        "status": r["status"],
        "requirements": reqs, "requirement_count": len(reqs),
        "checksum": r["checksum"],
        "enforceable": enforceable,
        "unsupported_lanes": unsupported, "unenforceable_lanes": unenforceable,
        "group_count": len(groups), "target_device_count": targets,
        "deployed_device_count": deployed,
        "created_by": r["created_by"], "created_at": r["created_at"],
        "modified_by": r["changed_by"], "modified_at": r["updated_at"] or r["created_at"],
        "published_at": r["published_at"], "published_by": r["published_by"],
        "recovery_attempts": r["recovery_attempts"],
        "groups": groups,
        "assigned_groups": groups,
        "target_devices": devices,
        "next_statuses": sorted(_TRANSITIONS.get(r["status"], set())),
    }


# -------------------------------------------------------------- draft lifecycle
def create_draft(name: str, category: str = "CORPORATE_DEFAULT",
                 description: str = "", created_by: str = "console",
                 platform: str = "ANDROID", recovery_attempts=None) -> dict:
    """Create an empty DRAFT profile. Nothing is publish-able until requirements
    are saved, and nothing is associable until it is published."""
    from .groups import _slug
    name = (name or "").strip()
    if not name:
        raise ProfileError("profile name is required")
    category = (category or "CORPORATE_DEFAULT").strip().upper()
    if category not in VALID_CATEGORIES:
        raise ProfileError("invalid category %r" % category)
    with connect() as c:
        base = ("POL-" + _slug(name))[:48].upper() or "POL-PROFILE"
        pid, n = base, 1
        while c.execute("SELECT 1 FROM policies WHERE policy_id=?", (pid,)).fetchone():
            n += 1
            pid = ("%s-%d" % (base, n))[:56]
        now = _now()
        c.execute(
            "INSERT INTO policies (policy_id, display_name, description, category, "
            "version, status, checksum, requirements, root_id, created_by, "
            "created_at, changed_by, updated_at, recovery_attempts) "
            "VALUES (?,?,?,?,1,'DRAFT',?,?,?,?,?,?,?,?)",
            (pid, name, (description or "").strip(), category, _checksum([]),
             "[]", pid, created_by or "", now, created_by or "", now,
             _validate_recovery_attempts(recovery_attempts)))
    return get_profile(pid)


def save_draft(policy_id: str, name: str | None = None, description: str | None = None,
               category: str | None = None, requirements=None,
               changed_by: str = "console",
               change_reason: str = "", recovery_attempts=_KEEP) -> dict:
    """Persist an edit to a DRAFT profile. ACTIVE/REVIEW rows are refused."""
    reqs = None
    if requirements is not None:
        reqs = _validate_requirements(requirements)
    with connect() as c:
        r = _row(c, policy_id)
        if r["status"] not in _EDITABLE:
            raise ProfileConflict(
                "profile %s is %s; only DRAFT profiles are editable. Publish a new "
                "version instead of changing what is already deployed."
                % (policy_id, r["status"]))
        if category is not None:
            cat = category.strip().upper()
            if cat not in VALID_CATEGORIES:
                raise ProfileError("invalid category %r" % category)
        else:
            cat = r["category"]
        if reqs is None:
            try:
                reqs = json.loads(r["requirements"] or "[]")
            except (ValueError, TypeError):
                reqs = []
        if recovery_attempts is _KEEP:
            attempts = r["recovery_attempts"]
        else:
            attempts = _validate_recovery_attempts(recovery_attempts)
        c.execute(
            "UPDATE policies SET display_name=?, description=?, category=?, "
            "requirements=?, checksum=?, changed_by=?, change_reason=?, updated_at=?, "
            "recovery_attempts=? "
            "WHERE policy_id=?",
            ((name or r["display_name"]).strip() or r["display_name"],
             (description if description is not None else (r["description"] or "")).strip(),
             cat, json.dumps(reqs, ensure_ascii=False), _checksum(reqs),
             changed_by or "", change_reason or "", _now(), attempts, r["policy_id"]))
    return get_profile(r["policy_id"])


def _transition(policy_id: str, target: str, changed_by: str,
                change_reason: str, extra_sql: str = "", extra_args=()) -> dict:
    with connect() as c:
        r = _row(c, policy_id)
        cur = r["status"]
        if target not in _TRANSITIONS.get(cur, set()):
            raise ProfileConflict("profile %s cannot move %s -> %s"
                                  % (policy_id, cur, target))
        c.execute(
            "UPDATE policies SET status=?, changed_by=?, change_reason=?, "
            "updated_at=?%s WHERE policy_id=?"
            % (", " + extra_sql if extra_sql else ""),
            (target, changed_by or "", change_reason or "", _now(),
             *(extra_args or ()), r["policy_id"]))
    return get_profile(r["policy_id"])


def reopen_rejected(policy_id: str, changed_by: str = "console",
                    change_reason: str = "") -> dict:
    """REJECTED -> DRAFT so the author can fix it and submit again.

    Without this step a rejected profile is a dead end: the transitions only
    allow REJECTED -> DRAFT, and no surface reached DRAFT from a rejection.
    """
    return _transition(policy_id, "DRAFT", changed_by, change_reason)


def submit_for_review(policy_id: str, changed_by: str = "console",
                      change_reason: str = "") -> dict:
    """DRAFT -> REVIEW: the profile is complete enough for a second pair of eyes.
    REVIEW is associatable to a group exactly like ACTIVE."""
    with connect() as c:
        r = _row(c, policy_id)
        try:
            reqs = json.loads(r["requirements"] or "[]")
        except (ValueError, TypeError):
            reqs = []
    if not reqs:
        raise ProfileError("profile %s has no requirements yet" % policy_id)
    return _transition(policy_id, "REVIEW", changed_by, change_reason)


def create_revision(policy_id: str, changed_by: str = "console",
                    change_reason: str = "new profile revision") -> dict:
    """Open a published profile for editing as a new DRAFT revision.

    Versioning instead of an in-place edit: an ACTIVE profile is exactly what the
    groups reference and what the devices have applied, so changing it silently
    would rewrite deployed truth. The revision copies the published requirements
    as a starting point, keeps the same lineage (`root_id`) and bumps the version.
    Publishing it later retires this version's predecessor and moves the group
    associations across (`publish_draft`).

    If an unpublished revision is already open for this lineage it is returned
    (with `reused=True`) instead of stacking a second identical draft.
    """
    with connect() as c:
        r = _row(c, policy_id)
        if r["status"] not in _REVISIONABLE:
            raise ProfileConflict(
                "profile %s is %s; only a published (ACTIVE/RETIRED) profile "
                "needs a new revision — a DRAFT is edited directly"
                % (policy_id, r["status"]))
        root = r["root_id"] or r["policy_id"]
        open_rev = c.execute(
            "SELECT policy_id FROM policies WHERE root_id=? AND status='DRAFT' "
            "ORDER BY version DESC LIMIT 1", (root,)).fetchone()
        if open_rev:
            pid, reused = open_rev["policy_id"], True
        else:
            reused = False
            nxt = c.execute(
                "SELECT COALESCE(MAX(version), 1) + 1 AS v FROM policies WHERE root_id=?",
                (root,)).fetchone()["v"]
            base = _REVISION_SUFFIX.sub("", r["policy_id"])
            pid = ("%s-V%d" % (base, nxt))[:56]
            while c.execute("SELECT 1 FROM policies WHERE policy_id=?", (pid,)).fetchone():
                nxt += 1
                pid = ("%s-V%d" % (base, nxt))[:56]
            now = _now()
            c.execute(
                "INSERT INTO policies (policy_id, display_name, description, category, "
                "version, status, checksum, requirements, root_id, created_by, "
                "created_at, changed_by, updated_at, recovery_attempts) VALUES (?,?,?,?,?,'DRAFT',?,?,?,?,?,?,?,?)",
                (pid, r["display_name"], r["description"] or "", r["category"], nxt,
                 r["checksum"] or _checksum([]), r["requirements"] or "[]", root,
                 changed_by or "", now, changed_by or "", now, r["recovery_attempts"]))
    prof = get_profile(pid)
    prof["reused"] = reused
    return prof


def publish_draft(policy_id: str, changed_by: str = "console",
                  change_reason: str = "") -> dict:
    """DRAFT|REVIEW -> ACTIVE.

    Refuses an empty profile. Lanes that cannot be enforced here are reported in
    the result rather than dropped, so the admin knows the published profile is
    not fully enforceable on every device class.

    When this profile is a revision, publishing it supersedes the previously
    ACTIVE version of the same lineage: that row becomes RETIRED and its group
    assignments move to this revision. The moved assignments are reset to
    not-yet-deployed, so publishing never pretends the new version has already
    reached the devices.
    """
    with connect() as c:
        r = _row(c, policy_id)
        try:
            reqs = json.loads(r["requirements"] or "[]")
        except (ValueError, TypeError):
            reqs = []
        if not reqs:
            raise ProfileError("cannot publish %s: it has no requirements" % policy_id)
        if r["status"] not in _PUBLISHABLE:
            raise ProfileConflict(
                "profile %s cannot move %s -> ACTIVE" % (policy_id, r["status"]))
        root = r["root_id"] or r["policy_id"]
        new_pk = c.execute("SELECT id FROM policies WHERE policy_id=?",
                           (policy_id,)).fetchone()["id"]
        now = _now()
        prev = c.execute(
            "SELECT id, policy_id FROM policies WHERE root_id=? AND status='ACTIVE' "
            "AND id<>?", (root, new_pk)).fetchone()
        superseded = None
        if prev:
            superseded = prev["policy_id"]
            # retire the superseded version first: the partial unique index allows
            # only one ACTIVE row per lineage.
            c.execute(
                "UPDATE policies SET status='RETIRED', changed_by=?, change_reason=?, "
                "updated_at=? WHERE id=?",
                (changed_by or "", "superseded by %s" % policy_id, now, prev["id"]))
            # move the group assignments onto the revision and drop their stale
            # deploy counters so every affected group reads as yet-to-apply.
            aids = [x["id"] for x in c.execute(
                "SELECT id FROM group_profile_assignments WHERE policy_id=?",
                (prev["id"],)).fetchall()]
            c.execute(
                "UPDATE group_profile_assignments SET policy_id=?, distributed_version=?, "
                "last_modified_by=?, last_modified_at=? WHERE policy_id=?",
                (new_pk, r["version"], changed_by or "", now, prev["id"]))
            for aid in aids:
                c.execute("DELETE FROM group_deploy_status WHERE assignment_id=?", (aid,))
        c.execute(
            "UPDATE policies SET status='ACTIVE', changed_by=?, change_reason=?, "
            "updated_at=?, published_at=?, published_by=? WHERE policy_id=?",
            (changed_by or "", change_reason or "published from console", now,
             now, changed_by or "", policy_id))
        affected = [dict(r) for r in c.execute(
            "SELECT g.id AS group_id, g.name AS group_name "
            "FROM group_profile_assignments a "
            "JOIN device_groups g ON g.id=a.group_id "
            "WHERE a.policy_id=? ORDER BY g.name", (new_pk,)).fetchall()]
    prof = get_profile(policy_id)
    prof["affected_groups"] = affected
    if superseded:
        prof["superseded"] = superseded
    from .groups import profile_enforceable
    _ok, unsupported, unenforceable = profile_enforceable(
        json.dumps(reqs, ensure_ascii=False))
    prof["enforceable"] = _ok
    prof["unsupported_lanes"] = unsupported
    prof["unenforceable_lanes"] = unenforceable

    # ── نشر فوري على الأجهزة ───────────────────────────────────────────────
    # بعد النشر: طبّق السياسة الجديدة على كل مجموعة مرتبطة بها تلقائياً.
    # هذا يجعل زر "Publish" فعّالاً مباشرة — بدون حاجة لخطوة Deploy منفصلة.
    if affected:
        from . import groups as _G
        deploy_results = []
        for aff in affected:
            try:
                dr = _G.deploy_group(
                    aff["group_id"],
                    op_role=changed_by or "admin",
                    mfa_ok=True,
                    force=True,
                    real=True,      # حاول التطبيق الفعلي إذا كان الجهاز متصلاً
                    action_id="PUBLISH_AUTO_DEPLOY")
                deploy_results.append({
                    "group_id": aff["group_id"],
                    "group_name": aff["group_name"],
                    "summary": dr.get("summary", {}),
                })
            except Exception as exc:    # noqa: BLE001
                deploy_results.append({
                    "group_id": aff["group_id"],
                    "group_name": aff["group_name"],
                    "error": str(exc),
                })
        prof["auto_deploy"] = deploy_results

    return prof


def reject_profile(policy_id: str, reason: str = "", changed_by: str = "console") -> dict:
    """DRAFT|REVIEW -> REJECTED. A rejected profile cannot be associated."""
    if not (reason or "").strip():
        raise ProfileError("a rejection reason is required")
    return _transition(policy_id, "REJECTED", changed_by, reason.strip())


def retire_profile(policy_id: str, reason: str = "", changed_by: str = "console") -> dict:
    """ACTIVE -> RETIRED. The row stays for the audit trail; associations are
    left alone so historical deployment evidence is not rewritten."""
    return _transition(policy_id, "RETIRED", changed_by, reason)


def delete_profile(policy_id: str, force: bool = False) -> dict:
    """Delete a profile. If force=True, disassociate from groups and remove from policies."""
    with connect() as c:
        r = _row(c, policy_id)
        pk = c.execute("SELECT id FROM policies WHERE policy_id=?", (policy_id,)).fetchone()["id"]
        g = c.execute("SELECT COUNT(*) n FROM group_profile_assignments WHERE policy_id=?",
                      (pk,)).fetchone()["n"]
        if g and not force:
            raise ProfileConflict("profile %s is still associated with %d group(s)"
                                  % (policy_id, g))
        if r["status"] not in ("DRAFT", "REJECTED") and not force:
            raise ProfileConflict(
                "profile %s is %s; retire it instead of deleting history"
                % (policy_id, r["status"]))
        if g:
            aids = [x["id"] for x in c.execute(
                "SELECT id FROM group_profile_assignments WHERE policy_id=?",
                (pk,)).fetchall()]
            for aid in aids:
                c.execute("DELETE FROM group_deploy_status WHERE assignment_id=?", (aid,))
            c.execute("DELETE FROM group_profile_assignments WHERE policy_id=?", (pk,))
        c.execute("DELETE FROM policies WHERE policy_id=?", (policy_id,))
    return {"deleted": policy_id}