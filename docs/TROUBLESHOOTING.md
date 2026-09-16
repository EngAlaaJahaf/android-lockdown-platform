# استكشاف الأخطاء — TROUBLESHOOTING

## أخطاء عربية تظهر بدل الاستثناءات (§36)
| العرض | السبب المعتاد | الإجراء |
|---|---|---|
| «تعذر تطبيق السياسة — مالك الجهاز غير مفعل» | الجهاز بلا DO | أكمل التجهيز (R2/`dpm set-device-owner`) |
| `ApplyBlocked: … no recovery channel` | سياسة تمس مسارًا حرجًا بلا قناة بديلة | أصدر شهادة الاسترداد أولًا أو فعّل زر ROLLBACK (`ALP_DPC_IN_APP_ROLLBACK=1`) |
| `APPLY blocked — no active recovery credential` | بوابة الحيازة | أصدر الشهادة للجهاز ثم أعد |
| `… N unresolved exceptions` | مسارات غير قابلة على هذا الجهاز | راجع تقرير القدرات؛ استبعدها أو استخدم `force` الموثّق |
| `adb devices` فارغ رغم التوصيل | تصحيح USB غير مفعل / `no_debugging_features` نشط / MTP فقط | فعّل تصحيح USB من خيارات المطوّر؛ إن كان القيد من منصتنا فزر ROLLBACK أولًا |
| MTP يظهر بلا ملفات | `no_usb_file_transfer` نشط | طبيعي تحت القيد — ليس عطلًا |
| شاشة FRP بعد إعادة ضبط | حساب Google سابق على الجهاز | أدخل الحساب السابق؛ لا أداة تجاوز في المنصة (محظور) |
| `tamper_check → broken>0` | تعديل يدوي في `audit_logs` | حقّق فورًا؛ السلسلة إلحاقية — راجع النسخة الاحتياطية |

## تشخيص سريع
```
python -X utf8 scripts/run_tests.py        # يجب: OK
adb devices -l                              # القناة حية؟
python scripts/scan_live_device.py          # بطاقة + قدرات الجهاز
```
