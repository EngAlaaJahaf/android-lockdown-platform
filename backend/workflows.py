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
from datetime import datetime
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


def is_agent_installed(serial: str, timeout: int = 15) -> bool:
    """True only when `pm path` reports the agent package on this serial.

    The console gates registration and group deployment behind this: a device
    with no agent can never receive a policy, so the New Devices page must
    show Install first instead of letting the operator silently skip it.
    """
    try:
        r = subprocess.run([adb(), "-s", serial, "shell", "pm", "path",
                            _AGENT_PACKAGE],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW or 0)
    except Exception:
        return False
    return r.returncode == 0 and _AGENT_PACKAGE in (r.stdout or "")


def _legacy_admin_active(target: str, timeout: int = 60) -> bool:
    """Is OUR admin active in `dumpsys device_policy` output?

    Legacy fallback (pre-24 Android): `dpm list-owners` does not exist there
    and 5.x dumpsys prints no Device Owner section, so neither proof channel
    works. An active admin entry is weaker than ownership — it is only ever
    used TOGETHER with a `set-device-owner` returncode of 0, which on any
    Android means the claim succeeded.
    """
    try:
        r = subprocess.run([adb(), "-s", target, "shell", "dumpsys",
                            "device_policy"],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW or 0)
    except Exception:
        return False
    txt = r.stdout or ""
    return f"{_AGENT_PACKAGE}/" in txt and "AlpDeviceAdminReceiver" in txt


def is_device_owner_active(serial: str, timeout: int = 30) -> bool:
    """True only when the phone itself names the agent as device owner.

    Read-only (`dpm list-owners`): the same proof provision_device_owner
    persists, reused here so read paths (details page, preflight) report the
    phone's truth instead of a stale column — e.g. after the admin grant was
    removed on the handset while the DB still says ACTIVE.
    """
    target = (serial or "").strip()
    if not target:
        return False
    try:
        r = subprocess.run([adb(), "-s", target, "shell", "dpm", "list-owners"],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW or 0)
    except Exception:
        return False
    if r.returncode == 0 and _AGENT_PACKAGE in (r.stdout or ""):
        return True
    # Pre-24 Android has no list-owners: fall back to the admin-active entry
    # (documented weaker proof — see _legacy_admin_active).
    try:
        if 0 < api_level_of(target) < 24:
            return _legacy_admin_active(target, timeout)
    except Exception:
        pass
    return False


_AGENT_PACKAGE = "com.alp.agent"
_AGENT_ACTIVITY = "com.alp.agent/.MainActivity"
_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENT_DEBUG_APK = os.path.join(_AGENT_ROOT, "android-agent", "alp-agent.apk")
_AGENT_RELEASE_APK = os.path.join(_AGENT_ROOT, "android-agent",
                                  "alp-agent-release.apk")
_AGENT_LEGACY_APK = os.path.join(_AGENT_ROOT, "android-agent",
                                 "alp-agent-legacy.apk")


def api_level_of(serial: str, timeout: int = 15) -> int:
    """This handset's API level (0 when unreachable/unparseable).

    One cheap getprop: lets the console offer the legacy build to Android
    5-6 phones instead of letting the standard install fail with a
    cryptic message.
    """
    target = (serial or "").strip()
    if not target:
        return 0
    try:
        r = subprocess.run([adb(), "-s", target, "shell", "getprop",
                            "ro.build.version.sdk"],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW or 0)
    except Exception:
        return 0
    try:
        return int((r.stdout or "").strip().split()[0])
    except (ValueError, IndexError):
        return 0


def agent_apk_path(variant: str = "auto") -> str:
    """Resolve the installable ALP agent APK without accepting a client path.

    The console button installs a packaged project APK only. Client-supplied
    filesystem paths are never accepted here: that would turn an admin click
    into arbitrary local-file installation.

    Variants: auto (release, else debug), release, debug, legacy (the
    minSdk-21 build for Android 5-6 handsets that reject the standard one
    with INSTALL_FAILED_OLDER_SDK).
    """
    choice = (variant or "auto").strip().lower()
    if choice not in ("auto", "release", "debug", "legacy"):
        raise ValueError("variant must be auto, release, debug or legacy")
    if choice in ("auto", "release") and os.path.isfile(_AGENT_RELEASE_APK):
        return _AGENT_RELEASE_APK
    if choice in ("auto", "debug") and os.path.isfile(_AGENT_DEBUG_APK):
        return _AGENT_DEBUG_APK
    if choice == "legacy":
        if os.path.isfile(_AGENT_LEGACY_APK):
            return _AGENT_LEGACY_APK
        raise ValueError("legacy agent APK not found — build it with "
                         "scripts/build_agent.py --release --min-sdk 21 "
                         "--apk android-agent/alp-agent-legacy.apk")
    if choice == "release":
        raise ValueError("release agent APK not found — build a release APK first")
    if choice == "debug":
        raise ValueError("debug agent APK not found — run scripts/build_agent.py first")
    raise ValueError("agent APK not found — run scripts/build_agent.py first")


def install_agent_app(serial: str = "", device_id: str = "",
                       variant: str = "auto", launch: bool = True) -> dict:
    """Install the packaged ALP agent on one attached device and verify it.

    Returns a result dict and never claims success it did not observe:
    `installed` is true only when `adb install` succeeded AND `pm path`
    reports the package. A failed launch is reported separately so the UI can
    continue with registration while warning the operator.
    """
    target = (serial or "").strip()
    if not target and (device_id or "").strip():
        with connect() as c:
            row = c.execute("SELECT serial FROM devices WHERE device_id=?",
                            (device_id.strip(),)).fetchone()
        if not row or not row["serial"]:
            raise ValueError(f"device {device_id.strip()!r} is not registered")
        target = row["serial"]
    if not target:
        attached = attached_serials()
        if not attached:
            raise ValueError("no device is attached — connect it over USB first")
        if len(attached) > 1:
            raise ValueError("several devices are attached — choose one: "
                             + ", ".join(attached))
        target = attached[0]

    apk = agent_apk_path(variant)
    test_only = os.path.basename(apk) == "alp-agent.apk"

    def sh(*args: str, timeout: int = 180):
        return subprocess.run([adb(), "-s", target, *args],
                              capture_output=True, text=True, timeout=timeout,
                              creationflags=_NO_WINDOW or 0)

    state = next((d for d in attached_detailed()
                  if d.get("serial") == target), None)
    if state is None:
        return {"serial": target, "installed": False, "package": _AGENT_PACKAGE,
                "apk": os.path.basename(apk),
                "error": f"{target} is no longer attached",
                "hint": "reconnect the USB cable, then refresh the new-device page"}
    if not state.get("ready"):
        return {"serial": target, "installed": False, "package": _AGENT_PACKAGE,
                "apk": os.path.basename(apk),
                "error": f"{target} is {state.get('state') or 'not ready'}",
                "hint": "on the phone, allow USB debugging for this computer, "
                        "then refresh the new-device page"}

    cmd = ["install", "-r", "-d"] + (["-t"] if test_only else []) + [apk]
    inst = sh(*cmd)
    out = ((inst.stdout or "") + "\n" + (inst.stderr or "")).strip()
    if inst.returncode != 0:
        if "INSTALL_FAILED_OLDER_SDK" in out:
            return {"serial": target, "installed": False,
                    "package": _AGENT_PACKAGE,
                    "apk": os.path.basename(apk),
                    "error": "this phone's Android is too old for the standard "
                             "build (needs Android 7.0/API 24+)",
                    "detail": out[-500:],
                    "hint": "install the legacy build instead (Android 5-6): "
                            "use variant 'legacy' — same guarded agent, "
                            "installable where the standard APK is refused"}
        return {"serial": target, "installed": False, "package": _AGENT_PACKAGE,
                "apk": os.path.basename(apk),
                "error": "the install was refused by the phone",
                "detail": out[-500:],
                "hint": "keep the phone unlocked and accept the install prompt, "
                        "then try again"}
    chk = sh("shell", "pm", "path", _AGENT_PACKAGE, timeout=60)
    if chk.returncode != 0 or _AGENT_PACKAGE not in (chk.stdout or ""):
        return {"serial": target, "installed": False, "package": _AGENT_PACKAGE,
                "apk": os.path.basename(apk),
                "error": "the package is missing after install",
                "detail": ((chk.stdout or "") + "\n" + (chk.stderr or "")).strip()[-500:],
                "hint": "try again; if it repeats, rebuild the agent APK"}
    launched, launch_error = False, ""
    if launch:
        started = sh("shell", "am", "start", "-n", _AGENT_ACTIVITY,
                     "--activity-no-history", timeout=60)
        launched = started.returncode == 0
        if not launched:
            launch_error = ((started.stdout or "") + "\n"
                            + (started.stderr or "")).strip()[-300:]
    return {"serial": target, "installed": True, "package": _AGENT_PACKAGE,
            "apk": os.path.basename(apk), "verified": True,
            "launched": launched, "launch_error": launch_error,
            "hint": "" if launched else "the app is installed; registration can "
                    "continue, but open the agent once on the phone"}


_AGENT_DO_RECEIVER = "com.alp.agent/.AlpDeviceAdminReceiver"


# Tables that hold per-device rows. device_id here is either the integer
# devices.pk (assignments, members, …) or the text device_id (tokens,
# vault, …) depending on the table — the deleter below covers both, and
# probes the real columns first so schema drift can never break it.
_DEVICE_CHILD_TABLES = (
    "device_group_members", "assignments", "compliance", "evidence",
    "failures", "job_executions", "command_nonces", "approvals",
    "approval_confirmations", "audit_logs", "recovery_actions", "sessions",
    "emergency_tokens", "recovery_credentials",
)


def delete_device(device_id: str) -> dict:
    """Delete one device record and every row that references it.

    Refuses when the app is PROVEN present (attached + `pm path` hit): the
    details page only offers Delete while the app is gone, and the backend
    re-checks instead of trusting the button. A detached phone proves
    nothing, so deletion proceeds with `presence_verified: False` reported
    honestly — the operator decided on a record they cannot reach.
    """
    key = (device_id or "").strip()
    if not key:
        raise ValueError("device_id is required")
    with connect() as c:
        row = c.execute("SELECT * FROM devices WHERE device_id=? OR serial=?",
                        (key, key)).fetchone()
        if not row:
            raise ValueError(f"device {key!r} is not registered")
        dev = dict(row)
        serial = (dev.get("serial") or "").strip()
        try:
            attached = bool(serial) and serial in attached_serials()
        except Exception:
            attached = False
        presence_verified = False
        if attached:
            try:
                present = bool(is_agent_installed(serial))
                presence_verified = True
            except Exception:
                present = False
            if present:
                raise ValueError(
                    f"agent {_AGENT_PACKAGE} is still installed on {serial} — "
                    "remove the app from the phone first")
        cleaned: dict = {}
        existing = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in _DEVICE_CHILD_TABLES:
            if table not in existing:
                continue
            cols = {r["name"] for r in c.execute(
                f"PRAGMA table_info({table})").fetchall()}
            if "device_id" not in cols:
                continue
            n = c.execute(f"DELETE FROM {table} WHERE device_id=?",
                          (dev["id"],)).rowcount or 0
            n += c.execute(f"DELETE FROM {table} WHERE device_id=?",
                           (dev["device_id"],)).rowcount or 0
            if n:
                cleaned[table] = n
        c.execute("DELETE FROM devices WHERE id=?", (dev["id"],))
    return {"deleted": True, "device_id": dev["device_id"],
            "serial": serial, "attached": attached,
            "presence_verified": presence_verified, "cleaned": cleaned}


def ensure_emergency_secret_on_device(serial: str = "",
                                      device_id: str = "") -> dict:
    """Push the per-device offline emergency secret right after install.

    The console-side credential is created (idempotently) and the same secret
    is delivered into the agent inside a SIGNED EMERGENCY_SECRET envelope, so
    the Emergency screen works the first time the holder opens it — no second
    console visit needed. Best-effort by design: a failed push never fails the
    install/owner claim itself, it is reported so the operator can retry the
    provision step from the Recovery panel.
    """
    target = (serial or "").strip()
    dev_id = (device_id or "").strip()
    if not dev_id and target:
        try:
            with connect() as c:
                row = c.execute("SELECT device_id FROM devices WHERE serial=?",
                                (target,)).fetchone()
            dev_id = row["device_id"] if row else ""
        except Exception:
            dev_id = ""
    if not dev_id:
        return {"provisioned": False,
                "reason": "device is not registered — enroll it first, then "
                          "re-run device-owner provisioning"}
    try:
        from .emergency import provision_offline_secret
        from .recovery_credentials import RecoveryVault
        RecoveryVault().ensure_for(dev_id)
        out = provision_offline_secret(dev_id, serial=target)
        return {"provisioned": bool(out.get("provisioned")),
                "device_id": dev_id, "delivery": out.get("delivery")}
    except Exception as ex:  # noqa: BLE001
        return {"provisioned": False, "device_id": dev_id,
                "error": f"{type(ex).__name__}: {ex}"}


def provision_device_owner(serial: str = "", device_id: str = "",
                           variant: str = "auto", launch: bool = True) -> dict:
    """Reinstall the agent and claim Device Owner on one attached device.

    Same steps as the documented R2 provisioning plan: install the packaged
    (non-testOnly) APK -> verify with `pm path` -> `user_setup_complete=0`
    -> `dpm set-device-owner` -> prove it in `dumpsys device_policy` ->
    restore the setup flag. The flag is restored on EVERY path, including
    refusal: a half-provisioned phone (setup flag stuck at 0) breaks the
    setup wizard, so leaving it set is never acceptable.

    Returns a dict; device-side refusals (accounts signed in, owner already
    taken) come back as device_owner False with a plain-language hint, never
    as an exception. Raises ValueError only for bad input (unknown device,
    ambiguous serial, missing APK) — same contract as install_agent_app.
    """
    import re as _re

    target = (serial or "").strip()
    dev_id = (device_id or "").strip()
    if not target and dev_id:
        with connect() as c:
            row = c.execute("SELECT serial FROM devices WHERE device_id=?",
                            (dev_id,)).fetchone()
        if not row or not row["serial"]:
            raise ValueError(f"device {dev_id!r} is not registered")
        target = row["serial"]
    if not target:
        attached = attached_serials()
        if not attached:
            raise ValueError("no device is attached — connect it over USB first")
        if len(attached) > 1:
            raise ValueError("several devices are attached — choose one: "
                             + ", ".join(attached))
        target = attached[0]
    if not dev_id:
        # Best-effort: a missing/unmigrated devices table must not stop the
        # actual provisioning work, only the bookkeeping around it.
        try:
            with connect() as c:
                row = c.execute("SELECT device_id FROM devices WHERE serial=?",
                                (target,)).fetchone()
            dev_id = row["device_id"] if row else ""
        except Exception:
            dev_id = ""

    base = {"serial": target, "package": _AGENT_PACKAGE,
            "receiver": _AGENT_DO_RECEIVER, "installed": False,
            "device_owner": False}

    def persist_owner_state(state: str) -> None:
        """Write ONLY what the phone proved. device_owner_state is a claim
        about the device, never about what the console was asked to do."""
        if not dev_id:
            return
        try:
            with connect() as c:
                c.execute("UPDATE devices SET device_owner_state=?, updated_at="
                          "datetime('now') WHERE device_id=?",
                          (state, dev_id))
        except Exception:
            pass

    def sh(*args: str, timeout: int = 120):
        return subprocess.run([adb(), "-s", target, *args],
                              capture_output=True, text=True, timeout=timeout,
                              creationflags=_NO_WINDOW or 0)

    def resync_owner_state() -> str:
        """Ask the phone who owns it, then persist exactly that.

        A REFUSED provisioning proves nothing: `set-device-owner` also refuses
        when the agent is ALREADY the owner (e.g. a plain reinstall), and
        writing NONE there would erase a true ACTIVE. So every non-happy path
        re-probes instead of assuming.
        """
        try:
            r = sh("shell", "dpm", "list-owners", timeout=60)
            txt = ((r.stdout or "") + (r.stderr or ""))
        except Exception:
            return ""
        if _AGENT_PACKAGE in txt:
            state = "ACTIVE"
        elif 0 < api_level_of(target) < 24 and _legacy_admin_active(target):
            # list-owners does not exist pre-24 and 5.x dumpsys prints no
            # owner section: our active admin entry is the available proof.
            state = "ACTIVE"
        else:
            state = "NONE"
        persist_owner_state(state)
        base["device_owner"] = state == "ACTIVE"
        return state

    inst = install_agent_app(serial=target, variant=variant, launch=launch)
    base.update({k: inst.get(k) for k in
                 ("installed", "apk", "verified", "launched")})
    if not inst.get("installed"):
        base.update({"error": inst.get("error", "agent install failed"),
                     "detail": inst.get("detail", ""),
                     "hint": inst.get("hint", "")})
        # Deliberately NOT probing or writing device_owner_state here: the app
        # never landed, so nothing about ownership was proven either way. The
        # stored value stays as the last thing the phone actually reported.
        return base

    prev_flag = None
    try:
        r = sh("shell", "settings", "get", "secure", "user_setup_complete",
               timeout=30)
        prev_flag = (r.stdout or "").strip() or None
        sh("shell", "settings", "put", "secure", "user_setup_complete", "0",
           timeout=30)
        dpm = sh("shell", "dpm", "set-device-owner", _AGENT_DO_RECEIVER,
                 timeout=60)
        dpm_out = ((dpm.stdout or "") + "\n" + (dpm.stderr or "")).strip()
        if dpm.returncode != 0:
            low = dpm_out.lower()
            if "already" in low and resync_owner_state() == "ACTIVE":
                # Not a failure at all: dpm refuses a second claim from the
                # package that already owns the device (what a plain reinstall
                # looks like). Report the truth instead of an error.
                base.update({"device_owner": True,
                             "already_owner": True,
                             "hint": "this app already is the device owner — "
                                     "nothing to claim"})
                base["emergency_secret"] = ensure_emergency_secret_on_device(
                    target, dev_id)
                return base
            if "account" in low:
                hint = ("the phone has signed-in accounts — remove every account "
                        "in Settings > Accounts, then run this again")
            elif "already" in low:
                hint = ("another owner is already set — remove it first, "
                        "then run this again")
            else:
                hint = "fix what the phone reports, then run this again"
            base.update({"error": "the phone refused device-owner provisioning",
                         "detail": dpm_out[-500:], "hint": hint})
            resync_owner_state()
            return base
        chk = sh("shell", "dumpsys", "device_policy", timeout=60)
        dump = chk.stdout or ""
        m = _re.search(r"[Dd]evice [Oo]wner[:\s]+(\S+)", dump)
        owner = m.group(1) if m else ""
        if owner and owner.lower() != "null" and _AGENT_PACKAGE in owner:
            base.update({"device_owner": True,
                         "hint": "device owner active ? restrictions now enforce "
                                 "at OS level"})
            persist_owner_state("ACTIVE")
            base["emergency_secret"] = ensure_emergency_secret_on_device(
                target, dev_id)
            return base
        elif (dpm.returncode == 0 and 0 < api_level_of(target) < 24
                and _legacy_admin_active(target)):
            # Pre-24 Android prints no Device Owner section in dumpsys and
            # has no list-owners: an accepted claim plus our active admin is
            # the available proof (weaker — said so in legacy_admin_active).
            base.update({"device_owner": True,
                         "legacy_proof": True,
                         "hint": "device owner active (legacy proof: claim "
                                 "accepted and admin active — 5.x prints no "
                                 "owner section)"})
            persist_owner_state("ACTIVE")
            base["emergency_secret"] = ensure_emergency_secret_on_device(
                target, dev_id)
            return base
        else:
            base.update({"error": "dpm accepted but the owner is not visible",
                         "detail": (dpm_out + "\n" + dump[:300]).strip()[-500:],
                         "hint": "reboot the phone and run this again"})
            resync_owner_state()
            return base
    finally:
        restore = prev_flag if prev_flag in ("0", "1") else "1"
        try:
            sh("shell", "settings", "put", "secure", "user_setup_complete",
               restore, timeout=30)
        except Exception:
            pass


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
    # Any other stored profile row is rehydrated from the DB. This used to be
    # limited to the POL-CUST-* prefix, which made a console-saved profile with
    # a different id unresolvable -- it appeared in the profile list but failed
    # every apply with "unknown policy".
    return _load_custom_policy(policy_id)


def _load_custom_policy(policy_id: str):
    """Rehydrate a stored profile (custom, or any non-reference row) from the DB."""
    from policy_engine import Policy
    with connect() as c:
        row = c.execute(
            "SELECT policy_id, display_name, category, version, status, "
            "requirements, created_by, recovery_attempts FROM policies WHERE policy_id=?",
            (policy_id,)).fetchone()
    if not row:
        return None
    p = Policy(row["policy_id"], row["display_name"], row["category"],
               version=row["version"] or 1, status=row["status"] or "ACTIVE",
               recovery_attempts=row["recovery_attempts"])
    for r in json.loads(row["requirements"] or "[]"):
        p.add(r.get("feature", ""), r.get("desired_state", "BLOCK"),
              risk=r.get("risk", "MEDIUM"))
    return p


def create_custom_policy(name: str, category: str, features,
                         risk: str = "MEDIUM", created_by: str = "console",
                         recovery_attempts: int | None = None) -> object:
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
    ts = datetime.now().strftime("%Y%m%d-%H%M%S.%f")
    policy_id = f"POL-CUST-{ts}"
    p = Policy(policy_id, name or f"سياسة مخصصة {ts}", category,
               version=1, status="ACTIVE", created_by=created_by,
               change_reason="created live from the management console",
               recovery_attempts=recovery_attempts)
    for f in features:
        p.add(f, "BLOCK", risk,
              fallback="org-defined; enforcement depends on real device capability")
    reqs = json.dumps(
        [{"feature": r.feature, "desired_state": r.desired_state, "risk": r.risk}
         for r in p.requirements], ensure_ascii=False)
    with connect() as c:
        c.execute(
            "INSERT INTO policies (policy_id, display_name, category, version, status, checksum, requirements, created_by, recovery_attempts) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (policy_id, p.display_name, category, p.version, p.status,
             p.checksum(), reqs, created_by, recovery_attempts))
    return p


def create_policy_from_catalog(features, name: str = "", risk: str = "MEDIUM",
                               created_by: str = "console") -> dict:
    """Create (and persist) a custom policy from ManageEngine catalog labels.

    `features` are ALP feature keys from the catalog (the console resolves the
    ManageEngine labels to those keys before calling). Returns:
        {"policy": Policy, "applied": [...], "excluded": {...}}
    where `excluded` lists catalog features handed in but NOT enforced (OEM/Knox
    or no real mechanism) so the console can show the admin honestly.
    """
    from backend import restrictions
    pol, applied, excluded = restrictions.policy_from_catalog(
        features, name=name or "سياسة القيود", risk=risk)
    by_feat = restrictions.by_feature()
    excluded_info = {}
    for f in excluded:
        row = (by_feat.get(f) or [{}])[0]
        excluded_info[f] = row.get("note") or row.get("tier") or "not enforceable"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S.%f")
    policy_id = f"POL-CUST-{ts}"
    pol.policy_id = policy_id
    pol.status = "ACTIVE"
    pol.created_by = created_by
    pol.change_reason = "built from ManageEngine MDM Plus restriction catalog"
    reqs = json.dumps(
        [{"feature": r.feature, "desired_state": r.desired_state, "risk": r.risk}
         for r in pol.requirements], ensure_ascii=False)
    with connect() as c:
        c.execute(
            "INSERT INTO policies (policy_id, display_name, category, version, status, checksum, requirements, created_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (policy_id, pol.display_name, pol.category, pol.version, pol.status,
             pol.checksum(), reqs, created_by))
    return {"policy": pol, "applied": applied, "excluded": excluded_info}


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
    """Deliver the signed envelope to the on-device agent over ADB.

    Returns (send, state). Every delivery keeps a local copy under out_dir (the
    audit trail) and then PUSHES the file to /data/local/tmp and wakes the
    agent, exactly like backend.channel.adb_channel.

    The delivery result is decided by whether the handset actually received the
    bytes: a failed push, or a device that is not attached, returns ok=False
    with the reason. Returning ok=True for a file that only ever existed on the
    server is what let the console report a policy as deployed to devices that
    never saw it.
    """
    os.makedirs(out_dir, exist_ok=True)
    state = {"staged": [], "pushed": [], "failed": []}

    def _remote_for(envelope):
        """Pick the on-device path that matches this command's action."""
        from .channel import REMOTE_FILES
        act = envelope.get("action", "APPLY_POLICY")
        return REMOTE_FILES.get(act,
                                REMOTE_FILES["APPLY_POLICY"])

    def send(envelope):
        cmd_id = envelope.get("cmd_id", "env")
        path = os.path.join(out_dir, cmd_id + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, ensure_ascii=False, indent=2)
        state["staged"].append(path)

        if not serial:
            err = "device has no ADB serial recorded"
            state["failed"].append(err)
            return {"ok": False, "error": err, "cmd_id": cmd_id,
                    "staged": path}

        target = _remote_for(envelope)
        act = envelope.get("action", "APPLY_POLICY")

        def sh(*args):
            return subprocess.run([adb(), "-s", serial, *args],
                                  capture_output=True, text=True, timeout=120,
                                  creationflags=_NO_WINDOW or 0)

        if serial not in attached_serials():
            err = ("device %s is not attached over ADB - envelope staged only"
                   % serial)
            state["failed"].append(err)
            return {"ok": False, "error": err, "cmd_id": cmd_id,
                    "staged": path, "serial": serial}

        p = sh("push", path, target)
        if p.returncode != 0:
            err = "adb push failed: %s" % ((p.stderr or p.stdout or "").strip()[:200])
            state["failed"].append(err)
            return {"ok": False, "error": err, "cmd_id": cmd_id,
                    "staged": path, "serial": serial}

        # Foreground first: on builds that vault background broadcasts the
        # explicit broadcast is deferred forever unless the app is awake.
        sh("shell", "am", "start", "-n", _AGENT_ACTIVITY, "--activity-no-history")
        b = sh("shell", "am", "broadcast", "-n",
               "com.alp.agent/.CommandReceiver",
               "-a", "com.alp.agent.%s" % act, "--receiver-foreground")

        state["pushed"].append({"cmd_id": cmd_id, "target": target,
                                "broadcast_rc": b.returncode})
        return {"ok": True, "error": None, "cmd_id": cmd_id,
                "staged": path, "pushed_to": target, "serial": serial,
                "broadcast_rc": b.returncode}

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
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, 'ENROLLMENT_PENDING', 'NONE', 'LOCAL_ADB', ?)""",
                (dev_id, serial, prof.manufacturer, prof.model, prof.android_version,
                 prof.api_level, prof.build_fingerprint,
                 prof.security_patch or None,
                 prof.bootloader.upper() or "UNKNOWN",
                 prof.verified_boot.upper() or "UNKNOWN",
                 prof.encryption.upper() or "UNKNOWN",
                 1 if lab else 0))
            c.execute("UPDATE devices SET last_seen_at=datetime('now') WHERE device_id=?", (dev_id,))
        else:
            # NOTE: device_owner_state is deliberately NOT written here. A scan
            # proves nothing about ownership, and claiming ACTIVE because the
            # console asked for it is what made restrictions "apply" on paper
            # while the phone had no owner at all. Ownership is only ever set
            # by provision_device_owner from a dumpsys proof.
            c.execute(
                """UPDATE devices SET security_patch=COALESCE(NULLIF(?,''),security_patch),
                       bootloader_state=COALESCE(NULLIF(?,''),bootloader_state),
                       verified_boot_state=COALESCE(NULLIF(?,''),verified_boot_state),
                       encryption_state=COALESCE(NULLIF(?,''),encryption_state),
                       last_seen_at=datetime('now')
                   WHERE device_id=?""",
                (prof.security_patch, prof.bootloader.upper(),
                 prof.verified_boot.upper(), prof.encryption.upper(), dev_id))
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
    with connect() as c:
        owner_row = c.execute(
            "SELECT device_owner_state FROM devices WHERE device_id=?",
            (dev_id,)).fetchone()
    owner_state = (owner_row["device_owner_state"] if owner_row else "") or "NONE"
    return {"device_id": dev_id, "manufacturer": prof.manufacturer,
            "model": prof.model, "android_version": prof.android_version,
            "api_level": prof.api_level,
            # Verified truth, not the requested flag.
            "device_owner": owner_state == "ACTIVE",
            "device_owner_state": owner_state,
            "next_step": ("group" if owner_state == "ACTIVE" else "install"),
            "next_step_reason": (
                "device owner is active — assign this device to a group"
                if owner_state == "ACTIVE" else
                "no device owner yet — run device-owner provisioning, "
                "restrictions cannot enforce until Android grants ownership")}


def run_director_apply(device_id: str, policy_id: str,
                       op_role: str, mfa_ok: bool,
                       serial: Optional[str] = None,
                       real: bool = False,
                       signing_key: str = "",
                       chan_dir: Optional[str] = None,
                       channel_send=None,
                       allow_channel_risk: bool = False,
                       force: bool = False) -> dict:
    """Full AD-4 pipeline for one device. Raises DirectorError/ApplyBlocked.

    channel_send: optional injected real transport (e.g. backend.channel).
    When neither chan_dir nor channel_send is given the command is prepared only.

    allow_channel_risk: real delivery of a profile containing a
    CHANNEL_RISK lane (e.g. DEVELOPER_OPTIONS, which kills the ADB session
    carrying the command) is refused unless the caller explicitly opts in.
    The console never opts in, so no button can orphan a phone by accident.

    force: apply the enforceable lanes even when the snapshot carries
    unresolved exceptions, instead of refusing the whole profile. The skipped
    lanes come back in `unresolved_lanes` so the console can report them; they
    are never silently dropped.
    """
    from .director import Director, ApplyBlocked, DirectorError
    from .config import signing_key as _current_key
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
    key = (signing_key or _current_key())

    channel, chan_state = None, {}
    serial = serial or dev["serial"]
    attached = bool(serial) and serial in attached_serials()
    if real and attached and not allow_channel_risk:
        from .restrictions import CHANNEL_RISK_FEATURES
        risky = set(pol.feature_map()) & CHANNEL_RISK_FEATURES
        if risky:
            raise DirectorError(
                f"refused: this profile would {', '.join(sorted(risky))} on "
                f"{serial} — that kills the USB session carrying the command, "
                "leaving rollback and recovery unreachable. Re-apply from a "
                "physical visit with allow_channel_risk, or drop the lane.")
    if channel_send is not None:
        channel, chan_state = channel_send, {}
    elif chan_dir and attached:
        channel, chan_state = staged_channel(serial, chan_dir)
    elif real and attached:
        # No silent delivery into the void: without the on-device agent there
        # is nothing to receive the envelope, so refuse up front with a clear
        # reason instead of failing later with a cryptic verification gap.
        if not is_agent_installed(serial):
            raise DirectorError(
                f"agent {_AGENT_PACKAGE} is not installed on {serial} — "
                "install it from the New Devices page first")
        from .channel import adb_channel
        channel, chan_state = adb_channel(serial)

    if real and attached:
        source = "REAL_DEVICE"
    else:
        obs = {}
        source = "SIMULATED"

    adapter, device_class = vendor_adapter_for_device(
        manufacturer=dev.get("manufacturer") or "", model=dev.get("model") or "",
        android_version=dev.get("android_version") or 0,
        api_level=api, build_fingerprint=dev.get("build_fingerprint") or "")

    def _observe(_dev):
        if real and attached:
            out = live_probe(serial).get("observed", {})
            # The handset's own state.json is the authority on which rows were
            # actually enforced; fold the rows it skipped into the observations so
            # the pipeline can report PARTIAL instead of a clean PASS.
            try:
                from .agent_state import read_last_apply, skipped_features
                agent_st = read_last_apply(serial)
            except Exception:
                agent_st = {}
            for feat in skipped_features(agent_st):
                out.setdefault(feat, "UNENFORCED")
            return out
        return obs

    director = Director(
        db_path=None, resolve_fn=resolve,
        verify_fn=VerificationEngine(_observe).verify,
        channel_send=channel, signing_key=key)
    subset_raw = os.environ.get("ALP_LANE_SUBSET", "")
    lane_subset = {s.strip().upper() for s in subset_raw.split(",") if s.strip()} or None
    res = director.apply(device_id, pol, cap,
                         op_role=op_role, mfa_ok=mfa_ok,
                         compat_layer=AndroidCompatibilityLayer(api),
                         vendor_adapter=adapter,
                         evidence_src=source, lane_subset=lane_subset,
                         force=force)
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
        # Lanes this handset has no mechanism for. Empty when the whole profile
        # applied cleanly.
        "unresolved_lanes": sorted(res.exceptions),
        "notes": list(res.notes),
    }


def reset_device_policies(device_id: str, serial: str | None = None) -> dict:
    """إلغاء كل القيود المطبقة على الجهاز عبر ADB وإعادة الجهاز لحالة نظيفة.

    يُرسل أوامر ADB مباشرة إلى الجهاز لإزالة كل قيود Device Owner
    المطبقة سابقاً، دون الحاجة إلى مسح البيانات (factory reset).

    بعد النجاح:
    - تُحذف كل assignments القديمة للجهاز من قاعدة البيانات
    - يُحدث group_deploy_status ليعكس الحالة الجديدة (NOT_DEPLOYED)
    - الجهاز جاهز لاستقبال السياسة الجديدة من المجموعة

    يعمل فقط عندما يكون الجهاز متصلاً عبر ADB.
    """
    with connect() as c:
        dev = dict(c.execute("SELECT * FROM devices WHERE device_id=?",
                             (device_id,)).fetchone() or {})
    if not dev:
        raise ValueError(f"device {device_id!r} not registered")

    target_serial = serial or dev.get("serial") or ""
    attached = bool(target_serial) and target_serial in attached_serials()

    adb_results = []
    adb_errors = []

    if attached:
        # 1. إرسال أمر CLEAR_POLICY عبر القناة الآمنة المشفرة للـ Agent DPC إذا كان مثبتاً
        try:
            from .channel import adb_channel
            from .command import new_command
            from .config import signing_key as _current_key
            channel, _ = adb_channel(target_serial)
            env = new_command(
                job_execution_id=0,
                device_id=device_id,
                action="CLEAR_POLICY",
                body={"reason": "admin reset and clean deployment", "scope": "ALL"},
                key=_current_key()
            )
            ch_res = channel(env, action="CLEAR_POLICY")
            adb_results.append({"channel_clear": ch_res})
        except Exception as exc:
            adb_errors.append({"channel_clear_error": str(exc)})

        # 2. أوامر ADB المباشرة لإلغاء كل قيود Device Owner والمستخدم على الجهاز
        _KNOWN_RESTRICTIONS = [
            "no_camera",
            "no_config_wifi",
            "no_config_tethering",
            "no_usb_file_transfer",
            "no_config_vpn",
            "no_unmute_microphone",
            "no_debugging_features",
            "no_safe_boot",
            "no_factory_reset",
            "no_install_unknown_sources",
            "no_modify_accounts",
            "no_share_location",
            "no_uninstall_apps",
            "no_clear_app_data",
            "no_bluetooth",
            "no_bluetooth_sharing",
            "no_network_reset",
            "no_sms",
            "no_outgoing_calls",
            "no_ambient_display",
            "no_data_roaming",
            "no_set_wallpaper",
            "no_mock_location",
        ]

        # إلغاء قيود الجهاز العامة
        _CLEAR_COMMANDS = [
            ["shell", "dpm", "set-camera-disabled", "com.alp.agent", "false"],
            ["shell", "dpm", "set-keyguard-disabled-features", "com.alp.agent", "0"],
            ["shell", "dpm", "set-screen-capture-disabled", "com.alp.agent", "false"],
            ["shell", "settings", "put", "global", "adb_enabled", "1"],
            ["shell", "settings", "put", "global", "airplane_mode_on", "0"],
            ["shell", "settings", "put", "global", "data_saver", "0"],
            ["shell", "settings", "put", "global", "data_roaming", "1"],
            ["shell", "settings", "put", "global", "auto_time", "1"],
            ["shell", "settings", "put", "global", "auto_time_zone", "1"],
        ]

        for r_name in _KNOWN_RESTRICTIONS:
            _CLEAR_COMMANDS.append(["shell", "dpm", "clear-user-restriction", "com.alp.agent", r_name])
            _CLEAR_COMMANDS.append(["shell", "cmd", "user", "set-restriction", r_name, "0"])

        for cmd in _CLEAR_COMMANDS:
            try:
                r = subprocess.run(
                    [adb(), "-s", target_serial] + cmd,
                    capture_output=True, text=True, timeout=10,
                    creationflags=_NO_WINDOW or 0)
                if r.returncode == 0 or "Unknown command" not in (r.stderr or ""):
                    adb_results.append({
                        "cmd": " ".join(cmd),
                        "ok": r.returncode == 0,
                        "out": (r.stdout or "").strip()[:100],
                    })
            except Exception as exc:
                adb_errors.append({"cmd": " ".join(cmd), "error": str(exc)})

    # مسح assignments السابقة بالكامل من قاعدة البيانات لضمان عدم بقاء أي قيد قديم
    with connect() as c:
        dev_pk = dev["id"]
        c.execute("DELETE FROM assignments WHERE device_id=?", (dev_pk,))
        c.execute("UPDATE devices SET compliance_state='UNKNOWN', current_policy_id=NULL WHERE id=?", (dev_pk,))

        # أعد ضبط group_deploy_status لكل المجموعات المرتبطة بهذا الجهاز
        gpa_rows = c.execute(
            "SELECT gpa.id FROM group_profile_assignments gpa "
            "JOIN device_group_members dgm ON dgm.group_id=gpa.group_id "
            "JOIN devices d ON d.id=dgm.device_id WHERE d.device_id=?",
            (device_id,)).fetchall()
        for row in gpa_rows:
            c.execute(
                "UPDATE group_deploy_status SET yet_to_apply_count=total_target_count, "
                "success_count=0, failed_count=0, not_applicable_count=0 "
                "WHERE assignment_id=?", (row["id"],))

        cleared_count = c.execute(
            "SELECT changes() AS n").fetchone()["n"]

    return {
        "device_id": device_id,
        "serial": target_serial,
        "attached": attached,
        "adb_commands_sent": len(adb_results),
        "adb_results": adb_results,
        "adb_errors": adb_errors,
        "db_assignments_cleared": True,
        "message": (
            "تم إلغاء القيود عبر ADB وتنظيف قاعدة البيانات — جاهز للنشر الجديد"
            if attached else
            "الجهاز غير متصل — تم تنظيف قاعدة البيانات فقط"
        ),
    }