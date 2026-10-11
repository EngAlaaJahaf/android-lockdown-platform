-- Migration 014: per-profile passcode-recovery attempts threshold.
--
-- The admin decides after how many wrong lock-screen attempts the handset
-- arms its offline recovery challenge (NULL = feature off). The agent
-- counts DeviceAdminReceiver.onPasswordFailed callbacks against this number
-- and, once armed, accepts the console-derived offline code (same HMAC
-- formula as the emergency codes, purpose "reset_password") to open the
-- system set-new-password screen. No wipe is ever involved.
PRAGMA foreign_keys = ON;
BEGIN;

ALTER TABLE policies ADD COLUMN recovery_attempts INTEGER NULL;

COMMIT;
