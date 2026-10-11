"""Android Lockdown Platform — backend control plane."""
__version__ = "0.1.0"

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters"):
    _p = os.path.join(_ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)