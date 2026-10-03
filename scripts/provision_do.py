"""Provision the connected device as Device Owner via the real R2_REPROVISION
recovery mode (same engine path the desktop console uses)."""
import os
import sys
import tempfile

ROOT = r"D:\projects\android-lockdown-platform"
sys.path.insert(0, ROOT)

ADB = r"D:\T\platform-tools-latest-windows\platform-tools\adb.exe"
os.environ["ALP_ADB"] = ADB
os.environ["ALP_SIGNING_KEY"] = "r2-live-test-key-0001"

fd, DB = tempfile.mkstemp(prefix="alp_r2_prov_", suffix=".db")
os.close(fd)
os.environ["ALP_DB"] = DB

from backend.db import run_migrations
from backend.recovery import RecoveryEngine

run_migrations(DB)

SERIAL = os.environ.get("ALP_SERIAL", "").strip()
if not SERIAL:
    import subprocess
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        if "\tdevice" in line:
            SERIAL = line.split("\t")[0].strip()
            break
print("target serial:", SERIAL)

eng = RecoveryEngine(db_path=DB, channel_send=None,
                     signing_key="r2-live-test-key-0001")
res = eng.recover("DEV-" + SERIAL, "R2_REPROVISION", "SUPER_ADMIN", admin_id=0,
                  mfa_ok=True, approval={"approved": True,
                                         "reason": "provision test device as DO"},
                  serial=SERIAL, exec_=True)
d = res.to_dict()
print("STATUS:", d["status"])
print("REASON:", d["reason"])
for step in d.get("details", {}).get("executed", []):
    print("  step", step["step"], "ok=", step["ok"], "|", step["out"][:90])
print("EVIDENCE:", d["evidence_id"])