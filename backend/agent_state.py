# -*- coding: utf-8 -*-
"""Read the agent's own account of what it did with the last command.

The agent writes files/state.json with the exact rows it applied, the rows it
skipped and any errors. The console must not report a profile as applied while
the handset is silently ignoring rows, so this is what tells the truth.
"""
from __future__ import annotations

import json
import os
import subprocess

from .workflows import adb, _AGENT_PACKAGE, _NO_WINDOW


def read_agent_state(serial: str, timeout: int = 20, filename: str = "state.json") -> dict:
    """{cmd_id, action, applied[], skipped[], errors[]} or {} when absent.

    `apply_result.json` is the durable record of the last policy apply; plain
    `state.json` is overwritten by later probes such as GET_STATE and so cannot
    answer "what did the policy actually enforce?".
    """
    if not serial:
        return {}
    try:
        r = subprocess.run(
            [adb(), "-s", serial, "shell", "run-as", _AGENT_PACKAGE,
             "cat", "files/" + filename],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW or 0)
    except Exception:
        return {}
    raw = (r.stdout or "").strip()
    if not raw or r.returncode != 0 or not raw.startswith("{"):
        return {}
    try:
        out = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(out, dict):
        return {}
    return out


def read_last_apply(serial: str, timeout: int = 20) -> dict:
    """The last APPLY_POLICY outcome, falling back to state.json when the
    dedicated file is missing (older agent builds)."""
    out = read_agent_state(serial, timeout, "apply_result.json")
    if out:
        return out
    out = read_agent_state(serial, timeout, "state.json")
    if out.get("action") in (None, "APPLY_POLICY"):
        return out
    return {}


def skipped_features(state: dict) -> list:
    """Feature names the agent refused, from "FEATURE:DESIRED" skip strings."""
    out = []
    for item in (state or {}).get("skipped") or []:
        text = str(item)
        out.append(text.split(":", 1)[0].strip() or text)
    return out