"""Desktop UI smoke test — real Tk window build, skipped when no display."""
from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from alp_manager import paths  # noqa: E402

paths.add_engine_paths()
paths.apply_runtime_env()

import tkinter as tk  # noqa: E402

try:
    _probe = tk.Tk()
    _probe.withdraw()
    _probe.update()
    _probe.destroy()
    TK_OK = True
except Exception:  # noqa: BLE001 — headless CI / no display
    TK_OK = False


@unittest.skipUnless(TK_OK, "no display available for tkinter")
class TestAppSmoke(unittest.TestCase):
    def test_app_builds_with_expected_tabs(self):
        from alp_manager.app import App
        app = App()
        app.update()
        for _ in range(30):
            app.update()
            time.sleep(0.03)
        names = [app._nb.tab(t, "text") for t in app._nb.tabs()]
        self.assertEqual(names, ["Session", "Devices", "Apply policy", "Recovery", "Audit"])
        app.destroy()


if __name__ == "__main__":
    unittest.main()