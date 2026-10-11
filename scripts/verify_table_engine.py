# -*- coding: utf-8 -*-
"""Headless verification of the reusable table engine.

Injects scripts/alp-table-proof.js into the live console and drives the engine's
own handlers in a real browser, so every claim below is observed rather than
assumed.
"""
import json
import os
import subprocess

AB = os.path.join(os.environ["APPDATA"], "npm", "agent-browser.cmd")
PROBE = ("http://127.0.0.1:8765/assets/alp-table-proof.js")


def ab(*args):
    r = subprocess.run([AB, *args], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return ((r.stdout or "").strip() + (r.stderr or "").strip())


def js(expr):
    """Evaluate and always hand back decoded JSON.

    agent-browser wraps the result in quotes for strings and returns errors as
    text, so a raw string result must not be mistaken for a JSON object.
    """
    out = ab("eval", expr)
    try:
        return json.loads(out)
    except (ValueError, TypeError):
        return {"__error__": out}


FAIL = []


def show(label, value):
    print("\n--- %s" % label)
    print(json.dumps(value, indent=1, ensure_ascii=False)
          if isinstance(value, (dict, list)) else value)


def expect(label, ok, detail=""):
    print("  %-58s %s" % (label, "OK" if ok else "FAIL " + str(detail)))
    if not ok:
        FAIL.append(label)


print("engine present :", js("typeof window.AlpTableEngine"))
print("inject probe   :", js(
    "(()=>{const s=document.createElement('script');s.src='%s?t='+Date.now();"
    "document.head.appendChild(s);return 'added';})()" % PROBE))
import time
time.sleep(2)
print("probe ready    :", js("typeof window.ALP_PROOF"))
if js("typeof window.ALP_PROOF") != "object":
    raise SystemExit("probe script did not load - cannot verify")

print("\n" + "=" * 62)
print("STANDARD HTML TABLE")
print("=" * 62)
print(js("window.ALP_PROOF.build()"))
show("hooks (resizers/sortable/cols)", js("window.__alpProofOut.hooks"))
expect("a resizer on every column",
       js("window.__alpProofOut.hooks.resizers") ==
       js("window.__alpProofOut.hooks.cols"),
       js("window.__alpProofOut.hooks"))
expect("every header marked sortable",
       js("window.__alpProofOut.hooks.sortable") ==
       js("window.__alpProofOut.hooks.cols"))

show("horizontal scroll wrapper", js("window.__alpProofOut.scroll"))
expect("wrapper has overflow-x auto",
       js("window.__alpProofOut.scroll.overflowX") == "auto")
expect("table is wider than the viewport so it can scroll",
       js("window.__alpProofOut.scroll.scrollable") is True)

js("window.ALP_PROOF.sortTest()")
s = js("window.__alpProofOut.sort")
show("sort by Members", s)
nums = [int(x) for x in s["before"]]
expect("ascending is numerically ordered",
       [int(x) for x in s["asc"]] == sorted(nums), s["asc"])
expect("descending is the reverse",
       [int(x) for x in s["desc"]] == sorted(nums, reverse=True), s["desc"])
expect("exactly one sort arrow is shown",
       s["indicator"]["arrowCount"] == 1, s["indicator"])
expect("arrow points down after the second click",
       s["indicator"]["arrow"] == "↓", s["indicator"])
expect("sorted header is marked active", s["indicator"]["active"] is True)

js("window.ALP_PROOF.typeTest()")
t = js("window.__alpProofOut.types")
show("numeric vs text columns", t)
expect("numeric column sorts 1,3,5,8,12,25 (not lexicographically)",
       t["numericAsc"] == ["1", "3", "5", "8", "12", "25"], t["numericAsc"])
expect("text column sorts alphabetically",
       t["textAsc"] == ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"],
       t["textAsc"])

js("window.ALP_PROOF.resizeTest()")
r = js("window.__alpProofOut.resize")
show("column resize", r)
expect("dragging the handle widens the header", r["headerGrew"] is True, r)
expect("body cells follow the header", r["bodyFollowed"] is True, r)
expect("a column cannot be dragged below the minimum",
       r["clampMin"]["notZero"] is True, r["clampMin"])

js("window.ALP_PROOF.syncTest()")
y = js("window.__alpProofOut.sync")
show("width survives a data refresh", y)
expect("resized width is preserved after rows re-render",
       abs(y["afterRefresh"] - y["kept"]) <= 2, y)

js("window.ALP_PROOF.scrollTest()")
sc = js("window.__alpProofOut.scrollMove")
show("scrolling the container", sc)
expect("container scrolls horizontally", sc["reached"] > 0, sc)

print("\n" + "=" * 62)
print("EMBER (MANAGEENGINE) TABLE")
print("=" * 62)
print(js("window.ALP_PROOF.emberTest()"))
e = js("window.__alpProofOut.ember")
show("ember enhancement", e)
expect("ember resizers attached", e["resizers"] > 0, e)
expect("ember headers sortable", e["sortable"] > 0, e)
expect("ember container scrolls horizontally",
       e["overflowX"] == "auto", e)
expect("ember rows sorted by the clicked column",
       e["sortedFirstCol"] == ["1", "11", "21", "31", "41"],
       e["sortedFirstCol"])
expect("ember rows repositioned in order",
       e["tops"][:3] == ["0px", "42px", "84px"], e["tops"])

js("window.ALP_PROOF.cleanup()")

print("\n" + "=" * 62)
print(("ALL TABLE CHECKS PASSED" if not FAIL else "FAILURES: %s" % FAIL))
print("=" * 62)