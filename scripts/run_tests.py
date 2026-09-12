"""ALP unified test runner — inserts all module dirs into sys.path first.

Usage:
    python scripts/run_tests.py                 # full suite (unit+integration+sim)
    python scripts/run_tests.py capability      # only the capability engine tests
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for sub in ("policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters"):
    sys.path.insert(0, os.path.join(ROOT, sub))

# Isolate every backend module from the real database/alp.db regardless of
# import order: set once, before any import of backend.config.
if "ALP_DB" not in os.environ:
    os.environ["ALP_DB"] = os.path.join(tempfile.mkdtemp(prefix="alp_suite_"), "suite.db")
os.environ.setdefault("ALP_SIGNING_KEY", "suite-only-dev-key-0001")
os.environ.setdefault("ALP_AUDIT_SALT", "suite-audit-salt")

TESTS_DIR = os.path.join(ROOT, "tests")


def discover(pattern: str = "test_*.py"):
    return unittest.defaultTestLoader.discover(TESTS_DIR, pattern=pattern)


def run(filter_prefix: str = "") -> int:
    if filter_prefix:
        loader = unittest.TestLoader()
        suite = loader.discover(TESTS_DIR, pattern="test_*.py")
        suite = unittest.TestSuite(
            t for t in suite._tests if t._tests and
            any(getattr(case, "__module__", "").endswith(filter_prefix) or
                filter_prefix in type(case).__module__
                for case in iter_cases(t)))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        result = unittest.TextTestRunner(verbosity=2).run(discover())
    return 0 if result.wasSuccessful() else 1


def iter_cases(suite):
    for x in suite:
        if isinstance(x, unittest.TestSuite):
            yield from iter_cases(x)
        else:
            yield x


if __name__ == "__main__":
    argv = sys.argv[1:]
    sys.exit(run(argv[0] if argv else ""))