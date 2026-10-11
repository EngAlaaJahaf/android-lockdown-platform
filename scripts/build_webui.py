"""ALP WebUI Builder & Assembler.

Compiles modular view templates from `webui/views/` into `webui/index.html`.
Allows developers to work on modular, clean view files while maintaining 100%
compatibility with both FastAPI and legacy HTTP servers.
"""
from __future__ import annotations

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI_DIR = os.path.join(PROJECT_ROOT, "webui")
TEMPLATE_PATH = os.path.join(WEBUI_DIR, "template_index.html")
OUTPUT_PATH = os.path.join(WEBUI_DIR, "index.html")


def build_webui() -> bool:
    if not os.path.isfile(TEMPLATE_PATH):
        print(f"[build_webui] Template not found: {TEMPLATE_PATH}")
        return False

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    def _replace_inject(match):
        rel_path = match.group(1).strip()
        full_path = os.path.join(WEBUI_DIR, rel_path.replace("/", os.sep))
        if os.path.isfile(full_path):
            with open(full_path, "r", encoding="utf-8") as inc_file:
                return inc_file.read()
        else:
            print(f"[build_webui] Warning: include file not found: {full_path}")
            return match.group(0)

    compiled = content
    max_depth = 5
    depth = 0
    while "<!-- INJECT:" in compiled and depth < max_depth:
        compiled = re.sub(r"<!-- INJECT: (.*?) -->", _replace_inject, compiled)
        depth += 1

    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        out.write(compiled)

    print(f"[build_webui] Successfully built {OUTPUT_PATH} ({len(compiled.splitlines())} lines, depth={depth})")
    return True


if __name__ == "__main__":
    success = build_webui()
    sys.exit(0 if success else 1)
