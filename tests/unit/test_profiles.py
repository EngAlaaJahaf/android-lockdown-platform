# -*- coding: utf-8 -*-
"""Profiles: the console draft lifecycle (DRAFT -> REVIEW -> ACTIVE -> RETIRED).

Isolated on a throwaway database via ALP_DB, following tests/unit/test_recovery.py,
so a lifecycle test can never touch database/alp.db. The HTTP contract (status
codes, RBAC, approval gates) is covered by scripts/api_profiles_smoke.py.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for _sub in ("policy-engine", "capability-engine", "verification-engine",
             "vendor-adapters", "compatibility"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

from backend.db import connect, run_migrations           # noqa: E402
from backend import groups as G                          # noqa: E402
from backend import profiles as P                        # noqa: E402

REQS = [{"feature": "CAMERA", "desired_state": "BLOCK", "risk": "HIGH"},
        {"feature": "USB", "desired_state": "RESTRICT", "risk": "MEDIUM"}]


class ProfileBase(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("ALP_DB")
        self._groups = []
        fd, self.db = tempfile.mkstemp(prefix="alp_prof_", suffix=".db")
        os.close(fd)
        os.environ["ALP_DB"] = self.db
        run_migrations(self.db)
        with connect() as c:
            c.execute("INSERT INTO devices (device_id, serial, manufacturer, model, "
                      "android_version, api_level) "
                      "VALUES ('PRF-D1','SER-1','google','Pixel 7',14,34)")

    def track_group(self, name="PRF group") -> dict:
        """Create a group and remember it. Tracked here rather than with
        addCleanup because tearDown removes the database file first, and
        addCleanup callbacks run after that."""
        g = G.create_group(name, created_by="pytest")
        self._groups.append(g["id"])
        return g

    def tearDown(self):
        for gid in self._groups:
            try:
                G.delete_group(gid)
            except G.GroupError:
                pass
        if self._prev is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db + suffix)
            except OSError:
                pass

    def draft(self, name="Kiosk Lockdown", reqs=REQS):
        p = P.create_draft(name, description="front desk", created_by="pytest")
        if reqs is not None:
            p = P.save_draft(p["policy_id"], requirements=reqs, changed_by="pytest")
        return p


class DraftCreationTests(ProfileBase):
    def test_create_draft_is_empty_and_not_published(self):
        p = P.create_draft("Kiosk Lockdown", description="front desk",
                           created_by="pytest")
        self.assertEqual(p["status"], "DRAFT")
        self.assertEqual(p["requirement_count"], 0)
        self.assertEqual(p["checksum"], P._checksum([]))
        self.assertEqual(p["modified_at"], p["created_at"])
        self.assertIsNone(p["published_at"])
        self.assertEqual(p["published_by"], "")

    def test_blank_name_and_bad_category_rejected(self):
        with self.assertRaises(P.ProfileError):
            P.create_draft("   ")
        with self.assertRaises(P.ProfileError):
            P.create_draft("X", category="NOT_A_CATEGORY")

    def test_duplicate_names_get_distinct_ids(self):
        a = P.create_draft("Dup", created_by="pytest")["policy_id"]
        b = P.create_draft("Dup", created_by="pytest")["policy_id"]
        self.assertNotEqual(a, b)
        with connect() as c:
            n = c.execute("SELECT COUNT(*) n FROM policies WHERE policy_id IN (?,?)",
                          (a, b)).fetchone()["n"]
        self.assertEqual(n, 2)

    def test_new_draft_reports_zero_counters(self):
        p = P.create_draft("Fresh", created_by="pytest")
        row = [r for r in P.list_profiles() if r["policy_id"] == p["policy_id"]][0]
        self.assertEqual((row["group_count"], row["target_device_count"],
                          row["deployed_device_count"]), (0, 0, 0))


class RequirementValidationTests(ProfileBase):
    def test_every_bad_row_is_reported_at_once(self):
        p = P.create_draft("Bad", created_by="pytest")
        with self.assertRaises(P.ProfileError) as ctx:
            P.save_draft(p["policy_id"], changed_by="pytest", requirements=[
                {"feature": "NOPE", "desired_state": "BLOCK"},
                {"feature": "CAMERA", "desired_state": "MAYBE"},
                {"desired_state": "BLOCK"},
                {"feature": "USB", "desired_state": "BLOCK", "risk": "SPICY"},
            ])
        msg = str(ctx.exception)
        for frag in ("unknown feature NOPE", "desired_state must be one of",
                     "row 2 has no feature", "risk must be one of"):
            self.assertIn(frag, msg)

    def test_requirements_are_normalised(self):
        p = self.draft(reqs=[{"feature": " camera ", "desired_state": "block",
                              "risk": "high"}])
        self.assertEqual(p["requirements"],
                         [{"feature": "CAMERA", "desired_state": "BLOCK", "risk": "HIGH"}])

    def test_checksum_tracks_the_requirement_set(self):
        p = self.draft()
        one = P.save_draft(p["policy_id"], requirements=REQS[:1], changed_by="pytest")
        two = P.save_draft(p["policy_id"], requirements=REQS, changed_by="pytest")
        self.assertNotEqual(one["checksum"], two["checksum"])
        self.assertEqual(two["checksum"], P._checksum(REQS))

    def test_save_without_requirements_keeps_them(self):
        p = self.draft()
        p = P.save_draft(p["policy_id"], description="updated", changed_by="pytest")
        self.assertEqual(p["requirement_count"], 2)
        self.assertEqual(p["description"], "updated")

    def test_changing_only_the_name_keeps_the_stored_requirements(self):
        p = self.draft()
        p = P.save_draft(p["policy_id"], name="Renamed", changed_by="pytest")
        self.assertEqual(p["name"], "Renamed")
        self.assertEqual(p["requirement_count"], 2)


class LifecycleTests(ProfileBase):
    def test_published_profile_is_not_editable(self):
        p = self.draft()
        p = P.publish_draft(p["policy_id"], changed_by="pytest")
        self.assertEqual(p["status"], "ACTIVE")
        self.assertIsNotNone(p["published_at"])
        self.assertEqual(p["published_by"], "pytest")
        with self.assertRaises(P.ProfileConflict) as ctx:
            P.save_draft(p["policy_id"], requirements=[], changed_by="pytest")
        self.assertIn("only DRAFT profiles are editable", str(ctx.exception))

    def test_published_profile_is_not_deleted(self):
        p = self.draft()
        P.publish_draft(p["policy_id"], changed_by="pytest")
        with self.assertRaises(P.ProfileConflict):
            P.delete_profile(p["policy_id"])
        with connect() as c:
            self.assertIsNotNone(c.execute(
                "SELECT 1 FROM policies WHERE policy_id=?",
                (p["policy_id"],)).fetchone(),
                "retire, don't erase, deployment history")

    def test_empty_profile_cannot_be_published(self):
        p = P.create_draft("Empty", created_by="pytest")
        with self.assertRaises(P.ProfileError) as ctx:
            P.publish_draft(p["policy_id"], changed_by="pytest")
        self.assertIn("no requirements", str(ctx.exception))
        self.assertEqual(P.get_profile(p["policy_id"])["status"], "DRAFT")

    def test_review_reject_reopen_round_trip(self):
        p = self.draft()
        p = P.submit_for_review(p["policy_id"], changed_by="pytest")
        self.assertEqual(p["status"], "REVIEW")
        self.assertEqual(sorted(p["next_statuses"]), ["ACTIVE", "DRAFT", "REJECTED"])
        p = P.reject_profile(p["policy_id"], reason="needs the OEM API",
                             changed_by="reviewer")
        self.assertEqual(p["status"], "REJECTED")
        self.assertEqual(p["next_statuses"], ["DRAFT"])
        self.assertEqual(P.delete_profile(p["policy_id"]), {"deleted": p["policy_id"]})

    def test_rejected_profile_can_be_reworked_and_resubmitted(self):
        p = self.draft()
        P.submit_for_review(p["policy_id"], changed_by="pytest")
        P.reject_profile(p["policy_id"], reason="needs the OEM API",
                         changed_by="reviewer")
        # a rejection must not be a dead end
        with self.assertRaises(P.ProfileConflict):
            P.submit_for_review(p["policy_id"], changed_by="pytest")
        p = P.reopen_rejected(p["policy_id"], changed_by="author",
                              change_reason="swapped in the OEM lane")
        self.assertEqual(p["status"], "DRAFT")
        self.assertEqual(p["modified_by"], "author")
        p = P.save_draft(p["policy_id"], requirements=REQS, changed_by="author")
        self.assertEqual(p["status"], "DRAFT")
        p = P.submit_for_review(p["policy_id"], changed_by="author")
        self.assertEqual(p["status"], "REVIEW")
        p = P.publish_draft(p["policy_id"], changed_by="author")
        self.assertEqual(p["status"], "ACTIVE")

    def test_reopen_only_applies_to_a_rejected_profile(self):
        p = self.draft()
        with self.assertRaises(P.ProfileConflict):
            P.reopen_rejected(p["policy_id"])
        with self.assertRaises(P.ProfileError):
            P.reopen_rejected("POL-NOPE")
        # REVIEW -> DRAFT is the "send it back to the author" path, and it must
        # not let a profile be submitted for review twice in a row.
        P.submit_for_review(p["policy_id"], changed_by="pytest")
        with self.assertRaises(P.ProfileConflict):
            P.submit_for_review(p["policy_id"], changed_by="pytest")
        P.reopen_rejected(p["policy_id"], changed_by="reviewer")
        self.assertEqual(P.submit_for_review(p["policy_id"],
                                             changed_by="pytest")["status"], "REVIEW")
        P.publish_draft(p["policy_id"], changed_by="pytest")
        with self.assertRaises(P.ProfileConflict):
            P.reopen_rejected(p["policy_id"])

    def test_reject_requires_a_reason(self):
        p = self.draft()
        with self.assertRaises(P.ProfileError):
            P.reject_profile(p["policy_id"], reason="  ", changed_by="pytest")

    def test_retire_is_terminal(self):
        p = self.draft()
        P.publish_draft(p["policy_id"], changed_by="pytest")
        p = P.retire_profile(p["policy_id"], reason="superseded", changed_by="pytest")
        self.assertEqual(p["status"], "RETIRED")
        self.assertEqual(p["next_statuses"], [])
        for call in (lambda: P.save_draft(p["policy_id"], requirements=REQS),
                     lambda: P.publish_draft(p["policy_id"]),
                     lambda: P.retire_profile(p["policy_id"])):
            with self.assertRaises(P.ProfileConflict):
                call()

    def test_illegal_transition_is_refused(self):
        p = self.draft()
        with self.assertRaises(P.ProfileConflict) as ctx:
            P.retire_profile(p["policy_id"], reason="skip")
        self.assertIn("DRAFT -> RETIRED", str(ctx.exception))

    def test_submit_needs_requirements(self):
        p = P.create_draft("No reqs", created_by="pytest")
        with self.assertRaises(P.ProfileError):
            P.submit_for_review(p["policy_id"], changed_by="pytest")

    def test_unknown_profile_is_reported(self):
        with self.assertRaises(P.ProfileError):
            P.get_profile("POL-NOPE")
        with self.assertRaises(P.ProfileError):
            P.publish_draft("POL-NOPE")


class AssociationGatingTests(ProfileBase):
    """A profile only reaches a group once it is published."""

    def group(self):
        return self.track_group()

    def test_draft_is_refused(self):
        p = P.create_draft("Unpublished", created_by="pytest")
        g = self.group()
        out = G.associate_profiles(g["id"], [p["policy_id"]], op_role="FLEET_ADMIN",
                                   mfa_ok=True, deploy=False)
        self.assertEqual(out["associated"], [])
        self.assertEqual(out["rejected"], [{"policy_id": p["policy_id"],
                                            "status": "DRAFT"}])

    def test_rejected_is_refused(self):
        p = self.draft()
        P.publish_draft(p["policy_id"], changed_by="pytest")
        P.retire_profile(p["policy_id"], reason="done", changed_by="pytest")
        g = self.group()
        out = G.associate_profiles(g["id"], [p["policy_id"]], op_role="FLEET_ADMIN",
                                   mfa_ok=True, deploy=False)
        self.assertEqual(out["associated"], [])
        self.assertEqual(out["rejected"][0]["status"], "RETIRED")

    def test_published_profile_associates_and_counters_become_real(self):
        p = self.draft()
        P.publish_draft(p["policy_id"], changed_by="pytest")
        g = self.group()
        G.add_members(g["id"], ["PRF-D1"], op_role="FLEET_ADMIN", mfa_ok=True,
                      deploy=False)
        out = G.associate_profiles(g["id"], [p["policy_id"]], op_role="FLEET_ADMIN",
                                   mfa_ok=True, deploy=False)
        self.assertEqual(out["associated"], [p["policy_id"]])
        got = P.get_profile(p["policy_id"])
        self.assertEqual(got["group_count"], 1)
        self.assertEqual(got["target_device_count"], 1)
        self.assertEqual(got["deployed_device_count"], 0,
                         "association alone is not a deployment")

    def test_associated_profile_cannot_be_deleted(self):
        """Defence in depth for a legacy association row.

        associate_profiles() refuses a DRAFT, so the only way a draft can still
        be referenced is a row that predates the gate (or was written by hand).
        delete_profile() must still refuse rather than cascade the assignment and
        rewrite what that group was carrying.
        """
        p = self.draft()
        g = self.group()
        with connect() as c:
            pk = c.execute("SELECT id FROM policies WHERE policy_id=?",
                           (p["policy_id"],)).fetchone()["id"]
            c.execute("INSERT INTO group_profile_assignments (group_id, policy_id) "
                      "VALUES (?,?)", (g["id"], pk))
        with self.assertRaises(P.ProfileConflict) as ctx:
            P.delete_profile(p["policy_id"])
        self.assertIn("still associated", str(ctx.exception))
        with connect() as c:
            self.assertIsNotNone(c.execute(
                "SELECT 1 FROM policies WHERE policy_id=?",
                (p["policy_id"],)).fetchone())


class ListingTests(ProfileBase):
    def test_list_filters_and_searches(self):
        p = self.draft("Findable Lockdown")
        P.create_draft("Other", created_by="pytest")
        P.publish_draft(p["policy_id"], changed_by="pytest")
        self.assertEqual([r["policy_id"] for r in P.list_profiles(status="ACTIVE")],
                         [p["policy_id"]])
        self.assertEqual([r["name"] for r in P.list_profiles(search="Findable")],
                         ["Findable Lockdown"])
        self.assertEqual(len(P.list_profiles(search="nothing-matches")), 0)

    def test_drafts_sort_first(self):
        active = self.draft("Active one")
        P.publish_draft(active["policy_id"], changed_by="pytest")
        draft = self.draft("Draft one")
        self.assertEqual(P.list_profiles()[0]["policy_id"], draft["policy_id"])

    def test_unenforceable_lanes_are_reported_not_hidden(self):
        p = self.draft(reqs=[{"feature": "S_VOICE", "desired_state": "BLOCK"}])
        row = [r for r in P.list_profiles() if r["policy_id"] == p["policy_id"]][0]
        self.assertFalse(row["enforceable"])
        self.assertTrue(any("S_VOICE" in u for u in row["unenforceable_lanes"]))
        self.assertEqual(row["unsupported_lanes"], [])

    def test_stored_requirements_match_the_row(self):
        p = self.draft()
        with connect() as c:
            stored = c.execute("SELECT requirements, checksum FROM policies "
                               "WHERE policy_id=?", (p["policy_id"],)).fetchone()
        self.assertEqual(json.loads(stored["requirements"]), p["requirements"])
        self.assertEqual(stored["checksum"], p["checksum"])


class VersioningTests(ProfileBase):
    """Editing a published profile opens a new DRAFT revision and supersedes on publish."""

    def test_create_revision_from_active_copies_requirements(self):
        v1 = self.draft("Kiosk Flow", reqs=[{"feature": "CAMERA", "desired_state": "BLOCK"}])
        P.publish_draft(v1["policy_id"], changed_by="pytest")

        v2 = P.create_revision(v1["policy_id"], changed_by="pytest")
        self.assertEqual(v2["status"], "DRAFT")
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["root_id"], v1["root_id"])
        self.assertNotEqual(v2["policy_id"], v1["policy_id"])
        self.assertEqual(v2["requirements"], [{"desired_state": "BLOCK", "feature": "CAMERA", "risk": "MEDIUM"}])
        self.assertFalse(v2["reused"])

    def test_create_revision_from_draft_is_refused(self):
        d = self.draft("Just a Draft")
        with self.assertRaises(P.ProfileConflict) as ctx:
            P.create_revision(d["policy_id"])
        self.assertIn("only a published", str(ctx.exception))

    def test_create_revision_is_idempotent_while_draft_open(self):
        v1 = self.draft("Stable Base")
        P.publish_draft(v1["policy_id"], changed_by="pytest")

        first = P.create_revision(v1["policy_id"], changed_by="pytest")
        second = P.create_revision(v1["policy_id"], changed_by="pytest")

        self.assertEqual(first["policy_id"], second["policy_id"])
        self.assertTrue(second["reused"])

    def test_publish_revision_retires_previous_and_moves_group_assignments(self):
        v1 = self.draft("Fleet Baseline", reqs=[{"feature": "CAMERA", "desired_state": "BLOCK"}])
        P.publish_draft(v1["policy_id"], changed_by="pytest")

        g = self.track_group()
        G.associate_profiles(g["id"], [v1["policy_id"]], op_role="FLEET_ADMIN", mfa_ok=True, deploy=False)

        # Confirm v1 is associated
        self.assertEqual(len(G.list_group_profiles(g["id"])), 1)
        self.assertEqual(G.list_group_profiles(g["id"])[0]["policy_id"], v1["policy_id"])

        # Create revision v2 and add a requirement
        v2 = P.create_revision(v1["policy_id"], changed_by="pytest")
        P.save_draft(v2["policy_id"], requirements=[
            {"feature": "CAMERA", "desired_state": "BLOCK"},
            {"feature": "BLUETOOTH", "desired_state": "BLOCK"}
        ], changed_by="pytest")

        # Publish v2
        pub2 = P.publish_draft(v2["policy_id"], changed_by="pytest")
        self.assertEqual(pub2["status"], "ACTIVE")
        self.assertEqual(pub2.get("superseded"), v1["policy_id"])

        # Check v1 became RETIRED
        old_v1 = P.get_profile(v1["policy_id"])
        self.assertEqual(old_v1["status"], "RETIRED")

        # Check group assignment transferred to v2
        gps = G.list_group_profiles(g["id"])
        self.assertEqual(len(gps), 1)
        self.assertEqual(gps[0]["policy_id"], v2["policy_id"])
        self.assertEqual(gps[0]["distributed_version"], 2)
        self.assertEqual([g["group_id"] for g in pub2.get("affected_groups") or []],
                         [g["id"]])

    def test_list_profiles_does_not_duplicate_superseded_revisions(self):
        # Create initial profile and publish it (version 1)
        v1 = self.draft("Device Enforce", reqs=[{"feature": "CAMERA", "desired_state": "BLOCK"}])
        P.publish_draft(v1["policy_id"], changed_by="pytest")

        # Create revision v2 and publish it
        v2 = P.create_revision(v1["policy_id"], changed_by="pytest")
        P.save_draft(v2["policy_id"], requirements=[
            {"feature": "CAMERA", "desired_state": "BLOCK"},
            {"feature": "BLUETOOTH", "desired_state": "BLOCK"}
        ], changed_by="pytest")
        P.publish_draft(v2["policy_id"], changed_by="pytest")

        # Create revision v3 and publish it
        v3 = P.create_revision(v2["policy_id"], changed_by="pytest")
        P.save_draft(v3["policy_id"], requirements=[
            {"feature": "CAMERA", "desired_state": "BLOCK"},
            {"feature": "BLUETOOTH", "desired_state": "BLOCK"},
            {"feature": "USB", "desired_state": "BLOCK"}
        ], changed_by="pytest")
        P.publish_draft(v3["policy_id"], changed_by="pytest")

        # Default listing: must return only ONE entry for 'Device Enforce', at version 3
        profiles = [p for p in P.list_profiles() if p["name"] == "Device Enforce"]
        self.assertEqual(len(profiles), 1, "Superseded revisions v1 and v2 must not duplicate the profile row")
        self.assertEqual(profiles[0]["version"], 3)
        self.assertEqual(profiles[0]["status"], "ACTIVE")
        self.assertEqual(profiles[0]["policy_id"], v3["policy_id"])
        self.assertEqual(profiles[0]["root_id"], v1["policy_id"])

        # When explicitly requesting superseded revisions (e.g. audit/history)
        all_revisions = [p for p in P.list_profiles(include_superseded=True) if p["name"] == "Device Enforce"]
        self.assertEqual(len(all_revisions), 3, "All revisions available when include_superseded=True")


if __name__ == "__main__":
    unittest.main(verbosity=2)