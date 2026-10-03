"""Generate the Ed25519 keypair for the on-device command barrier.

The PRIVATE key must live ONLY on the console (env ALP_ED_PRIV or
keys/alp_ed_priv.hex). The PUBLIC key is embedded into the agent APK at build
time (android-agent/alp_pubkey.hex) — it is not a secret.

    python scripts/gen_agent_key.py            # create keys (no-op if exists)
    python scripts/gen_agent_key.py --force    # overwrite existing keys
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.ed25519 import keygen_hex  # noqa: E402

KEYS_DIR = os.path.join(ROOT, "keys")
PRIV_FILE = os.path.join(KEYS_DIR, "alp_ed_priv.hex")
PUB_APK_FILE = os.path.join(ROOT, "android-agent", "alp_pubkey.hex")
GITIGNORE = os.path.join(KEYS_DIR, ".gitignore")


def main() -> int:
    force = "--force" in sys.argv
    if os.path.exists(PRIV_FILE) and not force:
        print(f"key file already exists: {PRIV_FILE}")
        print("use --force to regenerate (rebuild the APK afterwards!)")
        return 0
    priv, pub = keygen_hex()
    os.makedirs(KEYS_DIR, exist_ok=True)
    with open(PRIV_FILE, "w", encoding="utf-8") as fh:
        fh.write(priv + "\n")
    with open(PUB_APK_FILE, "w", encoding="utf-8") as fh:
        fh.write(pub + "\n")
    with open(GITIGNORE, "w", encoding="utf-8") as fh:
        fh.write("# private signing key — never commit\n*\n")
    line = "-" * 62
    print(line)
    print("Ed25519 keypair written.")
    print(f"  private (console only): {PRIV_FILE}")
    print(f"  public   (embedded in APK): {PUB_APK_FILE}")
    print(line)
    print("Requisite: rebuild the agent (scripts/build_agent.py) so the new")
    print("public key lands in res/raw/alp_pubkey.bin.")
    print("Ops note: keep the private key off the repo (keys/ is gitignored);")
    print("point ALP_ED_PRIV at it for the web console / desktop app / CLI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())