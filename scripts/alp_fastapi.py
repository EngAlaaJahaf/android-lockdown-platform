"""FastAPI launcher: `python scripts/alp_fastapi.py [--host H] [--port P]`."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "backend"))
for sub in ("policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters", "desktop"):
    p = os.path.join(ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import uvicorn  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(prog="alp_fastapi")
    p.add_argument("--host", default=os.environ.get("ALP_FASTAPI_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("ALP_FASTAPI_PORT", "8765")))
    p.add_argument("--reload", action="store_true", default=False)
    args, _ = p.parse_known_args()

    print(f"[ALP FastAPI] Starting server on http://{args.host}:{args.port}")
    print(f"[ALP FastAPI] Interactive API Docs: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "backend.fastapi_core.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
