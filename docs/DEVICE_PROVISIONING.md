# تجهيز الأجهزة — DEVICE_PROVISIONING

## الشروط المسبقة
- جهاز نظيف (بلا حسابات Google — مالك الجهاز يُرفض مع وجود حسابات).
- `user_setup_complete=0` أثناء التجهيز ثم إعادته `1` (تنفذها R2 تلقائيًا).
- ADB مصرّح عليه (نافذة «السماح بتصحيح أخطاء USB» مقبولة).

## المسار المدعوم حاليًا (SUPPORTED)
```
adb shell settings put secure user_setup_complete 0
adb shell dpm set-device-owner com.alp.agent/.AlpDeviceAdminReceiver
adb shell settings put secure user_setup_complete 1
```
منفذ في `RecoveryEngine._r2` (يتطلب `exec=True` + موافقة + شهادة) ومُختبَر على SM-J337P.

## المسارات الموثقة (PARTIALLY)
- **QR**: `ACTION_GET_PROVISIONING_MODE` + `ACTION_ADMIN_POLICY_COMPLIANCE` (API 24+) —
  النشاطان موثّقان في R2؛ واجهة توليد QR في الكونسول لاحقة.
- **NFC**: API 21+ — غير مفعّل (يُضاف عند الطلب).

## ملاحظة الترحيل («حارس الموبايل»)
تغيير حزمة الوكيل = هوية مالك-جهاز جديدة → التجهيز الجديد يكون بالحزمة الجديدة
على أجهزة نظيفة (أو بعد `dpm remove-active-admin` رسميًا للحزمة القديمة).
