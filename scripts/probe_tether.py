# -*- coding: utf-8 -*-
"""Prove whether the handset can reach the panel over the gnirehtet tether.

Uses `adb reverse` to open a device-side port onto the host, then asks the
device to open a socket with the platform's own toybox tools, so the answer
comes from the device and not from the host.
"""
import subprocess
import time

ADB = r"C:\Users\hp\AppData\Local\Android\Sdk\platform-tools\adb.exe"
SERIAL = "LT8110260130351"


def sh(*args, timeout=60):
    r = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True,
                       text=True, timeout=timeout)
    return ((r.stdout or "") + (r.stderr or "")).strip()


print("=== adb reverse tunnels (host->device direction) ===")
print(sh("reverse", "--list"))

print("\n=== can the device resolve/open anything? ===")
# `nc` is present on most builds; try both spellings.
for tool in ("nc", "toybox", "ping"):
    out = sh("shell", "which", tool)
    print("  %-8s -> %s" % (tool, out or "(absent)"))

print("\n=== ping the tether host alias ===")
for host in ("10.0.0.2", "10.0.2.2"):
    out = sh("shell", "ping", "-c", "2", "-W", "2", host)
    tail = [l for l in out.splitlines() if "packets" in l or "unreachable" in l]
    print("  %-9s %s" % (host, tail[-1] if tail else out.splitlines()[-1:]))

print("\n=== open a TCP connection to the panel from the device ===")
for host in ("10.0.0.2", "10.0.2.2", "127.0.0.1"):
    cmd = ('echo -e "GET /api/v1/health HTTP/1.0\\r\\n\\r\\n" | '
           'toybox nc -w 5 %s 8765' % host)
    out = sh("shell", cmd, timeout=40)
    first = out.splitlines()[0] if out else "(no output)"
    print("  %-9s -> %s" % (host, first[:70]))