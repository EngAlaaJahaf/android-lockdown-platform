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