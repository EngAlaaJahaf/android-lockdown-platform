# معمارية «حارس الموبايل» — ARCHITECTURE

## الطبقات
```
Windows Console (desktop/alp_manager: app_qt.py + controller.py)
        ↕ استدعاء مباشر
Backend (backend/): director → workflows → channel/adb_channel
        ↕ (حاليًا USB/ADB) ↕ (مستقبلًا: خلفية إدارة §33)
Android Agent (com.alp.agent): CommandReceiver → AlpOps → DPM
```

## المحركات
| المحرك | المجلد | الدور |
|---|---|---|
| Policy | `policy-engine/` | 6 سياسات + لقطات + استثناءات |
| Capability | `capability-engine/` | فحص 19 بندًا + تقرير قدرات |
| Verification | `verification-engine/` | مسبار حي + مطابقة + UNKNOWN الصادق |
| Compatibility | `compatibility/` | بوابات API/OEM |
| Vendor adapters | `vendor-adapters/` | Generic/Samsung(Knox GATED)/… |
| Device mgmt | `backend/workflows.py`, `fleet.py` | اكتشاف/تسجيل/تطبيق/حالة |
| Security | `backend/{rbac,auth,approval,recovery_credentials,audit}.py` | أدوار/موافقات/شهادات/سلسلة تدقيق |
| Recovery | `backend/recovery.py` + `management_channel.py` | R1–R4 + بوابة القناة |

## مخزن الحالة
SQLite (`%LOCALAPPDATA%\ALPManager\alp.db`, مخطط `database/schema.sql`):
devices, policies, capabilities, operations, evidence, administrators, roles,
recovery_credentials (AES-GCM), approvals, approval_confirmations, audit_logs (سلسلة SHA-256).

## قواعد معمارية ملزمة
1. لا PASS بلا `evidence_id` + قراءة `REAL_DEVICE` (§18).
2. لا تسليم REAL على مسار حرج بلا قناة استرداد مبرهنة (§20/§40).
3. لا انتقال حالة خارج مصفوفة `state_machine.py` (§9).
4. R3 (فلاش) مرفوض حكمًا من التطبيق (§70).
