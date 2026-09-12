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

SIGNING_KEY = os.environ.get("ALP_SIGNING_KEY", "")   # MUST be overridden in deployment
SESSION_TTL_SECONDS = int(os.environ.get("ALP_SESSION_TTL", "1800"))
AUDIT_CHAIN_SALT = os.environ.get("ALP_AUDIT_SALT", "alp-audit-chain")