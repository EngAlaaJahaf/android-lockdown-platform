"""ALP Manager desktop launcher.

    python desktop/run_app.py          # from source
    python desktop/run_app.py --tk      # force legacy Tk fallback UI
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alp_manager.paths import add_engine_paths, apply_runtime_env  # noqa: E402

add_engine_paths()
apply_runtime_env()

_force_tk = "--tk" in sys.argv or (os.environ.get("ALP_FORCE_TK") == "1")

def main() -> None:
    if not _force_tk:
        try:
            from alp_manager import app_qt  # noqa: E402
            app_qt.main()
            return
        except ImportError:
            print("PySide6 غير متاح — التبديل إلى الواجهة الاحتياطية Tk", file=sys.stderr)
    from alp_manager import app  # noqa: E402, PLC0415
    app.main()

if __name__ == "__main__":
    main()