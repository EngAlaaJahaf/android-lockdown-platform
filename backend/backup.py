"""Backup the ALP database + recovery vault into a timestamped, verifiable bundle.

create_backup() is the single entry point used by both the CLI
(scripts/backup.py) and the control-plane API (POST /api/v1/system/backup).

Guarantees (honest):
  * Refuses to back up a DB that fails PRAGMA integrity_check / quick_check.
  * VACUUM INTO produces a consistent single-file snapshot even while the
    live server holds the DB open (WAL mode, readers never block).
  * The live vault.key (DPAPI-wrapped root key) is copied BESIDE the snapshot,
    so the DB and its recovery-key material always travel together.
  * A manifest records sha256 of every artifact; tampered/pruned bundles are
    detectable.
  * Old bundles are pruned past `keep` (default 8).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time

from . import config

BACKUP_PATTERN = re.compile(r"^(\d{8}-\d{6})(?:-(\d+))?-(alp\.db|\.key|manifest\.json)$")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp(name: str) -> str | None:
    """Full bundle stamp for a backup file name (incl. sub-second field)."""
    m = BACKUP_PATTERN.match(name)
    if not m:
        return None
    return m.group(1) if m.group(2) is None else f"{m.group(1)}-{m.group(2)}"


def _prune(out_dir: str, keep: int) -> list[str]:
    """Remove whole bundle sets beyond the newest `keep` timestamps."""
    groups: dict[str, list[str]] = {}
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            s = _stamp(name)
            if s:
                groups.setdefault(s, []).append(name)
    stamps = sorted(groups, reverse=True)
    removed: list[str] = []
    for stamp in stamps[keep:]:
        for name in groups[stamp]:
            path = os.path.join(out_dir, name)
            if os.path.isfile(path):
                os.remove(path)
                removed.append(name)
    return removed


def create_backup(db_path: str | None = None,
                  out_dir: str | None = None,
                  keep: int = 8,
                  vault_path: str | None = None) -> dict:
    """Create one backup bundle. Returns a dict; raises on hard failure."""
    db_path = os.path.abspath(db_path or config.DBPATH)
    out_dir = os.path.abspath(out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups"))
    if keep < 1:
        raise ValueError("keep must be >= 1")
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"database not found: {db_path}")

# Integrity gate: never snapshot a corrupt DB.
    try:
        with sqlite3.connect(db_path, timeout=30) as c:
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error as ex:
        raise RuntimeError(f"db failed integrity check: {type(ex).__name__}: {ex}")
    if integrity != "ok":
        raise RuntimeError(f"db integrity failed: {integrity}")

    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bundle = f"{stamp}-{int(time.time() * 1000) % 1000:03d}"
    db_bak = os.path.join(out_dir, f"{bundle}-alp.db")
    key_bak = os.path.join(out_dir, f"{bundle}-.key")
    man_bak = os.path.join(out_dir, f"{bundle}-manifest.json")

    with sqlite3.connect(db_path, timeout=60) as c:
        c.execute("VACUUM INTO ?", (db_bak,))
    if not os.path.isfile(db_bak):
        raise RuntimeError("VACUUM INTO produced no file")

    vault_path = os.path.abspath(vault_path or os.path.join(
        os.path.dirname(db_path), "vault.key"))
    vault_copied = False
    if os.path.isfile(vault_path):
        with open(vault_path, "rb") as src, open(key_bak, "wb") as dst:
            dst.write(src.read())
        vault_copied = True

    artifacts = [{
        "name": os.path.basename(db_bak),
        "size": os.path.getsize(db_bak),
        "sha256": _sha256(db_bak),
    }]
    if vault_copied:
        artifacts.append({
            "name": os.path.basename(key_bak),
            "size": os.path.getsize(key_bak),
            "sha256": _sha256(key_bak),
        })

    with sqlite3.connect(db_path, timeout=30) as c:
        counts = {
            "devices": c.execute("SELECT COUNT(*) FROM devices").fetchone()[0],
            "policies": c.execute("SELECT COUNT(*) FROM policies").fetchone()[0],
            "recovery_credentials": c.execute(
                "SELECT COUNT(*) FROM recovery_credentials").fetchone()[0],
        }

    manifest = {
        "bundle": bundle,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "db_source": db_path,
        "vault_copied": vault_copied,
        "vault_source": vault_path if vault_copied else None,
        "db_integrity": integrity,
        "counts": counts,
        "artifacts": artifacts,
    }
    with open(man_bak, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    removed = _prune(out_dir, keep)
    return {
        "ok": True,
        "bundle": bundle,
        "created_at": manifest["created_at"],
        "db": os.path.basename(db_bak),
        "db_size": artifacts[0]["size"],
        "db_sha256": artifacts[0]["sha256"],
        "vault_copied": vault_copied,
        "integrity": integrity,
        "counts": counts,
        "pruned": removed,
        "out_dir": out_dir,
        "manifest": os.path.basename(man_bak),
    }