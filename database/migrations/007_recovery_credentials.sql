-- Migration 007: recovery_credentials — per-device system-generated recovery
-- credential table (AUTHENTICATION_AND_RECOVERY_DESIGN.html §7/§8/§16).
-- Credits the per-device possession factor for sensitive operations.
PRAGMA foreign_keys = ON;
BEGIN;

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

COMMIT;