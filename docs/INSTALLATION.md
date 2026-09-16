# التثبيت — INSTALLATION

## المتطلبات
- Windows 10/11 x64 · Python 3.11 (للبناء من المصدر فقط) · ADB platform-tools
  (مضمّن في الحزمة) · تعريف Samsung USB الرسمي عند الحاجة.

## من المثبّت (موصى به)
1. شغّل `RELEASE/AndroidLockdownManager_Setup-v1.0.0.exe` كمسؤول.
2. يثبّت التطبيق + التبعيات + ADB + يهيّئ قاعدة `%LOCALAPPDATA%\ALPManager\alp.db`
   (عبر `backend.db.run_migrations`) + اختصار سطح المكتب.
3. الإزالة من «إضافة/إزالة البرامج» (uninstaller مضمّن).

## النسخة المحمولة
- `RELEASE/AndroidLockdownManager-v1.0.0-windows-x64-portable.exe` — تشغيل مباشر
  بلا تثبيت؛ القاعدة تُنشأ بجانب المستخدم عند أول تشغيل.
- تحقق دائمًا: `SHA256SUMS.txt` في `RELEASE/`.

## من المصدر (للمطورين)
```
pip install -r requirements.txt
python -X utf8 scripts/run_tests.py   # يجب: 129 OK
python desktop/run_app.py
```

## أول تشغيل
1. وصّل جهازًا واحدًا عبر USB وفعّل «تصحيح أخطاء USB» عليه.
2. اللوحة تكتشفه تلقائيًا (بلا إدخال يدوي) وتعرض بطاقته.
3. أصدر شهادة الاسترداد للجهاز قبل أي إغلاق (بوابة الحيازة).
