-- =============================================================================
-- ANDROID LOCKDOWN PLATFORM — Master Schema (SQLite, migration 001)
-- Doc: DATABASE_DOCUMENTATION.md (see /docs)
-- Principals: real FKs, indexes on join/hot columns, constraints (CHECK),
-- append-only audit, idempotent command keys, policy versioning with checksum.
-- =============================================================================
PRAGMA foreign_keys = ON;

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. IDENTITY / RBAC
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,            -- SUPER_ADMIN | FLEET_ADMIN | POLICY_ADMIN |
    label_ar    TEXT NOT NULL,                   -- PROVISIONING_ADMIN | RECOVERY_ADMIN | AUDITOR | OPERATOR | READ_ONLY
    description TEXT,
    is_system   INTEGER NOT NULL DEFAULT 1 CHECK (is_system IN (0,1)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS administrators (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    role_id       INTEGER NOT NULL REFERENCES roles(id),
    password_hash TEXT,                          -- argon2/bcrypt placeholder: NEVER plaintext
    mfa_secret    TEXT,                          -- TOTP secret (encrypted at rest; never logged)
    mfa_enabled   INTEGER NOT NULL DEFAULT 0 CHECK (mfa_enabled IN (0,1)),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS permissions (
    id        INTEGER PRIMARY KEY,
    role_id   INTEGER NOT NULL REFERENCES roles(id),
    operation TEXT NOT NULL,   -- VIEW|CREATE|EDIT|APPLY|BULK_APPLY|LOCK|UNLOCK|PARTIAL_UNLOCK|
                               -- MAINTENANCE|RECOVER|RESTORE|UNENROLL|REENROLL|RETIRE|
                               -- FACTORY_RESET|FIRMWARE|KEY_MANAGEMENT|AUDIT
    decision  TEXT NOT NULL CHECK (decision IN ('ALLOW','DENY','REQUIRES_APPROVAL')),
    UNIQUE (role_id, operation)
);

-- -----------------------------------------------------------------------------
-- 2. DEVICES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    id                  INTEGER PRIMARY KEY,
    device_id           TEXT NOT NULL UNIQUE,    -- logical ID (e.g. DEV-0001)
    serial              TEXT,
    manufacturer        TEXT,
    model               TEXT,
    variant             TEXT,
    build_fingerprint   TEXT,
    android_version     INTEGER,                 -- 7..15
    api_level           INTEGER,
    security_patch      TEXT,
    bootloader_state    TEXT,                    -- UNKNOWN|LOCKED|UNLOCKED
    verified_boot_state TEXT,                    -- UNKNOWN|GREEN|YELLOW|ORANGE|RED
    encryption_state    TEXT,                    -- UNKNOWN|ACTIVE|INACTIVE|UNSUPPORTED
    device_owner_state  TEXT,                    -- UNKNOWN|ACTIVE|NONE
    dpc_state           TEXT,                    -- UNKNOWN|INSTALLED|ACTIVE|NONE
    enrollment_state    TEXT NOT NULL DEFAULT 'UNMANAGED' CHECK (
        enrollment_state IN ('UNMANAGED','ENROLLMENT_PENDING','ENROLLED','COMPLIANT',
                             'NON_COMPLIANT','QUARANTINED','MAINTENANCE','RECOVERY','RETIRED')
    ),
    control_channel     TEXT NOT NULL DEFAULT 'LOCAL_ADB' CHECK (control_channel IN ('LOCAL_ADB','AMAPI','DPC_LOCAL')),
    organization        TEXT,                    -- company/OU
    user_ref            TEXT,
    is_lab              INTEGER NOT NULL DEFAULT 0 CHECK (is_lab IN (0,1)),
    is_unsupported      INTEGER NOT NULL DEFAULT 0 CHECK (is_unsupported IN (0,1)),
    unsupported_note    TEXT,
    last_seen_at        TEXT,
    last_verification_at TEXT,
    compliance_state    TEXT DEFAULT 'UNKNOWN' CHECK (compliance_state IN ('COMPLIANT','NON_COMPLIANT','PARTIAL','UNKNOWN')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_devices_model ON devices(model);
CREATE INDEX IF NOT EXISTS idx_devices_android ON devices(android_version);
CREATE INDEX IF NOT EXISTS idx_devices_state ON devices(enrollment_state);
CREATE INDEX IF NOT EXISTS idx_devices_serial ON devices(serial);

-- -----------------------------------------------------------------------------
-- 3. DEVICE PROFILES / CAPABILITIES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_profiles (
    id               INTEGER PRIMARY KEY,
    profile_key      TEXT NOT NULL UNIQUE,      -- Manufacturer|Model|Variant|Build|Android
    manufacturer     TEXT NOT NULL,
    model            TEXT NOT NULL,
    variant          TEXT,
    android_version  INTEGER NOT NULL,
    api_level        INTEGER,
    build_id         TEXT,
    firmware_source  TEXT,                       -- e.g. A145PXXS8CYB3 (evidence ref)
    source_of_record TEXT,                       -- LAB_EVIDENCE | OFFICIAL_DOC | UNKNOWN
    class_tags       TEXT NOT NULL DEFAULT 'UNKNOWN',  -- UNKNOWN|VERIFIED|AV_DEP|VENDOR_DEP|PARTIAL|NOT_FEASIBLE
    verified_at      TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_profiles_model ON device_profiles(model, android_version);

CREATE TABLE IF NOT EXISTS capabilities (
    id           INTEGER PRIMARY KEY,
    profile_id   INTEGER NOT NULL REFERENCES device_profiles(id) ON DELETE CASCADE,
    feature      TEXT NOT NULL,                 -- wifi|bluetooth|camera|location|adb|safe_boot|
                                                -- factory_reset|tethering|screenshot|usb_file|...
    capability   TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (capability IN (
        'SUPPORTED','PARTIAL','UNKNOWN','DEVICE_DEPENDENT','VENDOR_DEPENDENT',
        'ANDROID_VERSION_DEPENDENT','NOT_FEASIBLE')),
    method       TEXT,                          -- DPM_RESTRICTION|SETTINGS_GLOBAL|LOCK_TASK|KNOX|PACKAGE_CTRL|...
    evidence_ref TEXT,
    UNIQUE (profile_id, feature)
);

-- -----------------------------------------------------------------------------
-- 4. POLICIES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS policies (
    id           INTEGER PRIMARY KEY,
    policy_id    TEXT NOT NULL UNIQUE,          -- e.g. POL-PHONE_ONLY
    display_name TEXT NOT NULL,
    category     TEXT NOT NULL,                 -- CORPORATE_DEFAULT|PHONE_ONLY|FULL_LOCKDOWN|PARTIAL_LOCKDOWN|MAINTENANCE|QUARANTINE
    version      INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','REVIEW','ACTIVE','RETIRED','REJECTED')),
    checksum     TEXT,                          -- sha256 of requirements JSON (integrity)
    requirements TEXT NOT NULL,                 -- JSON: feature -> desired state
    created_by   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    changed_by   TEXT,
    change_reason TEXT,
    UNIQUE (policy_id, version)
);
CREATE INDEX IF NOT EXISTS idx_policies_status ON policies(status, category);

-- Policy requirements rows (Feature Matrix §15)
CREATE TABLE IF NOT EXISTS policy_requirements (
    id           INTEGER PRIMARY KEY,
    policy_id    INTEGER NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    feature      TEXT NOT NULL,                 -- WIFI|BLUETOOTH|MOBILE_DATA|LOCATION|CAMERA|MICROPHONE|USB|ADB|
                                                -- DEVELOPER_OPTIONS|SAFE_BOOT|FACTORY_RESET|APP_INSTALLATION|
                                                -- UNKNOWN_SOURCES|BROWSER|PLAY_STORE|HOTSPOT|TETHERING|ACCOUNTS|
                                                -- USER_MANAGEMENT|SCREEN_CAPTURE|LOCK_TASK|APPLICATIONS|CALLS|SMS|CONTACTS
    desired_state TEXT NOT NULL,                -- BLOCK|ALLOW|RESTRICT|WARN_AUDIT
    supported_state TEXT DEFAULT 'UNKNOWN',
    enforcement_method TEXT,
    verification_method TEXT,
    risk TEXT DEFAULT 'LOW' CHECK (risk IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    fallback TEXT,
    UNIQUE (policy_id, feature)
);

-- -----------------------------------------------------------------------------
-- 5. ASSIGNMENTS / SNAPSHOTS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignments (
    id            INTEGER PRIMARY KEY,
    device_id     INTEGER NOT NULL REFERENCES devices(id),
    policy_id     INTEGER NOT NULL REFERENCES policies(id),
    snapshot      TEXT NOT NULL,                -- Policy Snapshot JSON as actually applied
    applied_at    TEXT,
    verified_at   TEXT,
    verified      INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
    verify_result TEXT,                         -- PASS|FAIL|PARTIAL|UNKNOWN
    restore_point TEXT,                         -- JSON restore point (before apply)
    UNIQUE (device_id, policy_id, snapshot)
);

-- -----------------------------------------------------------------------------
-- 6. FLEET OPERATIONS: JOBS / EXECUTIONS / ROLLOUTS / FAILURES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY,
    job_id       TEXT NOT NULL UNIQUE,          -- e.g. JOB-20260111-0001
    job_type     TEXT NOT NULL,                 -- APPLY_POLICY|RESTORE|UNLOCK|PARTIAL_UNLOCK|MAINTENANCE|RECOVER|UNENROLL|REENROLL|RETIRE|FACTORY_RESET|VERIFY
    policy_id    INTEGER REFERENCES policies(id),
    status       TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('DRAFT','QUEUED','RUNNING','COMPLETED','FAILED','FAILURE_QUEUE','STOPPED','APPROVAL_REQUIRED','ROLLEDBACK')),
    priority     INTEGER NOT NULL DEFAULT 5,
    idempotency_key TEXT NOT NULL UNIQUE,       -- prevents duplicate re-issue (§49)
    created_by   INTEGER REFERENCES administrators(id),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS job_executions (
    id               INTEGER PRIMARY KEY,
    job_id           INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    device_id        INTEGER NOT NULL REFERENCES devices(id),
    wave             INTEGER,                    -- wave 1..n in rollout
    status           TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','SENT','RUNNING','SUCCEEDED','FAILED','TIMED_OUT','RETRY')),
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    nonce            TEXT,                       -- replay protection (§48)
    command_signature TEXT,
    sent_at          TEXT,
    completed_at     TEXT,
    result           TEXT,
    evidence_ref     TEXT,
    UNIQUE (job_id, device_id)
);
CREATE INDEX IF NOT EXISTS idx_exec_device ON job_executions(device_id, status);

CREATE TABLE IF NOT EXISTS rollouts (
    id          INTEGER PRIMARY KEY,
    rollout_id  TEXT NOT NULL UNIQUE,
    policy_id   INTEGER NOT NULL REFERENCES policies(id),
    stage       TEXT NOT NULL DEFAULT 'DRAFT' CHECK (stage IN ('DRAFT','VALIDATE','DRY_RUN','PILOT','VERIFY','APPROVE','STAGED','FULL','STOPPED')),
    wave_size   INTEGER NOT NULL DEFAULT 5,      -- 5→20→100→remaining (§86)
    stop_threshold_percent INTEGER NOT NULL DEFAULT 10,
    current_wave INTEGER NOT NULL DEFAULT 0,
    approved_by INTEGER REFERENCES administrators(id),
    approved_at TEXT,
    created_by  INTEGER REFERENCES administrators(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rollout_waves (
    id          INTEGER PRIMARY KEY,
    rollout_id  INTEGER NOT NULL REFERENCES rollouts(id) ON DELETE CASCADE,
    wave        INTEGER NOT NULL,
    device_count INTEGER,
    failed_count INTEGER,
    status      TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RUNNING','VERIFIED','STOPPED','COMPLETED')),
    started_at  TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS failures (
    id            INTEGER PRIMARY KEY,
    job_id        INTEGER,
    device_id     INTEGER,
    failure_class TEXT NOT NULL,                -- AUTH|CAPABILITY|TIMEOUT|NETWORK|DEVICE_STATE|UNKNOWN
    detail        TEXT,
    in_failure_queue INTEGER NOT NULL DEFAULT 1 CHECK (in_failure_queue IN (0,1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_failures_queue ON failures(in_failure_queue, created_at);

-- -----------------------------------------------------------------------------
-- 7. COMPLIANCE / EVIDENCE
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compliance (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER NOT NULL REFERENCES devices(id),
    policy_id  INTEGER NOT NULL REFERENCES policies(id),
    result     TEXT NOT NULL CHECK (result IN ('COMPLIANT','NON_COMPLIANT','PARTIAL','UNKNOWN')),
    details    TEXT,                            -- JSON per-feature diff
    checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_compliance_device ON compliance(device_id, checked_at);

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY,
    evidence_id TEXT NOT NULL UNIQUE,           -- EV-YYYYMMDD-NNN
    device_id   INTEGER,
    job_id      INTEGER,
    kind        TEXT NOT NULL,                  -- SCREENSHOT|LOG|DUMP|SIGNATURE|RESULT
    payload_ref TEXT,                           -- path or signed token; never embedded secret
    result      TEXT,
    created_by  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- 8. APPROVALS / RECOVERY / AUDIT
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approvals (
    id           INTEGER PRIMARY KEY,
    approval_id  TEXT NOT NULL UNIQUE,
    action       TEXT NOT NULL,                 -- FACTORY_RESET|RETIRE|UNLOCK|RECOVER|BULK_APPLY|FIRMWARE|UNENROLL|...
    device_id    INTEGER REFERENCES devices(id),
    scope        TEXT,                          -- single|bulk
    requester    INTEGER REFERENCES administrators(id),
    approver_1   INTEGER REFERENCES administrators(id),
    approver_2   INTEGER REFERENCES administrators(id),   -- dual rule for destructive ops
    mfa_verified INTEGER NOT NULL DEFAULT 0 CHECK (mfa_verified IN (0,1)),
    reason       TEXT,
    decision     TEXT NOT NULL CHECK (decision IN ('PENDING','APPROVED','DENIED')),
    decided_at   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_approvals_state ON approvals(decision, created_at);

CREATE TABLE IF NOT EXISTS recovery_actions (
    id             INTEGER PRIMARY KEY,
    device_id      INTEGER REFERENCES devices(id),
    action_type    TEXT NOT NULL,               -- RESTORE_PREVIOUS|RESTORE_CORPORATE_DEFAULT|PARTIAL_UNLOCK|FULL_UNLOCK|
                                                -- MAINTENANCE|RECOVERY|RE_ENROLL|UNENROLL|RETIRE
    previous_state TEXT,
    requested_state TEXT,
    reason         TEXT,
    approval_id    INTEGER REFERENCES approvals(id),
    result         TEXT,
    result_detail  TEXT,
    created_by     INTEGER REFERENCES administrators(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- 8.1 RECOVERY CREDENTIALS — one system-generated, per-device credential.
--     AUTHENTICATION_AND_RECOVERY_DESIGN.html §7/§8/§16:
--       - never shared between devices, never shown to end users;
--       - stored encrypted ONLY (AES-256-GCM); the secret itself is never
--         written in plaintext, never logged, never exported;
--       - recovery_id is the display-only handle (XXXX-XXXX).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recovery_credentials (
    device_id             TEXT NOT NULL UNIQUE REFERENCES devices(device_id),
    recovery_id           TEXT NOT NULL UNIQUE,   -- display-only "XXXX-XXXX" (never the secret)
    credential_ciphertext BLOB NOT NULL,          -- AES-256-GCM (nonce||ct||tag) of the 32-byte credential
    nonce                 BLOB NOT NULL,          -- AES-GCM nonce (12 bytes)
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    rotated_at            TEXT,
    revoked               INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_recovery_creds_device ON recovery_credentials(device_id);

-- -----------------------------------------------------------------------------
-- 8.2 APPROVAL CONFIRMATIONS — named human confirmations for the approval gate.
--     Replaces the old TOTP/MFA factor: the possession factor for sensitive
--     device operations is the per-device recovery credential (verified by the
--     caller); dual rule = two distinct named confirmations for destructive ops.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approval_confirmations (
    id            INTEGER PRIMARY KEY,
    approval_id   TEXT NOT NULL REFERENCES approvals(approval_id),
    seq           INTEGER NOT NULL,
    approver_name TEXT NOT NULL,
    confirmed_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (approval_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_approval_confirmations ON approval_confirmations(approval_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    id           INTEGER PRIMARY KEY,
    entry_id     TEXT NOT NULL UNIQUE,
    actor        TEXT NOT NULL,
    role         TEXT,
    action       TEXT NOT NULL,
    device_id    TEXT,
    previous_state TEXT,
    new_state    TEXT,
    reason       TEXT,
    approval_id  TEXT,
    result       TEXT,
    evidence_ref TEXT,
    error        TEXT,
    ip           TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    prev_hash    TEXT,                          -- hash-chain: sha256(prev_hash + row fields)
    CHECK (length(entry_id) > 0)
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor, action);

-- -----------------------------------------------------------------------------
-- 9. SEED: system roles (fixed 8 per §28)
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO roles (id, code, label_ar, description, is_system) VALUES
 (1,'SUPER_ADMIN','مدير النظام الأعلى','Full control incl. keys & governance',1),
 (2,'FLEET_ADMIN','مدير الأسطول','Fleet-wide bulk operations within policy',1),
 (3,'POLICY_ADMIN','مدير السياسات','Draft, review, version policies',1),
 (4,'PROVISIONING_ADMIN','مدير التسجيل','Enrollment / provisioning flows',1),
 (5,'RECOVERY_ADMIN','مسترد النظام','Break-glass and recovery operations',1),
 (6,'AUDITOR','مدقق','Read access to audit; cannot modify',1),
 (7,'OPERATOR','مشغل','Day-to-day apply/verify on assigned scope',1),
 (8,'READ_ONLY','واطئ فقط','Read-only viewer',1);

COMMIT;