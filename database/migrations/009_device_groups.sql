-- Migration 009: device groups + group->profile assignment + deploy status.
--
-- Mirrors the ManageEngine MDM Plus 11.2.2508.01 data model (see
-- design-ref/mdm-plus-groups-profiles.txt and docs/reference/memdm/):
--   customgroup                -> device_groups
--   customgroupextn            -> (merged into device_groups: created_by/...)
--   customgroupmemberrel       -> device_group_members
--   grouptoprofilehistory      -> group_profile_assignments
--   groupcollnstatussummary    -> group_deploy_status
--   groupactionhistory         -> group_action_history
--   mdmresourcetoprofilehistory-> assignments (already in schema.sql, until now unused)
--
-- A ManageEngine "Profile" is a bundle of restrictions; in ALP that bundle is a
-- `policies` row, so group_profile_assignments.policy_id references policies(id).
PRAGMA foreign_keys = ON;
BEGIN;

-- ---------------------------------------------------------------- device group
CREATE TABLE IF NOT EXISTS device_groups (
    id              INTEGER PRIMARY KEY,
    group_key       TEXT NOT NULL UNIQUE,   -- stable slug used by the UI/URL
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    membership_type TEXT NOT NULL DEFAULT 'STATIC'
                    CHECK (membership_type IN ('STATIC','DYNAMIC')),
    platform_type   TEXT NOT NULL DEFAULT 'ANDROID',
    is_editable     INTEGER NOT NULL DEFAULT 1 CHECK (is_editable IN (0,1)),
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    modified_by     TEXT NOT NULL DEFAULT '',
    modified_at     TEXT NOT NULL DEFAULT (datetime('now')),
    -- DYNAMIC groups are recognised by the UI but the criteria engine is not
    -- implemented yet; membership for them stays empty and is reported as such
    -- rather than silently pretending a rule evaluated.
    criteria_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_device_groups_name ON device_groups(name);

-- ------------------------------------------------------------------ membership
CREATE TABLE IF NOT EXISTS device_group_members (
    id          INTEGER PRIMARY KEY,
    group_id    INTEGER NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
    device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    added_by    TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (group_id, device_id)
);
CREATE INDEX IF NOT EXISTS idx_dgm_device ON device_group_members(device_id);

-- ------------------------------------------------- group -> profile assignment
CREATE TABLE IF NOT EXISTS group_profile_assignments (
    id                   INTEGER PRIMARY KEY,
    group_id             INTEGER NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
    policy_id            INTEGER NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    distributed_version  INTEGER,          -- policy.version at association time
    assigned_by          TEXT NOT NULL DEFAULT '',
    assigned_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_modified_by     TEXT NOT NULL DEFAULT '',
    last_modified_at     TEXT NOT NULL DEFAULT (datetime('now')),
    remarks              TEXT NOT NULL DEFAULT '',
    UNIQUE (group_id, policy_id)
);
CREATE INDEX IF NOT EXISTS idx_gpa_group ON group_profile_assignments(group_id);
CREATE INDEX IF NOT EXISTS idx_gpa_policy ON group_profile_assignments(policy_id);

-- ------------------------------------------------------ deploy status summary
-- Mirrors memdm groupcollnstatussummary. Counters are recomputed from real rows
-- on every read; never written optimistically. not_applicable is filled from the
-- honest tier split so a partially-enforceable profile cannot look fully green.
CREATE TABLE IF NOT EXISTS group_deploy_status (
    id                   INTEGER PRIMARY KEY,
    assignment_id        INTEGER NOT NULL REFERENCES group_profile_assignments(id)
                         ON DELETE CASCADE,
    total_target_count   INTEGER NOT NULL DEFAULT 0,
    yet_to_apply_count   INTEGER NOT NULL DEFAULT 0,
    success_count        INTEGER NOT NULL DEFAULT 0,
    failed_count         INTEGER NOT NULL DEFAULT 0,
    not_applicable_count INTEGER NOT NULL DEFAULT 0,
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (assignment_id)
);

-- ------------------------------------------------------------- action history
CREATE TABLE IF NOT EXISTS group_action_history (
    id              INTEGER PRIMARY KEY,
    group_action_id TEXT NOT NULL UNIQUE,
    group_id        INTEGER NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
    action_id       TEXT NOT NULL,          -- ASSOCIATE_PROFILE|APPLY_PROFILE|...
    reason_message  TEXT NOT NULL DEFAULT '',
    action_status   TEXT NOT NULL DEFAULT 'INITIATED'
                    CHECK (action_status IN ('INITIATED','INPROGRESS','COMPLETED',
                                             'PARTIAL','FAILED')),
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    initiated_by    TEXT NOT NULL DEFAULT '',
    initiated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_modified_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_gah_group ON group_action_history(group_id);

COMMIT;