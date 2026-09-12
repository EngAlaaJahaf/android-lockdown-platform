-- Migration 003: strengthen audit hash-chain (own-hash + prev-pointer)
PRAGMA foreign_keys = ON;
BEGIN;
ALTER TABLE audit_logs ADD COLUMN hash TEXT;
-- backfill: compute hashes for existing rows using stored prev_hash as seed
UPDATE audit_logs SET hash = prev_hash || '|' || entry_id WHERE hash IS NULL;
COMMIT;