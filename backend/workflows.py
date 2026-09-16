"""Shared control-plane workflows, used by both the Desktop CLI and the HTTP API.

Keeps the honest-pipeline rules in ONE place:
  - capability is always built from Registry caps (never invents SUPPORTED);
  - REAL_DEVICE evidence is only ever what ADB actually observed;
  - SIMULATED sources can never produce a PASS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Optional

from .db import connect

# A windowed (console=False) app must never flash console windows when it
# shells out to adb.exe. On Windows, children of a GUI app get their own
# console unless CREATE_NO_WINDOW is requested explicitly.
_NO_WINDOW = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
              if sys.platform == "win32" else 0)


def adb() -> str:
    a = os.environ.get("ALP_ADB") or os.path.join(
        os.environ.get("ANDROID_HOME") or os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk"),
        "platform-tools", "adb.exe")
    return a if os.path.exists(a) else "adb"


def attached_serials() -> list[str]:
    r = subprocess.run([adb(), "devices"], capture_output=True, text=True,
                       timeout=20, creationflags=_NO_WINDOW or 0)
    out = []
    for ln in r.stdout.splitlines()[1:]:
        if ln.strip() and "offline" not in ln:
            out.append(ln.split()[0])
    return out


def attached_detailed() -> list[dict]:
    """`adb devices -l` parsed into {serial, state, model, ready, raw}.

    ``ready`` means the device is in the ``device`` (authorized+online) state,
    i.e. shell commands will actually run. ``unauthorized`` / ``offline``
    devices are reported but not usable — the UI uses this to tell the user
    to authorize USB debugging instead of silently pretending the phone
    is connected.
    """
    r = subprocess.run([adb(), "devices", "-l"], capture_output=True,
                       text=True, timeout=20, creationflags=_NO_WINDOW or 0)
    out = []
    for ln in r.stdout.splitlines()[1:]:
        if not ln.strip():
            continue
        parts = ln.split()
        if len(parts) < 2:
            continue
        entry = {"serial": parts[0], "state": parts[1],
                 "model": "", "ready": parts[1] == "device"}
        for tok in parts[2:]:
            k, _, v = tok.partition(":")
            if k == "model":
                entry["model"] = v
        out.append(entry)
    return out


def adb_observe(serial: str) -> dict:
    """Read only what ADB can honestly report; missing lanes stay unobserved."""
    def g(*args: str) -> str:
        try:
            r = subprocess.run([adb(), "-s", serial, "shell", *args],
                               capture_output=True, text=True, timeout=15,
                               creationflags=_NO_WINDOW or 0)
            return r.stdout.strip()
        except Exception:
            return ""
    facts = {}
    v = g("settings", "get", "global", "wifi_on")
    if v in ("1", "0"):
        facts["WIFI"] = "ON" if v == "1" else "OFF"
    v = g("settings", "get", "secure", "adb_enabled")
    if v in ("1", "0"):
        facts["ADB"] = "ON" if v == "1" else "OFF"
    v = g("settings", "get", "secure", "location_mode")
    if v and v.isdigit():
        facts["LOCATION"] = "OFF" if v == "0" else "ON"
    v = g("settings", "get", "global", "airplane_mode_on")
    if v in ("1", "0"):
        facts["MOBILE_DATA"] = "OFF" if v == "1" else "ON"
    return facts


def apps(serial: str) -> dict:
    """Real application inventory via `pm list packages` (host-side ADB).

    Honest only: returns exactly what `pm` printed. No package is ever
    claimed blocked/enabled here — app-level blocking happens through the
    device-owner DPC agent once enrolled (AGENT path); this view is the
    read-only inventory a manager reviews before policy scoping.
    """
    def g(*args: str) -> list[str]:
        try:
            r = subprocess.run([adb(), "-s", serial, "shell", *args],
                               capture_output=True, text=True, timeout=30,
                               creationflags=_NO_WINDOW or 0)
        except Exception:
            return []
        out = []
        for ln in r.stdout.splitlines():
            pkg = ln.strip()
            if pkg.startswith("package:"):
                name = pkg.split(":", 1)[1].strip()
                if name:
                    out.append(name)
        return out
    all_pkgs = set(g("pm", "list", "packages"))
    third_party = sorted(set(g("pm", "list", "packages", "-3")) & all_pkgs)
    system = sorted(all_pkgs - set(third_party))
    return {
        "serial": serial,
        "count": len(all_pkgs),
        "third_party_count": len(third_party),
        "system_count": len(system),
        "third_party": third_party,
        "system": system,
    }


def live_probe(serial: str) -> dict:
    """Rich REAL_DEVICE observation via ADB (verification-engine.probe)."""
    from verification_engine.probe import probe_live_device
    return probe_live_device(serial)


def classify_device(manufacturer: str = "", model: str = "",
                    android_version: int = 0, api_level: int = 0,
                    build_fingerprint: str = ""):
    """Vendor/version classification (device-agnostic)."""
    from vendor_adapters.registry import classify
    return classify(manufacturer=manufacturer, model=model,
                    android_version=android_version, api_level=api_level,
                    build_fingerprint=build_fingerprint)


def vendor_adapter_for_device(manufacturer: str = "", model: str = "",
                              android_version: int = 0, api_level: int = 0,
                              build_fingerprint: str = ""):
    from vendor_adapters.registry import select_adapter
    dc = classify_device(manufacturer, model, android_version, api_level,
                         build_fingerprint)
    return select_adapter(dc, knox_sdk_present=None), dc


def capability_for_device(conn, device_id: str):
    """Honest CapabilityProfile from Device Registry caps."""
    from capability_engine import CapabilityProfile
    dev = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
    if not dev:
        return None
    prof = CapabilityProfile(
        device_id=device_id, android_version=dev["android_version"] or 0,
        api_level=dev["api_level"] or 0, manufacturer=dev["manufacturer"] or "",
        model=dev["model"] or "", build_fingerprint=dev["build_fingerprint"] or "",
        device_owner=dev["device_owner_state"] == "ACTIVE")
    key = f"{dev['model']}|{dev['android_version']}|"
    p = conn.execute("SELECT p.* FROM device_profiles p WHERE p.profile_key LIKE ?",
                     (key + "%",)).fetchone()
    if p:
        for cap in conn.execute("SELECT feature, capability, method FROM capabilities WHERE profile_id=?",
                                (p["id"],)).fetchall():
            prof.states[cap["feature"]] = cap["capability"]
            if cap["method"]:
                prof.methods[cap["feature"]] = [m for m in cap["method"].split("|") if m]
    return prof


def resolve_policy(policy_id: str):
    from policy_engine import ALL_REFERENCE_POLICIES
    mapping = {
        "POL-PHONE_ONLY": "PHONE_ONLY", "PHONE_ONLY": "PHONE_ONLY",
        "POL-CORP_DEFAULT": "CORPORATE_DEFAULT", "CORPORATE_DEFAULT": "CORPORATE_DEFAULT",
        "POL-FULL_LOCKDOWN": "FULL_LOCKDOWN", "FULL_LOCKDOWN": "FULL_LOCKDOWN",
        "POL-PARTIAL": "PARTIAL_LOCKDOWN", "PARTIAL_LOCKDOWN": "PARTIAL_LOCKDOWN",
        "POL-MAINTENANCE": "MAINTENANCE", "MAINTENANCE": "MAINTENANCE",
        "POL-QUARANTINE": "QUARANTINE", "QUARANTINE": "QUARANTINE",
    }
    key = mapping.get(policy_id, policy_id).upper()
    b = ALL_REFERENCE_POLICIES.get(key)
    if b:
        return b()
    if policy_id.startswith("POL-CUST"):
        return _load_custom_policy(policy_id)
    return None


def _load_custom_policy(policy_id: str):
    """Rehydrate a console-created custom policy (POL-CUST-*) from the DB."""
    from policy_engine import Policy
    with connect() as c:
        row = c.execute(
            "SELECT policy_id, display_name, category, version, status, "
            "requirements, created_by FROM policies WHERE policy_id=?",
            (policy_id,)).fetchone()
    if not row:
        return None
    p = Policy(row["policy_id"], row["display_name"], row["category"],
               version=row["version"] or 1, status=row["status"] or "ACTIVE")
    for r in json.loads(row["requirements"] or "[]"):
        p.add(r.get("feature", ""), r.get("desired_state", "BLOCK"),
              risk=r.get("risk", "MEDIUM"))
    return p


def create_custom_policy(name: str, category: str, features,
                         risk: str = "MEDIUM", created_by: str = "console") -> object:
    """Create a console-managed custom policy (checkbox builder / Full Lockdown).

    `features` is a list of feature names to BLOCK. The policy is persisted
    with a POL-CUST-* id and becomes immediately resolvable (apply-able).
    """
    from policy_engine import Policy, FEATURES
    features = [f.strip().upper() for f in features if f and f.strip().upper() in FEATURES]
    if not features:
        raise ValueError("no valid features selected for custom policy")
    if category not in ("CORPORATE_DEFAULT", "PHONE_ONLY", "PARTIAL_LOCKDOWN",
                        "FULL_LOCKDOWN", "MAINTENANCE", "QUARANTINE"):
        raise ValueError(f"invalid category {category!r}")
    ts = time.strftime("%Y%m%d-%H%M%S")
    policy_id = f"POL-CUST-{ts}"
    p = Policy(policy_id, name or f"سياسة مخصصة {ts}", category,
               version=1, status="ACTIVE", created_by=created_by,
               change_reason="created live from the management console")
    for f in features:
        p.add(f, "BLOCK", risk,
              fallback="org-defined; enforcement depends on real device capability")
    reqs = json.dumps(
        [{"feature": r.feature, "desired_state": r.desired_state, "risk": r.risk}
         for r in p.requirements], ensure_ascii=False)
    with connect() as c:
        c.execute(
            "INSERT INTO policies (policy_id, display_name, category, version, status, checksum, requirements, created_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (policy_id, p.display_name, category, p.version, p.status,
             p.checksum(), reqs, created_by))
    return p


def persist_reference_policies() -> int:
    from policy_engine import ALL_REFERENCE_POLICIES
    imported = 0
    with connect() as c:
        for _, builder in ALL_REFERENCE_POLICIES.items():
            pol = builder()
            reqs = json.dumps(
                [{"feature": r.feature, "desired_state": r.desired_state, "risk": r.risk}
                 for r in pol.requirements], ensure_ascii=False)
            row = c.execute("SELECT id FROM policies WHERE policy_id=?",
                            (pol.policy_id,)).fetchone()
            if row:
                c.execute("UPDATE policies SET category=?, version=?, status=?, requirements=?, checksum=? "
                          "WHERE policy_id=?",
                          (pol.category, pol.version, pol.status, reqs, pol.checksum(), pol.policy_id))
            else:
                c.execute(
                    "INSERT INTO policies (policy_id, display_name, category, version, status, checksum, requirements, created_by) "
                    "VALUES (?,?,?,?,?,?,?,'workflows')",
                    (pol.policy_id, pol.display_name, pol.category, pol.version,
                     pol.status, pol.checksum(), reqs))
            imported += 1
    return imported


def staged_channel(serial: str, out_dir: str):
    """Stage the signed envelope for the on-device agent (PHASE 3 — not yet built).

    Returns (send, state); send(env) writes the envelope to out_dir. Deliveries
    are staged, never claimed as executed.
    """
    os.makedirs(out_dir, exist_ok=True)
    state = {"staged": []}
    def send(envelope):
        path = os.path.join(out_dir, envelope["cmd_id"] + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, ensure_ascii=False, indent=2)
        state["staged"].append(path)
        return {"ok": True, "error": None}
    return send, state


def enroll_device(device_id: Optional[str], serial: str,
                  device_owner: bool = False, lab: bool = False) -> dict:
    """Live ADB scan -> register device + profile + capabilities. Idempotent."""
    from capability_engine.scanner import adb_scan
    prof = adb_scan(adb=adb(), serial=serial)
    if prof.model:
        prof.model = prof.model.replace("_", "-")   # SM_J337P -> SM-J337P (adb -l spelling)
    dev_id = device_id or f"AVD-{serial.split('-')[-1]}"
    with connect() as c:
        exists = c.execute("SELECT id FROM devices WHERE device_id=?", (dev_id,)).fetchone()
        if not exists:
            c.execute(
                """INSERT INTO devices (device_id, serial, manufacturer, model, android_version,
                   api_level, build_fingerprint, security_patch, bootloader_state,
                   verified_boot_state, encryption_state,
                   enrollment_state, device_owner_state, control_channel, is_lab)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, 'ENROLLMENT_PENDING', ?, 'LOCAL_ADB', ?)""",
                (dev_id, serial, prof.manufacturer, prof.model, prof.android_version,
                 prof.api_level, prof.build_fingerprint,
                 prof.security_patch or None,
                 prof.bootloader.upper() or "UNKNOWN",
                 prof.verified_boot.upper() or "UNKNOWN",
                 prof.encryption.upper() or "UNKNOWN",
                 "ACTIVE" if device_owner else "NONE", 1 if lab else 0))
            c.execute("UPDATE devices SET last_seen_at=datetime('now') WHERE device_id=?", (dev_id,))
        else:
            c.execute(
                """UPDATE devices SET security_patch=COALESCE(NULLIF(?,''),security_patch),
                       bootloader_state=COALESCE(NULLIF(?,''),bootloader_state),
                       verified_boot_state=COALESCE(NULLIF(?,''),verified_boot_state),
                       encryption_state=COALESCE(NULLIF(?,''),encryption_state),
                       last_seen_at=datetime('now')
                   WHERE device_id=?""",
                (prof.security_patch, prof.bootloader.upper(), prof.verified_boot.upper(),
                 prof.encryption.upper(), dev_id))
        key = f"{prof.model}|{prof.android_version}|{(prof.build_fingerprint or '?')[:24]}"
        p = c.execute("SELECT id FROM device_profiles WHERE profile_key=?", (key,)).fetchone()
        if not p:
            cur = c.execute(
                """INSERT INTO device_profiles (profile_key, manufacturer, model, android_version,
                   api_level, build_id, source_of_record, class_tags, notes)
                   VALUES (?,?,?,?,?,?, 'LIVE_SCAN', 'ANDROID_VERSION_DEPENDENT', ?)""",
                (key, prof.manufacturer, prof.model, prof.android_version,
                 prof.api_level, (prof.build_fingerprint or "")[:24],
                 f"live adb scan of serial {serial}"))
            pid = cur.lastrowid
            for feat, st in prof.states.items():
                if st in ("ANDROID_VERSION_DEPENDENT", "PARTIAL"):
                    c.execute(
                        "INSERT INTO capabilities (profile_id, feature, capability, method) VALUES (?,?,?,?)",
                        (pid, feat, st, "|".join(prof.methods.get(feat, []))))
    return {"device_id": dev_id, "manufacturer": prof.manufacturer, "model": prof.model,
            "android_version": prof.android_version, "api_level": prof.api_level,
            "device_owner": device_owner}


def run_director_apply(device_id: str, policy_id: str,
                       op_role: str, mfa_ok: bool,
                       serial: Optional[str] = None,
                       real: bool = False,
                       signing_key: str = "",
                       chan_dir: Optional[str] = None,
                       channel_send=None) -> dict:
    """Full AD-4 pipeline for one device. Raises DirectorError/ApplyBlocked.

    channel_send: optional injected real transport (e.g. backend.channel).
    When neither chan_dir nor channel_send is given the command is prepared only.
    """
    from .director import Director, ApplyBlocked, DirectorError
    from .config import SIGNING_KEY
    from policy_engine.snapshot import resolve
    from compatibility import AndroidCompatibilityLayer
    from verification_engine import VerificationEngine

    pol = resolve_policy(policy_id)
    if pol is None:
        raise ValueError(f"unknown policy {policy_id!r}")
    persist_reference_policies()
    with connect() as c:
        dev = dict(c.execute("SELECT * FROM devices WHERE device_id=?",
                             (device_id,)).fetchone() or {})
    if not dev:
        raise ValueError(f"device {device_id!r} not registered")
    api = dev["api_level"] or 0
    cap = capability_for_device(connect(), device_id)
    key = (signing_key or SIGNING_KEY)

    channel, chan_state = None, {}
    serial = serial or dev["serial"]
    attached = bool(serial) and serial in attached_serials()
    if channel_send is not None:
        channel, chan_state = channel_send, {}
    elif chan_dir and attached:
        channel, chan_state = staged_channel(serial, chan_dir)

    if real and attached:
        obs = live_probe(serial).get("observed", {})
        source = "REAL_DEVICE"
    else:
        obs = {}
        source = "SIMULATED"

    adapter, device_class = vendor_adapter_for_device(
        manufacturer=dev.get("manufacturer") or "", model=dev.get("model") or "",
        android_version=dev.get("android_version") or 0,
        api_level=api, build_fingerprint=dev.get("build_fingerprint") or "")

    director = Director(
        db_path=None, resolve_fn=resolve,
        verify_fn=VerificationEngine(lambda _dev: obs).verify,
        channel_send=channel, signing_key=key)
    subset_raw = os.environ.get("ALP_LANE_SUBSET", "")
    lane_subset = {s.strip().upper() for s in subset_raw.split(",") if s.strip()} or None
    res = director.apply(device_id, pol, cap,
                         op_role=op_role, mfa_ok=mfa_ok,
                         compat_layer=AndroidCompatibilityLayer(api),
                         vendor_adapter=adapter,
                         evidence_src=source, lane_subset=lane_subset)
    return {
        "device_id": device_id, "policy_id": pol.policy_id, "stage": res.stage,
        "evidence_id": res.evidence_id, "audit_id": res.audit_id,
        "verification": res.verification.result if res.verification else None,
        "compliance": res.compliance,
        "source": source, "honest": res.verification.honest if res.verification else True,
        "observations": res.verification.observations if res.verification else {},
        "device_class": device_class.to_dict() if device_class else None,
        "vendor_adapter_status": adapter.status if adapter else None,
        "staged": chan_state.get("staged", []),
    }