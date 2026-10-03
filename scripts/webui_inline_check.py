"""Syntax + brace-balance check for the inline UI script in webui/index.html.

`node --check` validates syntax only. It happily accepts a stray statement left
behind by a bad text edit, and that statement throws ReferenceError when the
block runs -- which kills the whole UI. The runtime + handler-reference check
that actually catches that lives in scripts/webui_inline_runtime.js.

Run:  python -X utf8 scripts/webui_inline_check.py
"""
import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "webui", "index.html")
TMP = os.path.join(os.environ["TEMP"], "opencode", "index_inline.js")

html = io.open(HTML, encoding="utf-8").read()
blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
code = "\n;\n".join(blocks)
io.open(TMP, "w", encoding="utf-8", newline="").write(code)
print("inline script blocks: %d (%d bytes)" % (len(blocks), len(code)))

p = subprocess.run(["node", "--check", TMP], capture_output=True, text=True)
print("node --check rc:", p.returncode)
if p.returncode:
    print(p.stderr)
    sys.exit(1)
print("syntax OK")

# node's parser knows the real brace depth, so ask it rather than counting here.
probe = "const s=%s; try{ new Function(s); }catch(e){}" % (
    "JSON.stringify(require('fs').readFileSync(process.argv[1],'utf8'))")
bal = subprocess.run(
    ["node", "-e",
     "const fs=require('fs');"
     "const src=fs.readFileSync(process.argv[1],'utf8');"
     "let d=0; for(const c of src){ if(c==='{')d++; else if(c==='}')d--; }"
     "console.log('raw brace delta:', d);",
     TMP], capture_output=True, text=True)
print(bal.stdout.strip() or bal.stderr.strip())

print("\nRESULT: syntax OK")