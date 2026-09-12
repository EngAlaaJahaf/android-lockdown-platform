# ALP — Project Close Report (PHASE 0–4)

Generated: 2026-09-12 00:40:00 UTC

## Deliverables
- **PHASE 0 — Lab**: AVD `alp_lab` (API 36) provisioned; scan
  `reports/phase0/scan-emulator5554.json`; device library
  `LAB-0001`/`LAB-0002` (SM-A145P OS15/OS14, VERIFIED with ODIN evidence) +
  `DEV-0001` (SM-J320FN, UNKNOWN) in `database/alp.db`.
- **PHASE 1 — Control Plane (CLI)**: `scripts/alp.py` (bootstrap, MFA TOTP
  login, devices, enroll, policies, apply, jobs, approvals, audit, sim, report)
  against `backend/` (Director, command, verification/compliance engines, audit).
  Real `apply --real` on AVD produced honest FAIL/NON_COMPLIANT verdicts driven
  by actual ADB observations; `sim --n 200` full rollout; `audit --tamper` = 0
  broken chained entries. `reports/phase1/PHASE1_REPORT.md`.
- **PHASE 2 — HTTP API**: `backend/api/server.py` (stdlib, Bearer tokens from
  `auth.create_session`, RBAC per route, MFA-gated sensitive ops),
  `scripts/alp_api.py` + `scripts/api_smoke.py` (isolated server, negative
  RBAC/MFA/400 tests green).
- **PHASE 3 — Android Agent**: `android-agent/alp-agent.apk` (20,943 B) built
  with raw SDK tools (aapt2/javac/d8/zipalign/apksigner, no Gradle/Docker),
  signed with `android-agent/alp-debug.keystore`; Device Owner
  (`com.alp.agent/.AlpDeviceAdminReceiver`) active + Affiliated on AVD.
- **PHASE 4 — Live End-to-End**: signed envelope → `adb push` → explicit
  broadcast → DPM restriction application → `run-as` state read-back →
  cross-checked raw device change (BT OFF, restrictions live). See
  `reports/phase4/PHASE4_LIVE_ENFORCEMENT.md`.

## Honesty invariants held
- PASS requires a real device observation (verified by
  `test_pass_impossible_without_evidence`, `test_real_device_with_evidence_can_pass`).
- SIMULATED source can never yield PASS (`test_simulated_source_is_never_pass`).
- Verdict vocabulary on devices maps FAIL→NON_COMPLIANT; compliance wrote only
  on real PASS evidence.
- ADB/USB/DEVELOPER_OPTIONS restriction lanes implemented but intentionally not
  exercised on the emulator (they sever the adb transport); documented as
  physical-unit lanes. No SUPPORTED claim without Lab evidence.

## Quality gate
`scripts/run_tests.py`: **61/61 OK** in 5.84s (DB/signing/audit salt isolated).

## Reproducing Device-Owner provisioning after wipe
`settings put secure user_setup_complete 0` → `dpm set-device-owner …` →
`settings put secure user_setup_complete 1`. (Root cause read from AOSP
android16 DevicePolicyManagerService; recorded in the PHASE 4 report.)

## Out of scope / next lab
- Physical SM-A145P pass where adb-free device-owner verification is run.
- Field-collected compliance evidence stamping from the Device Owner.