-- Migration 011: profile version lineage (edit a published profile safely).
--
-- An ACTIVE profile must never be mutated in place: groups point at it and
-- devices have already applied it, so rewriting its requirements would silently
-- change deployed reality with no audit trail. Instead the console edits a
-- published profile by creating a new DRAFT *revision* that shares a `root_id`
-- with its predecessor. Publishing the revision supersedes the previous ACTIVE
-- version of the same lineage (it becomes RETIRED) and the group associations
-- move to the new revision, which then honestly reads as not-yet-deployed until
-- the next deploy run.
--
-- `root_id` is the lineage key: the policy_id of the first version. Rows that
-- predate versioning are their own root. A partial unique index allows only one
-- ACTIVE version per lineage while leaving DRAFT/REVIEW/RETIRED history free.
PRAGMA foreign_keys = ON;
BEGIN;

ALTER TABLE policies ADD COLUMN root_id TEXT;

UPDATE policies SET root_id = policy_id
 WHERE root_id IS NULL OR root_id = '';

CREATE INDEX IF NOT EXISTS idx_policies_root ON policies(root_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_policies_root_active
    ON policies(root_id) WHERE status = 'ACTIVE';

COMMIT;
