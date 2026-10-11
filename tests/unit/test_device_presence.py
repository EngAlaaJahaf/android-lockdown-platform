# -*- coding: utf-8 -*-
"""Device-details presence probe: opening details must reflect the phone.

Regression for the stale-details bug: the details page read only the
database, so after uninstalling the app from the phone it kept showing the
old groups/profiles as "Applied" with no Install button. _device_details now
re-probes `pm path` on every open and reports attached/agent_installed plus
the same next_step workflow the New Devices page uses.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "desktop"))
for _sub in ("backend", "policy-engine", "capability-engine",
             "verification-engine", "compatibility"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

from backend.db import connect, run_migrations  # noqa: E402
import backend.api.server as _srv  # noqa: E402


class DeviceDetailsPresenceTests(unittest.TestCase):
    def setUp(self):
        self._prev_db = os.environ.get("ALP_DB")
        fd, self._db = tempfile.mkstemp(prefix="alp_presence_", suffix=".db")
        os.close(fd)
        os.environ["ALP_DB"] = self._db
        run_migrations(self._db)
        with connect() as c:
            c.execute("DELETE FROM device_group_members WHERE device_id IN "
                      "(SELECT id FROM devices WHERE device_id='AVD-PRES-1')")
            c.execute("DELETE FROM devices WHERE device_id='AVD-PRES-1'")
            c.execute("INSERT INTO devices (device_id, serial, manufacturer, "
                      "model, android_version, api_level, device_owner_state) "
                      "VALUES ('AVD-PRES-1','SER-PRES-1','Samsung','SM-A145P',"
                      "15,35,'ACTIVE')")

    def tearDown(self):
        if self._prev_db is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev_db
        for suf in ("", "-wal", "-shm"):
            try:
                os.remove(self._db + suf)
            except OSError:
                pass

    def _details(self, attached, agent, owner=True):
        with mock.patch.object(_srv, "attached_serials",
                               return_value=["SER-PRES-1"] if attached else []), \
             mock.patch.object(_srv, "is_agent_installed", return_value=agent), \
             mock.patch.object(_srv, "is_device_owner_active",
                               return_value=owner):
            return _srv._device_details("AVD-PRES-1")

    def test_missing_app_reports_install_step(self):
        dev = self._details(attached=True, agent=False)
        self.assertTrue(dev["attached"])
        self.assertFalse(dev["agent_installed"])
        self.assertEqual(dev["next_step"], "install")
        self.assertIn("غير مثبت", dev["next_step_reason"])

    def test_present_app_with_owner_reports_group_step(self):
        dev = self._details(attached=True, agent=True, owner=True)
        self.assertTrue(dev["attached"])
        self.assertTrue(dev["agent_installed"])
        self.assertTrue(dev["device_owner_live"])
        self.assertEqual(dev["next_step"], "group")

    def test_present_app_without_owner_reports_provision_step(self):
        dev = self._details(attached=True, agent=True, owner=False)
        self.assertTrue(dev["agent_installed"])
        self.assertFalse(dev["device_owner_live"])
        self.assertEqual(dev["next_step"], "provision_owner")

    def test_detached_device_reports_offline(self):
        dev = self._details(attached=False, agent=False)
        self.assertFalse(dev["attached"])
        self.assertFalse(dev["agent_installed"])
        self.assertEqual(dev["next_step"], "offline")

    def test_unknown_device_still_404s(self):
        from backend.api.server import ApiError
        with self.assertRaises(ApiError):
            _srv._device_details("AVD-NOPE")


class DeleteDeviceTests(unittest.TestCase):
    def setUp(self):
        self._prev_db = os.environ.get("ALP_DB")
        fd, self._db = tempfile.mkstemp(prefix="alp_del_", suffix=".db")
        os.close(fd)
        os.environ["ALP_DB"] = self._db
        run_migrations(self._db)
        with connect() as c:
            c.execute("DELETE FROM device_group_members WHERE device_id IN "
                      "(SELECT id FROM devices WHERE device_id='AVD-DEL-1')")
            c.execute("DELETE FROM assignments WHERE device_id IN "
                      "(SELECT id FROM devices WHERE device_id='AVD-DEL-1')")
            c.execute("DELETE FROM devices WHERE device_id='AVD-DEL-1'")
            c.execute("DELETE FROM policies WHERE policy_id='POL-DEL-1'")
            c.execute("INSERT INTO devices (device_id, serial, manufacturer, "
                      "model, android_version, api_level, device_owner_state) "
                      "VALUES ('AVD-DEL-1','SER-DEL-1','Samsung','SM-A145P',"
                      "15,35,'NONE')")
            dev = c.execute("SELECT id FROM devices WHERE device_id='AVD-DEL-1'"
                            ).fetchone()["id"]
            c.execute("INSERT INTO policies (policy_id, display_name, "
                      "category, status, requirements) VALUES "
                      "('POL-DEL-1','del','CORPORATE_DEFAULT','ACTIVE','[]')")
            pol = c.execute("SELECT id FROM policies WHERE policy_id='POL-DEL-1'"
                            ).fetchone()["id"]
            c.execute("INSERT INTO device_groups (group_key, name) VALUES "
                      "('g-del','G-DEL')")
            gid = c.execute("SELECT id FROM device_groups WHERE group_key='g-del'"
                            ).fetchone()["id"]
            c.execute("INSERT INTO device_group_members (group_id, device_id) "
                      "VALUES (?,?)", (gid, dev))
            c.execute("INSERT INTO assignments (device_id, policy_id, snapshot) "
                      "VALUES (?,?,?)", (dev, pol, "[]"))

    def tearDown(self):
        if self._prev_db is None:
            os.environ.pop("ALP_DB", None)
        else:
            os.environ["ALP_DB"] = self._prev_db
        for suf in ("", "-wal", "-shm"):
            try:
                os.remove(self._db + suf)
            except OSError:
                pass

    def test_delete_cleans_children_and_row(self):
        from backend import workflows
        with mock.patch.object(workflows, "attached_serials", return_value=[]):
            out = workflows.delete_device("AVD-DEL-1")
        self.assertTrue(out["deleted"])
        self.assertFalse(out["presence_verified"])
        self.assertIn("device_group_members", out["cleaned"])
        self.assertIn("assignments", out["cleaned"])
        with connect() as c:
            self.assertIsNone(c.execute(
                "SELECT id FROM devices WHERE device_id='AVD-DEL-1'").fetchone())
            self.assertIsNone(c.execute(
                "SELECT id FROM device_group_members WHERE device_id NOT IN "
                "(SELECT id FROM devices)").fetchone())

    def test_delete_refuses_while_app_proven_present(self):
        from backend import workflows
        with mock.patch.object(workflows, "attached_serials",
                               return_value=["SER-DEL-1"]), \
             mock.patch.object(workflows, "is_agent_installed",
                               return_value=True):
            with self.assertRaises(ValueError) as ctx:
                workflows.delete_device("AVD-DEL-1")
        self.assertIn("still installed", str(ctx.exception))
        with connect() as c:
            self.assertIsNotNone(c.execute(
                "SELECT id FROM devices WHERE device_id='AVD-DEL-1'").fetchone())

    def test_delete_unknown_device_raises(self):
        from backend import workflows
        with self.assertRaises(ValueError):
            workflows.delete_device("AVD-NOPE")


if __name__ == "__main__":
    unittest.main()
