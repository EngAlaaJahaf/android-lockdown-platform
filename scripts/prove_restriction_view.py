# -*- coding: utf-8 -*-
"""Prove the read-only restrictions view now agrees with the profile.

Reproduces the rendering decision in Python against the real catalog + real
profile, so the two views can be compared without a browser.
"""
import json
import os
import re
import sys

ROOT = r"D:\projects\android-lockdown-platform"
sys.path.insert(0, ROOT)
from backend.db import connect  # noqa: E402

DATA = os.path.join(ROOT, "webui", "assets", "alp-restrictions-data.js")


def load_catalog():
    s = open(DATA, encoding="utf-8").read()
    lit = s[s.index("{"):]
    return json.loads(lit[: lit.rindex("}") + 1])


def render_state(item, req_map):
    """Mirrors renderProfileDetailsFeatures()."""
    lane = item.get("feature") or re.sub(r"[^A-Z0-9]", "_",
                                         item.get("name", "").upper())
    st = req_map.get(lane)
    defined = isinstance(st, str) and st != ""
    if not defined:
        return "Not set"
    if st in ("RESTRICT", "BLOCK"):
        return "Restricted"
    if st in ("ALLOW", "TRUE", "YES"):
        return "Allowed"
    return "Not set"


catalog = load_catalog()
with connect() as c:
    row = c.execute("SELECT policy_id, requirements FROM policies "
                    "WHERE status='ACTIVE' ORDER BY rowid DESC LIMIT 1").fetchone()
reqs = json.loads(row["requirements"] or "[]")
req_map = {r["feature"].upper().replace("-", "_"): (r.get("desired_state") or "").upper()
           for r in reqs if r.get("feature")}

print("profile:", row["policy_id"], "| lanes:", len(req_map))
missing = [f for items in catalog.values() for it in items if not it.get("feature")]
print("catalog rows without a lane key:", len(missing))

# 1) every lane in the policy must be reachable from some catalog row
covered = {it["feature"] for items in catalog.values() for it in items
           if it.get("feature")}
unreachable = sorted(f for f in req_map if f not in covered)
print("policy lanes no catalog row can show:", unreachable or "none")

# 2) the three rows from the screenshots
print("\n=== the reported rows ===")
for cat, items in catalog.items():
    for it in items:
        if it["name"] in ("Location services", "Mock locations", "Google Maps"):
            print("  %-18s lane=%-15s -> %s" % (it["name"], it["feature"],
                                                render_state(it, req_map)))

# 3) full scan: no row may claim a state the profile does not set
print("\n=== full scan ===")
counts = {}
wrong = []
for cat, items in catalog.items():
    for it in items:
        lane = it.get("feature")
        st = req_map.get(lane)
        shown = render_state(it, req_map)
        counts[shown] = counts.get(shown, 0) + 1
        if shown != "Not set":
            expect = "Restricted" if st in ("RESTRICT", "BLOCK") else "Allowed"
            if shown != expect:
                wrong.append((it["name"], lane, st, shown))
for k in sorted(counts):
    print("  %-12s %d" % (k, counts[k]))
print("\nmismatches:", wrong or "none")

# 4) the old buggy keying, for comparison
print("\n=== what the label-based lookup would have done ===")
for cat, items in catalog.items():
    for it in items:
        if it["name"] in ("Location services", "Mock locations", "Google Maps"):
            old_key = re.sub(r"[^A-Z0-9]", "_", it["name"].upper())
            old_st = req_map.get(old_key)
            old_shown = ("Restricted" if old_st in ("RESTRICT", "BLOCK")
                         else "Allowed" if old_st in ("ALLOW", "TRUE", "YES")
                         else "Allowed (catalog default - WRONG)")
            print("  %-18s old key=%-22s -> %s" % (it["name"], old_key, old_shown))
            print("  %-18s new key=%-22s -> %s" % ("", it["feature"],
                                                   render_state(it, req_map)))