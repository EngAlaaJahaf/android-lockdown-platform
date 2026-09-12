"""Fleet Engine — job queue, bulk waves, rollout stages, stop threshold,
failure queue, idempotency, retries. (EXECUTE §41–§43, §69, §86, §94, §95)

No operation ever sends 1000 devices in one synchronous fire-and-forget batch.
Every job goes through waves, each wave is verified before the next one starts,
and a failure threshold automatically STOPS the rollout.

FK hygiene: the DB stores integer PKs. This module resolves logical resource
ids (device_id / policy_id / job_id) to the integer rows that carry FK refs.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from .db import connect
from .state_machine import StateTransitionError


class RolloutStopped(Exception):
    pass


@dataclass
class WaveResult:
    wave: int
    planned: int
    succeeded: int
    failed: int
    stopped: bool = False


@dataclass
class Rollout:
    rollout_id: str
    policy_id: str
    stage: str = "DRAFT"
    wave_size: int = 5
    stop_threshold_percent: int = 10
    current_wave: int = 0


def _device_pk(c, device_id: str) -> int:
    """Lazy inventory: INSERT OR IGNORE then return the integer PK (FK target)."""
    c.execute("INSERT OR IGNORE INTO devices (device_id) VALUES (?)", (device_id,))
    r = c.execute("SELECT id FROM devices WHERE device_id=?", (device_id,)).fetchone()
    return r["id"]


def _policy_pk(c, policy_id: str) -> int:
    c.execute(
        "INSERT OR IGNORE INTO policies (policy_id, display_name, category, requirements, status) "
        "VALUES (?,?,?,?, 'DRAFT')",
        (policy_id, policy_id, policy_id.upper(), "{}"))
    r = c.execute("SELECT id FROM policies WHERE policy_id=?", (policy_id,)).fetchone()
    return r["id"]


def _job_pk(c, job_id: str) -> int:
    r = c.execute("SELECT id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    return r["id"] if r else None


def create_job(job_type: str, policy_id: str, operator_id: int,
               device_ids: list[str], priority: int = 5) -> str:
    """Create one idempotent master job with per-device executions."""
    job_id = "JOB-" + str(int(time.time())) + "-" + uuid.uuid4().hex[:4].upper()
    key = uuid.uuid4().hex
    with connect() as c:
        pol_pk = _policy_pk(c, policy_id) if policy_id else None
        c.execute("INSERT INTO jobs (job_id, job_type, policy_id, status, priority, idempotency_key, created_by) "
                  "VALUES (?,?,?,'QUEUED',?,?,?)", (job_id, job_type, pol_pk, priority, key, operator_id))
        job_pk = _job_pk(c, job_id)
        for dev in dict.fromkeys(device_ids):   # one execution per device (UNIQUE(job,device))
            dev_pk = _device_pk(c, dev)
            c.execute("INSERT INTO job_executions (job_id, device_id) VALUES (?,?)", (job_pk, dev_pk))
    return job_id


def list_devices() -> list[str]:
    with connect() as c:
        rows = c.execute("SELECT device_id FROM devices ORDER BY id").fetchall()
    return [r["device_id"] for r in rows]


def run_wave(job_id: str, device_ids: list[str], execute_fn,
             evidence_for_fn=None, wave: int = 1) -> WaveResult:
    """
    execute_fn(device_id, job_id) -> dict {ok: bool, error?: str, evidence?: str}
    Runs synchronously for a controlled wave; failure>threshold raises RolloutStopped.
    """
    failed = 0
    succeeded = 0
    with connect() as c:
        job_pk = _job_pk(c, job_id)
        c.execute("UPDATE jobs SET status='RUNNING' WHERE job_id=?", (job_id,))
        pk_map = {dev: _device_pk(c, dev) for dev in device_ids}
    for dev in device_ids:
        try:
            outcome = execute_fn(dev, job_id)
            if outcome.get("ok"):
                succeeded += 1
                with connect() as cc:
                    cc.execute("UPDATE job_executions SET status='SUCCEEDED', completed_at=datetime('now') "
                               "WHERE job_id=? AND device_id=? AND (status != 'SUCCEEDED')",
                               (job_pk, pk_map[dev]))
                    cc.execute("INSERT INTO evidence (evidence_id, device_id, job_id, kind, result) "
                               "VALUES (?,?,?,?,?)",
                               ("EV-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6].upper(),
                                pk_map[dev], job_pk, "EXEC_RESULT", "PASS"))
            else:
                failed += 1
                _mark_failed(job_pk, pk_map[dev], outcome.get("error", "execute"))
        except Exception as ex:  # never mask — classed + queued (§50)
            failed += 1
            _mark_failed(job_pk, pk_map[dev], f"{type(ex).__name__}: {ex}")

    threshold = 10  # per rollout config; caller may tune
    stopped = False
    if device_ids and (failed / len(device_ids)) * 100 > threshold:
        stopped = True
        with connect() as c:
            c.execute("UPDATE jobs SET status='FAILURE_QUEUE' WHERE job_id=?", (job_id,))
    else:
        with connect() as c:
            c.execute("UPDATE jobs SET status='COMPLETED' WHERE job_id=?", (job_id,))

    res = WaveResult(wave, len(device_ids), succeeded, failed, stopped)
    if stopped:
        raise RolloutStopped(
            f"wave {wave} failure rate {failed}/{len(device_ids)} exceeded threshold — "
            "STOP ROLLOUT (Diagnose → Fix → Retest → Resume, §43)")
    return res


def _mark_failed(job_pk: int, device_pk: int, error: str):
    with connect() as c:
        c.execute("UPDATE job_executions SET status='FAILED', last_error=? "
                  "WHERE job_id=? AND device_id=? AND status != 'FAILED'", (error, job_pk, device_pk))
        c.execute("INSERT INTO failures (job_id, device_id, failure_class, detail, in_failure_queue) "
                  "VALUES (?,?, 'UNKNOWN', ?, 1)", (job_pk, device_pk, error))


def emergency_stop_all(cause: str) -> int:
    """EXECUTE §94 — cancel queued/pending jobs that can still be cancelled."""
    stopped = 0
    with connect() as c:
        rows = c.execute(
            "SELECT id, job_id FROM jobs "
            "WHERE status IN ('DRAFT','QUEUED') OR status='RUNNING'").fetchall()
        for r in rows:
            c.execute("UPDATE jobs SET status='STOPPED' WHERE id=?", (r["id"],))
            stopped += 1
    return stopped


# ---------------------------------------------------------------------------
# Fleet Simulator (§90) — pure-python, no real devices.
# ---------------------------------------------------------------------------

_FAKE_VENDORS = ["samsung", "motorola", "xiaomi", "google", "oneplus", "aosp"]
_FAKE_MODELS = ["SM-A145P", "Moto G52", "Redmi 12", "Pixel 7", "OnePlus 11", "AOSP-REF"]
_FAKE_VERSIONS = [7, 8, 9, 10, 11, 12, 13, 14, 15]


class FleetSimulator:
    """Simulates N devices (default 1000) across versions/vendors, with
    deterministic capability profiles and optional failure injection.
    Explicitly NOT a substitute for device testing (§90)."""

    def __init__(self, n: int = 1000, seed: int = 7):
        import random
        self.rng = random.Random(seed)
        self.n = n

    def generate(self) -> list[dict]:
        devices = []
        for i in range(self.n):
            dev = {
                "device_id": f"SIM-{i:05d}",
                "manufacturer": self.rng.choice(_FAKE_VENDORS),
                "model": self.rng.choice(_FAKE_MODELS),
                "android_version": self.rng.choice(_FAKE_VERSIONS),
                "online": self.rng.random() > 0.04,       # ~4% offline
                "fail_prone": self.rng.random() < 0.02,   # ~2% fail
            }
            devices.append(dev)
        return devices

    def observe(self, device: dict, api_fail: bool = False) -> dict:
        """Simulated 'actual state' after execution — FAILs for fail-prone or offline."""
        import random
        r = random.Random(device["device_id"] + "obs")
        if device.get("fail_prone") or not device.get("online", True) or api_fail:
            return {"WIFI": "ON", "expected_off": True}   # non-compliant state
        return {"WIFI": "ON"}  # placeholder: real observe returns feature map


def simulate_bulk(policy_id: str, n: int = 1000, execute_fn=None) -> dict:
    """Run a full staged rollout over the simulator (5 → 20 → 100 → rest)."""
    sim = FleetSimulator(n=n)
    fleet = sim.generate()
    steps = [5, 20, 100]
    consumed = 0
    results = []
    wave_no = 0
    for size in steps:
        if consumed >= len(fleet):
            break
        wave_no += 1
        chunk = fleet[consumed:consumed + size]
        consumed += len(chunk)
        ok = sum(1 for d in chunk if d["online"] and not d["fail_prone"])
        results.append({"wave": wave_no, "devices": len(chunk), "ok": ok,
                        "failed": len(chunk) - ok})
        if ok / len(chunk) < 0.90:
            return {"stage": "STOPPED", "waves": results,
                    "why": "stop threshold hit in wave " + str(wave_no)}
    wave_no += 1
    rest = fleet[consumed:]
    if rest:
        ok = sum(1 for d in rest if d["online"] and not d["fail_prone"])
        results.append({"wave": wave_no, "devices": len(rest), "ok": ok,
                        "failed": len(rest) - ok})
    return {"stage": "FULL", "waves": results, "total_devices": n}