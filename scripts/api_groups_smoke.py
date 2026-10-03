"""End-to-end exercise of the Device Groups HTTP surface against a scratch DB.

Starts the real API server in-process on a scratch copy of alp.db with the
migrations applied, logs in through the real /auth/login, then drives the
group -> profile workflow with the real RBAC gate.

Asserts the honesty rules this platform cares about:
  * no profile is reported as successful while no device is attached, and the
    label is STAGED, never APPLIED;
  * a DRAFT profile cannot be associated;
  * counters always add up to the real expected target count;
  * READ_ONLY can list but never write.

Run:  python -X utf8 scripts/api_groups_smoke.py
The production admin password is never used or guessed; test-only admins are
created inside the scratch copy only.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(tempfile.gettempdir(), "alp_api_groups.db")
for suf in ("", "-wal", "-shm"):
    if os.path.exists(TMP + suf):
        os.remove(TMP + suf)
shutil.copy(os.path.join(ROOT, "database", "alp.db"), TMP)

PORT = 8799
os.environ["ALP_DB"] = TMP
os.environ["ALP_SIGNING_KEY"] = "api-groups-test-signing-key-0123456789"
os.environ["ALP_API_PORT"] = str(PORT)
os.environ["ALP_API_HOST"] = "127.0.0.1"
os.environ["ALP_SESSION_TTL_SECONDS"] = "3600"

sys.path.insert(0, ROOT)
for sub in ("backend", "policy-engine", "capability-engine", "compatibility",
            "verification-engine", "vendor-adapters", "desktop"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from backend import config, db            # noqa: E402
config.DBPATH = TMP
config.API_PORT = PORT
db.DBPATH = TMP
db.run_migrations()

from backend.db import connect            # noqa: E402
from backend import auth as auth_mod      # noqa: E402
from backend.api.server import Handler, CHAN_DIR   # noqa: E402

# Test-only admins created in the SCRATCH copy so the real production admin
# password is never touched or guessed.
SUPER_PW = "api-test-super-pw-0001"
RO_PW = "api-test-ro-pw-0001"
with connect() as c:
    c.execute("DELETE FROM sessions WHERE token LIKE 'test%'")
    for user, pw, role_id in (("apitest_super", SUPER_PW, 1), ("apitest_ro", RO_PW, 8)):
        c.execute("INSERT INTO administrators (username, password_hash, role_id, "
                  "active, mfa_enabled, display_name) VALUES (?,?,?,1,0,?) "
                  "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, "
                  "role_id=excluded.role_id, active=1, mfa_enabled=0",
                  (user, auth_mod.hash_password(pw), role_id, user))

BASE = "http://127.0.0.1:%d" % PORT


def _assert_port_free(port):
    """Refuse to run if something already owns the port.

    ThreadingHTTPServer sets allow_reuse_address, and on Windows that lets a
    second process bind a port that is already LISTENing. Without this guard the
    new server silently loses every race to the old one, so the script tests
    somebody else's process and reports its failures as its own.
    """
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(
                "port %d is already in use - stop the server holding it before "
                "running this smoke test" % port)
    finally:
        probe.close()


_assert_port_free(PORT)
TOKEN = {"v": None}
CALLS = []


def call(method, path, body=None, token=True, expect=None):
    url = BASE + path
    # DELETE carries its body too (approval flags), so always send JSON
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token and TOKEN["v"]:
        req.add_header("Authorization", "Bearer " + TOKEN["v"])
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, payload = r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        status, payload = e.code, json.loads(e.read().decode())
    CALLS.append((method, path, status))
    if expect is not None and status != expect:
        raise AssertionError("%s %s -> %s (want %s): %s"
                             % (method, path, status, expect, payload))
    return status, payload


def section(name):
    print("\n=== %s ===" % name)


# ---------------------------------------------------------------- fixtures
with connect() as c:
    for dev in ("D-API-1", "D-API-2"):
        c.execute("INSERT INTO devices (device_id, serial, manufacturer, model, "
                  "android_version, api_level, is_lab) VALUES (?,?,?,?,?,?,1) "
                  "ON CONFLICT(device_id) DO UPDATE SET serial=excluded.serial",
                  (dev, "S-" + dev, "Samsung", "SM-A145P", 15, 35))
    # a DRAFT profile that must be refused
    c.execute("INSERT OR REPLACE INTO policies (policy_id, display_name, category, "
              "status, requirements) VALUES ('POL-API-DRAFT','مسودة','CORPORATE_DEFAULT',"
              "'DRAFT',?)", (json.dumps([{"feature": "CAMERA", "desired_state": "BLOCK",
                                          "risk": "MEDIUM"}]),))
print("devices + DRAFT profile seeded")

os.makedirs(CHAN_DIR, exist_ok=True)
httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.6)

try:
    section("auth")
    st, p = call("GET", "/api/v1/health", token=False)
    print("  health:", p["data"])
    st, p = call("GET", "/api/v1/groups", token=False, expect=401)
    print("  unauthenticated -> 401 OK")

    st, p = call("POST", "/api/v1/auth/login",
                 {"username": "apitest_super", "password": SUPER_PW}, token=False,
                 expect=200)
    TOKEN["v"] = p["data"]["token"]
    print("  logged in as", p["data"]["username"], "| mfa_required =",
          p["data"].get("mfa_required"))
    assert p["data"]["token"]

    section("detected contract for the New Devices page")
    st, p = call("GET", "/api/v1/devices/detected", expect=200)
    assert isinstance(p["data"], list), "detected must return a list"
    for d in p["data"]:
        # The frontend gates Install/Register/Group behind agent_installed and
        # renders next_step verbatim; every entry must carry the full key set
        # even with no ADB attached.
        for key in ("serial", "state", "model", "ready", "registered",
                    "agent_installed", "next_step", "next_step_reason"):
            assert key in d, "detected entry is missing %r" % key
        assert isinstance(d["agent_installed"], bool)
        assert d["next_step"] in ("authorize", "install", "register", "group")
    print("  detected entries: %d (all carry agent_installed + next_step)"
          % len(p["data"]))

    section("group CRUD")
    st, p = call("POST", "/api/v1/groups",
                 {"name": "API Lab", "description": "from the API test"}, expect=200)
    gid = p["data"]["id"]
    print("  created id=%s key=%s members=%s profiles=%s"
          % (gid, p["data"]["group_key"], p["data"]["members"], p["data"]["profiles"]))

    st, p = call("POST", "/api/v1/groups", {"name": ""}, expect=400)
    print("  empty name -> 400:", p["error"])

    st, p = call("GET", "/api/v1/groups", expect=200)
    print("  list has %d group(s)" % len(p["data"]))

    st, p = call("PUT", "/api/v1/groups/%d" % gid, {"description": "renamed"}, expect=200)
    print("  updated description:", p["data"]["description"])

    section("members auto-apply the group's profiles")
    st, p = call("POST", "/api/v1/groups/%d/members" % gid,
                 {"device_ids": ["D-API-1"]}, expect=200)
    print("  added:", p["data"]["added"], "| deploy summary:",
          json.dumps(p["data"]["deploy"]["summary"]))

    st, p = call("POST", "/api/v1/groups/%d/members" % gid,
                 {"device_id": "D-API-1"}, expect=200)
    print("  idempotent: added=%s already_present=%s"
          % (p["data"]["added"], p["data"]["already_present"]))

    st, p = call("POST", "/api/v1/groups/%d/members" % gid,
                 {"device_ids": ["D-NOT-REGISTERED"]}, expect=400)
    print("  unregistered device -> 400:", p["error"])

    st, p = call("POST", "/api/v1/groups/%d/members" % gid,
                 {"device_ids": []}, expect=400)
    print("  empty device_ids -> 400:", p["error"])

    st, p = call("GET", "/api/v1/groups/%d/members" % gid, expect=200)
    print("  members tab:", [(m["device_id"], m["model"]) for m in p["data"]])

    section("associate profiles -> auto-apply to members")
    st, p = call("POST", "/api/v1/groups/%d/profiles" % gid,
                 {"policy_ids": ["POL-FULL_LOCKDOWN"]}, expect=200)
    d = p["data"]
    print("  associated:", d["associated"])
    print("  summary   :", json.dumps(d["deploy"]["summary"]))
    for r in d["deploy"]["results"]:
        print("    %-12s %-8s %s" % (r["device_id"], r["outcome"], r["detail"]))

    section("honesty: no device attached must never read as success")
    st, p = call("GET", "/api/v1/groups/%d/profiles" % gid, expect=200)
    row = p["data"][0]
    s = row["execution_status"]
    print("  profile:", row["profile_name"])
    print("  status :", json.dumps(s))
    assert s["success_count"] == 0, "must not claim success with no device attached"
    assert s["label"] == "STAGED", "label must be STAGED, got %s" % s["label"]
    assert s["label"] != "APPLIED"

    section("DRAFT profile must be refused")
    st, p = call("POST", "/api/v1/groups/%d/profiles" % gid,
                 {"policy_ids": ["POL-API-DRAFT"]}, expect=409)
    print("  -> 409:", p["error"][:90])

    st, p = call("POST", "/api/v1/groups/%d/profiles" % gid,
                 {"policy_ids": ["POL-DOES-NOT-EXIST"]}, expect=400)
    print("  unknown profile -> 400:", p["error"])

    section("group status roll-up")
    st, p = call("GET", "/api/v1/groups/%d/status" % gid, expect=200)
    g = p["data"]
    print("  label=%s members=%s profiles=%s expected=%s counts=%s"
          % (g["label"], g["members"], g["profiles"], g["expected_targets"],
             json.dumps(g["counts"])))
    c = g["counts"]
    assert c["success"] + c["yet_to_apply"] + c["failed"] + c["not_applicable"] \
        == g["expected_targets"], "counters must add up"

    section("second member then deploy")
    call("POST", "/api/v1/groups/%d/members" % gid,
         {"device_ids": ["D-API-2"], "deploy": False}, expect=200)
    st, p = call("POST", "/api/v1/groups/%d/deploy" % gid,
                 {"skip_approval": True}, expect=200)
    print("  summary:", json.dumps(p["data"]["summary"]))
    st, p = call("GET", "/api/v1/groups/%d/status" % gid, expect=200)
    print("  after deploy:", json.dumps(p["data"]["counts"]),
          "label=", p["data"]["label"])
    assert p["data"]["expected_targets"] == 2

    section("action history")
    st, p = call("GET", "/api/v1/groups/%d/actions" % gid, expect=200)
    for a in p["data"]:
        print("   %-20s %-10s ok=%s bad=%s" % (a["action_id"], a["action_status"],
                                               a["success_count"], a["failure_count"]))
    assert p["data"], "action history must not be empty"

    section("move a device between groups")
    st, p = call("POST", "/api/v1/groups", {"name": "Second"}, expect=200)
    gid2 = p["data"]["id"]
    st, p = call("POST", "/api/v1/groups/%d/move" % gid,
                 {"to_group": gid2, "device_id": "D-API-2"}, expect=200)
    print("  moved ->", json.dumps(p["data"], ensure_ascii=False))
    st, p = call("GET", "/api/v1/groups/%d/members" % gid, expect=200)
    print("  source group now has:", [m["device_id"] for m in p["data"]])
    assert "D-API-2" not in [m["device_id"] for m in p["data"]]

    section("disassociate is scoped to one group")
    call("POST", "/api/v1/groups/%d/profiles" % gid2,
         {"policy_ids": ["POL-FULL_LOCKDOWN"]}, expect=200)
    st, p = call("DELETE", "/api/v1/groups/%d/profiles/POL-FULL_LOCKDOWN" % gid,
                 expect=200)
    print("  disassociate from group 1:", json.dumps(p["data"]))
    st, p = call("GET", "/api/v1/groups/%d/profiles" % gid2, expect=200)
    print("  group 2 keeps:", [x["policy_id"] for x in p["data"]])
    assert any(x["policy_id"] == "POL-FULL_LOCKDOWN" for x in p["data"]), \
        "disassociating from group 1 must not strip group 2"

    section("delete cascades")
    st, p = call("DELETE", "/api/v1/groups/%d" % gid2, {}, expect=403)
    print("  unapproved delete -> 403:", p["error"])
    st, p = call("DELETE", "/api/v1/groups/%d" % gid2,
                 {"skip_approval": True}, expect=200)
    print("  deleted:", json.dumps(p["data"], ensure_ascii=False))
    with connect() as c2:
        left = c2.execute("SELECT COUNT(*) n FROM group_profile_assignments "
                          "WHERE group_id=?", (gid2,)).fetchone()["n"]
    print("  leftover assignments:", left)
    assert left == 0

    section("404 for unknown routes")
    call("GET", "/api/v1/groups/%d/nope" % gid, expect=404)
    call("POST", "/api/v1/groups/notanumber", {}, expect=404)
    call("GET", "/api/v1/groups/999999", expect=400)
    print("  unknown sub-route / bad id handled")

    section("RBAC: READ_ONLY must be refused on writes")
    saved = TOKEN["v"]
    st, p = call("POST", "/api/v1/auth/login",
                 {"username": "apitest_ro", "password": RO_PW}, token=False, expect=200)
    TOKEN["v"] = p["data"]["token"]
    print("  logged in as", p["data"]["username"])
    st, p = call("GET", "/api/v1/groups", expect=200)
    print("  READ_ONLY can list groups:", len(p["data"]))
    for method, path, b in (("POST", "/api/v1/groups", {"name": "nope"}),
                            ("POST", "/api/v1/groups/%d/members" % gid,
                             {"device_ids": ["D-API-1"]}),
                            ("POST", "/api/v1/groups/%d/profiles" % gid,
                             {"policy_ids": ["POL-FULL_LOCKDOWN"]}),
                            ("PUT", "/api/v1/groups/%d" % gid, {"description": "x"}),
                            ("DELETE", "/api/v1/groups/%d" % gid,
                             {"skip_approval": True}),
                            ("POST", "/api/v1/groups/%d/deploy" % gid, {})):
        st, p = call(method, path, b, expect=403)
        print("   %-6s %-34s -> 403 %s" % (method, path[:34], p["error"][:52]))
    TOKEN["v"] = saved
    print("  restored super-admin session")

    print("\nALL API GROUP CHECKS PASSED (%d HTTP calls)" % len(CALLS))
finally:
    httpd.shutdown()

with connect() as c:
    c.execute("DELETE FROM compliance WHERE device_id IN "
              "(SELECT id FROM devices WHERE device_id LIKE 'D-API-%')")
    c.execute("DELETE FROM assignments WHERE device_id IN "
              "(SELECT id FROM devices WHERE device_id LIKE 'D-API-%')")
    c.execute("DELETE FROM device_group_members WHERE device_id IN "
              "(SELECT id FROM devices WHERE device_id LIKE 'D-API-%')")
    c.execute("DELETE FROM group_action_history WHERE group_id NOT IN "
              "(SELECT id FROM device_groups)")
    c.execute("DELETE FROM group_deploy_status WHERE assignment_id NOT IN "
              "(SELECT id FROM group_profile_assignments)")
    c.execute("DELETE FROM device_groups")
    c.execute("DELETE FROM devices WHERE device_id LIKE 'D-API-%'")
    c.execute("DELETE FROM policies WHERE policy_id='POL-API-DRAFT'")
print("scratch fixtures cleaned")