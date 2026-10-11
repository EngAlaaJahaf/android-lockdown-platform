# -*- coding: utf-8 -*-
"""Device Groups: membership implies the group's profiles apply.

Each test drives backend.groups directly against a throw-away scratch database
(migrated per test), so nothing here can touch the real database/alp.db. The
end-to-end HTTP contract (RBAC, status codes, approval gates) is covered by
scripts/api_groups_smoke.py.
"""
import io
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for _sub in ("backend", "policy-engine", "capability-engine",
             "verification-engine", "vendor-adapters", "compatibility"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

from backend.db import connect, run_migrations             # noqa: E402
from backend import groups as G                     # noqa: E402

TAG = "GRP-TEST"


def _seed_device(device_id: str):
    with connect() as c:
        c.execute("DELETE FROM compliance WHERE device_id IN "
                  "(SELECT id FROM devices WHERE device_id=?)", (device_id,))
        c.execute("DELETE FROM assignments WHERE device_id IN "
                  "(SELECT id FROM devices WHERE device_id=?)", (device_id,))
        c.execute("DELETE FROM device_group_members WHERE device_id IN "
                  "(SELECT id FROM devices WHERE device_id=?)", (device_id,))
        c.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
        # ON CONFLICT upsert, not INSERT OR REPLACE: REPLACE is a DELETE+INSERT
        # and compliance/assignments hold ON DELETE NO ACTION refs to devices.
        c.execute("INSERT INTO devices (device_id, serial, manufacturer, model, "
                  "android_version, api_level, is_lab) VALUES (?,?,?,?,?,?,1) "
                  "ON CONFLICT(device_id) DO UPDATE SET serial=excluded.serial",
                  (device_id, "SER-" + device_id, "Samsung", "SM-A145P", 15, 35))


def _delete_policy(policy_id: str):
    """Remove a test profile and every row that references it.

    group_profile_assignments / assignments / compliance all hold FKs to policies
    (some ON DELETE NO ACTION), so the test clears them explicitly. The group is
    deleted first: its assignments cascade away, which is the order the schema
    actually permits.
    """
    with connect() as c:
        row = c.execute("SELECT id FROM policies WHERE policy_id=?",
                        (policy_id,)).fetchone()
        if not row:
            return
        pk = row["id"]
        c.execute("DELETE FROM group_deploy_status WHERE assignment_id IN "
                  "(SELECT id FROM group_profile_assignments WHERE policy_id=?)", (pk,))
        c.execute("DELETE FROM group_profile_assignments WHERE policy_id=?", (pk,))
        c.execute("DELETE FROM assignments WHERE policy_id=?", (pk,))
        c.execute("DELETE FROM compliance WHERE policy_id=?", (pk,))
        c.execute("DELETE FROM policies WHERE policy_id=?", (policy_id,))


def _seed_policy(policy_id: str, status: str = "ACTIVE", features=None):
    import json
    features = features or ["CAMERA", "WIFI"]
    with connect() as c:
        _delete_policy(policy_id)
        c.execute("INSERT INTO policies (policy_id, display_name, category, status, "
                  "requirements) VALUES (?,?,?,?,?)",
                  (policy_id, "pytest " + policy_id, "CORPORATE_DEFAULT", status,
                   json.dumps([{"feature": f, "desired_state": "BLOCK",
                                "risk": "MEDIUM"} for f in features])))


class GroupTestBase(unittest.TestCase):
    def setUp(self):
        self._prev_db = os.environ.get("ALP_DB")
        fd, self._db = tempfile.mkstemp(prefix="alp_grp_", suffix=".db")
        os.close(fd)
        os.environ["ALP_DB"] = self._db
        run_migrations(self._db)
        self.dev = TAG + "-D1"
        self.dev2 = TAG + "-D2"
        self.pol = TAG + "-P1"
        _seed_device(self.dev)
        _seed_device(self.dev2)
        _seed_policy(self.pol)
        self.g = G.create_group(TAG + " group", created_by="pytest")

    def tearDown(self):
        try:
            G.delete_group(self.g["id"])
        except G.GroupError:
            pass
        if self._prev_db is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev_db
        for suf in ("", "-wal", "-shm"):
            try:
                os.remove(self._db + suf)
            except OSError:
                pass

    def db_untouched(self) -> bool:
        """The production database must exist but must never be written by a test."""
        prod = os.path.join(ROOT, "database", "alp.db")
        return os.path.abspath(prod) != os.path.abspath(self._db)


class DisassociationDeliveryTests(GroupTestBase):
    def prepare_assignment(self):
        G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                      mfa_ok=True, deploy=False)
        G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                             mfa_ok=True, deploy=False)

    def test_offline_disassociation_produces_signed_clear_on_next_pull(self):
        from unittest.mock import patch
        from backend.agent_policy_pull import build_apply_envelope
        self.prepare_assignment()
        with patch("backend.workflows.attached_serials", return_value=[]):
            result = G.disassociate_profile(self.g["id"], self.pol)
        self.assertEqual(result["reconciliation"][0]["status"], "pending_sync")
        answer = build_apply_envelope(self.dev, signing_key="test-key")
        self.assertEqual(answer["state"], "delivered")
        self.assertEqual(answer["envelope"]["action"], "CLEAR_POLICY")
        self.assertEqual(answer["envelope"]["device_id"], self.dev)
        self.assertEqual(answer["fingerprint"], "unassigned")

    def test_online_disassociation_sends_clear(self):
        from unittest.mock import patch, Mock
        self.prepare_assignment()
        send = Mock(return_value={"ok": True})
        with patch("backend.workflows.attached_serials", return_value=["SER-" + self.dev]), \
                patch("backend.channel.adb_channel", return_value=(send, {})):
            result = G.disassociate_profile(self.g["id"], self.pol)
        self.assertEqual(result["reconciliation"][0]["status"], "sent")
        self.assertEqual(send.call_args.args[1], "CLEAR_POLICY")

    def test_unknown_device_never_receives_clear(self):
        from backend.agent_policy_pull import build_apply_envelope
        self.assertNotIn("envelope", build_apply_envelope("missing-device"))

    def test_remaining_group_keeps_policy_effective(self):
        from unittest.mock import patch
        from backend.agent_policy_pull import policy_for_device
        self.prepare_assignment()
        other = G.create_group(TAG + " remaining")
        G.add_members(other["id"], [self.dev], op_role="FLEET_ADMIN",
                      mfa_ok=True, deploy=False)
        G.associate_profiles(other["id"], [self.pol], op_role="FLEET_ADMIN",
                             mfa_ok=True, deploy=False)
        with patch("backend.workflows.attached_serials", return_value=[]):
            G.disassociate_profile(self.g["id"], self.pol)
        answer = policy_for_device(self.dev)
        self.assertEqual(answer["state"], "up_to_date")
        self.assertEqual(answer["policy_id"], self.pol)


class GroupCrudTests(GroupTestBase):
    def test_create_assigns_unique_key_and_counts(self):
        self.assertTrue(self.g["group_key"].startswith("grp-test-group"))
        self.assertEqual(self.g["members"], 0)
        self.assertEqual(self.g["profiles"], 0)
        second = G.create_group(TAG + " group", created_by="pytest")
        try:
            self.assertNotEqual(second["group_key"], self.g["group_key"],
                                "a duplicate name must still get a distinct key")
        finally:
            G.delete_group(second["id"])

    def test_blank_name_rejected(self):
        with self.assertRaises(G.GroupError):
            G.create_group("   ", created_by="pytest")

    def test_bad_membership_type_rejected(self):
        with self.assertRaises(G.GroupError):
            G.create_group(TAG + " dyn", membership_type="WEIRD")

    def test_dynamic_group_stores_criteria(self):
        g = G.create_group(TAG + " dyn", membership_type="DYNAMIC",
                           created_by="pytest", criteria_json='{"model":"SM"}')
        try:
            self.assertEqual(g["membership_type"], "DYNAMIC")
            with connect() as c:
                row = c.execute("SELECT criteria_json FROM device_groups WHERE id=?",
                                (g["id"],)).fetchone()
            self.assertEqual(row["criteria_json"], '{"model":"SM"}')
        finally:
            G.delete_group(g["id"])

    def test_update_and_missing_group(self):
        up = G.update_group(self.g["id"], description="changed")
        self.assertEqual(up["description"], "changed")
        with self.assertRaises(G.GroupError):
            G.get_group(99999999)


class MembershipTests(GroupTestBase):
    def test_unregistered_device_is_never_invented(self):
        with self.assertRaises(G.GroupError) as ctx:
            G.add_members(self.g["id"], [TAG + "-NOPE"], op_role="FLEET_ADMIN",
                          mfa_ok=True)
        self.assertIn("not registered", str(ctx.exception))
        with connect() as c:
            n = c.execute("SELECT COUNT(*) n FROM devices WHERE device_id=?",
                          (TAG + "-NOPE",)).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_add_is_idempotent(self):
        a = G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
        self.assertEqual(a["added"], [self.dev])
        b = G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
        self.assertEqual(b["added"], [])
        self.assertEqual(b["already_present"], [self.dev])
        self.assertEqual(G.get_group(self.g["id"])["members"], 1)

    def test_remove_member(self):
        G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                      mfa_ok=True, deploy=False)
        out = G.remove_member(self.g["id"], self.dev)
        self.assertTrue(out["removed"])
        self.assertEqual(G.get_group(self.g["id"])["members"], 0)

    def test_joining_a_group_deploys_its_profiles(self):
        """The behaviour the admin asked for: membership implies the group's
        profile applies to that device immediately."""
        G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                             mfa_ok=True, deploy=False)
        out = G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                            mfa_ok=True, deploy=True)
        d = out["deploy"]
        self.assertEqual(d["summary"]["total"], 1,
                         "adding a member must deploy the group's profile to it")
        self.assertEqual(d["results"][0]["device_id"], self.dev)
        self.assertEqual(d["results"][0]["policy_id"], self.pol)

    def test_move_device_between_groups(self):
        other = G.create_group(TAG + " other", created_by="pytest")
        try:
            G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
            G.move_device(self.g["id"], other["id"], self.dev, moved_by="pytest")
            self.assertEqual(G.get_group(self.g["id"])["members"], 0)
            self.assertEqual(G.get_group(other["id"])["members"], 1)
        finally:
            G.delete_group(other["id"])


class AssociationTests(GroupTestBase):
    def test_associate_is_idempotent(self):
        a = G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                                 mfa_ok=True, deploy=False)
        self.assertEqual(a["associated"], [self.pol])
        b = G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                                 mfa_ok=True, deploy=False)
        self.assertEqual(b["associated"], [])
        self.assertEqual(b["already_associated"], [self.pol])

    def test_draft_profile_is_refused(self):
        draft = TAG + "-PDRAFT"
        _seed_policy(draft, status="DRAFT")
        try:
            out = G.associate_profiles(self.g["id"], [draft], op_role="FLEET_ADMIN",
                                       mfa_ok=True, deploy=False)
            self.assertEqual(out["associated"], [])
            self.assertEqual(out["rejected"][0]["policy_id"], draft)
            self.assertEqual(out["rejected"][0]["status"], "DRAFT")
        finally:
            _delete_policy(draft)

    def test_unknown_profile_rejected(self):
        with self.assertRaises(G.GroupError):
            G.associate_profiles(self.g["id"], [TAG + "-MISSING"],
                                 op_role="FLEET_ADMIN", mfa_ok=True, deploy=False)

    def test_association_deploys_to_existing_members(self):
        G.add_members(self.g["id"], [self.dev, self.dev2], op_role="FLEET_ADMIN",
                      mfa_ok=True, deploy=False)
        out = G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                                   mfa_ok=True, deploy=True)
        self.assertEqual(out["deploy"]["summary"]["total"], 2)

    def test_disassociate_is_scoped_to_one_group(self):
        """Disassociating from group A must not strip the same profile from
        group B, even for a device that is in both."""
        other = G.create_group(TAG + " other", created_by="pytest")
        try:
            G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
            G.add_members(other["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
            G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                                 mfa_ok=True, deploy=True)
            G.associate_profiles(other["id"], [self.pol], op_role="FLEET_ADMIN",
                                 mfa_ok=True, deploy=True)
            G.disassociate_profile(self.g["id"], self.pol)
            self.assertEqual(G.list_group_profiles(self.g["id"]), [])
            kept = [p["policy_id"] for p in G.list_group_profiles(other["id"])]
            self.assertIn(self.pol, kept,
                          "group B must keep the profile and its assignment")
            st = G.deploy_status(_conn(), other["id"],
                                 _policy_fk(self.pol))
            self.assertGreater(st["total_target_count"], 0,
                               "the surviving group's status must remain intact")
        finally:
            G.delete_group(other["id"])


class DeployStatusTests(GroupTestBase):
    def test_no_device_attached_never_reads_as_success(self):
        G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                      mfa_ok=True, deploy=True)
        G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                             mfa_ok=True, deploy=True)
        row = G.list_group_profiles(self.g["id"])[0]
        self.assertEqual(row["policy_id"], self.pol,
                         "the API must expose the text policy_id, not the FK")
        st = row["execution_status"]
        self.assertEqual(st["success_count"], 0)
        self.assertEqual(st["label"], "STAGED")
        self.assertNotEqual(st["label"], "APPLIED")

    def test_counters_cover_this_groups_members_only(self):
        G.add_members(self.g["id"], [self.dev, self.dev2], op_role="FLEET_ADMIN",
                      mfa_ok=True, deploy=True)
        G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                             mfa_ok=True, deploy=True)
        st = G.list_group_profiles(self.g["id"])[0]["execution_status"]
        self.assertEqual(st["total_target_count"], 2)
        buckets = (st["success_count"] + st["yet_to_apply_count"]
                   + st["failed_count"] + st["not_applicable_count"])
        self.assertEqual(buckets, st["total_target_count"],
                         "buckets must add up to the target count")

    def test_group_isolation_in_status(self):
        other = G.create_group(TAG + " other", created_by="pytest")
        try:
            G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
            G.add_members(other["id"], [self.dev2], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
            G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                                 mfa_ok=True, deploy=False)
            G.associate_profiles(other["id"], [self.pol], op_role="FLEET_ADMIN",
                                 mfa_ok=True, deploy=False)
            a = G.group_status(self.g["id"])
            b = G.group_status(other["id"])
            self.assertEqual(a["expected_targets"], 1)
            self.assertEqual(b["expected_targets"], 1)
            self.assertEqual(a["label"], "NOT_DEPLOYED")
        finally:
            G.delete_group(other["id"])

    def test_group_status_rollup_sums_profiles(self):
        second = TAG + "-P2"
        _seed_policy(second)
        try:
            G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=True)
            G.associate_profiles(self.g["id"], [self.pol, second],
                                 op_role="FLEET_ADMIN", mfa_ok=True, deploy=True)
            g = G.group_status(self.g["id"])
            self.assertEqual(g["profiles"], 2)
            self.assertEqual(g["expected_targets"], 2)
            self.assertEqual(g["counts"]["total"], 2)
            self.assertEqual(g["counts"]["success"], 0)
        finally:
            _delete_policy(second)

    def test_action_history_is_recorded(self):
        G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                      mfa_ok=True, deploy=True)
        G.associate_profiles(self.g["id"], [self.pol], op_role="FLEET_ADMIN",
                             mfa_ok=True, deploy=True)
        actions = [a["action_id"] for a in G.list_group_actions(self.g["id"])]
        self.assertIn("ADD_DEVICE", actions)
        self.assertIn("ASSOCIATE_PROFILE", actions)


class VendorOnlyProfileTests(GroupTestBase):
    def test_non_enforceable_profile_is_not_applicable(self):
        """A profile made only of OEM-only lanes must be reported, not hollowly
        deployed as a success."""
        vendor = TAG + "-PVENDOR"
        _seed_policy(vendor, features=["S_VOICE"])
        try:
            G.add_members(self.g["id"], [self.dev], op_role="FLEET_ADMIN",
                          mfa_ok=True, deploy=False)
            G.associate_profiles(self.g["id"], [vendor], op_role="FLEET_ADMIN",
                                 mfa_ok=True, deploy=True)
            st = G.list_group_profiles(self.g["id"])[0]["execution_status"]
            self.assertEqual(st["not_applicable_count"], 1)
            self.assertEqual(st["success_count"], 0,
                             "an unenforceable profile must never count as applied")
        finally:
            _delete_policy(vendor)


class CascadeTests(GroupTestBase):
    def test_delete_removes_members_and_assignments(self):
        gid = self.g["id"]
        G.add_members(gid, [self.dev], op_role="FLEET_ADMIN", mfa_ok=True,
                      deploy=False)
        G.associate_profiles(gid, [self.pol], op_role="FLEET_ADMIN",
                             mfa_ok=True, deploy=True)
        G.delete_group(gid)
        with connect() as c:
            for t in ("device_group_members", "group_profile_assignments"):
                n = c.execute("SELECT COUNT(*) n FROM %s WHERE group_id=?" % t,
                              (gid,)).fetchone()["n"]
                self.assertEqual(n, 0, "%s must cascade" % t)


def _conn():
    c = connect()
    return c


def _policy_fk(policy_id: str) -> int:
    with connect() as c:
        return c.execute("SELECT id FROM policies WHERE policy_id=?",
                         (policy_id,)).fetchone()["id"]


class ApprovalGateConsistencyTests(unittest.TestCase):
    """Every approval gate in the HTTP API must honour `skip_approval`.

    The group members and group profiles association routes were built with
    `approved = bool(body.get("approver1"))` only. The console sends
    `skip_approval: true`, so those two routes answered 403
    "BULK_APPLY requires approval gate" and the Add-to-Group button did nothing.
    Every other route already OR'd in `skip_approval`; this test keeps them from
    drifting apart again.
    """

    @staticmethod
    def _server_source():
        path = os.path.join(ROOT, "backend", "api", "server.py")
        with io.open(path, encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def _gates(src):
        """Yield (start_offset, block_text) for every approval={...} literal."""
        out = []
        for m in re.finditer(r"approval=\{", src):
            depth, i = 0, m.end() - 1
            while i < len(src):
                if src[i] == "{":
                    depth += 1
                elif src[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            out.append((m.start(), src[m.end():i]))
        return out

    def test_every_approval_gate_accepts_skip_approval(self):
        gates = self._gates(self._server_source())
        self.assertTrue(gates, "no approval gate found in server.py")
        # Only gates that read the request body inline are checked. Some routes
        # hoist the decision into a local first (e.g. /recovery computes
        # `approved = bool(skip_approval) or bool(approver1)`) and the vault
        # routes are unconditionally `approved: True` by design.
        inline = [(_o, b) for _o, b in gates if "approved\": bool(" in b]
        self.assertGreaterEqual(len(inline), 7, "expected the usual inline gates")
        bad = [b.strip().replace("\n", " ")[:140] for _o, b in inline
               if "skip_approval" not in b]
        self.assertFalse(
            bad,
            "these approval gates ignore skip_approval, so the console gets "
            "403 and the action silently fails: %r" % bad)

    def test_members_and_profiles_routes_accept_skip_approval(self):
        src = self._server_source()
        for reason in ("add members", "associate profiles"):
            idx = src.find('body.get("reason", "%s")' % reason)
            self.assertNotEqual(idx, -1, "route with reason %r not found" % reason)
            window = src[max(0, idx - 500):idx]
            self.assertIn(
                "skip_approval", window,
                "the %r route must honour skip_approval like every other gate"
                % reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
