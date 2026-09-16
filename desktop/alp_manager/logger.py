# -*- coding: utf-8 -*-
"""Tiny structured runtime logger for the ALP Manager desktop app.

The open-console model means the app starts straight into the dashboard with
no terminal behind it, so an uncaught exception would otherwise be a silent
close with nothing to read. This module:

  * appends structured events to  %LOCALAPPDATA%\\ALPManager\\logs\\alp.log
  * writes any startup crash to  %LOCALAPPDATA%\\ALPManager\\logs\\startup-error.log

It NEVER logs secrets: callers pass event names, device ids and outcomes only.
"""
from __future__ import annotations

import os
import time


def log_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "ALPManager", "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _safe(obj) -> str:
    if isinstance(obj, (dict, list)):
        try:
            import json
            return json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return str(obj)
    return str(obj)


def log_event(tag: str, message: str = "", level: str = "INFO", **data) -> None:
    """Append `tag message k=v ...` to alp.log. Never passed a secret."""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        fields = " ".join(f"{k}={_safe(v)}" for k, v in data.items() if v not in (None, ""))
        line = f"{ts} [{level}] {tag} {message}".rstrip()
        if fields:
            line += " | " + fields
        with open(os.path.join(log_dir(), "alp.log"), "a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except Exception:  # noqa: BLE001 — logging must never crash the app
        pass


def log_error(tag: str, exc: BaseException, message: str = "", **data) -> None:
    try:
        log_event(tag, message or str(exc), level="ERROR", **data)
    except Exception:  # noqa: BLE001
        pass


def log_startup_error(exc: BaseException, traceback_text: str = "") -> None:
    """Record a startup crash with a full traceback for the operator."""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(log_dir(), "startup-error.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {ts} =====\n")
            fh.write(f"{type(exc).__name__}: {exc}\n")
            if traceback_text:
                fh.write(traceback_text + "\n")
    except Exception:  # noqa: BLE001
        pass