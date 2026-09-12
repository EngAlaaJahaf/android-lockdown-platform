"""Director (AD-4 pipeline) offline tests — honest fakes, no real devices."""
import os
import sys
import unittest

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
        res = d.apply("LAB-0001", pol, cap, compat_layer=AndroidCompatibilityLayer(35),
                      evidence_src="REAL_DEVICE")
        self.assertEqual(res.verification.result, "PARTIAL")
        self.assertEqual(res.compliance, "NON_COMPLIANT", "violation trumps partial")

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


if __name__ == "__main__":
    unittest.main()