-- Migration 008: approval_confirmations — named human confirmations for the
-- approval gate (dual rule = two distinct named confirmations for destructive
-- ops). Replaces the old MFA/TOTP approver factor.
PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE IF NOT EXISTS approval_confirmations (
    id            INTEGER PRIMARY KEY,
    approval_id   TEXT NOT NULL REFERENCES approvals(approval_id),
    seq           INTEGER NOT NULL,
    approver_name TEXT NOT NULL,
    confirmed_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (approval_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_approval_confirmations ON approval_confirmations(approval_id);

COMMIT;