# دليل السياسات — POLICY_GUIDE

## السياسات الست (REVIEW إلزامية قبل التطبيق)
| السياسة | الوصف |
|---|---|
| POL-FULL_LOCKDOWN | الإغلاق الأقصى (25 مسارًا BLOCK + ALLOW للمكالمات/الرسائل/الأسماء) |
| POL-PARTIAL | مزيج مُقلَّص (يرث CORPORATE) |
| POL-CORP_DEFAULT | معيار المؤسسة |
| POL-PHONE_ONLY | هاتف فقط |
| POL-MAINTENANCE | صيانة (ADB/خيارات المطوّر ALLOW) |
| POL-QUARANTINE | حجر |

## قاعدة العرض (§14)
لا يظهر مسار «قابل للتنفيذ» إلا بعد مطابقة القدرات الحية للجهاز المحدد
(`SUPPORTED/PARTIALLY/UNSUPPORTED/REQUIRES_*` — §2).

## المعاينة قبل التطبيق (§15)
الجهاز + السياسة + الحالية + المستهدفة + المخاطر + الطريقة + (مالك؟ OEM؟ استرداد؟).

## المسارات الحرجة
`ADB, DEVELOPER_OPTIONS, USB, USB_NETWORKING` — تطبيقها على REAL يتطلب قناة
استرداد مبرهنة (بوابة `management_channel`) وإلا `ApplyBlocked`.
