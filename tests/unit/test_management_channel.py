# -*- coding: utf-8 -*-
import os, tempfile, sqlite3
from backend.management_channel import (
    management_channel_status, check_recovery_channel, RecoveryChannelError,
    CRITICAL_FEATURES)
from backend import db

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestManagementChannel:
    SCHEMA = open(os.path.join(_ROOT, "database", "schema.sql")).read()

    def _fresh(self, tmp):
        path = os.path.join(tmp, "mc_test.db")
        conn = sqlite3.connect(path)
        try:
            conn.row_factory = sqlite3.Row
            conn.executescript(self.SCHEMA)
        finally:
            conn.close()
        return path

    def test_critical_features_constant(self):
        assert "ADB" in CRITICAL_FEATURES
        assert "USB" in CRITICAL_FEATURES
        assert "WIFI" not in CRITICAL_FEATURES
        assert "CAMERA" not in CRITICAL_FEATURES

    def test_non_critical_features_no_blocking(self):
        """Non-critical lanes are allowed even when no recovery channel exists."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fresh(tmp)
            res = check_recovery_channel(
                "DEV-01", ["WIFI", "CAMERA", "MICROPHONE"],
                db_path=path, attached=False)
            assert res["allowed"] is True
            assert res["critical_lanes"] == []

    def test_critical_lane_no_recovery_blocks(self):
        """Critical lanes blocked when no recovery channel is available."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fresh(tmp)
            res = check_recovery_channel(
                "DEV-01", ["ADB", "DEVELOPER_OPTIONS", "USB"],
                db_path=path, attached=False, strict=False)
            assert res["allowed"] is False
            assert res["critical_lanes"] == sorted(["ADB","DEVELOPER_OPTIONS","USB"])
            assert "NONE" in res["summary"]

    def test_critical_lane_adb_live_allows(self):
        """ADB live channel satisfies the recovery gate."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fresh(tmp)
            res = check_recovery_channel(
                "DEV-01", ["USB", "ADB"],
                db_path=path, serial="FAKE", attached=True)
            assert res["allowed"] is True
            assert res["channels"]["adb_live"] is True

    def test_critical_lane_credential_issued_allows_engine(self):
        """Recovery credential issued satisfies the gate (engine usable)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fresh(tmp)
            conn = sqlite3.connect(path)
            try:
                conn.execute("INSERT INTO devices (device_id,model) VALUES ('DEV-02','SM-X')")
                conn.execute("INSERT INTO recovery_credentials "
                             "(device_id,recovery_id,credential_ciphertext,nonce) "
                             "VALUES ('DEV-02','CCCC-BBBB',X'01',X'02')")
                conn.commit()
            finally:
                conn.close()
            res = check_recovery_channel(
                "DEV-02", ["USB_NETWORKING"],
                db_path=path, attached=False)
            assert res["allowed"] is True
            assert res["channels"]["recovery_engine"] is True

    def test_critical_lane_inapp_rollback_allows(self):
        """In-app rollback flag satisfies the gate."""
        res = check_recovery_channel(
            "DEV-03", ["DEVELOPER_OPTIONS"],
            attached=False, dpc_in_app_rollback=True)
        assert res["allowed"] is True
        assert res["channels"]["dpc_in_app_rollback"] is True

    def test_strict_raises_RecoveryChannelError(self):
        """Strict mode raises when no recovery channel is available."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fresh(tmp)
            try:
                check_recovery_channel(
                    "DEV-04", ["ADB", "USB"],
                    db_path=path, attached=False, strict=True)
                assert False, "expected exception"
            except RecoveryChannelError:
                pass

    def test_strict_off_returns_dict_only(self):
        """Non-strict mode reports blocked but does not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fresh(tmp)
            res = check_recovery_channel(
                "DEV-05", ["USB"],
                db_path=path, attached=False, strict=False)
            assert res["allowed"] is False
            assert isinstance(res, dict)

    def test_mixed_features_partial_critical(self):
        """Only critical features are checked; allowed when non-critical present."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fresh(tmp)
            res = check_recovery_channel(
                "DEV-06", ["WIFI", "USB", "CAMERA"],
                db_path=path, attached=False, strict=False)
            assert res["allowed"] is False
            assert res["critical_lanes"] == ["USB"]