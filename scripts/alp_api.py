"""PHASE 2 launcher: `python scripts/alp_api.py [--host H] [--port P]`."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
for sub in ("policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters"):
    sys.path.insert(0, os.path.join(ROOT, sub))

import backend.api.server as server  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(prog="alp_api")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    args, _ = p.parse_known_args()
    if args.host:
        os.environ["ALP_API_HOST"] = args.host
    if args.port:
        os.environ["ALP_API_PORT"] = str(args.port)
    server.main()


if __name__ == "__main__":
    main()