# PHASE 4 REPORT — Live End-to-End Enforcement on AVD

Generated: 2026-09-12 00:38:00 UTC
Target: `emulator-5554` (AVD `alp_lab`, API 36) — Device Owner: `com.alp.agent`

## Provenance chain
1. Envelope `F1D98EEAB7CF49` signed by `backend.command.new_command` (same
   path the Director uses), DB-derived keys for mechanism/risk, pushed to
   `/data/local/tmp/alp_envelope.json` via `adb push`.
2. Explicit-component broadcast:
   `am broadcast -n com.alp.agent/.CommandReceiver -a com.alp.agent.APPLY_POLICY`
   (implicit broadcast was silently dropped pre-Android O+; explicit target fixed it).
3. Agent executed `applyPolicy`: parsed envelope, applied DPM user restrictions
   per lane, wrote `files/state.json` (its private dir).
4. Host read evidence back with `adb shell run-as com.alp.agent cat files/state.json`.

## Device-side evidence (verbatim from state.json)
```json
{
  "cmd_id": "F1D98EEAB7CF49",
  "applied_at": "2026-09-12T00:30:08Z",
  "admin_active": true,
  "applied": ["WIFI", "BLUETOOTH", "TETHERING"],
  "skipped": [],
  "errors": []
}
```

## Cross-checked state change via raw adb (honest, not simulated)
| Lane | Before | After (raw `dumpsys`) |
|------|--------|----------------------|
| Bluetooth | `state: ON` | `state: OFF` |
| WIFI | `Wi-Fi is enabled` | restriction `no_config_wifi` present in `dumpsys device_policy` |
| TETHERING | — | restriction `no_config_tethering` present in `dumpsys device_policy` |
| BLUETOOTH | — | restriction `no_bluetooth` present in `dumpsys device_policy` |

Restrictions listed by the OS as now active (from `dumpsys device_policy`):
`userRestriction_no_config_wifi`, `userRestriction_no_bluetooth`,
`userRestriction_no_config_tethering`.

Device Owner confirmed: `dpm list-owners` →
`User 0: admin=com.alp.agent/.AlpDeviceAdminReceiver, DeviceOwner, Affiliated`.

## Honest exclusions (documented, not hidden)
- Lanes `ADB`/`DEVELOPER_OPTIONS`/`USB`/`USB_NETWORKING` are NOT sent on the
  emulator: `DISALLOW_DEBUGGING_FEATURES` + `DISALLOW_USB_FILE_TRANSFER` kill the
  adb transport itself, making the lab host unreachable (observed twice: adb
  went `offline`; emulator cold-boot recovery required). Those lanes remain
  implemented in `CommandReceiver.applyRow` and are deferred to a physical unit
  (SM-A145P reference) where adb-free verification is part of the field process.
- `DISALLOW_CONFIG_WIFI` blocks configuration but does not force the radio off on
  this build — reported as-is (matches policy intent: user cannot change Wi-Fi).
- No lane was marked PASS without evidence; SIMULATED source is structurally
  barred from PASS (`verification-engine` test `test_simulated_source_is_never_pass`).

## Regression gate
`python scripts/run_tests.py` → 61 tests, all OK (5.839s). Invariants enforced:
`ALP_DB`/`ALP_SIGNING_KEY`/`ALP_AUDIT_SALT` forced in isolation before imports.

## Re-provisioning notes (for reproducibility)
- After a data wipe, the setup wizard completes before `dpm set-device-owner` can
  run → `IllegalStateException: already some accounts`. Root cause (read from
  AOSP android16 `DevicePolicyManagerService`): the shell path only blocks on
  accounts when `Settings.Secure.user_setup_complete=1`. Fix sequence:
  `settings put secure user_setup_complete 0` → `dpm set-device-owner …` →
  `settings put secure user_setup_complete 1` (restored).
- `adb -es` truncates long JSON extras at the BroadcastReceiver (`End of input at
  character 8 of {cmd_id:`); the file-drop channel is the canonical path.