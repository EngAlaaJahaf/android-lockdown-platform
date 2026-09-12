"""Database layer (SQLite, stdlib). Paths from config; schema in /database/schema.sql.

Provides Connection helpers that enforce PRAGMA foreign_keys, WAL, and safe row
factories. Migrations 001/002 are applied automatically on first boot.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Optional

from .config import DBPATH, SCHEMA_SQL, MIGRATIONS_DIR

_lock = threading.Lock()


def _resolve_path(explicit: Optional[str] = None) -> str:
    """Canonical default DB path: explicit arg wins, then the ALP_DB env var,
    then the module-level default. ALP_DB stays authoritative so components or
    tests that re-point config.DBPATH / db.DBPATH at runtime never leak a stale
    store into sibling callers."""
    if explicit:
        return explicit
    return os.environ.get("ALP_DB") or DBPATH


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    db_path = _resolve_path(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrated() -> bool:
    with connect() as c:
        try:
            c.execute("SELECT 1 FROM roles LIMIT 1")
            return True
        except sqlite3.Error:
            return False


def run_migrations(db_path: Optional[str] = None) -> list[str]:
    """Apply schema.sql + migrations/*.sql idempotently. Returns applied files."""
    applied = []
    db_path = _resolve_path(db_path)
    with _lock:
        with connect(db_path) as c:
            c.executescript(_read(SCHEMA_SQL))
            applied.append(os.path.basename(SCHEMA_SQL))
            for name in sorted(os.listdir(MIGRATIONS_DIR)):
                if not name.endswith(".sql"):
                    continue
                path = os.path.join(MIGRATIONS_DIR, name)
                marker = "_migrated_" + name.replace(".", "_")
                have = c.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (marker,)).fetchone()
                if have:
                    continue
                c.executescript(_read(path))
                c.execute(f"CREATE TABLE IF NOT EXISTS {marker} (id INTEGER PRIMARY KEY)")
                applied.append(name)
    return applied


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()