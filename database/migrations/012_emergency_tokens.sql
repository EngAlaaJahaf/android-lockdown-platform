-- Migration 012: offline emergency uninstall tokens.
--
-- If an admin pushes a channel-killing restriction by mistake (or any bug
-- orphans a phone), USB delivery of CLEAR/WITHDRAW envelopes is gone. The way
-- back that needs no cable is a secret the phone holder types into the agent
-- itself (opened with the dialer secret code): the console issues a
-- high-entropy one-time token NOW, shows it ONCE, and stores only its hash.
-- The agent carries the same hash (provisioned earlier over USB inside a
-- signed envelope) and verifies locally: match -> full local rollback +
-- Device-Owner self-withdraw + uninstall prompt. No network, no USB.
--
-- Single-use on the device, time-boxed here; revocation only bites before
-- provisioning (after that the device is offline by definition, so expiry is
-- the bound). Plaintext is never stored anywhere.
PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE IF NOT EXISTS emergency_tokens (
    id            INTEGER PRIMARY KEY,
    token_id      TEXT NOT NULL UNIQUE,   -- public handle, e.g. ET-9f3ac2e1
    device_id     TEXT NOT NULL,          -- console device_id (AVD-…)
    token_sha256  TEXT NOT NULL,          -- hex of SHA256(token); the token itself never lands here
    label         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL DEFAULT '',
    expires_at    TEXT NOT NULL,
    used_at       TEXT,                   -- set on first successful verify (single use)
    revoked_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_emergency_tokens_device
    ON emergency_tokens(device_id);

COMMIT;
