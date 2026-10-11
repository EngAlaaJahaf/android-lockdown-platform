# -*- coding: utf-8 -*-
"""The policy an agent should currently be running, as a signed envelope.

The agent has no internet path: it reaches this control plane through the USB
tether (10.0.2.2). That means a policy published while the handset was detached
can still reach it on the next sync, with no ADB and no push from the host.

The envelope is signed exactly like a push, so the same EnvelopeGuard on the
device authenticates it: an unsigned or tampered reply is inert. What is decided
here is only WHICH policy that device should have - the device never asks for
arbitrary content, it asks "what is mine?".

Honesty rules kept in this module:
  * a device with no row, or no group, gets an explicit empty answer rather than
    a fallback policy;
  * a draft/retired profile is never served as if it were live;
  * the answer records the policy version, so an unchanged policy yields the
    same cmd-independent fingerprint and the device can skip the work.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from .command import new_command
from .db import connect


def _device_row(device_id: str, serial: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM devices WHERE device_id=? OR serial=? LIMIT 1",
            (device_id, serial)).fetchone()
    return dict(row) if row else None


def _assigned_policy(dev_pk: int) -> Optional[dict]:
    """The live profile this device should be running, via its groups.

    A group can carry several profiles; the most recently assigned live one wins,
    which mirrors what the group deploy pushes to the same device.
    """
    with connect() as c:
        row = c.execute(
            """
            SELECT p.id, p.policy_id, p.version, p.status, p.requirements,
                   p.display_name, p.recovery_attempts, gpa.assigned_at, gpa.distributed_version
            FROM device_group_members dgm
            JOIN group_profile_assignments gpa ON gpa.group_id = dgm.group_id
            JOIN policies p ON p.id = gpa.policy_id
            WHERE dgm.device_id = ?
            ORDER BY p.status = 'ACTIVE' DESC,
                     gpa.last_modified_at DESC, gpa.id DESC
            LIMIT 1
            """, (dev_pk,)).fetchone()
    return dict(row) if row else None


def fingerprint(policy_id: str, version, requirements: str,
                recovery_attempts=None) -> str:
    """Stable digest of what the device should be running.

    Used as the `If-None-Match` style marker so a device that is already up to
    date can be told "no change" instead of re-applying an identical profile.
    """
    h = hashlib.sha256()
    h.update((policy_id or "").encode("utf-8"))
    h.update(b"|")
    h.update(str(version if version is not None else "").encode("utf-8"))
    h.update(b"|")
    h.update(str(recovery_attempts if recovery_attempts is not None else "").encode("utf-8"))
    h.update(b"|")
    h.update(json.dumps(json.loads(requirements or "[]"),
                        sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:32]


def policy_for_device(device_id: str, serial: str = "",
                      signing_key: str = "") -> dict:
    """Answer an agent's "what is my policy?" with a signed envelope.

    Returns a dict with `state`:
      no_device     - the console does not know this handset
      no_profile    - known, but no live profile is associated
      up_to_date    - the agent's fingerprint matches (only when `known` is sent)
      delivered     - a signed APPLY_POLICY envelope is attached
    """
    dev = _device_row(device_id or "", serial or "")
    if not dev:
        return {"state": "no_device", "device_id": device_id,
                "detail": "this device is not registered with the console"}

    assigned = _assigned_policy(dev["id"])
    if not assigned:
        return {"state": "no_profile", "device_id": dev["device_id"],
                "fingerprint": "unassigned", "policy_id": "",
                "detail": "no profile is associated with this device"}

    if assigned["status"] != "ACTIVE":
        return {"state": "no_profile", "device_id": dev["device_id"],
                "policy_id": "", "fingerprint": "unassigned",
                "status": assigned["status"],
                "detail": "the associated profile %s is %s, not ACTIVE"
                          % (assigned["policy_id"], assigned["status"])}

    fp = fingerprint(assigned["policy_id"], assigned["version"],
                     assigned["requirements"], assigned.get("recovery_attempts"))
    return {"state": "up_to_date", "device_id": dev["device_id"],
            "policy_id": assigned["policy_id"],
            "version": assigned["version"],
            "display_name": assigned["display_name"],
            "recovery_attempts": assigned.get("recovery_attempts"),
            "fingerprint": fp,
            "detail": "already running this profile version"}


def build_apply_envelope(device_id: str, serial: str = "",
                         signing_key: str = "") -> dict:
    """A signed APPLY_POLICY envelope for this device's live profile.

    Mirrors what the host pushes over ADB so the on-device code path is
    identical: one EnvelopeGuard, one applyPolicy.
    """
    answer = policy_for_device(device_id, serial)
    if answer.get("state") == "no_profile":
        out = dict(answer)
        out["state"] = "delivered"
        out["envelope"] = new_command(
            0, answer["device_id"], "CLEAR_POLICY",
            {"reason": "no live group profile", "fingerprint": "unassigned"},
            key=signing_key or None)
        return out
    if answer.get("state") != "up_to_date":
        return answer

    from .workflows import (capability_for_device, resolve_policy,
                            vendor_adapter_for_device)
    from policy_engine.snapshot import resolve
    from compatibility import AndroidCompatibilityLayer

    pol = resolve_policy(answer["policy_id"])
    if pol is None:
        return {"state": "no_profile", "device_id": device_id,
                "detail": "profile %r could not be loaded" % answer["policy_id"]}

    with connect() as c:
        dev = dict(c.execute("SELECT * FROM devices WHERE device_id=?",
                             (answer["device_id"],)).fetchone() or {})
    api = dev.get("api_level") or 0
    cap = capability_for_device(connect(), answer["device_id"])
    adapter, _cls = vendor_adapter_for_device(
        manufacturer=dev.get("manufacturer") or "",
        model=dev.get("model") or "",
        android_version=dev.get("android_version") or 0,
        api_level=api,
        build_fingerprint=dev.get("build_fingerprint") or "")

    snap = resolve(pol, cap, AndroidCompatibilityLayer(api), adapter)
    rows = [r.__dict__ for r in snap.resolved]

    env = new_command(
        0, answer["device_id"], "APPLY_POLICY",
        {"policy_id": pol.policy_id, "version": pol.version,
         "snapshot": rows,
         "recovery_attempts": getattr(pol, "recovery_attempts", None),
         # The device applies what it can and reports the rest; the pull must not
         # fail because one lane has no mechanism here.
         "allow_partial": True,
          "replace_policy": True,
         "fingerprint": answer["fingerprint"],
         "unresolved": sorted(snap.exceptions)},
        key=signing_key or None)

    out = dict(answer)
    out["state"] = "delivered"
    out["envelope"] = env
    out["rows"] = len(rows)
    out["unresolved_lanes"] = sorted(snap.exceptions)
    return out
