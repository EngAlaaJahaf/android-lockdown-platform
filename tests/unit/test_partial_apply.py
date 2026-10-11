# -*- coding: utf-8 -*-
"""Regression proof for the partial-apply path.

A lane this handset has no mechanism for must no longer cancel the whole
deployment; the enforceable lanes must reach the device and the refused lanes
must be reported so the console can name them.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for _sub in ("policy-engine", "capability-engine", "verification-engine",
             "compatibility", "vendor-adapters"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

from backend import db as db_mod                      # noqa: E402
from backend.groups import (profile_enforceable,       # noqa: E402
                            OUT_APPLIED, OUT_PARTIAL, OUT_NOT_APPLICABLE)
from backend.restrictions import by_feature, ENFORCEABLE_TIERS  # noqa: E402

KNOX = '[{"feature":"FIRMWARE_RECOVERY","desired_state":"RESTRICT"}]'
CAM = '[{"feature":"CAMERA","desired_state":"RESTRICT"}]'
BOTH = ('[{"feature":"CAMERA","desired_state":"RESTRICT"},'
        '{"feature":"FIRMWARE_RECOVERY","desired_state":"RESTRICT"}]')


class TestProfileEnforceable(unittest.TestCase):
    """One unenforceable lane must not condemn the whole profile."""

    def _run(self, reqs):
        return profile_enforceable(reqs, by_feature, ENFORCEABLE_TIERS)

    def test_enforceable_lane_is_deployable(self):
        ok, _uns, unen = self._run(CAM)
        self.assertTrue(ok)
        self.assertEqual(unen, [])

    def test_single_knox_lane_alone_is_not_applicable(self):
        ok, _uns, unen = self._run(KNOX)
        self.assertFalse(ok, "a profile with zero enforceable lanes must not deploy")
        self.assertTrue(unen, "the refusal must name the lane")

    def test_one_knox_lane_does_not_kill_the_camera_lane(self):
        ok, _uns, unen = self._run(BOTH)
        self.assertTrue(ok, "camera is enforceable, so the profile must deploy")
        self.assertEqual(len(unen), 1)
        self.assertIn("FIRMWARE_RECOVERY", unen[0])

    def test_result_is_json_serialisable(self):
        ok, uns, unen = self._run(BOTH)
        json.dumps({"ok": ok, "unsupported": uns, "unenforceable": unen})


class TestDirectorPartialApply(unittest.TestCase):
    """Director must apply the enforceable subset when force=True and record
    the refused lanes in the compliance snapshot."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alp-partial-")
        self.db = os.path.join(self.tmp, "alp.db")
        # ALP_DB is authoritative for every connect() in the process, so the
        # director writes its compliance row into this scratch store.
        self._real_env = os.environ.get("ALP_DB")
        os.environ["ALP_DB"] = self.db
        db_mod.run_migrations(self.db)

        from backend.db import connect

        def _conn():
            return connect(self.db)

        self._connect = _conn
        with _conn() as c:
            c.execute("INSERT INTO devices (device_id, serial, manufacturer, model, "
                      "android_version, api_level) VALUES ('D1','S1','LT','LT_8110',15,35)")
            c.execute("INSERT INTO policies (policy_id, display_name, category, status, "
                      "version, requirements) VALUES ('P1','p','CORPORATE_DEFAULT',"
                      "'ACTIVE',1,?)", (BOTH,))

    def tearDown(self):
        if self._real_env is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._real_env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _snapshot(self, exceptions):
        class S:
            def __init__(self, exc):
                self.exceptions = list(exc)
                self.resolved = []
        return S(exceptions)

    def _director(self, exceptions):
        from backend import director as D

        def resolve(policy, capability, compat_layer, vendor_adapter):
            return self._snapshot(exceptions)

        class V:
            result = "PARTIAL"
            honest = True
            observations = {"CAMERA": "RESTRICTED"}
            evidence_id = ""

        sent = []

        d = D.Director(db_path=None, resolve_fn=resolve,
                       verify_fn=lambda *a, **k: V(),
                       channel_send=lambda env: (sent.append(env) or {"ok": True}))
        return d, sent

    def _policy(self):
        from policy_engine import Policy
        return Policy("P1", "p", "CORPORATE_DEFAULT", "ACTIVE", 1, [])

    def test_force_applies_enforceable_subset_and_records_lanes(self):
        d, sent = self._director(["FIRMWARE_RECOVERY"])
        res = d.apply("D1", self._policy(), None, force=True,
                      evidence_src="REAL_DEVICE")
        self.assertEqual(res.stage, "COMPLETE")
        self.assertEqual(len(sent), 1, "the enforceable subset must still be sent")
        self.assertIn("FIRMWARE_RECOVERY", res.exceptions)

        row = self._connect().execute(
            "SELECT details FROM compliance WHERE device_id=(SELECT id FROM devices "
            "WHERE device_id='D1')").fetchone()
        details = json.loads(row["details"] or "{}")
        self.assertIn("__unresolved_lanes__", details)
        self.assertEqual(details["__unresolved_lanes__"], ["FIRMWARE_RECOVERY"])

    def test_without_force_the_whole_profile_is_refused(self):
        from backend.director import ApplyBlocked
        d, sent = self._director(["FIRMWARE_RECOVERY"])
        with self.assertRaises(ApplyBlocked):
            d.apply("D1", self._policy(), None, force=False,
                    evidence_src="REAL_DEVICE")
        self.assertEqual(sent, [], "nothing may be sent on a refused profile")

    def test_clean_profile_writes_no_unresolved_marker(self):
        d, sent = self._director([])
        res = d.apply("D1", self._policy(), None, force=True,
                      evidence_src="REAL_DEVICE")
        self.assertEqual(res.exceptions, [])
        row = self._connect().execute(
            "SELECT details FROM compliance WHERE device_id=(SELECT id FROM devices "
            "WHERE device_id='D1')").fetchone()
        details = json.loads(row["details"] or "{}")
        self.assertNotIn("__unresolved_lanes__", details)


class TestClassifyReportsPartial(unittest.TestCase):
    def test_partial_verification_on_real_device_is_partial_not_failure(self):
        from backend.groups import _classify
        out, verified = _classify({"source": "REAL_DEVICE",
                                   "verification": "PARTIAL"})
        self.assertEqual(out, OUT_PARTIAL)
        self.assertTrue(verified)


class TestRestrictionCatalogLaneKeys(unittest.TestCase):
    """Every catalog row must carry the ALP lane key it governs.

    The read-only view once looked rows up by display label, so "Location
    services" searched for LOCATION_SERVICES while the policy lane is LOCATION.
    The miss was silent and rendered a RESTRICT lane as its catalog default.
    """

    DATA = os.path.join(ROOT, "webui", "assets", "alp-restrictions-data.js")
    JS = os.path.join(ROOT, "webui", "assets", "alp-console.js")

    @classmethod
    def setUpClass(cls):
        from backend.restrictions import by_feature
        cls.lanes = set()
        cls.labels = {}
        for feature, rows in by_feature().items():
            cls.lanes.add(feature)
            for r in rows:
                for key in ("label", "label_ar", "name"):
                    lab = (r.get(key) or "").strip()
                    if lab:
                        cls.labels[lab] = feature

    def _catalog(self):
        src = open(self.DATA, encoding="utf-8").read()
        lit = src[src.index("{"):]
        return json.loads(lit[: lit.rindex("}") + 1])

    def test_every_row_has_a_feature_key(self):
        missing = [it.get("name")
                   for items in self._catalog().values() for it in items
                   if not it.get("feature")]
        self.assertEqual(missing, [], "catalog rows without a lane key")

    def test_feature_keys_are_real_lanes(self):
        unknown = sorted({it["feature"] for items in self._catalog().values()
                          for it in items
                          if it.get("feature") and it["feature"] not in self.lanes})
        self.assertEqual(unknown, [], "feature keys not known to the engine")

    def test_location_services_maps_to_location(self):
        rows = {it["name"]: it for items in self._catalog().values()
                for it in items}
        self.assertEqual(rows["Location services"]["feature"], "LOCATION")
        self.assertEqual(rows["Mock locations"]["feature"], "MOCK_LOCATIONS")
        self.assertEqual(rows["Google Maps"]["feature"], "GOOGLE_MAPS")

    def test_label_normalisation_is_not_used_for_lookup(self):
        src = open(self.JS, encoding="utf-8").read()
        start = src.index("function renderProfileDetailsFeatures")
        body = src[start:start + 2600]
        self.assertIn("item.feature", body,
                      "the row's own lane key must drive the lookup")
        self.assertNotIn("const normKey = item.name.toUpperCase()", body,
                         "label-derived lookup must be gone")

    def test_render_reports_not_set_instead_of_a_default(self):
        src = open(self.JS, encoding="utf-8").read()
        start = src.index("function renderProfileDetailsFeatures")
        # The row markup lives further down the function than a fixed slice.
        body = src[start: src.index("\nfunction ", start + 10)]
        self.assertIn("Not set", body,
                      "a lane absent from the profile must read as Not set")
        self.assertIn("!defined", body)

    def test_lanes_without_a_catalog_row_are_known(self):
        """Some engine lanes have no catalog row (ADB, GPS, MOBILE_DATA...).

        They are enforced by the agent but the reference catalog has no ManageEngine
        label for them, so the read-only view cannot show them. That gap is
        recorded here so it cannot grow unnoticed.
        """
        try:
            from policy_engine import FEATURES
        except ImportError:
            self.skipTest("policy_engine not on the path")
        covered = {it["feature"] for items in self._catalog().values()
                   for it in items if it.get("feature")}
        uncovered = sorted(set(FEATURES) - covered)
        # Known, accepted gap: ALP-native lanes with no ManageEngine counterpart.
        self.assertEqual(
            sorted(set(uncovered) - {"ADB", "GPS", "MOBILE_DATA",
                                     "USER_MANAGEMENT", "APPLICATIONS",
                                     "CALLS", "CONTACTS", "ETHERNET",
                                     "LOCK_TASK", "FACTORY_RESET_RECOVERY",
                                     "REFLAH_FIRMWARE", "CHROME_APP",
                                     "GMAIL_APP", "GOOGLE_APPS",
                                     "PLAYSTORE_APP", "YOUTUBE_APP"}),
            [],
            "new engine lanes appeared with no catalog row: %s" % uncovered)


class TestStagedChannelReallyDelivers(unittest.TestCase):
    """staged_channel used to write a local file and return ok=True.

    That made the console report policies as deployed to handsets that never
    received a byte. Delivery must be attempted over ADB and must fail loudly
    when the device is absent.
    """

    def setUp(self):
        import backend.workflows as W
        self.W = W
        self.tmp = tempfile.mkdtemp(prefix="alp-stage-")
        self.calls = []

        class R:
            def __init__(self, rc=0, err=""):
                self.returncode = rc
                self.stderr = err
                self.stdout = ""

        def fake_run(cmd, **kw):
            self.calls.append(cmd)
            joined = " ".join(cmd)
            if "push" in joined:
                return R(0 if self.push_ok else 1, "device offline")
            return R(0)

        self.R = R
        self.push_ok = True
        real_run, real_attached = W.subprocess.run, W.attached_serials
        W.subprocess.run = fake_run
        W.attached_serials = lambda: ["LT8110260130351"]
        self._restore = (real_run, real_attached)

    def tearDown(self):
        self.W.subprocess.run, self.W.attached_serials = self._restore
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self):
        return {"cmd_id": "ABC123", "action": "APPLY_POLICY",
                "body": {"policy_id": "P1"}}

    def test_push_and_broadcast_happen(self):
        send, state = self.W.staged_channel("LT8110260130351", self.tmp)
        out = send(self._env())
        self.assertTrue(out["ok"], out)
        joined = [" ".join(c) for c in self.calls]
        self.assertTrue(any("push" in c for c in joined), joined)
        self.assertTrue(any("broadcast" in c for c in joined), joined)
        self.assertTrue(any("alp_envelope.json" in c for c in joined), joined)

    def test_failed_push_is_not_reported_as_success(self):
        self.push_ok = False
        send, _state = self.W.staged_channel("LT8110260130351", self.tmp)
        out = send(self._env())
        self.assertFalse(out["ok"], "a failed push must not claim success")
        self.assertIn("push failed", out["error"])

    def test_absent_device_is_not_reported_as_success(self):
        self.W.attached_serials = lambda: []
        send, _state = self.W.staged_channel("LT8110260130351", self.tmp)
        out = send(self._env())
        self.assertFalse(out["ok"])
        self.assertIn("not attached", out["error"])

    def test_missing_serial_is_not_reported_as_success(self):
        send, _state = self.W.staged_channel("", self.tmp)
        out = send(self._env())
        self.assertFalse(out["ok"])
        self.assertIn("serial", out["error"])

    def test_action_selects_the_matching_remote_file(self):
        send, _state = self.W.staged_channel("LT8110260130351", self.tmp)
        out = send({"cmd_id": "D1", "action": "CLEAR_POLICY", "body": {}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["pushed_to"], "/data/local/tmp/alp_rollback.json")

    def test_local_audit_copy_is_still_written(self):
        send, state = self.W.staged_channel("LT8110260130351", self.tmp)
        send(self._env())
        self.assertEqual(len(state["staged"]), 1)
        self.assertTrue(os.path.exists(state["staged"][0]))


class TestAgentStateReporting(unittest.TestCase):
    """The console must surface what the handset actually enforced."""

    def test_skipped_features_parses_feature_desired_rows(self):
        from backend.agent_state import skipped_features
        got = skipped_features({"skipped": ["CAMERA:RESTRICT", "WIFI:RESTRICT"]})
        self.assertEqual(got, ["CAMERA", "WIFI"])

    def test_skipped_features_tolerates_bare_values(self):
        from backend.agent_state import skipped_features
        self.assertEqual(skipped_features({"skipped": ["OS_UPGRADE"]}),
                         ["OS_UPGRADE"])

    def test_missing_state_reads_as_empty(self):
        from backend.agent_state import (read_agent_state, read_last_apply,
                                         skipped_features)
        self.assertEqual(read_agent_state(""), {})
        self.assertEqual(read_last_apply(""), {})
        self.assertEqual(skipped_features({}), [])

    def test_apply_result_is_preferred_over_overwritten_state(self):
        # A later GET_STATE overwrites state.json; the durable apply record must
        # win so the console can still name the rows the handset refused.
        from backend import agent_state

        class FakeProc:
            returncode = 0

            def __init__(self, stdout):
                self.stdout = stdout

        def fake_run(cmd, **kw):
            name = cmd[-1]
            if name.endswith("apply_result.json"):
                return FakeProc('{"action":"APPLY_POLICY","skipped":'
                                '["CAMERA:RESTRICT"],"applied":["WIFI"]}')
            # state.json was clobbered by a state probe
            return FakeProc('{"action":"GET_STATE","applied":[],'
                            '"skipped":[],"errors":["REJECTED GET_STATE: expired"]}')

        real_run, real_adb = agent_state.subprocess.run, agent_state.adb
        agent_state.subprocess.run = fake_run
        agent_state.adb = lambda: "adb"
        try:
            got = agent_state.read_last_apply("SERIAL")
        finally:
            agent_state.subprocess.run = real_run
            agent_state.adb = real_adb
        self.assertEqual(agent_state.skipped_features(got), ["CAMERA"])

    def test_skipped_rows_become_unenforced_observations(self):
        # A skipped row must reach the verification observations, otherwise the
        # pipeline cannot tell PARTIAL from PASS.
        from backend.agent_state import skipped_features
        observed = {"CAMERA": "RESTRICTED"}
        for feat in skipped_features({"skipped": ["WIFI:RESTRICT"]}):
            observed.setdefault(feat, "UNENFORCED")
        self.assertEqual(observed["WIFI"], "UNENFORCED")
        self.assertEqual(observed["CAMERA"], "RESTRICTED")


class TestAgentRestrictMeansBlock(unittest.TestCase):
    """Regression: the agent used to drop every RESTRICT row silently.

    A profile expressed with desired=RESTRICT therefore lifted nothing while
    the console reported it applied. The Java switch now routes RESTRICT into
    the BLOCK branch; this asserts the source keeps that guarantee.
    """
    SRC = os.path.join(ROOT, "android-agent", "app", "src", "com", "alp",
                       "agent", "AlpOps.java")

    def setUp(self):
        with open(self.SRC, encoding="utf-8") as fh:
            self.src = fh.read()

    def test_apply_row_handles_restrict_next_to_block(self):
        start = self.src.index("private static boolean applyRow")
        body = self.src[start:start + 6000]
        self.assertIn('case "BLOCK"', body)
        self.assertIn('case "RESTRICT"', body)
        self.assertLess(body.index('case "BLOCK"'), body.index('case "RESTRICT"'),
                        "RESTRICT must share the BLOCK branch, not fall to default")

    def test_restrict_is_not_left_in_the_default_branch(self):
        start = self.src.index("private static boolean applyRow")
        body = self.src[start:start + 6000]
        # The unknown-value guard must stay, but RESTRICT must be handled above
        # it, otherwise the row is dropped without any trace.
        default_at = body.index("default:")
        self.assertLess(body.index('case "RESTRICT"'), default_at)


if __name__ == "__main__":
    unittest.main()