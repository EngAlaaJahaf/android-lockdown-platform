"""Console-side PIN provisioning for the on-device PinGuard.

Builds a SIGNED PROVISION_PIN envelope (Ed25519 private key held only on the
console side) and delivers it over the real ADB channel to
/data/local/tmp/alp_pin.json. The agent's PinGuard only provisions a pin whose
envelope passes EnvelopeGuard, so a user on the device can never set or reset
the rollback PIN themselves.
"""
from __future__ import annotations

import os
import secrets

from . import command
from .channel import adb_channel
from .config import PROJECT_ROOT, ed25519_private_hex, signing_key

DEFAULT_CHAN_DIR = os.path.join(PROJECT_ROOT, "reports", "phase1", "commands")


def provision_pin(device_id: str, pin: str = "", *,
                  serial: str = "", signing_key_: str = "",
                  chan_dir: str = "") -> dict:
    """Issue + deliver a PROVISION_PIN envelope for `device_id`.

    `pin` is auto-generated (crypto-random 6 digits) when empty; the returned
    dict carries it exactly once for the caller (console UI) to show the user.

    Returns {"pin", "envelope", "delivery"}; `delivery` follows the adb
    channel shape ({ok, action, cmd_id, staged, error?}).
    """
    os.environ.setdefault("ALP_SIGNING_KEY",
                          signing_key_ or signing_key())
    if not serial:
        # The ADB transport needs the DEVICE serial, not the console device_id
        # ("AVD-…"), which differs on real hardware.
        from .db import connect  # noqa: PLC0415
        with connect() as c:
            row = c.execute("SELECT serial FROM devices WHERE device_id=?",
                            (device_id,)).fetchone()
        serial = row["serial"] if row else device_id
    pk = ed25519_private_hex()
    if not pk:
        raise RuntimeError(
            "Ed25519 private key not configured — run scripts/gen_agent_key.py "
            "or set ALP_ED_PRIV (the embedded APK key must match)")
    if not pin:
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
    if not (4 <= len(pin) <= 12) or not pin.isdigit():
        raise ValueError("pin must be 4-12 digits")

    env = command.new_command(1, device_id, "PROVISION_PIN", {"pin": pin},
                              ed_key=pk)
    out_dir = chan_dir or DEFAULT_CHAN_DIR
    send, _state = adb_channel(serial or device_id, out_dir=out_dir)
    delivery = send(env, "PROVISION_PIN")
    return {"pin": pin, "envelope": env, "delivery": delivery}