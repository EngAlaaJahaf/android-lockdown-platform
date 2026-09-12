"""Runtime path resolution for the ALP Manager desktop application.

Works in both source (python desktop/run_app.py) and frozen PyInstaller (onefile)
modes. Persistent user data (DB, session, reports, keys) lives under
%LOCALAPPDATA%\\ALPManager so that onefile re-extraction never loses state.
"""
from __future__ import annotations

import os
import sys

APP_NAME = "ALPManager"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> str:
    """Where bundled data (schema.sql, migrations) is extracted / lives."""
    return getattr(sys, "_MEIPASS", None) or project_root()


def project_root() -> str:
    """Source tree root when running from source."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def persist_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def default_db() -> str:
    if not is_frozen():
        return os.path.join(project_root(), "database", "alp.db")
    return os.path.join(persist_dir(), "alp.db")


def session_file() -> str:
    return os.path.join(persist_dir(), "session.json")


def persist_reports_dir() -> str:
    d = os.path.join(persist_dir(), "reports")
    os.makedirs(d, exist_ok=True)
    return d


def ensure_keys() -> tuple[str, str]:
    """Create (or read) a persistent HMAC signing key + audit salt. NEVER logged."""
    base = persist_dir()
    key_path = os.path.join(base, "signing.key")
    salt_path = os.path.join(base, "audit.salt")
    signing = os.environ.get("ALP_SIGNING_KEY")
    salt = os.environ.get("ALP_AUDIT_SALT")
    if not signing or signing == "suite-only-dev-key-0001":
        if not os.path.exists(key_path):
            with open(key_path, "w", encoding="utf-8") as fh:
                fh.write(os.urandom(32).hex())
        signing = open(key_path, encoding="utf-8").read().strip()
    if not salt or salt == "suite-audit-salt":
        if not os.path.exists(salt_path):
            with open(salt_path, "w", encoding="utf-8") as fh:
                fh.write(os.urandom(32).hex())
        salt = open(salt_path, encoding="utf-8").read().strip()
    return signing, salt


def apply_runtime_env() -> None:
    """Set env used by backend.config BEFORE any backend import. Idempotent."""
    if is_frozen():
        os.environ.setdefault("ALP_DATA_ROOT", bundle_root())
    os.environ.setdefault("ALP_DB", default_db())
    os.environ.setdefault("ALP_REPORTS_DIR", persist_reports_dir())
    signing, salt = ensure_keys()
    os.environ["ALP_SIGNING_KEY"] = signing
    os.environ["ALP_AUDIT_SALT"] = salt


def add_engine_paths() -> None:
    """Make the separated engine packages importable (also drives PyInstaller
    modulegraph when imported from run_app). The root itself must be on the
    path because backend/tests live directly under it; the engine dirs expose
    their nested underscore packages via their parent dir."""
    root = project_root()
    candidates = [root] + [os.path.join(root, s) for s in (
        "policy-engine", "capability-engine",
        "verification-engine", "compatibility", "vendor-adapters")]
    for p in reversed(candidates):
        if p not in sys.path:
            sys.path.insert(0, p)