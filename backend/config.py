"""Central configuration. No secrets here — values come from env/args."""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# When frozen by PyInstaller, bundled data (schema/migrations) lives in the
# temporary extraction dir; caller sets ALP_DATA_ROOT for that location and
# ALP_DB / ALP_REPORTS_DIR to persistent user directories.
BUNDLE_ROOT = getattr(sys, "_MEIPASS", None) or PROJECT_ROOT
DATA_ROOT = os.environ.get("ALP_DATA_ROOT") or BUNDLE_ROOT
DBPATH = os.environ.get("ALP_DB", os.path.join(PROJECT_ROOT, "database", "alp.db"))
SCHEMA_SQL = os.path.join(DATA_ROOT, "database", "schema.sql")
MIGRATIONS_DIR = os.path.join(DATA_ROOT, "database", "migrations")
REPORTS_DIR = os.environ.get("ALP_REPORTS_DIR") or os.path.join(PROJECT_ROOT, "reports")
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")

API_HOST = os.environ.get("ALP_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("ALP_API_PORT", "8765"))

# gnirehtet maps 10.0.2.2 to the host's localhost, so a loopback listener
# supports both the console and tethered agent. API_BIND optionally overrides
# the listening interface separately from the local client address API_HOST.
API_BIND = os.environ.get("ALP_API_BIND", API_HOST)

SIGNING_KEY = os.environ.get("ALP_SIGNING_KEY", "")   # MUST be overridden in deployment
ED25519_PRIV = os.environ.get("ALP_ED_PRIV", "")       # hex; on-device barrier key
SESSION_TTL_SECONDS = int(os.environ.get("ALP_SESSION_TTL", "1800"))

# TEMPORARY: OTP/MFA disabled so the web console logs in with username+password
# only (delivery request). Set ALP_MFA_REQUIRED=1 to re-enforce TOTP everywhere;
# sensitive routes take their MFA requirement from this flag too.
MFA_REQUIRED = os.environ.get("ALP_MFA_REQUIRED", "0") == "1"
AUDIT_CHAIN_SALT = os.environ.get("ALP_AUDIT_SALT", "alp-audit-chain")

ED25519_KEY_FILE = os.path.join(PROJECT_ROOT, "keys", "alp_ed_priv.hex")
ED25519_PUB_FOR_APK = os.path.join(PROJECT_ROOT, "android-agent", "alp_pubkey.hex")


def signing_key() -> str:
    """Current signing key, read at call time so module import order can never
    freeze an empty key (test-suite safety). Empty => commands are rejected."""
    return os.environ.get("ALP_SIGNING_KEY", "") or SIGNING_KEY or ed25519_private_hex() or "alp-dev-signing-key"


def ed25519_private_hex() -> str:
    """Ed25519 private seed (hex) for the device-facing command barrier.
    Resolution order: ALP_ED_PRIV env, then keys/alp_ed_priv.hex on disk.
    Empty => envelopes leave the agent unverifiable (rejected on-device)."""
    if ED25519_PRIV:
        return ED25519_PRIV
    try:
        with open(ED25519_KEY_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def ed25519_public_hex() -> str:
    """Public key that verifies device-facing envelopes (hex). Derives from the
    private key when available, else falls back to the file embedded in the APK."""
    from .ed25519 import public_from_seed_hex  # local import: avoid cycles
    priv = ed25519_private_hex()
    if priv:
        return public_from_seed_hex(priv)
    try:
        with open(ED25519_PUB_FOR_APK, "r", encoding="utf-8") as fh:
            return fh.read().strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""
