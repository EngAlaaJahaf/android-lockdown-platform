"""Director (AD-4 pipeline) offline tests — honest fakes, no real devices."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for sub in ("backend", "policy-engine", "capability-engine",
            "verification-engine", "compatibility"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from backend import director, db
from backend import config as _cfg
from policy_engine import phone_only, corporate_default_v1
from policy_engine.snapshot import resolve
from capability_engine import CapabilityProfile
from compatibility import AndroidCompatibilityLayer
from verification_engine import VerificationEngine


class FakeChannel:
    def __init__(self, ok=True):
        self.ok = ok
        self.envelopes = []
        self.verified = 0

    def send(self, envelope):
        self.envelopes.append(envelope)
        return {"ok": self.ok, "error": None}


def mirror_observations(expected: dict, override: dict | None = None) -> dict:
    """Honest test fake: the device reports exactly the requested state (or override)."""
    obs = {f: v for f, v in expected.items()}
    if override:
        obs.update(override)
    return obs


def make_fake_verify(observed_devices):
    def _observe(device_id):
        return observed_devices.get(device_id, {})
    return VerificationEngine(_observe).verify


class TestDirector(unittest.TestCase):
    def setUp(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(prefix="alp_dir_"), "d.db")
        # Sync the authoritative routing (env + module attrs) so this module
        # runs against *its own* DB and restores afterwards — no leakage into
        # sibling test modules regardless of discovery/run order.
        self._prev = {"env": os.environ.get("ALP_DB"),
                      "cfg": _cfg.DBPATH, "db": db.DBPATH}
        os.environ["ALP_DB"] = path
        _cfg.DBPATH = path
        db.DBPATH = path
        os.environ["ALP_SIGNING_KEY"] = "director-test-key"
        db.run_migrations()

    def tearDown(self):
        if self._prev["env"] is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev["env"]
        _cfg.DBPATH = self._prev["cfg"]
        db.DBPATH = self._prev["db"]
        # policy must be review-approved
        from backend.db import connect
        with connect() as c:
            c.execute("INSERT OR IGNORE INTO policies (policy_id, display_name, category, status, requirements) "
                      "VALUES ('POL-PHONE_ONLY','x','PHONE_ONLY','REVIEW','{}')")

    def _capability(self, api=35, model="SM-A145P"):
        cap = CapabilityProfile(device_id="LAB-0001", android_version=15, api_level=api,
                                model=model, device_owner=True)
        for f in ("WIFI", "ADB", "CAMERA", "GPS"):
            cap.states[f] = "SUPPORTED"
        return cap

    def _grant_recovery(self, device_id="LAB-0001"):
        """Real REAL deliveries on critical lanes need a recovery channel (mandate)."""
        from backend.db import connect
        with connect() as c:
            c.execute("INSERT OR IGNORE INTO devices (device_id, manufacturer, model, "
                      "android_version, api_level) VALUES (?,?,?,?,?)",
                      (device_id, "Samsung", "SM-A145P", 15, 35))
            c.execute("INSERT OR REPLACE INTO recovery_credentials "
                      "(device_id, recovery_id, credential_ciphertext, nonce) "
                      "VALUES (?,?,X'0102030405060708090a0b0c',X'01020304050a0b0c0d010203')",
                      (device_id, "AAAA-AAAA"))

    def test_pipeline_happy_path(self):
        from capability_engine import CapabilityProfile, CapabilityState
        cap = CapabilityProfile(device_id="LAB-0001", android_version=15, api_level=35,
                                model="SM-A145P", device_owner=True)
        pol = phone_only()   # must be persisted as REVIEW for _persist to update device
        cap.states.update({f: "SUPPORTED" for f in pol.feature_map()})
        from backend.db import connect
        with connect() as c:
            c.execute("INSERT OR IGNORE INTO devices (device_id, manufacturer, model, android_version, api_level) "
                      "VALUES ('LAB-0001','Samsung','SM-A145P',15,35)")
        # the fake observes exactly what the policy demands (mirror) — pipeline mechanics
        def _observe(device_id):
            from policy_engine.snapshot import resolve as _resolve
            snap = _resolve(pol, cap, AndroidCompatibilityLayer(35))
            return {r.feature: ("OFF" if r.desired == "BLOCK" else
                                "ON" if r.desired == "ALLOW" else "RESTRICT")
                    for r in snap.resolved}
        d = director.Director(resolve_fn=resolve, verify_fn=VerificationEngine(_observe).verify,
                              channel_send=FakeChannel().send, signing_key="director-test-key")
        self._grant_recovery()
        res = d.apply("LAB-0001", pol, cap,
                      compat_layer=AndroidCompatibilityLayer(35), evidence_src="REAL_DEVICE")
        self.assertEqual(res.stage, "COMPLETE")
        self.assertTrue(res.evidence_id)
        self.assertEqual(res.verification.result, "PASS")
        self.assertEqual(res.compliance, "COMPLIANT")

    def test_draft_policy_rejected(self):
        from backend.db import connect
        with connect() as c:
            c.execute("INSERT OR IGNORE INTO policies (policy_id, display_name, category, status, requirements) "
                      "VALUES ('POL-DRAFT','x','PHONE_ONLY','DRAFT','{}')")
        pol = phone_only(); pol.policy_id = "POL-DRAFT"; pol.status = "DRAFT"
        d = director.Director(resolve_fn=resolve,
                              verify_fn=make_fake_verify({"LAB-0001": {}}),
                              channel_send=FakeChannel().send, signing_key="k")
        with self.assertRaises(director.DirectorError):
            d.apply("LAB-0001", pol, self._capability(), compat_layer=AndroidCompatibilityLayer(35))

    def test_snapshot_exceptions_block_unless_force(self):
        cap = self._capability(api=22)      # API 22: wifi block infeasible -> exception
        verif = make_fake_verify({"LAB-0001": {}})
        d = director.Director(resolve_fn=resolve, verify_fn=verif,
                              channel_send=FakeChannel().send, signing_key="k")
        with self.assertRaises(director.ApplyBlocked):
            d.apply("LAB-0001", phone_only(), cap, compat_layer=AndroidCompatibilityLayer(22))
        res = d.apply("LAB-0001", phone_only(), cap, compat_layer=AndroidCompatibilityLayer(22), force=True)
        self.assertEqual(res.stage, "COMPLETE")

    def test_channel_down_blocks(self):
        verif = make_fake_verify({"LAB-0001": {"WIFI": "OFF"}})
        d = director.Director(resolve_fn=resolve, verify_fn=verif,
                              channel_send=FakeChannel(ok=False).send, signing_key="k")
        with self.assertRaises(director.DirectorError):
            d.apply("LAB-0001", phone_only(), self._capability(), compat_layer=AndroidCompatibilityLayer(35))

    def test_mismatch_yields_non_compliant(self):
        from capability_engine import CapabilityProfile
        cap = CapabilityProfile(device_id="LAB-0001", android_version=15, api_level=35,
                                model="SM-A145P", device_owner=True)
        pol = phone_only()
        cap.states.update({f: "SUPPORTED" for f in pol.feature_map()})

        def _observe(device_id):
            from policy_engine.snapshot import resolve as _resolve
            snap = _resolve(pol, cap, AndroidCompatibilityLayer(35))
            obs = {r.feature: ("OFF" if r.desired == "BLOCK" else
                               "ON" if r.desired == "ALLOW" else "RESTRICT")
                   for r in snap.resolved}
            obs["WIFI"] = "ON"            # violation: wifi should be OFF
            return obs
        d = director.Director(resolve_fn=resolve, verify_fn=VerificationEngine(_observe).verify,
                              channel_send=FakeChannel().send, signing_key="k")
        self._grant_recovery()
        res = d.apply("LAB-0001", pol, cap, compat_layer=AndroidCompatibilityLayer(35),
                      evidence_src="REAL_DEVICE")
        self.assertEqual(res.verification.result, "PARTIAL")
        self.assertEqual(res.compliance, "NON_COMPLIANT", "violation trumps partial")

    def test_partial_apply_leaves_pending_but_marks_managed(self):
        # A PARTIAL verdict means the profile IS deployed with named gaps:
        # enrollment leaves PENDING (Managed in the UI) while the gap stays
        # visible as compliance PARTIAL. FAIL/UNKNOWN must still not advance.
        from backend.db import connect
        with connect() as c:
            c.execute("INSERT OR IGNORE INTO devices (device_id, manufacturer, "
                      "model, android_version, api_level, enrollment_state) "
                      "VALUES ('LAB-PART','Samsung','SM-A145P',15,35,"
                      "'ENROLLMENT_PENDING')")
        d = director.Director(resolve_fn=resolve,
                              verify_fn=make_fake_verify({"LAB-PART": {}}),
                              channel_send=FakeChannel().send, signing_key="k")
        d._persist("LAB-PART", "POL-PHONE_ONLY", "PARTIAL", "EV-P1",
                   "ENROLLED", {}, exceptions=["AUTO_SYNC"])
        with connect() as c:
            row = c.execute("SELECT enrollment_state, compliance_state "
                            "FROM devices WHERE device_id='LAB-PART'").fetchone()
        self.assertEqual(row["enrollment_state"], "ENROLLED")
        self.assertEqual(row["compliance_state"], "PARTIAL")
        d._persist("LAB-PART", "POL-PHONE_ONLY", "FAIL", "EV-P2",
                   "ENROLLED", {})
        with connect() as c:
            row = c.execute("SELECT enrollment_state, compliance_state "
                            "FROM devices WHERE device_id='LAB-PART'").fetchone()
        self.assertEqual(row["enrollment_state"], "ENROLLED")
        self.assertEqual(row["compliance_state"], "NON_COMPLIANT")

    def test_audit_recorded(self):
        from backend import audit
        verif = make_fake_verify({"LAB-0001": {"WIFI": "OFF", "ADB": "OFF", "CAMERA": "OFF", "GPS": "OFF"}})
        lg = audit.AuditLog()
        d = director.Director(resolve_fn=resolve, verify_fn=verif,
                              channel_send=FakeChannel().send, signing_key="k", audit=lg)
        res = d.apply("LAB-0001", phone_only(), self._capability(),
                      compat_layer=AndroidCompatibilityLayer(35))
        self.assertTrue(res.audit_id)
        self.assertEqual(lg.tamper_check()["broken"], 0)

    def test_workflow_apply_registered_db_device(self):
        """run_director_apply must tolerate sqlite3.Row devices (the live path
        crashed on dev.get(...) when the device came straight from the DB)."""
        from backend import workflows
        from backend.db import connect
        with connect() as c:
            c.execute(
                "INSERT INTO devices (device_id, serial, manufacturer, model, "
                "android_version, api_level, is_lab) VALUES (?,?,?,?,?,?,1)",
                ("D-REG", "SERREG1", "Samsung", "SM-A145P", 15, 35))
        chan = FakeChannel(ok=True)
        res = workflows.run_director_apply(
            "D-REG", "POL-FULL_LOCKDOWN", op_role="FLEET_ADMIN",
            mfa_ok=True, serial="SERREG1", real=False, signing_key="k",
            channel_send=chan.send)
        self.assertEqual(res["stage"], "COMPLETE")
        self.assertTrue(res["evidence_id"])

    def test_real_apply_refuses_when_agent_missing(self):
        """A real delivery with no on-device agent must fail loudly up front,
        not silently push an envelope nobody receives."""
        from backend import workflows
        from backend.director import DirectorError
        from backend.db import connect
        with connect() as c:
            c.execute(
                "INSERT INTO devices (device_id, serial, manufacturer, model, "
                "android_version, api_level, is_lab) VALUES (?,?,?,?,?,?,1)",
                ("D-NOAGENT", "SERNOAG", "Samsung", "SM-A145P", 15, 35))
            # a risk-free profile: the agent guard (not the channel guard)
            # must be the one that fires here.
            c.execute(
                "INSERT INTO policies (policy_id, display_name, category, "
                "status, requirements) VALUES (?,?,?,?,?)",
                ("POL-NOAGENT", "no agent", "CORPORATE_DEFAULT", "ACTIVE",
                 '[{"feature": "CAMERA", "desired_state": "BLOCK"}]'))
        with mock.patch.object(workflows, "attached_serials",
                               return_value=["SERNOAG"]), \
             mock.patch.object(workflows, "is_agent_installed",
                               return_value=False):
            with self.assertRaises(DirectorError) as ctx:
                workflows.run_director_apply(
                    "D-NOAGENT", "POL-NOAGENT", op_role="FLEET_ADMIN",
                    mfa_ok=True, serial="SERNOAG", real=True, signing_key="k")
        self.assertIn("not installed", str(ctx.exception))

    def _dev_policy_with_dev_options(self, device_id="D-CHRISK",
                                     serial="SERCHRISK"):
        """A stored ACTIVE profile containing only DEVELOPER_OPTIONS=BLOCK."""
        from backend.db import connect
        with connect() as c:
            c.execute(
                "INSERT INTO devices (device_id, serial, manufacturer, model, "
                "android_version, api_level, is_lab) VALUES (?,?,?,?,?,?,1)",
                (device_id, serial, "Samsung", "SM-A145P", 15, 35))
            c.execute(
                "INSERT INTO policies (policy_id, display_name, category, "
                "status, requirements) VALUES (?,?,?,?,?)",
                ("POL-CHANNEL-RISK", "channel risk", "CORPORATE_DEFAULT",
                 "ACTIVE", '[{"feature": "DEVELOPER_OPTIONS", '
                           '"desired_state": "BLOCK", "risk": "HIGH"}]'))

    def test_channel_risk_lane_refuses_real_delivery(self):
        """Pushing USB-debugging-off over the live ADB session would orphan
        the phone (rollback unreachable) — refuse unless explicitly allowed."""
        from backend import workflows
        from backend.director import DirectorError
        self._dev_policy_with_dev_options()
        with mock.patch.object(workflows, "attached_serials",
                               return_value=["SERCHRISK"]):
            with self.assertRaises(DirectorError) as ctx:
                workflows.run_director_apply(
                    "D-CHRISK", "POL-CHANNEL-RISK", op_role="FLEET_ADMIN",
                    mfa_ok=True, serial="SERCHRISK", real=True, signing_key="k",
                    channel_send=FakeChannel().send)
        self.assertIn("USB", str(ctx.exception))

    def test_channel_risk_override_proceeds(self):
        """Explicit opt-in (physical visit) lets the operator take the risk —
        once a recovery channel exists for the second gate."""
        from backend import workflows
        self._dev_policy_with_dev_options()
        self._grant_recovery("D-CHRISK")
        chan = FakeChannel(ok=True)
        with mock.patch.object(workflows, "attached_serials",
                               return_value=["SERCHRISK"]), \
             mock.patch.object(workflows, "is_agent_installed",
                               return_value=True), \
             mock.patch.object(workflows, "live_probe",
                               return_value={"observed": {}}):
            res = workflows.run_director_apply(
                "D-CHRISK", "POL-CHANNEL-RISK", op_role="FLEET_ADMIN",
                mfa_ok=True, serial="SERCHRISK", real=True, signing_key="k",
                channel_send=chan.send, allow_channel_risk=True)
        self.assertEqual(res["stage"], "COMPLETE")

    def test_adb_lane_refuses_real_delivery(self):
        """The ADB lane kills the USB session carrying the command (proven
        the hard way on a lab handset) — same refusal as DEVELOPER_OPTIONS."""
        from backend import workflows
        from backend.director import DirectorError
        from backend.db import connect
        with connect() as c:
            c.execute("INSERT OR IGNORE INTO devices (device_id, manufacturer, "
                      "model, android_version, api_level) "
                      "VALUES ('D-CHADB','Samsung','SM-J3119',5,22)")
            c.execute("INSERT OR IGNORE INTO policies (policy_id, display_name, "
                      "category, status, requirements) VALUES "
                      "('POL-CHANNEL-ADB','adb risk','CORPORATE_DEFAULT','ACTIVE',"
                      "'[{\"feature\": \"ADB\", \"desired_state\": \"BLOCK\", "
                      "\"risk\": \"HIGH\"}]')")
        with mock.patch.object(workflows, "attached_serials",
                               return_value=["SERCHADB"]):
            with self.assertRaises(DirectorError) as ctx:
                workflows.run_director_apply(
                    "D-CHADB", "POL-CHANNEL-ADB", op_role="FLEET_ADMIN",
                    mfa_ok=True, serial="SERCHADB", real=True, signing_key="k",
                    channel_send=FakeChannel().send)
        self.assertIn("ADB", str(ctx.exception))


class InstallAgentTests(unittest.TestCase):
    def test_install_reports_verified_package_and_launch(self):
        from backend import workflows
        import subprocess as _sp
        runs = [
            _sp.CompletedProcess(args=[], returncode=0, stdout="Success", stderr=""),
            _sp.CompletedProcess(args=[], returncode=0,
                                 stdout="package:/data/app/com.alp.agent/base.apk",
                                 stderr=""),
            _sp.CompletedProcess(args=[], returncode=0, stdout="Starting", stderr=""),
        ]
        with mock.patch.object(workflows, "attached_serials", return_value=["S1"]), \
             mock.patch.object(workflows, "attached_detailed", return_value=[
                 {"serial": "S1", "state": "device", "ready": True}]), \
             mock.patch.object(workflows, "agent_apk_path",
                               return_value="/tmp/alp-agent-release.apk"), \
             mock.patch("subprocess.run", side_effect=runs) as run:
            out = workflows.install_agent_app(serial="S1")
        self.assertTrue(out["installed"])
        self.assertTrue(out["verified"])
        self.assertTrue(out["launched"])
        self.assertEqual(out["package"], "com.alp.agent")
        install_cmd = run.call_args_list[0][0][0]
        self.assertIn("install", install_cmd)
        self.assertNotIn("-t", install_cmd)

    def test_older_sdk_failure_names_the_real_cause(self):
        from backend import workflows
        import subprocess as _sp
        old = _sp.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="Failure [INSTALL_FAILED_OLDER_SDK]")
        with mock.patch.object(workflows, "attached_serials", return_value=["S1"]), \
             mock.patch.object(workflows, "attached_detailed", return_value=[
                 {"serial": "S1", "state": "device", "ready": True}]), \
             mock.patch.object(workflows, "agent_apk_path",
                               return_value="/tmp/alp-agent-release.apk"), \
             mock.patch("subprocess.run", return_value=old):
            out = workflows.install_agent_app(serial="S1")
        self.assertFalse(out["installed"])
        self.assertIn("too old", out["error"])
        self.assertNotIn("missing after install", out["error"])

    def test_api_level_of_parses_getprop(self):
        from backend import workflows
        import subprocess as _sp
        ok = _sp.CompletedProcess(args=[], returncode=0, stdout="22\n", stderr="")
        with mock.patch("subprocess.run", return_value=ok):
            self.assertEqual(workflows.api_level_of("S1"), 22)
        bad = _sp.CompletedProcess(args=[], returncode=0, stdout="???\n", stderr="")
        with mock.patch("subprocess.run", return_value=bad):
            self.assertEqual(workflows.api_level_of("S1"), 0)
        with mock.patch("subprocess.run", side_effect=OSError("no adb")):
            self.assertEqual(workflows.api_level_of("S1"), 0)
        self.assertEqual(workflows.api_level_of(""), 0)

    def test_legacy_variant_resolution(self):
        from backend import workflows
        with mock.patch("os.path.isfile", return_value=False):
            with self.assertRaises(ValueError) as ctx:
                workflows.agent_apk_path("legacy")
        self.assertIn("legacy", str(ctx.exception))
        with self.assertRaises(ValueError):
            workflows.agent_apk_path("bogus")

    def test_unauthorized_device_is_reported_not_installed(self):
        from backend import workflows
        with mock.patch.object(workflows, "attached_serials", return_value=["S1"]), \
             mock.patch.object(workflows, "attached_detailed", return_value=[
                 {"serial": "S1", "state": "unauthorized", "ready": False}]), \
             mock.patch.object(workflows, "agent_apk_path",
                               return_value="/tmp/alp-agent-release.apk"), \
             mock.patch("subprocess.run") as run:
            out = workflows.install_agent_app(serial="S1")
        self.assertFalse(out["installed"])
        self.assertIn("unauthorized", out["error"])
        run.assert_not_called()

    def test_bad_variant_is_rejected_before_adb(self):
        from backend import workflows
        with mock.patch.object(workflows, "attached_serials", return_value=["S1"]), \
             mock.patch.object(workflows, "attached_detailed", return_value=[
                 {"serial": "S1", "state": "device", "ready": True}]), \
             mock.patch("subprocess.run") as run:
            with self.assertRaises(ValueError):
                workflows.install_agent_app(serial="S1", variant="bogus")
        run.assert_not_called()

    def test_agent_presence_true_only_on_pm_path_hit(self):
        from backend import workflows
        import subprocess as _sp
        hit = _sp.CompletedProcess(args=[], returncode=0,
                                   stdout="package:/data/app/com.alp.agent/base.apk",
                                   stderr="")
        miss = _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        fail = _sp.CompletedProcess(args=[], returncode=1, stdout="error", stderr="")
        with mock.patch("subprocess.run", return_value=hit):
            self.assertTrue(workflows.is_agent_installed("S1"))
        with mock.patch("subprocess.run", return_value=miss):
            self.assertFalse(workflows.is_agent_installed("S1"))
        with mock.patch("subprocess.run", return_value=fail):
            self.assertFalse(workflows.is_agent_installed("S1"))
        with mock.patch("subprocess.run", side_effect=OSError("no adb")):
            self.assertFalse(workflows.is_agent_installed("S1"))


class ProvisionDeviceOwnerTests(unittest.TestCase):
    def _run(self, *outputs):
        import subprocess as _sp
        return [_sp.CompletedProcess(args=[], returncode=code,
                                     stdout=out, stderr=err)
                for code, out, err in outputs]

    def _provision(self, install_ok=True, adb_outputs=()):
        from backend import workflows
        inst = {"serial": "S1", "installed": install_ok,
                "apk": "alp-agent-release.apk", "verified": install_ok,
                "launched": True}
        with mock.patch.object(workflows, "install_agent_app",
                               return_value=inst), \
             mock.patch("subprocess.run",
                        side_effect=list(adb_outputs)) as run:
            return workflows.provision_device_owner(serial="S1"), run

    def _restored_flag(self, run):
        for c in run.call_args_list:
            argv = c[0][0]
            if "user_setup_complete" in argv:
                pass
        puts = [c[0][0][-1] for c in run.call_args_list
                if "user_setup_complete" in c[0][0] and "put" in c[0][0]]
        return puts

    def test_success_path(self):
        out, run = self._provision(adb_outputs=self._run(
            (0, "1\n", ""),
            (0, "", ""),
            (0, "Success\n", ""),
            (0, "Device Owner: ComponentInfo{com.alp.agent/"
                ".AlpDeviceAdminReceiver}\n", ""),
            (0, "", ""),
        ))
        self.assertTrue(out["installed"])
        self.assertTrue(out["device_owner"])
        self.assertIn("1", self._restored_flag(run))

    def test_success_path_provisions_emergency_secret(self):
        from backend import workflows
        with mock.patch.object(workflows, "install_agent_app",
                               return_value={"serial": "S1", "installed": True,
                                             "verified": True, "launched": True}), \
             mock.patch("subprocess.run", side_effect=self._run(
                 (0, "1\n", ""),
                 (0, "", ""),
                 (0, "Success\n", ""),
                 (0, "Device Owner: ComponentInfo{com.alp.agent/"
                     ".AlpDeviceAdminReceiver}\n", ""),
                 (0, "", ""))), \
             mock.patch.object(workflows, "ensure_emergency_secret_on_device",
                               return_value={"provisioned": True,
                                             "device_id": "AVD-S1"}) as ensure:
            out = workflows.provision_device_owner(serial="S1")
        ensure.assert_called_once_with("S1", "")
        self.assertTrue(out["device_owner"])
        self.assertTrue(out["emergency_secret"]["provisioned"])

    def test_already_owner_path_provisions_emergency_secret(self):
        from backend import workflows
        import subprocess as _sp
        outs = [
            _sp.CompletedProcess(args=[], returncode=0, stdout="1\n", stderr=""),
            _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            _sp.CompletedProcess(
                args=[], returncode=1, stdout="",
                stderr="Error: Not allowed to set the device owner "
                       "because it is already set.\n"),
            _sp.CompletedProcess(
                args=[], returncode=0, stdout="admin=com.alp.agent/"
                ".AlpDeviceAdminReceiver\n", stderr=""),
        ]
        with mock.patch.object(workflows, "install_agent_app",
                               return_value={"serial": "S1", "installed": True,
                                             "verified": True, "launched": True}), \
             mock.patch("subprocess.run", side_effect=outs), \
             mock.patch.object(workflows, "ensure_emergency_secret_on_device",
                               return_value={"provisioned": True,
                                             "device_id": "AVD-S1"}) as ensure:
            out = workflows.provision_device_owner(serial="S1")
        self.assertTrue(out.get("already_owner"))
        self.assertTrue(out["emergency_secret"]["provisioned"])
        ensure.assert_called_once_with("S1", "")

    def test_helper_skips_unregistered_device_without_touching_vault(self):
        from backend import emergency as _emg
        from backend import workflows
        with mock.patch.object(workflows, "connect") as conn, \
             mock.patch("backend.recovery_credentials.RecoveryVault") as vault, \
             mock.patch.object(_emg, "provision_offline_secret") as prov:
            cur = conn.return_value.__enter__.return_value
            cur.execute.return_value.fetchone.return_value = None
            out = workflows.ensure_emergency_secret_on_device("S9", "")
        self.assertFalse(out["provisioned"])
        self.assertIn("enroll", out["reason"])
        vault.assert_not_called()
        prov.assert_not_called()

    def test_helper_provisions_registered_device(self):
        from backend import emergency as _emg
        from backend import workflows
        with mock.patch("backend.recovery_credentials.RecoveryVault") as vault, \
             mock.patch.object(_emg, "provision_offline_secret",
                               return_value={"provisioned": True,
                                             "delivery": {"ok": True}}):
            out = workflows.ensure_emergency_secret_on_device(
                "S1", device_id="AVD-S1")
        self.assertTrue(out["provisioned"])
        self.assertEqual(out["device_id"], "AVD-S1")
        vault.return_value.ensure_for.assert_called_once_with("AVD-S1")

    def test_accounts_refusal_restores_flag_and_explains(self):
        out, run = self._provision(adb_outputs=self._run(
            (0, "1\n", ""),
            (0, "", ""),
            (1, "Error: Not allowed to set the device owner because there "
                "are already some accounts on the device.\n", ""),
            (0, "", ""),
        ))
        self.assertTrue(out["installed"])
        self.assertFalse(out["device_owner"])
        self.assertIn("account", (out.get("hint") or "").lower())
        self.assertIn("1", self._restored_flag(run))

    def test_failed_install_never_touches_dpm(self):
        from backend import workflows
        with mock.patch.object(workflows, "install_agent_app",
                               return_value={"serial": "S1", "installed": False,
                                             "error": "refused"}), \
             mock.patch("subprocess.run") as run:
            out = workflows.provision_device_owner(serial="S1")
        self.assertFalse(out["installed"])
        self.assertFalse(out["device_owner"])
        run.assert_not_called()

    def test_legacy_success_without_dumpsys_owner_line(self):
        # Pre-24 Android prints no Device Owner section: an accepted claim
        # plus our active admin is the available (weaker, labelled) proof.
        from backend import workflows
        dump = ("Current Device Policy Manager state:\n"
                "  Enabled Device Admins (User 0):\n"
                "  com.alp.agent/.AlpDeviceAdminReceiver:\n    uid=10121\n")
        with mock.patch.object(workflows, "install_agent_app",
                               return_value={"serial": "S1", "installed": True,
                                             "verified": True,
                                             "launched": True}), \
             mock.patch.object(workflows, "ensure_emergency_secret_on_device",
                               return_value={"provisioned": False}), \
             mock.patch("subprocess.run",
                        side_effect=self._run(
                            (0, "1\n", ""),
                            (0, "", ""),
                            (0, "Success\n", ""),
                            (0, dump, ""),
                            (0, "22\n", ""),
                            (0, dump, ""),
                            (0, "", ""),
                        )):
            out = workflows.provision_device_owner(serial="S1")
        self.assertTrue(out["installed"])
        self.assertTrue(out["device_owner"])
        self.assertTrue(out.get("legacy_proof"))
        self.assertNotIn("error", out)

    def test_legacy_already_owner_resync_via_admin_entry(self):
        from backend import workflows
        dump = ("Enabled Device Admins (User 0):\n"
                "  com.alp.agent/.AlpDeviceAdminReceiver:\n")
        with mock.patch.object(workflows, "install_agent_app",
                               return_value={"serial": "S1", "installed": True,
                                             "verified": True,
                                             "launched": True}), \
             mock.patch.object(workflows, "ensure_emergency_secret_on_device",
                               return_value={"provisioned": False}), \
             mock.patch("subprocess.run",
                        side_effect=self._run(
                            (0, "1\n", ""),
                            (0, "", ""),
                            (1, "",
                             "IllegalStateException: device owner already set"),
                            (1, "usage: dpm", ""),
                            (0, "22\n", ""),
                            (0, dump, ""),
                            (0, "", ""),
                        )):
            out = workflows.provision_device_owner(serial="S1")
        self.assertTrue(out.get("already_owner"))
        self.assertTrue(out["device_owner"])

    def test_is_device_owner_active_legacy_fallback(self):
        from backend import workflows
        dump = "com.alp.agent/.AlpDeviceAdminReceiver:\n"
        with mock.patch("subprocess.run",
                        side_effect=self._run(
                            (1, "usage: dpm", ""),
                            (0, "22\n", ""),
                            (0, dump, ""),
                        )):
            self.assertTrue(workflows.is_device_owner_active("S1"))
        with mock.patch("subprocess.run",
                        side_effect=self._run(
                            (1, "usage: dpm", ""),
                            (0, "35\n", ""),
                        )):
            self.assertFalse(workflows.is_device_owner_active("S1"))


class DeviceOwnerStateIsProvenTests(unittest.TestCase):
    """device_owner_state is a claim about the PHONE. It must only ever be
    written from a dumpsys proof — writing it because the console asked is
    what let restrictions "deploy" onto a device that owned nothing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alp-do-")
        self.db_path = os.path.join(self.tmp, "alp.db")
        db.run_migrations(self.db_path)
        with db.connect(self.db_path) as c:
            c.execute("INSERT INTO devices (device_id, serial, manufacturer, "
                      "model, android_version, api_level, device_owner_state) "
                      "VALUES ('AVD-S1','S1','Samsung','SM-A145P',15,35,'NONE')")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _owner_state(self):
        with db.connect(self.db_path) as c:
            return c.execute("SELECT device_owner_state FROM devices "
                             "WHERE device_id='AVD-S1'").fetchone()[0]

    def _provision(self, dumpsys_owner: bool):
        from backend import workflows
        import subprocess as _sp
        outs = [
            _sp.CompletedProcess(args=[], returncode=0, stdout="1\n", stderr=""),
            _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            _sp.CompletedProcess(args=[], returncode=0, stdout="Success\n", stderr=""),
            _sp.CompletedProcess(
                args=[], returncode=0,
                stdout=("Device Owner: ComponentInfo{com.alp.agent/"
                        ".AlpDeviceAdminReceiver}\n" if dumpsys_owner else ""),
                stderr=""),
            _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        with mock.patch.object(workflows, "connect",
                               lambda *a, **k: db.connect(self.db_path)), \
             mock.patch.object(workflows, "install_agent_app",
                               return_value={"serial": "S1", "installed": True,
                                             "verified": True, "launched": True}), \
             mock.patch("subprocess.run", side_effect=outs):
            return workflows.provision_device_owner(serial="S1")

    def test_proof_of_ownership_persists_active(self):
        out = self._provision(dumpsys_owner=True)
        self.assertTrue(out["device_owner"])
        self.assertEqual(self._owner_state(), "ACTIVE")

    def test_refusal_never_claims_active(self):
        # dpm printed nothing useful -> the phone is NOT an owner, so the
        # column must not say ACTIVE.
        out = self._provision(dumpsys_owner=False)
        self.assertFalse(out["device_owner"])
        self.assertEqual(self._owner_state(), "NONE")

    def test_already_owner_refusal_keeps_active(self):
        """`set-device-owner` refuses even when THIS app is already the owner
        (a plain reinstall looks exactly like that). Probing first is what
        stops a true ACTIVE from being downgraded to NONE."""
        from backend import workflows
        import subprocess as _sp
        outs = [
            _sp.CompletedProcess(args=[], returncode=0, stdout="1\n", stderr=""),
            _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            _sp.CompletedProcess(
                args=[], returncode=1,
                stdout="", stderr="Error: Not allowed to set the device owner "
                                  "because it is already set.\n"),
            _sp.CompletedProcess(
                args=[], returncode=0,
                stdout="1 owner:\nUser 0: admin=com.alp.agent/"
                       ".AlpDeviceAdminReceiver,DeviceOwner,Affiliated\n",
                stderr=""),
        ]
        with mock.patch.object(workflows, "connect",
                               lambda *a, **k: db.connect(self.db_path)), \
             mock.patch.object(workflows, "install_agent_app",
                               return_value={"serial": "S1", "installed": True,
                                             "verified": True, "launched": True}), \
             mock.patch("subprocess.run", side_effect=outs):
            out = workflows.provision_device_owner(serial="S1")
        self.assertTrue(out["device_owner"])
        self.assertTrue(out.get("already_owner"))
        self.assertNotIn("error", out)
        self.assertEqual(self._owner_state(), "ACTIVE")

    def test_enroll_scan_never_claims_ownership(self):
        """A plain enroll carries no ownership proof at all."""
        from backend import workflows
        from capability_engine import scanner as scanner_mod
        prof = mock.Mock(model="SM-A145P", manufacturer="Samsung",
                         android_version=15, api_level=35,
                         build_fingerprint="fp", security_patch="2026-01",
                         bootloader="unlocked", verified_boot="green",
                         encryption="yes", states={}, methods={})
        with mock.patch.object(workflows, "connect",
                               lambda *a, **k: db.connect(self.db_path)), \
             mock.patch.object(scanner_mod, "adb_scan", return_value=prof):
            out = workflows.enroll_device("AVD-S1", "S1", device_owner=True)
        self.assertFalse(out["device_owner"])
        self.assertEqual(out["device_owner_state"], "NONE")
        self.assertEqual(out["next_step"], "install")
        self.assertEqual(self._owner_state(), "NONE")


if __name__ == "__main__":
    unittest.main()