"""ALP Manager desktop launcher.

    python desktop/run_app.py          # from source
    python desktop/run_app.py --tk      # force legacy Tk fallback UI

Any startup crash is recorded to the ALPManager log directory so a GUI
startup failure is never a silent close, and it is re-raised (console mode)
so the operator sees the traceback.
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alp_manager.paths import add_engine_paths, apply_runtime_env  # noqa: E402

add_engine_paths()
apply_runtime_env()

_force_tk = "--tk" in sys.argv or (os.environ.get("ALP_FORCE_TK") == "1")

def main() -> int:
    try:
        if not _force_tk:
            try:
                from alp_manager import app_qt  # noqa: E402
                return app_qt.main()
            except ImportError:
                print("PySide6 غير متاح — التبديل إلى الواجهة الاحتياطية Tk", file=sys.stderr)
        from alp_manager import app  # noqa: E402, PLC0415
        return app.main()
    except BaseException as ex:  # noqa: BLE001
        from alp_manager import logger
        tb = traceback.format_exc()
        logger.log_startup_error(ex, tb)
        raise

if __name__ == "__main__":
    sys.exit(main())