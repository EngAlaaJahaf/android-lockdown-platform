"""Append-only audit with SHA-256 hash-chaining (§31/§52, EXECUTE §52).

Each entry stores:
  prev_hash — the previous entry's OWN hash (tamper-evidence link)
  hash      — sha256(prev_hash + canonical fields of THIS entry)

Verification walks the chain and reports any broken link or modified row.
No secrets/tokens/keys are ever written into audit payloads (guard enforced).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Optional

from .db import connect
from .config import AUDIT_CHAIN_SALT

FORBIDDEN_FIELDS = ("password", "secret", "token", "private_key", "signing_key",
                    "mfa", "recovery_key", "credential", "nonce", "command_signature")


class AuditLog:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def _redact(self, data: dict) -> dict:
        for k in list(data.keys()):
            kl = k.lower()
            if any(b in kl for b in FORBIDDEN_FIELDS):
                data[k] = "[REDACTED]"
        return data

    def _canonical(self, row: dict) -> str:
        copy = {k: v for k, v in row.items()
                if k not in ("id", "prev_hash", "hash")}
        return json.dumps(copy, sort_keys=True, ensure_ascii=False, default=str)

    def record(self, actor: str, role: str, action: str, device_id: str = "",
               previous_state: str = "", new_state: str = "", reason: str = "",
               approval_id: str = "", result: str = "", evidence_ref: str = "",
               error: str = "", extra: Optional[dict] = None) -> str:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        entry_id = "AUD-" + uuid.uuid4().hex[:12].upper()
        row = {
            "entry_id": entry_id, "actor": actor, "role": role, "action": action,
            "device_id": device_id, "previous_state": previous_state,
            "new_state": new_state, "reason": reason, "approval_id": approval_id,
            "result": result, "evidence_ref": evidence_ref, "error": error,
            "ip": (extra or {}).get("ip", ""), "created_at": now,
        }
        row = self._redact(row)
        prev_hash = self._last_hash()
        canonical = self._canonical(row)
        own_hash = hashlib.sha256(
            (prev_hash + canonical + AUDIT_CHAIN_SALT).encode("utf-8")).hexdigest()
        payload = dict(row)
        payload["prev_hash"] = prev_hash
        payload["hash"] = own_hash
        with connect(self.db_path) as c:
            c.execute(
                """INSERT INTO audit_logs
                   (entry_id, actor, role, action, device_id, previous_state,
                    new_state, reason, approval_id, result, evidence_ref, error,
                    ip, created_at, prev_hash, hash)
                   VALUES (:entry_id,:actor,:role,:action,:device_id,:previous_state,
                           :new_state,:reason,:approval_id,:result,:evidence_ref,:error,
                           :ip,:created_at,:prev_hash,:hash)""", payload)
        return entry_id

    def _last_hash(self) -> str:
        """Hash of the newest chain link. Legacy/unhashed rows are skipped so a
        pre-existing NULL never poisons every subsequent entry with a TypeError."""
        with connect(self.db_path) as c:
            r = c.execute("SELECT hash FROM audit_logs WHERE hash IS NOT NULL "
                          "AND hash <> '' ORDER BY rowid DESC LIMIT 1").fetchone()
            return r["hash"] if r and r["hash"] else "GENESIS"

    def tamper_check(self) -> dict:
        """Walk the chain; report broken links and modified rows."""
        with connect(self.db_path) as c:
            rows = c.execute("SELECT * FROM audit_logs ORDER BY rowid ASC").fetchall()
        broken = []
        unhashed = []
        prev_own = "GENESIS"
        for r in rows:
            if not r["hash"]:
                unhashed.append(r["entry_id"])
                continue
            if r["prev_hash"] != prev_own:
                broken.append(f"{r['entry_id']}: prev pointer mismatch")
            recomputed = hashlib.sha256(
                (r["prev_hash"] + self._canonical(dict(r)) + AUDIT_CHAIN_SALT).encode()).hexdigest()
            if recomputed != r["hash"]:
                broken.append(f"{r['entry_id']}: row modified")
            prev_own = r["hash"]
        return {"links": len(rows) - len(unhashed), "broken": len(broken),
                "detail": broken, "unhashed_legacy": unhashed}

    def tail(self, limit: int = 50) -> list:
        with connect(self.db_path) as c:
            rows = c.execute(
                "SELECT entry_id,actor,role,action,device_id,result,created_at "
                "FROM audit_logs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]