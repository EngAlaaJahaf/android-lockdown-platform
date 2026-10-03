"""Create a verifiable backup bundle of the ALP database + recovery vault.

Usage:
  python scripts/backup.py [out_dir] [--keep N]

Writes into <out_dir> (default ../backups):
  <bundle>-alp.db        consistent VACUUM INTO snapshot
  <bundle>-.key          live vault.key copied alongside (when present)
  <bundle>-manifest.json sha256 of every artifact + integrity + db counts

Prunes bundles beyond --keep (default 8). Exits non-zero on failure.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.backup import create_backup  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    keep = 8
    if "--keep" in args:
        i = args.index("--keep")
        if i + 1 < len(args):
            keep = int(args[i + 1])
    out_dir = next((a for a in args if not a.startswith("--")), None)
    try:
        out = create_backup(out_dir=out_dir, keep=keep)
    except Exception as ex:  # noqa: BLE001
        print(f"backup FAILED: {type(ex).__name__}: {ex}")
        return 1
    print("backup ok")
    print(f"  bundle   : {out['bundle']}")
    print(f"  db       : {out['db']} ({out['db_size']} B)")
    print(f"  sha256   : {out['db_sha256']}")
    print(f"  vault    : {'copied' if out['vault_copied'] else 'NOT PRESENT'}")
    print(f"  integrity: {out['integrity']}")
    print(f"  counts   : {out['counts']}")
    print(f"  pruned   : {out['pruned']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())