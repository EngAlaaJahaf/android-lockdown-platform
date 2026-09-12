# PHASE 0 — Lab Preparation: Report

Status: **COMPLETE**
Date: 2026-09-12
Baseline: `docs/IMPLEMENTATION_BASELINE.md` (ALP-BASE-001)

## Objectives met (from EXECUTE gate)
1. Development + verification environment validated (tools, SDK, ADB).
2. Baseline repo created with schema, migrations, engine modules, backend control plane.
3. Device Registry seeded from physical firmware evidence; honest class tags.
4. Emulator device booted and capability-scanned live via ADB.

## Environment (verified 2026-09-12)
- Python 3.11.9, Node 22.12.0, OpenJDK (Zulu) 17.0.9.
- Android SDK: platforms 31/34/35/36.1, build-tools 34–36, aapt2/d8/apksigner/zipalign.
- AVD `alp_lab` (Pixel 4, Google APIs Play Store, API 36 = Android 16) — **booted, adb reachable**.
- No physical device attached (device-grade verdicts stay `NOT VERIFIED ON REAL DEVICE`).

## Test suite
- `python scripts/run_tests.py` → **55 tests, all OK** (0 failures).
- Covered: capability model (evidence gate, no silent SUPPORTED), policy model +
  snapshot resolution (API-boundary exceptions), verification engine (PASS impossible
  without evidence; simulated source never `is_pass`), compliance verdicts
  (violation → NON_COMPLIANT; unknowns never fabricate), security (audit hash-chain
  + tamper detection, scrypt, TOTP RFC-6238, sessions, RBAC matrix, dual-approval
  gate, HMAC command channel + nonce replay + expiry), fleet (waves, stop threshold,
  emergency stop), simulator (5→20→100→rest staging).

## Device Registry (seeded via scripts/seed_devices.py)
| device_id | model | OS | class_tag | evidence |
|---|---|---|---|---|
| LAB-0001 | SM-A145P (XSG) | 15 | VERIFIED | ODIN `AP_..._meta_OS15.tar.md5` |
| LAB-0002 | SM-A145P (XSG) | 14 | VERIFIED | ODIN `AP_..._meta_OS14.tar.md5` |
| DEV-0001 | SM-J320FN | 7  | UNKNOWN   | none — honest |

Notes: enrollment_state = ENROLLMENT_PENDING (provisioning step comes in PHASE 3+).
Capabilities per profile are `SUPPORTED` only where firmware evidence exists; J3 rows
stay `UNKNOWN`.

## Live live capability scan (emulator-5554, API 36 / Android 16)
`scripts/scan_live_device.py` → `reports/phase0/scan-emulator5554.json`
- All enforceables classified `ANDROID_VERSION_DEPENDENT` (never fabricated SUPPORTED).
- `GPS` = PARTIAL (hardware raw-off impossible from app layer — honest).
- `FACTORY_RESET_RECOVERY` and `REFLAH_FIRMWARE` = NOT_FEASIBLE from DPC (governance lanes).

## Issues found & fixed during the phase
- `backend` import failed because run-tests/env pushed package dirs instead of project root → fixed runner + `scripts/alp_env.ps1`.
- `hashlib.scrypt` memory-limit error → explicit `maxmem=512MB`.
- Audit chain false-positives → `_canonical()` now excludes the integer `id` column.
- State machine rejected the `ENROLLED` gateway (missing from STATES) → added.
- Command verify mutated the envelope (killed replay detection) → verify on a copy.
- Suite env isolation: `run_tests.py` now pins ALP_DB/SIGNING_KEY/AUDIT_SALT **before** any backend import (import-order bug).
- Scanner dropped Android 16 (out of 7..15 range) → range widened to 6..16 (API 36).

## Gate recommendation
**Open PHASE 1 (Project Foundation).** No blockers. Lab evidence rule remains in force:
nothing here claims device-grade support beyond the firmware-backed profiles above.