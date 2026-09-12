"""ALP Manager desktop launcher.

    python desktop/run_app.py          # from source
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alp_manager.paths import add_engine_paths, apply_runtime_env  # noqa: E402

add_engine_paths()
apply_runtime_env()

from alp_manager.app import main  # noqa: E402

if __name__ == "__main__":
    main()