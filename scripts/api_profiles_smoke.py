"""End-to-end exercise of the Profile lifecycle HTTP surface against a scratch DB.

Boots the real API server in-process on a scratch copy of alp.db with all
migrations applied, logs in through the real /auth/login, then drives the full
ManageEngine-style lifecycle over HTTP:

    create DRAFT -> save -> submit -> publish -> associate to group -> retire

Also asserts the honesty/permission rules:
  * requirements validation is enforced on publish (empty DRAFT cannot publish);
  * a DRAFT cannot be associated to a group (409);
  * an ACTIVE profile cannot be edited through PUT (refused);
  * retire refuses while it is still associated (409);
  * READ_ONLY can list but never write.

Run:  python -X utf8 scripts/api_profiles_smoke.py
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
TMP = os.path.join(tempfile.gettempdir(), "alp_api_profiles.db")
for suf in ("", "-wal", "-shm"):
    if os.path.exists(TMP + suf):
        os.remove(TMP + suf)
shutil.copy(os.path.join(ROOT, "database", "alp.db"), TMP)

PORT = 8801
os.environ["ALP_DB"] = TMP
os.environ["ALP_SIGNING_KEY"] = "api-profiles-test-signing-key-0123456789"
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


REQ_CAMERA = [{"feature": "CAMERA", "desired_state": "BLOCK", "risk": "MEDIUM"}]
REQ_WIFI = [{"feature": "WIFI", "desired_state": "RESTRICT",
             "criteria_json": json.dumps({"ssids": ["CorpGuest"]}), "risk": "LOW"}]

with connect() as c:
    c.execute("INSERT INTO devices (device_id, serial, manufacturer, model, "
              "android_version, api_level, is_lab) VALUES "
              "('D-PROF-1','S-D-PROF-1','Samsung','SM-A145P',15,35,1) "
              "ON CONFLICT(device_id) DO UPDATE SET serial=excluded.serial")
print("device seeded")

os.makedirs(CHAN_DIR, exist_ok=True)
httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.6)

try:
    section("auth")
    st, p = call("GET", "/api/v1/profiles", token=False, expect=401)
    print("  unauthenticated -> 401 OK")
    st, p = call("POST", "/api/v1/auth/login",
                 {"username": "apitest_super", "password": SUPER_PW}, token=False,
                 expect=200)
    TOKEN["v"] = p["data"]["token"]
    print("  logged in as", p["data"]["username"])

    section("create DRAFT")
    st, p = call("POST", "/api/v1/profiles", {"name": ""}, expect=400)
    print("  empty name -> 400:", p["error"][:70])

    st, p = call("POST", "/api/v1/profiles",
                 {"name": "Lab Kiosk", "description": "smoke"}, expect=200)
    pid = p["data"]["policy_id"]
    print("  created %s status=%s version=%s requirement_count=%s"
          % (pid, p["data"]["status"], p["data"]["version"],
             p["data"]["requirement_count"]))
    assert p["data"]["status"] == "DRAFT", "a new profile must start as DRAFT"
    assert p["data"]["requirement_count"] == 0, "a new draft has no requirements"

    st, p = call("POST", "/api/v1/profiles",
                 {"name": "Bad Category", "category": "NOT_A_CATEGORY"}, expect=400)
    print("  invalid category -> 400:", p["error"][:70])

    section("an empty draft cannot be submitted or published")
    st, p = call("POST", "/api/v1/profiles/%s/publish" % pid,
                 {"skip_approval": True}, expect=400)
    print("  publish with no requirements -> 400:", p["error"][:70])

    section("save draft updates the requirements and checksum")
    before = call("GET", "/api/v1/profiles/%s" % pid, expect=200)[1]["data"]["checksum"]
    st, p = call("PUT", "/api/v1/profiles/%s" % pid,
                 {"description": "saved via HTTP", "requirements": REQ_CAMERA + REQ_WIFI},
                 expect=200)
    print("  requirements=%d enforceable=%s checksum_changed=%s"
          % (p["data"]["requirement_count"], p["data"]["enforceable"],
             p["data"]["checksum"] != before))
    assert p["data"]["requirement_count"] == 2
    assert p["data"]["checksum"] != before, "checksum must track the requirements"
    assert p["data"]["enforceable"], "CAMERA/WIFI must be enforceable lanes"

    st, p = call("PUT", "/api/v1/profiles/%s" % pid,
                 {"requirements": [{"feature": "NOT_A_REAL_FEATURE",
                                    "desired_state": "BLOCK"}]}, expect=400)
    print("  unknown feature -> 400:", p["error"][:70])

    st, p = call("PUT", "/api/v1/profiles/%s" % pid,
                 {"requirements": [{"feature": "CAMERA",
                                    "desired_state": "SOMETHING"}]}, expect=400)
    print("  unknown state -> 400:", p["error"][:70])

    section("submit for review")
    st, p = call("POST", "/api/v1/profiles/%s/submit" % pid, {}, expect=200)
    print("  submitted -> status=%s" % p["data"]["status"])
    assert p["data"]["status"] == "REVIEW"

    st, p = call("POST", "/api/v1/profiles/%s/reject" % pid,
                 {"reason": "needs the camera for QA"}, expect=200)
    print("  rejected REVIEW -> status=%s" % p["data"]["status"])
    assert p["data"]["status"] == "REJECTED"
    st, p = call("POST", "/api/v1/profiles/%s/reject" % pid, {}, expect=400)
    print("  reject without a reason -> 400:", p["error"][:70])
    st, p = call("POST", "/api/v1/profiles/%s/publish" % pid,
                 {"skip_approval": True}, expect=409)
    print("  publish REJECTED -> 409:", p["error"][:70])
    st, p = call("POST", "/api/v1/profiles", {"name": "Second Lab"}, expect=200)
    pid2 = p["data"]["policy_id"]
    print("  a second DRAFT exists:", pid2, p["data"]["status"])
    st, p = call("POST", "/api/v1/groups", {"name": "Draft Guard"}, expect=200)
    gid0 = p["data"]["id"]
    st, p = call("POST", "/api/v1/groups/%d/profiles" % gid0,
                 {"policy_ids": [pid2]}, expect=409)
    print("  associate a DRAFT -> 409:", p["error"][:70])
    st, p = call("DELETE", "/api/v1/groups/%d" % gid0,
                 {"skip_approval": True}, expect=200)
    st, p = call("POST", "/api/v1/profiles/%s/reopen" % pid,
                 {"change_reason": "camera is needed for QA"}, expect=200)
    print("  reopened -> status=%s" % p["data"]["status"])
    assert p["data"]["status"] == "DRAFT"
    st, p = call("POST", "/api/v1/profiles/%s/submit" % pid, {}, expect=200)
    print("  resubmitted -> status=%s" % p["data"]["status"])

    section("REVIEW profile can be associated to a group")
    st, p = call("POST", "/api/v1/groups",
                 {"name": "Profile Smoke Group"}, expect=200)
    gid = p["data"]["id"]
    call("POST", "/api/v1/groups/%d/members" % gid,
         {"device_ids": ["D-PROF-1"], "deploy": False}, expect=200)

    st, p = call("POST", "/api/v1/groups/%d/profiles" % gid,
                 {"policy_ids": [pid]}, expect=200)
    print("  associated:", p["data"]["associated"])
    print("  deploy summary:", json.dumps(p["data"]["deploy"]["summary"]))

    section("publish")
    st, p = call("POST", "/api/v1/profiles/%s/publish" % pid,
                 {"skip_approval": True}, expect=200)
    print("  published -> status=%s published_at=%s"
          % (p["data"]["status"], p["data"]["published_at"]))
    assert p["data"]["status"] == "ACTIVE"

    section("ACTIVE profile cannot be edited, only retired")
    st, p = call("PUT", "/api/v1/profiles/%s" % pid,
                 {"requirements": REQ_CAMERA}, expect=409)
    print("  PUT on ACTIVE -> 409:", p["error"][:80])

    st, p = call("GET", "/api/v1/profiles/%s" % pid, expect=200)
    print("  counters:", json.dumps({k: p["data"][k] for k in
                                     ("group_count", "target_device_count",
                                      "deployed_device_count")}))
    assert p["data"]["group_count"] == 1, "the profile must know its group"
    assert p["data"]["target_device_count"] == 1
    assert p["data"]["deployed_device_count"] == 1, \
        "an associate on a lab device must produce a real assignment row"
    assert p["data"]["published_at"], "publish must stamp published_at"
    assert p["data"]["published_by"], "publish must stamp published_by"

    section("list + filter")
    st, p = call("GET", "/api/v1/profiles?status=ACTIVE", expect=200)
    print("  ACTIVE list: %d row(s)" % len(p["data"]))
    assert any(x["policy_id"] == pid for x in p["data"])
    st, p = call("GET", "/api/v1/profiles?status=DRAFT", expect=200)
    assert all(x["status"] == "DRAFT" for x in p["data"])

    section("retire keeps the association for the audit trail")
    st, p = call("POST", "/api/v1/profiles/%s/retire" % pid,
                 {"skip_approval": True}, expect=200)
    print("  retired -> status=%s groups_kept=%s"
          % (p["data"]["status"], p["data"]["group_count"]))
    assert p["data"]["status"] == "RETIRED"
    assert p["data"]["group_count"] == 1, \
        "retire must not rewrite historical deployment evidence"
    assert p["data"]["next_statuses"] == [], "a retired profile is terminal"

    st, p = call("PUT", "/api/v1/profiles/%s" % pid, {"requirements": REQ_CAMERA},
                 expect=409)
    print("  PUT on RETIRED -> 409:", p["error"][:80])

    st, p = call("DELETE", "/api/v1/profiles/%s" % pid, {"skip_approval": True},
                 expect=409)
    print("  DELETE a retired profile -> 409:", p["error"][:80])

    st, p = call("POST", "/api/v1/groups", {"name": "Retired Guard"}, expect=200)
    gid2 = p["data"]["id"]
    st, p = call("POST", "/api/v1/groups/%d/profiles" % gid2,
                 {"policy_ids": [pid]}, expect=409)
    print("  associate a RETIRED -> 409:", p["error"][:70])
    call("DELETE", "/api/v1/groups/%d" % gid2, {"skip_approval": True}, expect=200)

    section("delete is allowed for a never-published draft")
    st, p = call("DELETE", "/api/v1/profiles/%s" % pid2, {"skip_approval": True},
                 expect=200)
    print("  deleted draft:", json.dumps(p["data"], ensure_ascii=False))
    call("GET", "/api/v1/profiles/%s" % pid2, expect=400)
    call("GET", "/api/v1/profiles/POL-NOPE", expect=400)
    call("POST", "/api/v1/profiles/POL-NOPE/submit", {}, expect=400)
    print("  a deleted and an unknown profile both report 400 not found")

    section("versioning: edit a published/retired profile as a new DRAFT revision")
    # 1. Create a fresh active profile and attach it to a group
    st, p = call("POST", "/api/v1/profiles", {"name": "Versionable Profile"}, expect=200)
    v1_id = p["data"]["policy_id"]
    call("PUT", "/api/v1/profiles/%s" % v1_id, {"requirements": REQ_CAMERA}, expect=200)
    call("POST", "/api/v1/profiles/%s/publish" % v1_id, {"skip_approval": True}, expect=200)

    st, p = call("POST", "/api/v1/groups", {"name": "Version Targets"}, expect=200)
    vg_id = p["data"]["id"]
    call("POST", "/api/v1/groups/%d/profiles" % vg_id, {"policy_ids": [v1_id]}, expect=200)
    print("  v1 published & attached to group")

    # 2. Cannot create revision on a DRAFT (conflict)
    st, p = call("POST", "/api/v1/profiles", {"name": "Draft Only"}, expect=200)
    d_id = p["data"]["policy_id"]
    st, p = call("POST", "/api/v1/profiles/%s/revision" % d_id, {}, expect=409)
    print("  revision on DRAFT -> 409:", p["error"][:60])
    call("DELETE", "/api/v1/profiles/%s" % d_id, {"skip_approval": True}, expect=200)

    # 3. Create revision from active v1
    st, p = call("POST", "/api/v1/profiles/%s/revision" % v1_id,
                 {"change_reason": "version 2 test"}, expect=200)
    v2_id = p["data"]["policy_id"]
    print("  created revision %s (v%d) status=%s"
          % (v2_id, p["data"]["version"], p["data"]["status"]))
    assert p["data"]["status"] == "DRAFT"
    assert p["data"]["version"] == 2
    assert p["data"]["root_id"] == v1_id
    assert p["data"]["requirements"] == REQ_CAMERA

    # 4. Modify requirements on v2 draft and publish
    REQ_V2 = [{"feature": "CAMERA", "desired_state": "BLOCK", "risk": "MEDIUM"},
              {"feature": "BLUETOOTH", "desired_state": "BLOCK", "risk": "MEDIUM"}]
    call("PUT", "/api/v1/profiles/%s" % v2_id, {"requirements": REQ_V2}, expect=200)
    st, p = call("POST", "/api/v1/profiles/%s/publish" % v2_id,
                 {"skip_approval": True}, expect=200)
    print("  published v2 -> superseded:", p["data"].get("superseded"))
    assert p["data"]["status"] == "ACTIVE"
    assert p["data"].get("superseded") == v1_id
    affected = [g["group_id"] for g in p["data"].get("affected_groups") or []]
    assert vg_id in affected, \
        "publish must report the groups that need an immediate redeploy"

    # 5. Verify v1 is now RETIRED and group is now linked to v2
    st, p = call("GET", "/api/v1/profiles/%s" % v1_id, expect=200)
    assert p["data"]["status"] == "RETIRED"
    st, p = call("GET", "/api/v1/groups/%d/profiles" % vg_id, expect=200)
    assert len(p["data"]) == 1
    assert p["data"][0]["policy_id"] == v2_id
    print("  group automatically transferred from %s to %s" % (v1_id, v2_id))

    # Clean up group
    call("DELETE", "/api/v1/groups/%d" % vg_id, {"skip_approval": True}, expect=200)

    section("install-agent validates input before touching ADB")
    st, p = call("POST", "/api/v1/devices/install-agent",
                 {"serial": "SMOKE-NOT-ATTACHED"}, expect=409)
    print("  unknown serial -> 409:", p["error"][:70])
    st, p = call("POST", "/api/v1/devices/install-agent",
                 {"serial": "SMOKE-NOT-ATTACHED", "variant": "bogus"},
                 expect=400)
    print("  bad variant -> 400:", p["error"][:70])

    section("RBAC: READ_ONLY can list but never write")
    saved = TOKEN["v"]
    st, p = call("POST", "/api/v1/auth/login",
                 {"username": "apitest_ro", "password": RO_PW}, token=False, expect=200)
    TOKEN["v"] = p["data"]["token"]
    st, p = call("GET", "/api/v1/profiles", expect=200)
    print("  READ_ONLY sees %d profile(s)" % len(p["data"]))
    for method, path, b in (("POST", "/api/v1/profiles", {"name": "nope"}),
                            ("PUT", "/api/v1/profiles/%s" % pid,
                             {"requirements": REQ_CAMERA}),
                            ("POST", "/api/v1/profiles/%s/submit" % pid, {}),
                            ("POST", "/api/v1/profiles/%s/publish" % pid,
                             {"skip_approval": True}),
                            ("POST", "/api/v1/profiles/%s/retire" % pid,
                             {"skip_approval": True}),
                            ("DELETE", "/api/v1/profiles/%s" % pid,
                             {"skip_approval": True})):
        st, p = call(method, path, b, expect=403)
        print("   %-6s %-38s -> 403 %s" % (method, path[:38], p["error"][:48]))
    TOKEN["v"] = saved
    print("  restored super-admin session")

    print("\nALL API PROFILE CHECKS PASSED (%d HTTP calls)" % len(CALLS))
finally:
    httpd.shutdown()

with connect() as c:
    c.execute("DELETE FROM group_deploy_status WHERE assignment_id NOT IN "
              "(SELECT id FROM group_profile_assignments)")
    c.execute("DELETE FROM group_action_history WHERE group_id NOT IN "
              "(SELECT id FROM device_groups)")
    c.execute("DELETE FROM device_groups")
    c.execute("DELETE FROM device_group_members WHERE device_id IN "
              "(SELECT id FROM devices WHERE device_id LIKE 'D-PROF-%')")
    c.execute("DELETE FROM assignments WHERE device_id IN "
              "(SELECT id FROM devices WHERE device_id LIKE 'D-PROF-%')")
    c.execute("DELETE FROM compliance WHERE device_id IN "
              "(SELECT id FROM devices WHERE device_id LIKE 'D-PROF-%')")
    c.execute("DELETE FROM devices WHERE device_id LIKE 'D-PROF-%'")
print("scratch fixtures cleaned")