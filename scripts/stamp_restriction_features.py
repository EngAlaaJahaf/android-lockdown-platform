# -*- coding: utf-8 -*-
"""Pin an explicit ALP lane key onto every catalog row in alp-restrictions-data.js.

Why: the read-only restrictions view looked a row up by its display label
("Location services" -> LOCATION_SERVICES) while the policy lane is LOCATION.
That silent miss made a RESTRICT lane render as "Allowed".

The mapping is derived from backend/restrictions.py, which already carries the
authentic ManageEngine label for each ALP lane - so it is data, not a guess. Rows
whose label genuinely has no lane are stamped "feature": null and the renderer
shows them as Undefined instead of inventing an Allowed/Restricted default.
"""
import json
import os
import re
import sys

ROOT = r"D:\projects\android-lockdown-platform"
sys.path.insert(0, ROOT)
from backend.restrictions import by_feature  # noqa: E402

DATA = os.path.join(ROOT, "webui", "assets", "alp-restrictions-data.js")

HEADER_END = "window.ALP_AUTHENTIC_RESTRICTIONS_DATA = "


def norm(s):
    return re.sub(r"[^A-Z0-9]", "_", s.upper()).strip("_")


def build_label_map():
    """normalised label -> set of lanes that own that label."""
    out = {}
    for feature, rows in by_feature().items():
        for r in rows:
            for key in ("label", "label_ar", "name"):
                lab = (r.get(key) or "").strip()
                if lab:
                    out.setdefault(norm(lab), set()).add(feature)
    return out


def main():
    src = open(DATA, encoding="utf-8").read()
    head = src[: src.index(HEADER_END)]
    # The file is `window.X = {...};`. Take from the first brace to the LAST
    # brace so the final category's closing bracket stays inside the literal.
    lit = src[src.index("{"):]
    data = json.loads(lit[: lit.rindex("}") + 1])
    label_map = build_label_map()
    print("lanes in restrictions.py:", len(label_map))

    stamped, unmapped, ambiguous = 0, [], []
    for cat, items in data.items():
        for it in items:
            label = it.get("name", "")
            k = norm(label)
            cands = label_map.get(k)
            if not cands:
                it["feature"] = None
                unmapped.append((cat, label))
                continue
            if len(cands) > 1:
                # Several lanes share one label (e.g. Camera + Video Recording).
                # Prefer the lane whose key equals the label, else the widest.
                pick = k if k in cands else sorted(cands)[0]
                ambiguous.append((cat, label, sorted(cands), pick))
            else:
                pick = next(iter(cands))
            it["feature"] = pick
            stamped += 1

    # Key order: keep the catalog fields, put `feature` right after `name`.
    out = {}
    for cat, items in data.items():
        rows = []
        for it in items:
            row = {"name": it.get("name"),
                   "feature": it.get("feature"),
                   "isSub": it.get("isSub"),
                   "versionBox": it.get("versionBox"),
                   "hasSafe": it.get("hasSafe"),
                   "hasDeviceOwner": it.get("hasDeviceOwner"),
                   "hasProfileOwner": it.get("hasProfileOwner"),
                   "hasDeviceWide": it.get("hasDeviceWide"),
                   "hasInfo": it.get("hasInfo"),
                   "statusText": it.get("statusText"),
                   "isAllowed": it.get("isAllowed"),
                   "isRestricted": it.get("isRestricted")}
            rows.append({k: v for k, v in row.items() if v is not None})
        out[cat] = rows

    with open(DATA, "w", encoding="utf-8") as fh:
        fh.write(head)
        fh.write(HEADER_END)
        fh.write(json.dumps(out, ensure_ascii=False, indent=2))
        fh.write(";\n")

    # verify
    check = open(DATA, encoding="utf-8").read()
    cl = check[check.index("{"):]
    json.loads(cl[: cl.rindex("}") + 1])
    print("stamped with a lane :", stamped)
    print("ambiguous labels   :", len(ambiguous))
    for cat, label, cands, pick in ambiguous:
        print("   %-22s %-38s %s -> %s" % (cat, label[:38], cands, pick))
    print("no lane in catalog :", len(unmapped))
    for cat, label in unmapped:
        print("   %-22s %s" % (cat, label))
    print("\ncatalog parses as JSON: OK")

    # report the lanes this profile actually uses
    from backend.db import connect
    with connect() as c:
        row = c.execute("SELECT policy_id, requirements FROM policies "
                        "WHERE status='ACTIVE' ORDER BY rowid DESC "
                        "LIMIT 1").fetchone()
    used = {r.get("feature") for r in json.loads(row["requirements"] or "[]")}
    covered = {it["feature"] for items in out.values() for it in items
               if it.get("feature")}
    print("\nlanes used by %s: %d" % (row["policy_id"], len(used)))
    missing = sorted(f for f in used if f not in covered)
    print("policy lanes with NO catalog row:", missing or "none")


if __name__ == "__main__":
    main()