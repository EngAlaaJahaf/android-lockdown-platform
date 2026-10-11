"""Tests for the backup bundle builder (backend.backup)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backend.backup import BACKUP_PATTERN, create_backup  # noqa: E402


def _build_db(path: str):
    c = sqlite3.connect(path)
    c.executescript(
        """CREATE TABLE devices(id INTEGER PRIMARY KEY, device_id TEXT, serial TEXT);
           CREATE TABLE policies(id INTEGER PRIMARY KEY, policy_id TEXT, status TEXT);
           CREATE TABLE recovery_credentials(id INTEGER PRIMARY KEY, device_id TEXT, revoked INTEGER);
           INSERT INTO devices(device_id,serial) VALUES ('DEV-1','LT1111'),('DEV-2','LT2222');
           INSERT INTO policies(policy_id,status) VALUES ('POL-1','ACTIVE');
           INSERT INTO recovery_credentials(device_id,revoked) VALUES ('DEV-1',0);""")
    c.commit()
    c.close()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


class BackupBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alp_backup_test_")
        self.db_path = os.path.join(self.tmp, "alp.db")
        _build_db(self.db_path)
        with open(os.path.join(self.tmp, "vault.key"), "wb") as fh:
            fh.write(b"wrapped-root-key-material")
        self.out_dir = os.path.join(self.tmp, "backups")

    def _bundle_files(self):
        return sorted(
            BACKUP_PATTERN.sub("", os.path.basename(f))
            for f in os.listdir(self.out_dir)
            if BACKUP_PATTERN.match(os.path.basename(f)))

    def test_backup_bundle_parts(self):
        out = create_backup(self.db_path, self.out_dir, keep=8)
        self.assertTrue(out["ok"])
        self.assertEqual(out["integrity"], "ok")
        self.assertTrue(out["vault_copied"])
        self.assertEqual(out["counts"], {"devices": 2, "policies": 1,
                                         "recovery_credentials": 1})

        db_bak = os.path.join(self.out_dir, out["db"])
        self.assertTrue(os.path.isfile(db_bak))
        self.assertEqual(_sha256(db_bak), out["db_sha256"])

        pairs = set()
        for name in os.listdir(self.out_dir):
            m = BACKUP_PATTERN.match(name)
            if m:
                stamp = m.group(1) if m.group(2) is None else f"{m.group(1)}-{m.group(2)}"
                pairs.add((stamp, m.group(3)))
        stamps = sorted({p[0] for p in pairs})
        self.assertEqual(len(stamps), 1)
        suffix = os.path.splitext(out["db"])[1]
        self.assertEqual(suffix, ".db")
        names = set(os.listdir(self.out_dir))
        self.assertIn(f"{stamps[0]}-.key", names)
        self.assertIn(f"{stamps[0]}-manifest.json", names)

        with open(os.path.join(self.out_dir,
                               f"{stamps[0]}-manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["db_integrity"], "ok")
        self.assertEqual(manifest["artifacts"][0]["sha256"], out["db_sha256"])

    def test_backup_snapshot_holds_rows(self):
        out = create_backup(self.db_path, self.out_dir, keep=8)
        snap = sqlite3.connect(os.path.join(self.out_dir, out["db"]))
        self.assertEqual(snap.execute("SELECT COUNT(*) FROM devices").fetchone()[0], 2)
        snap.close()

    def test_missing_vault_is_honest(self):
        os.remove(os.path.join(self.tmp, "vault.key"))
        out = create_backup(self.db_path, self.out_dir, keep=8)
        self.assertTrue(out["ok"])
        self.assertFalse(out["vault_copied"])

    def test_prune_keeps_only_newest(self):
        for _ in range(3):
            create_backup(self.db_path, self.out_dir, keep=1)
        stamps = set()
        for name in os.listdir(self.out_dir):
            m = BACKUP_PATTERN.match(name)
            if m:
                stamps.add(m.group(1))
        self.assertEqual(len(stamps), 1)

    def test_refuses_corrupt_db(self):
        with open(self.db_path, "wb") as fh:
            fh.write(b"this is definitely not a sqlite database")
        with self.assertRaises(RuntimeError):
            create_backup(self.db_path, self.out_dir, keep=8)
        self.assertFalse(os.path.isdir(self.out_dir))


if __name__ == "__main__":
    unittest.main()