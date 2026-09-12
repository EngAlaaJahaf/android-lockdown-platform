-- Migration 006: operational mode + applied policy on devices (state machine persistence)
PRAGMA foreign_keys = ON;
BEGIN;
ALTER TABLE devices ADD COLUMN mode TEXT DEFAULT 'UNMANAGED';
ALTER TABLE devices ADD COLUMN current_policy_id TEXT;
COMMIT;