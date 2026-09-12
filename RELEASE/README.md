# ALP Manager — حزمة الإصدار v1.0.0-rc1

نظام إدارة تقييد (Lockdown) لأجهزة Android عبر قنوات مدروسة القدرات، بواجهة عربية (RTL).

## الملفات
- `AndroidLockdownManager_Setup-v1.0.0.exe` — المثبّت (لكل مستخدم، بدون صلاحيات إدارة).
  التثبيت: شغّل الملف. الإزالة: الإعدادات > التطبيقات > ALP Manager > إلغاء التثبيت،
  أو `... --uninstall`.
- `AndroidLockdownManager-v1.0.0-windows-x64-portable.exe` — نسخة محمولة (شغّل مباشرة).
- `SHA256SUMS.txt` — بصمات التحقق للنسختين.
- `FINAL_RELEASE_VALIDATION_REPORT.html` — تقرير التحقق النهائي (بالعربية).
- `IMPLEMENTATION_CHANGELOG.md` — سجل التنفيذ.

## التحقق من البصمة
```powershell
Get-FileHash .\AndroidLockdownManager_Setup-v1.0.0.exe -Algorithm SHA256
```

## البيانات
تُحفظ البيانات في `%LOCALAPPDATA%\ALPManager\` (قاعدة البيانات، المفاتيح، التقارير)
ولا تتأثر بإعادة تثبيت النسخة المحمولة.

## الحالة
**READY FOR CONTROLLED PILOT** — انظر تقرير التحقق: لا يوجد جهاز SM-J337P فيزيائي لتوثيق
نتائج حقيقية؛ كل نتائج تلك الفئة مصنّفة محاكاة حتى تتوفر عينة مختبرية.