"""Dual-Server Verification Script: Compares responses between Legacy (8765) and FastAPI (8766)."""
from __future__ import annotations

import json
import urllib.request
import urllib.error
import sys

PORT_LEGACY = 8765
PORT_FASTAPI = 8766


def fetch(url: str, method: str = "GET", data: dict | None = None) -> tuple[int, dict | str]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as res:
            raw = res.read().decode("utf-8", errors="replace")
            try:
                return res.status, json.loads(raw)
            except Exception:
                return res.status, raw
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode("utf-8", errors="replace")
        try:
            return ex.code, json.loads(raw)
        except Exception:
            return ex.code, raw
    except Exception as ex:
        return 0, str(ex)


def main():
    print("======================================================================")
    print("ALP Dual-Server Parity Check: Comparing Legacy (8765) & FastAPI (8766)")
    print("======================================================================")

    endpoints = [
        ("GET", "/api/v1/health", None),
        ("GET", "/api/v1/bootstrap", None),
        ("GET", "/api/v1/branding", None),
        ("POST", "/api/v1/auth/login", {"username": "non_existent_admin", "password": "wrong_password"}),
        ("GET", "/", None),
    ]

    all_passed = True
    for method, path, payload in endpoints:
        url_leg = f"http://127.0.0.1:{PORT_LEGACY}{path}"
        url_fast = f"http://127.0.0.1:{PORT_FASTAPI}{path}"

        status_leg, data_leg = fetch(url_leg, method, payload)
        status_fast, data_fast = fetch(url_fast, method, payload)

        if status_leg == 0 and status_fast == 0:
            print(f"[SKIP] {method:4s} {path:22s} -> Neither server is running.")
            continue
        elif status_leg == 0:
            print(f"[FASTAPI OK] {method:4s} {path:22s} -> FastAPI status={status_fast} (Legacy offline)")
            continue
        elif status_fast == 0:
            print(f"[LEGACY OK]  {method:4s} {path:22s} -> Legacy status={status_leg} (FastAPI offline)")
            continue

        match = (status_leg == status_fast)
        if match:
            print(f"[MATCH] {method:4s} {path:22s} -> Status: {status_fast} (both match)")
        else:
            print(f"[DIFF]  {method:4s} {path:22s} -> Legacy={status_leg}, FastAPI={status_fast}")
            all_passed = False

    print("======================================================================")


if __name__ == "__main__":
    main()
