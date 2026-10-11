-- Migration 010: profile (policy) draft lifecycle.
--
-- The ManageEngine console flow is: Create Profile -> edit restrictions -> Save
-- (stays DRAFT) -> Publish. Before this migration `policies` had no lifecycle
-- bookkeeping: `create_custom_policy()` wrote status='ACTIVE' on the very first
-- save, so there was no honest "draft exists but was never published" state, and
-- no column to show the description / who touched it last / when it went live.
--
-- status vocabulary is already enforced by the policies CHECK constraint:
--   DRAFT | REVIEW | ACTIVE | RETIRED | REJECTED
--
-- DRAFT is deliberately NOT associatable to a group (groups.associate_profiles
-- refuses it), so an unfinished profile can never reach a device by accident.
PRAGMA foreign_keys = ON;
BEGIN;

ALTER TABLE policies ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE policies ADD COLUMN updated_at   TEXT;
ALTER TABLE policies ADD COLUMN published_at TEXT;
ALTER TABLE policies ADD COLUMN published_by TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_policies_status ON policies(status);

COMMIT;