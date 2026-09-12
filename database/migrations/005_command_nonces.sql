-- Migration 005: command nonces (replay protection) + device state transitions
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE IF NOT EXISTS command_nonces (
    id         INTEGER PRIMARY KEY,
    cmd_id     TEXT NOT NULL,
    nonce      TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nonce ON command_nonces(nonce);
COMMIT;