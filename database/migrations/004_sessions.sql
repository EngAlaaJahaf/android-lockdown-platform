-- Migration 004: sessions (short-lived, revocable, device-bound later)
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE IF NOT EXISTS sessions (
    id       INTEGER PRIMARY KEY,
    token    TEXT NOT NULL UNIQUE,
    admin_id INTEGER NOT NULL REFERENCES administrators(id),
    revoked  INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0,1)),
    device_binding TEXT,                       -- device_id bound for sensitive ops
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
COMMIT;