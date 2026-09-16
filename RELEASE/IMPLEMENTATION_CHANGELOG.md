# IMPLEMENTATION_CHANGELOG — v1.0.0-rc1

> Release date: 2026-09-12 · Status: **READY FOR CONTROLLED PILOT**
> Previous baseline: `docs/IMPLEMENTATION_BASELINE.md` (git `faebe29`).

This changelog records the work delivered for the full execution mandate
(71 requirements: Arabic RTL desktop UI, capability-driven policies, honest
verification, recovery, RBAC/audit, diagnostics, Windows EXE + installer,
release packaging, final report).

## 1) Desktop application (Arabic RTL, Qt)
- New **Arabic-first RTL UI** `desktop/alp_manager/app_qt.py` (~1 470 lines)
  with 15 pages:
  1. الرئيسية (dashboard/cards) — 2. الأجهزة (devices) — 3. تفاصيل الجهاز —
  4. فحص القدرات (capabilities, from real live probe) — 5. السياسات (policies) —
  6. تطبيق السياسة مع المعاينة (apply with preview) — 7. التحقق (verification) —
  8. حالة الالتزام (compliance) — 9. الاسترداد (recovery R1–R4) —
  10. السجلات (audit chain + tamper check) — 11. التقارير (reports) —
  12. التشخيص (diagnostics) — 13. الإعدادات (settings) — 14. المساعدة (help) —
  15. حول البرنامج (about).
- Arabic state vocabulary everywhere: متوافق / متوافق جزئيًا / غير متوافق /
  غير مدعوم / غير معروف / فشل التنفيذ — never claims "نجاح" without proof.
- Dark theme stylesheet, Arabic font stack (Segoe UI / Tahoma + HarfBuzz shaping),
  QThreadPool background tasks with per-tag result handlers, 4 s auto-refresh.
- Launcher `desktop/run_app.py` now prefers Qt (`app_qt`), falls back to Tk
  (`--tk` or `ALP_FORCE_TK=1`).
- `Controller` grew 4 honest methods (unit-tested):
  - `capabilities(device_id)` — capability profile from real registry + device row.
  - `policy_preview(device_id, policy)` — per-requirement desired vs CURRENT,
    with `source = REAL_DEVICE | DEVICE_NOT_ATTACHED`.
  - `reports_list(device_id)` — persisted reports (md/json/html).
  - `diagnostics()` — DB, ADB, session, audit-chain, bootstrap state.

## 2) Bugs found and fixed during validation (honest engineering)
- **`paths.add_engine_paths()`** put `backend` on `sys.path` as a direct entry,
  but the package lives at `root/backend`; only cwd-based imports ever worked.
  `python desktop/run_app.py` crashed with `ModuleNotFoundError: backend`.
  Fixed to also expose the repository root. (Regression covered by new smoke.)
- **`backend/workflows.run_director_apply`** crashed on `sqlite3.Row.get(...)`
  — the real APPLY path died with `AttributeError`. Converted to `dict(row)`.
  Covered by new `test_workflow_apply_registered_db_device`.
- **VerificationEngine felt "BLOCK" intents were unmet by an ACTIVE restriction**:
  policy `WIFI: BLOCK` vs live `RESTRICTED` produced FAIL even though a proven
  restriction is the enforcement proof. `RESTRICTED` now satisfies
  `OFF | RESTRICT | BLOCK`. Covered by `test_restricted_observation_satisfies_block_intent`.
- **app_qt**: fixed `_statusBar()`→`statusBar()`, removed duplicated dead
  `QGridLayout` on a frame, ternary precedence bug in probe line, unused import.
  Live-windowed smoke run: clean event loop, 15 pages, device table renders.

## 3) Verification & tests
- New tests for capabilities / preview honesty / diagnostics / reports
  (`tests/unit/test_controller.py`) + the two regressions above.
- **Full suite: `108 tests, OK`** (`python scripts/run_tests.py`).
- Headless **live validation on emulator-5554** (real ADB):
  - preview `source = REAL_DEVICE`; observed WIFI/BLUETOOTH `RESTRICTED`,
    MOBILE_DATA `OFF`, TETHERING `RESTRICTED`.
  - `apply POL-FULL_LOCKDOWN` → `stage COMPLETE`, real evidence
    `EV-20260912-AB301CE8`, audit `AUD-6B068F73E6A2`.
  - honest verification outcome: **UNKNOWN** (many lanes not yet observable on
    the emulator) → never a fabricated PASS; compliance `NON_COMPLIANT`.
  - audit chain recorded `AD4_APPLY` + `RECOVER_R4`.

## 4) Windows release artifacts
- **Portable EXE** `dist/ALPManager.exe` (52 100 471 B, PySide6, onefile,
  `console=false`). Verified: launches, window events, 15 pages, responsive.
  Copies also on Desktop.
- **Installer** `dist/AndroidLockdownManager_Setup.exe` (59 637 183 B). Hosts a
  per-user installer (no admin): installs to `%LOCALAPPDATA%\Programs\AndroidLockdownManager`,
  creates Start-Menu + Desktop shortcuts, per-user uninstall entry.
  **Full install → run → uninstall cycle verified on the binary.**
- Data remains out-of-line: `%LOCALAPPDATA%\ALPManager\` (DB/keys/reports) so
  onefile re-extraction never loses state.

## 5) What is NOT done / honest limitations
- **No physical SM-J337P available** — Samsung J3 (2018+) support is delivered
  and unit-tested against the vendor registry, but all device-level results for
  that class are classified SIMULATED, never presented as real-device evidence.
  → Final status is **READY FOR CONTROLLED PILOT**, not PRODUCTION-READY.
- Emulator validation used API 36; some lanes (CAMERA, MICROPHONE, GPS-LOCATION
  switch) are not observable there → honest UNKNOWN.
- Tk fallback is untested after the Qt switch (acceptable: fallback only).

## 6) Files
- `desktop/alp_manager/app_qt.py` — new Arabic RTL Qt UI.
- `desktop/alp_manager/controller.py` — +4 methods.
- `desktop/alp_manager/paths.py` — sys.path fix.
- `desktop/run_app.py` — Qt-first launcher.
- `backend/workflows.py`, `verification-engine/verification_engine/__init__.py` — fixes.
- `tests/unit/test_controller.py`, `tests/unit/test_director.py`,
  `tests/unit/test_verification.py` — new/updated tests (108 total).
- `deployment/ALPManager.spec`, `deployment/installer_app.py`,
  `deployment/AndroidLockdownManager_Setup.spec` — build + installer.
- `RELEASE/*` — packaged artifacts. `FINAL_RELEASE_VALIDATION_REPORT.html` — full report.

## 7) Open-console redesign (P0–P4) — v1.0.0 rebuild
> Same version, **rebuilt artifacts** (grower sizes: portable 55,927,374 B, setup
> 63,444,130 B). New SHA256 in `SHA256SUMS.txt`. Full suite now **110 tests OK**.

Authentication model switch — **no interactive Login/TOTP at startup**:
- The dashboard opens directly in a *local-operator* mode (`Controller._require_session(session_required=False)`). Every sensitive operation is gated by a **per-device recovery credential** (possession factor) — `RecoveryVault.verify_for()` must return `ok` before APPLY / RECOVER / FIRMWARE can run (`Controller._can_use_recovery`).
- Recovery credentials are **encrypted-only** via Windows DPAPI (`backend/recovery_credentials.py`), stored per-device, never shared, never displayed. UIs show only a display-only `Recovery ID: XXXX-XXXX`. Recovery is a legitimate mechanism only — the docs never present it as a bypass/«بلا حماية».
- Approval factor replaced: legacy `approval.approve(approval_id, approver_id, mfa_ok=True)` kept for old callers (suffixes username as `admin:<username>`); new `approval.confirm(approval_id, approver_name, reason=...)` records **named human confirmations**; the dual rule requires **two distinct names** (rejects same name twice).
- Legacy session roles (RBAC) still exist internally; `auth.authorize()` also accepts `credential_ok`. `backend/recovery.py` keeps its legacy `mfa_ok=` positional-first signature so old callers stay valid.

Controller / UI / CLI changes (`controller.py`, `app_qt.py`, `app.py`, `scripts/alp.py`):
- `apply()` drops the MFA param and requires the possession gate; passes `mfa_ok=True` into `run_director_apply` only after `_can_use_recovery` succeeded.
- `recover()` = possession gate first; R1/R2 dual approval via `confirm()` unless `skip_approval`; R3 auto-approves at controller level so the engine emits an honest REFUSED; results carry `d["ok"]`/`d["error"]`.
- New controller API: `recovery_status()`, `recovery_vault_summary()`, `rotate_recovery()`, `revoke_recovery()`.
- Qt + Tk UIs: header login widgets replaced by a single local-operator status label; apply/recovery tabs show possession status with refresh; recovery approver fields are named confirmation fields.
- `backdoor` terminology removed from docs; `SYSTEM_OPERATION_AND_USER_SCENARIOS.html` migrated to the open-console flow (no TOTP/MFA user-facing mentions remain); new `AUTHENTICATION_AND_RECOVERY_DESIGN.html`.

Database: `recovery_credentials` and `approval_confirmations` tables added
(migrations `007`, `008`).

## 8) Plug-in auto-detection — v1.0.0 rebuild #2
> Rebuilt artifacts again: portable 55,931,659 B, setup 63,449,968 B.
> New SHA256 in `SHA256SUMS.txt`. Full suite now **111 tests OK**.

"يتعرّف عليه مباشرة": connect a phone and the app shows it immediately —
no manual serial typing needed.
- `backend/workflows.attached_detailed()` — parses `adb devices -l` into
  `{serial, state, model, ready}`; `ready` = authorized+online (`device`),
  `unauthorized`/`offline` are reported honestly (UI tells the user to enable
  USB debugging instead of pretending the phone is usable).
- `Controller.detected()` — merges the live ADB list with the DB registration
  set, flagging `registered` and readiness.
- Qt UI (`app_qt.py`): the Devices page shows a live banner of detected phones
  (ready / needs USB-debugging / already registered) and auto-fills the serial
  field with the first ready unregistered device — one click on
  «تسجيل الجهاز» finishes enrollment. Polled every 4 s by the existing timer.
- Tk fallback (`app.py`) gets the same detection line + auto-fill.
- Test: `test_detected_lists_attached_state_and_registration` (mocked ADB,
  hermetic).

## 9) Frozen-EXE fix: engine packages were missing — v1.0.0 rebuild #3
> Critical fix for the packaged binaries. Rebuilt again: portable 55,996,283 B,
> setup 63,486,299 B. New SHA256 in `SHA256SUMS.txt`. Tests unchanged (111 OK).

Runtime `ModuleNotFoundError: No module named 'capability_engine'` in the EXE —
the five engine packages are imported lazily inside
`backend/workflows.py` functions (`capability_engine`, `policy_engine`,
`verification_engine`, `vendor_adapters`, `compatibility`), but the PyInstaller
spec's `pathex=[ROOT]` could not resolve them because they live under
`*-engine/` / `vendor-adapters/` / `compatibility/` subdirectories. They were
therefore never bundled, and every probe / apply / capabilities / preview /
verify action failed at runtime.
- `deployment/ALPManager.spec`: `pathex` now also includes the five engine dirs.
- Verified via `archive_viewer`: the EXE now embeds `capability_engine(.scanner)`,
  `policy_engine(.snapshot)`, `verification_engine(.probe/.compliance)`,
  `vendor_adapters(.registry)`, `compatibility` — and `warn-*.txt` has 0
  "not found" entries. Root cause: packaging, not application logic.
- Installer hardening (rebuild of `dist/AndroidLockdownManager_Setup.exe` only —
  ALPManager.exe unchanged): first-attempt remove/overwrite of the 55 MB exe
  could fail on a transient real-time AV lock; `uninstall()` / `install()` now
  retry with backoff and report a clear error instead of failing silently.
**Verified live: install → immediate uninstall cleans dir/exe/shortcuts/
   uninstall-entry on the first attempt; user data in `%LOCALAPPDATA%\ALPManager`
   is preserved.** Setup SHA256→`82AC…61948`; portable unchanged `5533A…D9DD`.

## 10) Hardening pass + real-device pilot — v1.0.0 rebuild #4 (2026-09-13)
> Rebuilt artifacts: portable 55,991,946 B, setup 63,511,653 B. New SHA256 in
> `SHA256SUMS.txt`. Full suite now **118 tests OK**. First controlled pilot run
> on a **real SM-J337P** device (attached via ADB).

Console-window suppression (P0): every runtime subprocess (`adb`, `dumpsys`,
`powershell`) is now launched with `CREATE_NO_WINDOW` (`backend/workflows.py`,
`backend/channel.py`, `backend/recovery.py`,
`verification-engine/verification_engine/probe.py`,
`capability-engine/capability_engine/scanner.py`,
`deployment/installer_app.py`) — no command windows ever flash on screen.

Startup crash is never silent:
- New `desktop/alp_manager/logger.py` — structured runtime logger to
  `%LOCALAPPDATA%\ALPManager\logs\alp.log` (+ `startup-error.log`); never logs
  secrets.
- `desktop/run_app.py` and both UIs move the full startup into `main() -> int`,
  catch any startup failure, write the traceback, and show the log dir instead
  of closing invisibly.

Device selection & context everywhere:
- Devices page shows a live 5-column discovery table (الجهاز/الرقم التسلسلي/
  الحالة/الاتصال/التسجيل) + «فتح الجهاز (تحديد)» + «إعادة البحث (ADB)».
- An active-device banner (الجهاز المحدد) is persisted via
  `set_active_device()/active_device()` (plain `active.json`, metadata only) and
  mirrored into Apply/Recovery combos; probe/capability scans use the active
  context first.

Apply flow is now gated honestly:
- New `Controller.preflight(device_id, policy)` returns a real checklist
  (registration, policy known, ADB attach/authorization, device-policy
  readability, Device-Owner/DPM channel warning, per-device recovery credential,
  capability scope) with verdict PASS | CONDITIONAL | FAIL and `can_apply`.
- The Apply page runs preflight first, locks all sensitive widgets during the
  operation, asks for confirmation, then applies; on success the Verification
  page shows a structured summary table (device/policy/phase/evidence source/
  verdict/compliance/evidence_id/audit_id/chain integrity) plus the audit trail
  with HMAC tamper check. Recovery page is similarly locked and flow-tracked.

Per-device recovery credential is **auto-issued at first registration** on this
console (`RecoveryVault.ensure_for` inside `Controller.enroll`; new
`Controller.issue_recovery` for repair) — ownership of the issuing console is the
possession factor; credentials stay DPAPI-encrypted and never displayed.

Robustness:
- `backend/config.signing_key()` reads the env at call time — eliminates an
  import-order flake that froze an empty signing key and broke 3
  `test_security.py` tests in full-suite runs only.
- Fixed `_sync_active()` `'NoneType' has no attribute 'get'` crash on a fresh
  database (no active device yet) — found by the packaged-EXE smoke, not by unit
  tests.
- Model normalization `SM_J337P` → `SM-J337P` (adb `-l` spelling) in
  `workflows` + `Controller.detected()`.

Real-device pilot results (SM-J337P, serial 520041d74247b58b):
- ADB attach detected; UI-ready device; enrolled as `AVD-520041d74247b58b`
  (auto ID, never hardcoded); active-device context persists across restarts.
- `preflight POL-PHONE_ONLY` on the fresh console: PASS registration/ADB/
  policy-read/capability checks; WARN no Device-Owner DPC (plan-only →
  conditional lane); latest run blocks only on the missing credential in an
  un-issued state, and auto-issuance at enrollment now clears it — honest
  CONDITIONAL, never fabricated PASS.

## 11) Error-handling hardening — v1.0.0 rebuild #5 (2026-09-13)
> Rebuilt artifacts: portable 55,991,945 B, setup 63,509,487 B. New SHA256 in
> `SHA256SUMS.txt`. Full suite now **119 tests OK**.

Real pilot APPLY on the physical SM-J337P exposed a masking bug:
- `Controller.apply`/`recover` passed `device_id=`/`policy=` keywords to
  `logger.log_error()`, whose signature had no `**data` — so any real engine
  failure raised `TypeError: log_error() got an unexpected keyword argument
  'device_id'` and the true cause was hidden. `log_error` now forwards `**data`
  (same contract as `log_event`); regression test
  `test_apply_internal_error_not_masked_by_logger` ensures the real error
  surfaces.
- `apply`/`recover` also passed the import-frozen `config.SIGNING_KEY`; switched
  to call-time `config.signing_key()` so a stale frozen value can never silently
  fail signing.

Pilot outcome (real device, real evidence `EV-20260913-1300D9CD`,
`AUD-58CE3956FF20`, `stage=COMPLETE`, `source=REAL_DEVICE`): verification grades
itself honestly — `verification=PARTIAL`, `compliance=NON_COMPLIANT`,
`honest=false`, WIFI still `ON` — the system reports the gap instead of
fabricating a PASS. `staged: []` is a display artifact of the injected live
channel (chan_state not populated on that path) and does not affect evidence.

## 12) Mandate gap-close: extended identity, compliance persistence, UI gaps,
      FULL LOCKDOWN wizard, live apply green-path — v1.0.0 rebuild #6/#7
> Rebuilt artifacts (final): portable 56,007,781 B, setup 63,526,775 B. New
> SHA256 in `SHA256SUMS.txt`. Full suite now **129 tests OK** (124 → 129).
> Final controlled pilot on the same physical SM-J337P.

Accurate on-device identity (B2): the REAL probe now reads and stores 6 more
evidence fields — `security_patch` (e.g. `2021-10-01`), `kernel_version`
(`uname -r`), `bootloader`, `verified_boot` (`green`/`orange`…), `encryption`,
`baseband`. All shown in the device page probe summary; absent values are
honestly `""` (never guessed).
(`verification-engine/verification_engine/probe.py`)

Dead-code hygiene (B3): removed the `_not_used()` director stub and its comment
block, the vestigial `AdapterFactory` (vendor-adapters) and unused `Optional`
import, and the back-compat `Layer` alias (compatibility); deleted the orphan
`backend/verification_support.py`.

Compliance snapshot persistence (B4): `apply()` now writes the per-feature
**expected vs actual** snapshot into the `compliance` table (truthfully
`UNKNOWN` until a Device Owner proves enforcement) with FK-safe policy lookup.
Regressions in `tests/unit/test_custom_policies.py::ComplianceSnapshotTests`.

Repository hygiene (B5): `requirements.txt` (PySide6==6.11.1,
pyinstaller==6.20.0, pytest==9.1.1), `.gitignore` covers `database/alp.db*`,
tracked DB removed from the index (`git rm --cached`). The runtime DB stays
`%LOCALAPPDATA%\ALPManager\alp.db`.

Honest apps inventory: new `workflows.apps(serial)` + `Controller.apps()` read the
real `pm list packages`/`-3` list (third-party vs system) — presented as a
read-only inventory with the honest caveat that uninstall blocking only becomes
possible after Device Owner via the DPC agent (page «التطبيقات»).

Custom-policy builder + FULL LOCKDOWN wizard:
- `workflows.create_custom_policy(name, category, features, risk)` persists
  `POL-CUST-YYYYMMDD-HHMMSS` policies (requirements JSON) that
  `resolve_policy()` rehydrates; validated against `FEATURES`/categories.
- Policies page gains a checked builder grid over 27 blockable features
  (category «عامة/تقييد/اتصالات…») and a **Full Lockdown wizard**
  (`FullLockdownWizard`): 25 features pre-checked, creates a
  FULL_LOCKDOWN/CRITICAL custom policy in one step.

Real live apply green-path (the run that matters):
- `POL-PARTIAL` (corporate-derived) had `GPS`/`LOCATION: RESTRICT` lanes, but the
  compatibility layer only mapped BLOCK for them → every REAL apply on the
  attached SM-J337P stopped at the honest gate
  `ApplyBlocked: ... 2 unresolved exceptions: ['GPS','LOCATION']`.
- Root cause fixed: `GPS`/`LOCATION` now map `RESTRICT` → the same
  `user_restriction_disable_location_services` mechanism as BLOCK (parity rule,
  exactly like `MOBILE_DATA`). New `tests/unit/test_restrict_location.py` (5
  tests) locks the parity and the API≥23 floor. **Deployment PIPELINE first
  real end-to-end run on the physical device completed**:
  `stage=COMPLETE`, `ok=True`, `source=REAL_DEVICE`, evidence
  `EV-20260913-947AA082`, audit `AUD-2B48F422A6F7`, compliance row persisted
  (`result=UNKNOWN`, honest — DPC not yet provisioned). Earlier blocked run and
  full debug chain preserved in the internal session notes.

Full suite: **129 tests OK** (`python scripts/run_tests.py`). Both artifacts
rebuilt (portable + installer), smoke-launched offscreen (clean), copied to
`RELEASE/`, SHA256 regenerated.

## 13) On-device DPC lockdown — Device Owner installed on the physical SM-J337P
> Post-release live step. No desktop EXE rebuild (no desktop code changed);
> the Android agent was rebuilt (same signature) and reinstalled over its DPC.

- **Device Owner provisioned for real**: `adb shell dpm set-device-owner
  com.alp.agent/.AlpDeviceAdminReceiver` → Success (user 0,
  `provisioningState: 3`). Do-owner survives the update reinstall (same keystore
  `alp`, `apksigner` cert match).
- **Critical agent bug fixed (`android-agent/app/src/com/alp/agent/AlpOps.java`)**:
  `processPending` treated the **absence** of a CLEAR/GET/APPLY envelope file as a
  pending request — so any app resume with no `alp_rollback.json` present ran
  `clearPolicy("{}")` and wiped every just-applied restriction seconds later
  (observed in logcat: APPLY applied 17 lanes at `04:45:25`, CLEAR wiped at
  `04:45:47`). Now every command requires its file to physically exist, and
  `clearPolicy` refuses to run without an explicit CLEAR envelope
  (`clear_rejected_no_envelope`). Envelope `cmd_id` dedup via
  `shared_prefs/alp_processed` still holds.
- **Applied on the device** via envelope `REAL-EXEC-20260913-03` (17 BLOCK lanes
  collapsing to 12 distinct OS tokens). Ground-truth `dumpsys device_policy`
  on `520041d74247b58b` now shows active:
  `no_config_wifi · no_bluetooth · no_config_tethering · no_usb_file_transfer ·
  no_config_vpn · no_unmute_microphone · no_safe_boot · no_factory_reset ·
  no_install_unknown_sources · no_modify_accounts · no_share_location` +
  `disableCamera=true` (`setCameraDisabled`). Behavioral proof: `svc bluetooth
  disable` now killed (rc=137) by the DO restriction.
- **Honest backend run after lockdown**: `apply POL-FULL_LOCKDOWN real` via the
  real ADB channel → `stage=COMPLETE`, `source=REAL_DEVICE`, evidence
  `EV-20260913-F35BF615`, audit `AUD-7E372EC40A18`. Live observations
  WIFI=OFF · MOBILE_DATA=OFF · LOCATION=OFF · CAMERA=RESTRICTED.
  `verification=UNKNOWN` honestly: the platform probe reads 4 lanes; the other 13
  are proven by the dumpsys evidence above. Compliance `NON_COMPLIANT` (missing
  unreadable lanes) — no fabricated PASS.
- **Deliberately left open**: ADB / DEVELOPER_OPTIONS
  (`no_debugging_features`) is NOT in the envelope — blocking it cuts the
  management bridge permanently; awaiting explicit destructive authorization.

## 14) Emergency recovery architecture - management-channel protection (DO NOT cut the bridge)
> Response to the EMERGENCY_DEVICE_RECOVERY mandate: after the SM-J337P physically
> kept its USB-cable but lost its ADB interface, no future policy is allowed to
> sever the only management channel without a demonstrated recovery channel.

- **Management Channel Protection (`backend/management_channel.py`)**: new layer
  defining CRITICAL_FEATURES = {ADB, DEVELOPER_OPTIONS, USB, USB_NETWORKING}.
  `management_channel_status()` reports the trio `adb_live`,
  `dpc_in_app_rollback`, `recovery_engine` (credential issued to the device in
  `recovery_credentials`). `check_recovery_channel()` returns a dict; in `strict`
  mode it raises `RecoveryChannelError` when a REAL delivery targets a critical
  lane and no channel is usable.
- **Gate wired into `backend/director.py apply()`**: every apply with
  `evidence_src == "REAL_DEVICE"` runs the gate; on `RecoveryChannelError` the
  apply is blocked (`ApplyBlocked`) instead of severing the bridge. Gate note is
  appended to the apply even when it passes (`recovery-channel-check: ...`).
  Env `ALP_DPC_IN_APP_ROLLBACK=1` enables the in-app channel (miroir of the
  rebuilt agent).
- **In-app rollback added to the agent** (`MainActivity` ROLLBACK /
  "إلغاء القيود" button ->
  `AlpOps.localRollback()`): builds a `UI-ROLLBACK-<ts>` CLEAR envelope and calls
  `clearPolicy` from on-device UI - a non-ADB recovery path independent of the
  host channel. Agent rebuilt (25,039 B, same signature); install blocked by the
  very transport loss it mitigates.
- **Device restore tooling** (host side, not signed as a bypass - plain
  `adb shell dpm remove-active-admin`, the official path): `restore_default.py`
  pushes CLEAR_POLICY envelope `RESTORE-20260913-01` as
  `/data/local/tmp/alp_rollback.json`, verifies restrictions cleared, removes the
  device owner, uninstalls `com.alp.agent`. Triggered automatically by
  `watch_and_restore.py` (polling + `adb-server` restart every 90 s) the moment a
  shell answers.
- **Tests**: 9 new offline tests for the gate (`tests/unit/test_management_channel.py`
  - lacks, strict/non-strict, adb-live, in-app, credential-engine paths); fixed a
  real Windows resource bug found by them: `backend.db.connect()` `with`-block
  only scopes a transaction, the handle stayed open and locked temp DBs (now
  closed explicitly). `test_director` REAL_DEVICE cases now require an issued
  recovery credential (real-world behavior). Full suite: **129 tests OK**.
- **Never applied by either tool**: ADB/DEVELOPER_OPTIONS blocking, factory
  reset, FRP/Knox bypass. The device keeps its restrictions (device physically
  alive via PnP, MTP, RNDIS) until it reappears on ADB; classify recovery
  status: BLOCKED (transport), data preserved.
