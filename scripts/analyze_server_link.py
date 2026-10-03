"""Extract control-plane endpoint candidates from the APK's DEX string pools.

Filters out Dalvik type descriptors (Lcom/...;) and library noise so the
remaining strings are the app's own HTTP paths and config keys.
"""
import io
import os
import re
import zipfile

APK = os.path.join("extracted-apks", "manageengine-mdm", "manageengine-mdm.apk")
OUT = os.path.join("docs", "ME_AGENT_SERVER_LINK_ANALYSIS.md")

STR_RE = re.compile(rb"[\x20-\x7e]{4,}")

# Must look like an HTTP path (leading slash) and not a Dalvik descriptor.
PATH_RE = re.compile(r"^/[A-Za-z0-9_\-./{}$:]{2,90}$")
DESCRIPTOR = re.compile(
    r"^[LI!\[;]*(com|android|androidx|kotlin|okhttp3|kotlinx|java|javax|org|io)/")
KEY_RE = re.compile(r"^[a-z][a-z0-9_\-\.]{2,45}$", re.I)
KEYWORDS = (
    "server", "url", "host", "port", "endpoint", "api", "tenant", "token",
    "auth", "device", "enroll", "command", "config", "proxy", "cert",
    "timeout", "retry", "poll", "sync", "passphrase", "key",
)
INTERESTING_PATH = re.compile(
    r"^/(api|sdk|mdm|agent|rest|servlet|device|server|command|enroll|config|"
    r"policy|profile|report|sync|remote|oauth|auth|token|fcm|push|log)", re.I)


def collect():
    z = zipfile.ZipFile(APK)
    paths, keys = set(), set()
    for name in [n for n in z.namelist()
                 if re.match(r"classes\d*\.dex$", n)]:
        data = z.read(name)
        for m in STR_RE.finditer(data):
            try:
                s = m.group().decode("ascii")
            except Exception:
                continue
            if DESCRIPTOR.match(s):
                continue
            if PATH_RE.match(s) and INTERESTING_PATH.match(s):
                paths.add(s)
            elif KEY_RE.match(s) and any(k in s.lower() for k in KEYWORDS):
                keys.add(s)
    z.close()
    return sorted(paths), sorted(keys)


def main():
    paths, keys = collect()
    lines = ["# ManagedEngine MDM Agent — Server / Control-Plane Link Analysis",
             "",
             "Static, read-only string analysis of `manageengine-mdm.apk`",
             "(com.manageengine.mdm.android v24.04.05.ADB). No secrets are",
             "reproduced here; only structural endpoint shapes and config keys.",
             "", "## HTTP endpoint paths found in DEX string pools", "",
             "```"]
    lines += ["%-62s" % p for p in paths]
    lines += ["```", "", "## Control-plane configuration keys", "", "```"]
    lines += ["%-42s" % k for k in keys]
    lines += ["```", ""]
    text = "\n".join(lines)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("paths: %d, keys: %d" % (len(paths), len(keys)))
    print("\n".join(lines[:60]))
    print("...\nwritten:", OUT)


if __name__ == "__main__":
    main()