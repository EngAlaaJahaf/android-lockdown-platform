# IMPLEMENTATION BASELINE — Android Lockdown & Fleet Management Platform

**Document ID:** ALP-BASE-001 · **Date:** 2026-09-12 · **Status:** PHASE 0 STARTED (EXECUTE granted)

> Multiplier: applies to the whole project. "Baseline" = the verified starting state the implementation
> is mapped against, per EXECUTE command STEP 1–3.

---

## 1. Current Architecture (approved, from ANDROID_LOCKDOWN_PLATFORM_MASTER_PLAN.html — Decided AD-1..AD-6)

```
MANAGEMENT CONSOLE
   │
   ▼
DESKTOP MANAGER            (Windows; approved: CLI-first at build, Web console via backend)
   │  Secure Control Channel (ADB/USB for lab & local devices; signed commands)
   ▼
ANDROID AGENT / DPC        (Device Owner, API 21+; DPM + UserManager Restrictions + Settings.Global + LockTask)
   │
   ┌──────────┬────────────┬─────────────┐
Capability   Policy       Verification    Compliance
 Engine      Engine         Engine         Engine
   └──────────┼────────────┬─────────────┘
   Compatibility Layer (Android 7→15 per-version adapters)
   Vendor Adapters (Samsung/Knox first; Motorola/Xiaomi/Pixel/OnePlus/AOSP hooks)
   Device Profiles (DeviceProfile-first; Evidence gates)
   Android Device
```

**Approved decisions being implemented (do not redesign):**
- AD-1 Hybrid (Desktop + DPC + local channel). Cloud-only MDM: deferred outside MVP.
- AD-2 Official enforcement path only: DPM, user restrictions, Settings.Global, LockTask. No ROM/root/flash in production.
- AD-3 Samsung model-per-profile; SM-A145P dual-OS reference; SM-J320FN as floor (Android 7.0).
- AD-4 Sequence: Discover→Identify→Assess→Capability→Select Policy→Validate→Apply→Verify→Evidence→Monitor→Comply→Recover→Audit.
- AD-5 Hard-grade scenarios (Flash/Recovery/Bootloader/External re-flash) are GOVERNANCE-fenced (Lab Only, dual approval), never "supported" from-app.
- AD-6 Deferred build-time decisions now resolved under EXECUTE: Python-first (backend/engines/CLI), ADB as channel, SDK tools (aapt2/d8/apksigner, no Gradle dependency), both lab devices in scope, Android 15 adapter included from start.

## 2. Current Files (verified at start of Phase 0)

| Path | Role | Size |
| --- | --- | --- |
| `F:\root phon\ANDROID_LOCKDOWN_PLATFORM_MASTER_PLAN.html` | Master plan (61 sections, source of truth) | 152,990 B |
| `F:\root phon\ANDROID_LOCKDOWN_PROJECT_MASTER_PLAN.html` | Historical project plan (unchanged) | 136,300 B |
| `F:\root phon\ANDROID_LOCKDOWN_IMPLEMENTATION_PLAN.html` | Implementation plan (34 sections, tech decisions) | 165,945 B |
| `F:\root phon\ANDROID_LOCKDOWN_FLEET_ADMIN_EXECUTION_PLAN.html` | Fleet-Admin execution plan (PRE-EXECUTION final) | 150,701 B |
| `F:\root phon\انظمه تفليش\A145PXXS8DYI2_A145POJM8DYI2_XSG.zip` | Official OS15 firmware (lab-only reference) | 5,895 MB |
| `F:\root phon\انظمه تفليش\SAMFW.COM_SM-A145P_XSG_A145PXXS8CYB3_fac.zip` | Official OS14 firmware (lab-only reference) | 5,471 MB |
| `F:\root phon\انظمه تفليش\A145PXXS8DYI2_A145POJM8DYI2_XSG\*` | OS15: AP/BL/CP/CSC/HOME_CSC (tar.md5) | 5,805 MB |
| `F:\root phon\انظمه تفليش\SAMFW.COM_SM-A145P_XSG_A145PXXS8CYB3_fac\*` | OS14: AP/BL/CP/CSC/HOME_CSC (tar.md5) | 5,739 MB |
| `F:\root phon\انظمه تفليش\SAMSUNG A11tool\*` | 3rd-party flashing/EDL tool (lab recovery reference ONLY — §27 gate) | 19 MB |
| `F:\root phon\انظمه تفليش\أدوات صيانة وسوفت وير /ChipGenius` | Hardware identification tool (reference) | — |

Firmware channel classification: **LAB-ONLY REFERENCE**. Never executed on real user devices. Per AD-5/§27, any use requires Lab + dual approval.

## 3. Environment (verified 2026-09-12)

| Tool | Path | Version | Verdict |
| --- | --- | --- | --- |
| Python | `C:\Users\sh\AppData\Local\Programs\Python\Python311\python.exe` | 3.11.9 | **BUILD TOOLCHAIN (approved Python-first)** |
| Node.js | `C:\Program Files\nodejs\node.exe` | v22.12.0 | optional (not required) |
| Java (Zulu) | `C:\Program Files\Zulu\zulu-17` | OpenJDK 17.0.9 | APK compile |
| Android SDK | `C:\Users\sh\AppData\Local\Android\Sdk` | platforms 31/34/35/36.1; build-tools 34.0.0/35.0.0/35.0.1/36.0.0 | **APK build via aapt2/d8/apksigner** |
| aapt2/d8/apksigner/zipalign | build-tools\35.0.1 | present | verified |
| ADB | platform-tools\adb.exe | present | control channel |
| Emulator image | system-images\android-36\google_apis_playstore | present | **avd boot planned (Phase 11)** |
| Gradle | — | absent | not required (SDK tools path) |
| Git | `C:\Program Files\Git` | present | repo initialized |
| Docker CLI | present | daemon NOT running (exit 1) | deployment option (later phases) |
| sqlite3 | platform-tools\sqlite3.exe | present | DB validation |
| Physical devices | `adb devices` | **EMPTY LIST** | **NO LAB HARDWARE ATTACHED** |

## 4. Current Modules / Build / Test State

- **Source code:** none yet (this baseline precedes Phase 1 code).
- **Build state:** N/A (no code).
- **Test state:** nothing to run (no code).
- **Database:** none (schema authored in Phase 1, migrations after).

## 5. Missing Components (→ implementation backlog)

1. Desktop Manager (CLI + Web console) — **not built**
2. Android Agent / DPC (Device Owner) — **not built** (APK via SDK tools planned)
3. Backend control-plane + API + auth + secure command channel — **not built**
4. Capability Engine — **not built**
5. Policy Engine + Policy Schema + PHONE_ONLY/Corporate Default vN — **not built**
6. Verification Engine — **not built**
7. Compliance Engine — **not built**
8. Compatibility Layer (7→15 adapters) — **not built**
9. Vendor Adapters (Samsung/Knox + hooks) — **not built**
10. Fleet: Job queue / Bulk / Rollout / Stop threshold / Failure queue — **not built**
11. RBAC / MFA / Approvals / Audit / Break-Glass / Recovery — **not built**
12. Device Registry (inventory DB + firmware evidence rows) — **not built**
13. Device Profiles (SM-A145P OS14/15 + SM-J320FN) — **not built**
14. Testing infra (unit/integration/device/sim) — **not built**
15. Fleet Simulator (1000+) — **not built**
16. Reporting / Observability — **not built**
17. Documentation set (17 docs) — **not built**
18. Packaging / deployment — **not built**

## 6. Broken Components

None (nothing implemented yet — no broken code exists). The four reference plans are static documents.

## 7. Risks (pre-implementation)

| # | Risk | Status |
| --- | --- | --- |
| R-01 | No physical lab device attached → device-grade results will be `NOT VERIFIED ON REAL DEVICE` until hardware/emulator present | Mitigate: boot AVD (android-36) for DO provisioning proof |
| R-02 | Gradle absent — APK build must use raw SDK tools | Mitigated: aapt2+d8+apksigner verified present |
| R-03 | Samsung Knox API requires Enterprise SDK (licensing) | Plan: Knox adapter stubbed `VENDOR DEPENDENT`, honest UNKNOWN |
| R-04 | USB/ADB channel on mixed fleet (7.x w/o debugging) | Mitigated: Local-channel design (ADB + DPC), verification over `dumpsys` |
| R-05 | Third-party flashing tools must remain LAB ONLY | Governance §27 enforced in docs + scripts guard |

## 8. Phase-0 Task List (from EXECUTE §115 STEP 4)

- [ ] Create project structure (done)
- [ ] Git init (done)
- [ ] This baseline (done)
- [ ] Device Registry DB design + seed from firmware evidence
- [ ] Lab environment report (this document §3)
- [ ] AVD (android-36) creation + boot verification
- [ ] Phase 0 report → gate → Phase 1