-- Migration 013: purpose-scoped emergency tokens.
--
-- Like the reference "Device Access Recovery Key" (unlock / pause kiosk /
-- revoke management), one token must not open every door: a token minted for
-- lifting restrictions must never be able to withdraw management, and vice
-- versa. The agent enforces the scope offline together with the hash check.
PRAGMA foreign_keys = ON;
BEGIN;

ALTER TABLE emergency_tokens ADD COLUMN purpose TEXT NOT NULL
    DEFAULT 'withdraw_uninstall';

COMMIT;
