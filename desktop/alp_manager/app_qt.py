# -*- coding: utf-8 -*-
"""ALP Manager — واجهة إدارة وتقييد أجهزة المؤسسة (Qt عربية RTL).

مبنية فوق وحدة التحكم Controller (headless, خالية من الواجهة) فلا تتسرب أي
حقيقة وهمية إلى الشاشة: كل نجاح يأتي من التحقق الفعلي REAL_DEVICE مع
evidence_id، والمحاكاة لا تمنح PASS أبدًا.

نموذج الخيوط: أي استدعاء قد يحجب (ADB/AdbBusBase) ينفَّذ في QThreadPool عبر
task() وتُردَّ النتيجة إلى واجهة الخيوط الرئيسية عبر Bus.done — لا تُلمس
الواجهات إلا من الخيط الرئيسي.
"""
from __future__ import annotations

import json
import os
import sys

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QPlainTextEdit, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl

from backend.recovery import RECOVERY_MODES
from .controller import Controller

__version__ = "1.0.0-rc1"
APP_TITLE = "منصة إدارة وتقييد أجهزة المؤسسة"
APP_TITLE_EN = "Android Lockdown Platform (ALP) — أر.سي 1"

# ---------------------------------------------------------------------------
# ترجمة الحالات (المصطلح -> العربية) — لا تُمنح العربية إلا بمطابقة فعلية.
# ---------------------------------------------------------------------------
COMPLIANCE_AR = {
    "COMPLIANT": "متوافق",
    "NON_COMPLIANT": "غير متوافق",
    "PARTIAL": "متوافق جزئيًا",
    "UNKNOWN": "غير معروف",
    "ENROLLED": "مسجّل",
    "UNMANAGED": "غير مُدار",
    "RETIREMENT": "خارج الخدمة",
    "RECOVERY": "استرداد",
    "MAINTENANCE": "وضع الصيانة",
    "QUARANTINE": "حجر صحي",
    "": "غير معروف",
}
ENROLL_AR = {
    "UNMANAGED": "غير مُدار",
    "ENROLLMENT_PENDING": "قيد التسجيل",
    "ENROLLED": "مسجّل",
    "CORPORATE_STANDARD": "الوضع المؤسسي",
    "PARTIAL_LOCKDOWN": "تقييد جزئي",
    "PHONE_ONLY": "وضع الهاتف فقط",
    "FULL_LOCKDOWN": "القفل الكامل",
    "MAINTENANCE": "وضع الصيانة",
    "QUARANTINE": "حجر صحي",
    "RECOVERY": "استرداد",
    "RETIREMENT": "خارج الخدمة",
}
OWNER_AR = {"ACTIVE": "مفعّل", "INACTIVE": "غير مفعّل", "": "غير مفعّل"}
VERDICT_AR = {"PASS": "نجح التحقق", "FAIL": "فشل التحقق", "PARTIAL": "تحقق جزئي",
              "UNKNOWN": "غير معروف", "PENDING": "قيد الإنشاء"}
REC_STATUS_AR = {"COMPLETE": "اكتمل", "PARTIAL": "جزئي", "FAILED": "فشل",
                 "REFUSED": "مرفوض", "PLAN_ONLY": "خطة فقط"}
REC_MODE_AR = {
    "R1_RESTORE_POINT": "استعادة نقطة الحفظ (إزالة التقييدات المطبّقة)",
    "R2_REPROVISION": "إعادة التسجيل (خطة فقط)",
    "R3_LAB_FLASH": "فلاش مختبر للبرنامج الثابت (مرفوض دائمًا)",
    "R4_DIAGNOSTIC": "تشخيص (قراءة فقط + تقرير)",
}
FEATURE_AR = {
    "WIFI": "شبكة Wi-Fi", "BLUETOOTH": "البلوتوث", "MOBILE_DATA": "بيانات الجوال",
    "LOCATION": "الموقع الجغرافي", "CAMERA": "الكاميرا", "MICROPHONE": "الميكروفون",
    "TETHERING": "نقطة الاتصال (Hotspot)", "USB": "نقل الملفات عبر USB",
    "VPN": "شبكات VPN", "ADB": "تصحيح الأخطاء (ADB)", "SAFE_BOOT": "الإقلاع الآمن",
    "FACTORY_RESET": "إعادة الضبط المصنعية", "APP_INSTALLATION": "تثبيت التطبيقات",
    "ACCOUNTS": "إدارة الحسابات", "ETHERNET": "شبكة إيثرنت",
    "DEVELOPER_OPTIONS": "خيارات المطور", "SCREEN_CAPTURE": "لقطات الشاشة",
    "GPS": "GPS",
}
OBSERVED_AR = {
    "ON": "مفعّل", "OFF": "معطّل", "RESTRICTED": "مقيّد بإدارة المؤسسة",
    "": "غير معلوم",
}
RISK_AR = {"HIGH": "عالية", "MEDIUM": "متوسطة", "LOW": "منخفضة", "": ""}
DESIRED_AR = {"BLOCK": "تقييد", "ALLOW": "إتاحة", "": ""}

# الخطوط المخصصة للعربية (يُشكِّلها HarfBuzz عبر Qt)
FONT_FAMILY = "Segoe UI"
FONT_SIZE = 10


def tx(d: dict, key: str, default: str = "") -> str:
    v = d.get(key, "")
    if v is None:
        v = ""
    return str(v)


def ar_state(d: dict, key: str, table: dict) -> str:
    return table.get(tx(d, key), tx(d, key) or "")


# ---------------------------------------------------------------------------
# طبقة تنفيذ المهام في الخلفية — آمنة للخيوط
# ---------------------------------------------------------------------------
class Bus(QObject):
    done = Signal(str, object, bool)  # (tag, result, is_error)


BUS = Bus()
_POOL = QThreadPool.globalInstance()


class Task(QRunnable):
    def __init__(self, tag: str, fn, *args, **kwargs):
        super().__init__()
        self.tag = tag
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
        except Exception as ex:  # noqa: BLE001 — يُعرض للمسؤول بالعربية
            BUS.done.emit(self.tag, {"ok": False, "error": f"{type(ex).__name__}: {ex}"}, True)
        else:
            BUS.done.emit(self.tag, res, False)


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ctl = Controller()
        self._last_probe = {}          # serial -> bundle
        self._last_apply = None
        self._busy = False
        self._session_label = None
        self._quick_status = None

        self.setWindowTitle(f"{APP_TITLE} — {APP_TITLE_EN}  v{__version__}")
        self.resize(1320, 840)

        self._build_ui()
        BUS.done.connect(self._on_done)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(4000)

        self._task("bootstrap", self.ctl.needs_bootstrap)
        self._task("devices", self._snapshot)
        self._task("diagnostics", self.ctl.diagnostics)

    # ------------------------------------------------------------------
    # بنية النوافذ
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._build_header(outer)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # الشريط الجانبي
        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setFixedWidth(230)
        self._nav.setMinimumWidth(230)
        pages = [
            ("dashboard", "الرئيسية"),
            ("devices", "الأجهزة"),
            ("details", "تفاصيل الجهاز"),
            ("capabilities", "فحص القدرات"),
            ("policies", "السياسات"),
            ("apply", "تطبيق السياسة"),
            ("verification", "التحقق"),
            ("compliance", "حالة الالتزام"),
            ("recovery", "الاسترداد"),
            ("audit", "السجلات"),
            ("reports", "التقارير"),
            ("diagnostics", "التشخيص"),
            ("settings", "الإعدادات"),
            ("help", "المساعدة"),
            ("about", "حول البرنامج"),
        ]
        self._nav_keys = {}
        for key, label in pages:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self._nav.addItem(item)
            self._nav_keys[key] = label
        body.addWidget(self._nav)

        # طبقة الصفحات
        self._stack = QStackedWidget()
        self._build_dashboard()
        self._build_devices()
        self._build_details()
        self._build_capabilities()
        self._build_policies()
        self._build_apply()
        self._build_verification()
        self._build_compliance()
        self._build_recovery()
        self._build_audit()
        self._build_reports()
        self._build_diagnostics()
        self._build_settings()
        self._build_help()
        self._build_about()
        body.addWidget(self._stack, 1)

        self._nav.currentRowChanged.connect(
            lambda i: self._stack.setCurrentIndex(max(i, 0)))
        self._nav.setCurrentRow(0)

    def _build_header(self, outer):
        top = QFrame()
        top.setObjectName("header")
        lay = QHBoxLayout(top)
        lay.setContentsMargins(14, 8, 14, 8)

        title = QLabel(APP_TITLE)
        title.setObjectName("app_title")
        title.setFont(QFont(FONT_FAMILY, 16, QFont.Bold))
        lay.addWidget(title)

        tag = QLabel("منظومة آمنة قائمة على التحقق الفعلي")
        tag.setObjectName("app_tag")
        lay.addWidget(tag)
        lay.addStretch(1)

        self._quick_status = QLabel("")
        self._quick_status.setObjectName("quick_status")
        lay.addWidget(self._quick_status)

        lay.addSpacing(14)
        u = QLabel("المستخدم")
        lay.addWidget(u)
        self._ui_user = QLineEdit()
        self._ui_user.setPlaceholderText("اسم المدير")
        self._ui_user.setMaximumWidth(130)
        lay.addWidget(self._ui_user)
        self._ui_pass = QLineEdit()
        self._ui_pass.setPlaceholderText("كلمة المرور")
        self._ui_pass.setEchoMode(QLineEdit.Password)
        self._ui_pass.setMaximumWidth(130)
        lay.addWidget(self._ui_pass)
        self._ui_totp = QLineEdit()
        self._ui_totp.setPlaceholderText("رمز المصادقة (TOTP)")
        self._ui_totp.setMaximumWidth(110)
        lay.addWidget(self._ui_totp)
        b_login = QPushButton("دخول")
        b_login.setObjectName("btn_acc")
        b_login.clicked.connect(self._login)
        lay.addWidget(b_login)
        b_boot = QPushButton("إنشاء المدير الأول")
        b_boot.setObjectName("btn_acc")
        b_boot.clicked.connect(self._bootstrap)
        lay.addWidget(b_boot)
        b_out = QPushButton("خروج")
        b_out.setObjectName("btn_ghost")
        b_out.clicked.connect(self._logout)
        lay.addWidget(b_out)
        self._b_login = b_login
        self._b_boot = b_boot
        self._session_label = QLabel("غير مسجّل الدخول")
        self._session_label.setObjectName("session")
        lay.addWidget(self._session_label)
        outer.addWidget(top)

    # ------------------------------------------------------------------
    # الصفحة: الرئيسية
    # ------------------------------------------------------------------
    def _build_dashboard(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)

        self._no_device_banner = QLabel("لم يتم اكتشاف جهاز. قم بتوصيل جهاز Android للبدء.")
        self._no_device_banner.setObjectName("banner_warn")
        self._no_device_banner.setWordWrap(True)
        self._no_device_banner.hide()
        v.addWidget(self._no_device_banner)

        cards = QHBoxLayout()
        self._card_attached = self._card("الأجهزة المتصلة")
        self._card_locked = self._card("الأجهزة المقيّدة")
        self._card_ok = self._card("الأجهزة المتوافقة")
        self._card_need = self._card("تحتاج إجراءً")
        for c in (self._card_attached, self._card_locked,
                  self._card_ok, self._card_need):
            cards.addWidget(c[0])
        v.addLayout(cards)

        t = QLabel("الأجهزة")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._table_dash = self._mk_device_table(compact=True)
        v.addWidget(self._table_dash)
        v.addStretch(1)
        self._stack.addWidget(page)

    def _card(self, caption):
        f = QFrame()
        f.setObjectName("card")
        lay = QVBoxLayout(f)
        val = QLabel("—")
        val.setObjectName("card_value")
        cap = QLabel(caption)
        cap.setObjectName("card_caption")
        lay.addWidget(val)
        lay.addWidget(cap)
        return f, val

    def _mk_device_table(self, compact=False):
        table = QTableWidget(0, 7)
        table.setObjectName("dtable")
        table.setHorizontalHeaderLabels(
            ["المعرّف", "الرقم التسلسلي", "الطراز", "أندرويد",
             "حالة التسجيل", "مالك الجهاز", "الالتزام"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        if compact:
            table.setMaximumHeight(300)
        return table

    def _render_devices(self, devices):
        for name, tbl in (("dashboard", getattr(self, "_table_dash", None)),
                          ("devices", getattr(self, "_table_dev", None))):
            if tbl is None:
                continue
            tbl.setRowCount(0)
            for d in devices:
                r = tbl.rowCount()
                tbl.insertRow(r)
                vals = [
                    tx(d, "device_id"), tx(d, "serial"), tx(d, "model"),
                    str(tx(d, "android_version")),
                    ar_state(d, "enrollment_state", ENROLL_AR),
                    ar_state(d, "device_owner_state", OWNER_AR),
                    ar_state(d, "compliance_state", COMPLIANCE_AR),
                ]
                for c, val in enumerate(vals):
                    it = QTableWidgetItem(val)
                    if c in (4, 6):  # تلوين الحالة
                        it.setForeground(self._status_color(val))
                    tbl.setItem(r, c, it)
            if not devices:
                tbl.setRowCount(0)

    def _status_color(self, text) -> QColor:
        if text in ("متوافق", "فعّال"):
            return QColor("#1d8a4c")
        if text in ("غير متوافق", "فشل", "مرفوض"):
            return QColor("#c0392b")
        if text in ("متوافق جزئيًا", "جزئي"):
            return QColor("#c07a00")
        if text == "مقيّد بإدارة المؤسسة":
            return QColor("#2f6fed")
        return QColor("#4a4a4a")

    # ------------------------------------------------------------------
    # الصفحة: الأجهزة
    # ------------------------------------------------------------------
    def _build_devices(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)

        row = QHBoxLayout()
        lbl = QLabel("الرقم التسلسلي:")
        row.addWidget(lbl)
        self._dev_serial = QLineEdit()
        self._dev_serial.setPlaceholderText("مثال: emulator-5554 أو SM-J337P")
        row.addWidget(self._dev_serial, 1)
        lbl2 = QLabel("المعرّف (اختياري):")
        row.addWidget(lbl2)
        self._dev_did = QLineEdit()
        self._dev_did.setMaximumWidth(160)
        row.addWidget(self._dev_did)
        self._dev_lab = QComboBox()
        self._dev_lab.addItems(["جهاز تشغيلي", "جهاز مختبر (Lab)"])
        row.addWidget(self._dev_lab)
        b = QPushButton("تسجيل الجهاز")
        b.setObjectName("btn_acc")
        b.clicked.connect(self._enroll)
        row.addWidget(b)
        v.addLayout(row)

        row2 = QHBoxLayout()
        b_probe = QPushButton("فحص الجهاز (قراءة فعلية)")
        b_probe.clicked.connect(lambda: self._probe_action())
        row2.addWidget(b_probe)
        b_rep = QPushButton("توليد تقرير الجهاز")
        b_rep.clicked.connect(self._report_action)
        row2.addWidget(b_rep)
        b_refresh = QPushButton("تحديث القائمة (ADB)")
        b_refresh.clicked.connect(lambda: self._task("devices", self._snapshot))
        row2.addWidget(b_refresh)
        row2.addStretch(1)
        v.addLayout(row2)

        self._table_dev = self._mk_device_table()
        self._table_dev.itemSelectionChanged.connect(self._device_selected)
        v.addWidget(self._table_dev, 1)

        self._dev_log = QPlainTextEdit()
        self._dev_log.setPlaceholderText("نتائج عمليات الأجهزة…")
        self._dev_log.setMaximumHeight(190)
        v.addWidget(self._dev_log)
        self._stack.addWidget(page)

    def _selected_device_row(self) -> dict:
        tbl = self._table_dev
        sel = tbl.selectionModel().selectedRows()
        if not sel:
            return {}
        r = sel[0].row()
        if tbl.item(r, 0) is None:
            return {}
        return {"device_id": tbl.item(r, 0).text(),
                "serial": tbl.item(r, 1).text(),
                "model": tbl.item(r, 2).text(),
                "enrollment_state": tbl.item(r, 4).text()}

    def _device_selected(self):
        d = self._selected_device_row()
        self._last_apply_dev = d
        if d:
            self._dev_log.setPlainText(f"تم تحديد الجهاز: {d['device_id']} [{d['serial']}]")
            self._render_apply_preview()

    def _enroll(self):
        serial = self._dev_serial.text().strip()
        if not serial:
            self._err("تسجيل الجهاز", "الرقم التسلسلي مطلوب")
            return
        did = self._dev_did.text().strip()
        lab = self._dev_lab.currentIndex() == 1
        self._task("enroll", self.ctl.enroll, serial, did, lab)

    def _probe_action(self):
        d = self._selected_device_row()
        if not d or not d["serial"]:
            self._err("فحص الجهاز", 'اختر جهازًا مسجّلًا ثم اضغط "فحص الجهاز".')
            return
        self._busy_start("فحص الجهاز…")
        self._task("probe", self.ctl.probe, d["serial"])

    def _report_action(self):
        d = self._selected_device_row()
        if not d or not d["device_id"]:
            self._err("تقرير الجهاز", "اختر جهازًا من القائمة أولًا.")
            return
        self._task("report", self.ctl.generate_device_report, d["device_id"])

    # ------------------------------------------------------------------
    # الصفحة: تفاصيل الجهاز
    # ------------------------------------------------------------------
    def _build_details(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("تفاصيل الجهاز (قراءة فعلية من ADB عبر الفحص)")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        v.addWidget(self._details, 1)
        b = QPushButton("تحديث من الفحص الحالي")
        b.clicked.connect(self._refresh_details)
        v.addWidget(b)
        self._stack.addWidget(page)

    def _refresh_details(self):
        for serial, bundle in self._last_probe.items():
            self._details.setPlainText(self._probe_pretty(serial, bundle))
            return
        self._details.setPlainText("لا يوجد فحص مسبق. نفّذ فحصًا من صفحة الأجهزة أولًا.")

    # ------------------------------------------------------------------
    # الصفحة: فحص القدرات
    # ------------------------------------------------------------------
    def _build_capabilities(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("فحص القدرات — حسب ما يمكن اكتشافه وإدارته فعليًا")
        t.setObjectName("section_title")
        v.addWidget(t)

        row = QHBoxLayout()
        b = QPushButton("فحص القدرات للجهاز المحدد")
        b.setObjectName("btn_acc")
        b.clicked.connect(self._cap_scan)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)

        self._cap_table = QTableWidget(0, 4)
        self._cap_table.setHorizontalHeaderLabels(
            ["الميزة", "الحالة المرصودة", "التحكم المتاح", "المخاطرة / ملاحظة"])
        self._cap_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._cap_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cap_table.verticalHeader().setVisible(False)
        self._cap_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        v.addWidget(self._cap_table, 1)
        self._cap_note = QLabel("")
        self._cap_note.setObjectName("note")
        v.addWidget(self._cap_note)
        self._stack.addWidget(page)

    def _cap_scan(self):
        d = self._selected_device_row()
        if not d or not d["serial"]:
            self._err("فحص القدرات", "اختر جهازًا أولًا.")
            return
        self._busy_start("جاري فحص القدرات…")
        self._task("cap_scan", self.ctl.probe, d["serial"])

    def _render_capabilities(self, bundle: dict):
        identity = bundle.get("identity") or {}
        observed = bundle.get("observed") or {}
        restrictions = bundle.get("restrictions") or {}
        lanes = sorted(set(list(observed.keys()) + list(restrictions.keys())))
        self._cap_table.setRowCount(0)
        for feat in lanes:
            r = self._cap_table.rowCount()
            self._cap_table.insertRow(r)
            ob = observed.get(feat, "")
            locked = ob == "RESTRICTED" or feat in restrictions
            control = "قابل للتقييد" if feat in (
                "WIFI", "BLUETOOTH", "TETHERING", "USB", "VPN", "MICROPHONE",
                "ADB", "SAFE_BOOT", "FACTORY_RESET", "APP_INSTALLATION",
                "ACCOUNTS", "LOCATION") else ("عبر إعدادات النظام فقط" if ob else "غير مدعوم هنا")
            risk = "مرتفعة" if feat in ("ADB", "FACTORY_RESET", "SAFE_BOOT") else ""
            items = [QTableWidgetItem(FEATURE_AR.get(feat, feat)),
                     QTableWidgetItem(OBSERVED_AR.get(ob, ob or "غير معلوم")),
                     QTableWidgetItem("مقيّد" if locked else control),
                     QTableWidgetItem(risk)]
            if locked:
                items[1].setForeground(QColor("#2f6fed"))
            self._cap_table.setItem(r, 0, items[0])
            self._cap_table.setItem(r, 1, items[1])
            self._cap_table.setItem(r, 2, items[2])
            self._cap_table.setItem(r, 3, items[3])
        src = bundle.get("source", "")
        self._cap_note.setText(
            f"مصدر الفحص: {src} — الجهاز: {identity.get('model') or '؟'} "
            f"(أندرويد {identity.get('android_version') or '؟'}), "
            f"API {identity.get('api_level') or '؟'}. "
            "النتيجة من القراءة الفعلية وليست افتراضًا.")

    # ------------------------------------------------------------------
    # الصفحة: السياسات
    # ------------------------------------------------------------------
    def _build_policies(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("السياسات المتاحة")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._pol_table = QTableWidget(0, 5)
        self._pol_table.setHorizontalHeaderLabels(
            ["المعرّف", "الاسم", "الفئة", "الإصدار", "الحالة"])
        self._pol_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._pol_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pol_table.verticalHeader().setVisible(False)
        v.addWidget(self._pol_table, 1)
        self._stack.addWidget(page)

    def _render_policies(self, pols):
        self._pol_table.setRowCount(0)
        for p in pols:
            r = self._pol_table.rowCount()
            self._pol_table.insertRow(r)
            for c, val in enumerate([
                    tx(p, "policy_id"), tx(p, "display_name"),
                    tx(p, "category"), str(tx(p, "version")),
                    tx(p, "status")]):
                self._pol_table.setItem(r, c, QTableWidgetItem(val))

    # ------------------------------------------------------------------
    # الصفحة: تطبيق السياسة (مع معاينة قبل وبعد)
    # ------------------------------------------------------------------
    def _build_apply(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)

        form = QFrame()
        form.setObjectName("box")
        fl = QHBoxLayout(form)
        fl.addWidget(QLabel("الجهاز:"))
        self._apply_dev = QComboBox()
        self._apply_dev.setMinimumWidth(260)
        self._apply_dev.activated.connect(self._render_apply_preview)
        fl.addWidget(self._apply_dev)
        fl.addWidget(QLabel("السياسة:"))
        self._apply_pol = QComboBox()
        self._apply_pol.setMinimumWidth(240)
        self._apply_pol.activated.connect(self._render_apply_preview)
        fl.addWidget(self._apply_pol)
        fl.addWidget(QLabel("رمز TOTP:"))
        self._apply_mfa = QLineEdit()
        self._apply_mfa.setMaximumWidth(120)
        fl.addWidget(self._apply_mfa)
        fl.addWidget(QLabel("الميزات (اختياري، مفصولة بفاصلة):"))
        self._apply_sub = QLineEdit()
        self._apply_sub.setMaximumWidth(160)
        fl.addWidget(self._apply_sub)
        v.addWidget(form)

        t = QLabel("معاينة تغييرات السياسة قبل التنفيذ")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._prev_table = QTableWidget(0, 5)
        self._prev_table.setHorizontalHeaderLabels(
            ["الميزة", "الإستهداف", "الحالة الحالية", "الإجراء", "المخاطرة"])
        self._prev_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._prev_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._prev_table.verticalHeader().setVisible(False)
        self._prev_table.setMaximumHeight(220)
        v.addWidget(self._prev_table)
        self._prev_note = QLabel("اختر جهازًا وسياسة لبناء المعاينة.")
        self._prev_note.setObjectName("note")
        v.addWidget(self._prev_note)

        row = QHBoxLayout()
        b = QPushButton("تطبيق السياسة الآن")
        b.setObjectName("btn_danger")
        b.clicked.connect(self._apply_action)
        row.addWidget(b)
        b2 = QPushButton("تحديث المعاينة")
        b2.clicked.connect(self._render_apply_preview)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)

        self._apply_log = QPlainTextEdit()
        self._apply_log.setReadOnly(True)
        v.addWidget(self._apply_log, 1)
        self._stack.addWidget(page)

    def _render_apply_preview(self, *_):
        did = self._apply_dev.currentData() or (self._last_apply_dev or {}).get("device_id")
        pol = self._apply_pol.currentText()
        if not did or not pol:
            self._prev_table.setRowCount(0)
            self._prev_note.setText("اختر جهازًا وسياسة لبناء المعاينة.")
            return
        pol_id = pol.split()[0]
        self._prev_note.setText("جاري بناء المعاينة من القراءة الفعلية…")
        self._task("preview", self.ctl.policy_preview, did, pol_id)

    def _render_preview(self, res):
        if not res.get("ok"):
            self._prev_note.setText(res.get("error", "تعذر بناء المعاينة"))
            self._prev_table.setRowCount(0)
            return
        rows = res["rows"]
        self._prev_table.setRowCount(0)
        for row in rows:
            r = self._prev_table.rowCount()
            self._prev_table.insertRow(r)
            feat = row["feature"]
            cur = row["current"]
            action = "تقييد" if row.get("desired") == "BLOCK" else ("إتاحة" if row.get("desired") == "ALLOW" else "—")
            vals = [FEATURE_AR.get(feat, feat), DESIRED_AR.get(row.get("desired"), ""),
                    OBSERVED_AR.get(cur, cur or "غير معلوم"), action,
                    RISK_AR.get(row.get("risk"), "")]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 2 and cur == "RESTRICTED":
                    it.setForeground(QColor("#2f6fed"))
                self._prev_table.setItem(r, c, it)
        src = rows[0].get("source", "") if rows else ""
        note = f"سياسة: {res['display_name']} — مصدر الحالة الحالية: {src}"
        if src == "DEVICE_NOT_ATTACHED":
            note += " — الجهاز غير متصل الآن، لن يتم التطبيق الفعلي."
        self._prev_note.setText(note)

    def _apply_action(self):
        did = self._apply_dev.currentData()
        pol = self._apply_pol.currentText()
        mfa = self._apply_mfa.text().strip()
        sub = self._apply_sub.text().strip()
        if not did or not pol:
            self._err("تطبيق السياسة", "اختر الجهاز والسياسة.")
            return
        if not mfa:
            self._err("تطبيق السياسة",
                      "رمز المصادقة TOTP مطلوب — التطبيق لا يتم دون مدقق حي.")
            return
        pol_id = pol.split()[0]
        self._busy_start("جاري تنفيذ التطبيق والتحقق…")
        self._task("apply", self.ctl.apply, did, pol_id, mfa, True, sub)

    # ------------------------------------------------------------------
    # الصفحة: التحقق
    # ------------------------------------------------------------------
    def _build_verification(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("التحقق من السياسة")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._verify_note = QLabel(
            "التحقق يحدث داخل عملية التطبيق (Apply → قراءة الحالة الفعلية → المقارنة → "
            "النتيجة مع evidence_id). لا يُعدّ الأمر ناجحًا لمجرد إرساله.")
        self._verify_note.setWordWrap(True)
        self._verify_note.setObjectName("note")
        v.addWidget(self._verify_note)
        self._verify_log = QPlainTextEdit()
        self._verify_log.setReadOnly(True)
        v.addWidget(self._verify_log, 1)
        b = QPushButton("عرض نتيجة آخر تطبيق / تحقق")
        b.clicked.connect(self._show_last_apply)
        v.addWidget(b)
        self._stack.addWidget(page)

    def _show_last_apply(self):
        self._verify_log.setPlainText(self._fmt_json(self._last_apply))

    # ------------------------------------------------------------------
    # الصفحة: حالة الالتزام
    # ------------------------------------------------------------------
    def _build_compliance(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("حالة الالتزام بالسياسات")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._comp_table = qtable = QTableWidget(0, 6)
        qtable.setHorizontalHeaderLabels(
            ["المعرّف", "الطراز", "حالة التسجيل", "مالك الجهاز", "الالتزام", "آخر تحقق"])
        qtable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        qtable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        qtable.verticalHeader().setVisible(False)
        v.addWidget(qtable, 1)
        n = QLabel("تشير حالة الالتزام إلى مطابقة الحالة الفعلية للسياسة المطبّقة.")
        n.setObjectName("note")
        v.addWidget(n)
        self._stack.addWidget(page)

    # ------------------------------------------------------------------
    # الصفحة: الاسترداد
    # ------------------------------------------------------------------
    def _build_recovery(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)

        form = QFrame()
        form.setObjectName("box")
        fl = QHBoxLayout(form)
        fl.addWidget(QLabel("الجهاز:"))
        self._rec_dev = QComboBox()
        self._rec_dev.setMinimumWidth(240)
        fl.addWidget(self._rec_dev)
        fl.addWidget(QLabel("الوضع:"))
        self._rec_mode = QComboBox()
        for mode in RECOVERY_MODES:
            self._rec_mode.addItem(f"{mode}", mode)
        fl.addWidget(self._rec_mode)
        fl.addWidget(QLabel("رمز TOTP:"))
        self._rec_mfa = QLineEdit()
        self._rec_mfa.setMaximumWidth(120)
        fl.addWidget(self._rec_mfa)
        v.addWidget(form)

        form2 = QFrame()
        form2.setObjectName("box")
        fl2 = QHBoxLayout(form2)
        fl2.addWidget(QLabel("الموافقة الثانية (المستخدم):"))
        self._rec_aprv_u = QLineEdit()
        self._rec_aprv_u.setMaximumWidth(130)
        fl2.addWidget(self._rec_aprv_u)
        fl2.addWidget(QLabel("رمز الموافق:"))
        self._rec_aprv_t = QLineEdit()
        self._rec_aprv_t.setMaximumWidth(120)
        fl2.addWidget(self._rec_aprv_t)
        fl2.addWidget(QLabel("السبب:"))
        self._rec_reason = QLineEdit()
        self._rec_reason.setMaximumWidth(180)
        fl2.addWidget(self._rec_reason)
        v.addWidget(form2)

        self._rec_mode.currentTextChanged.connect(self._rec_hint_update)
        self._rec_hint = QLabel("")
        self._rec_hint.setObjectName("note")
        v.addWidget(self._rec_hint)
        self._rec_hint_update()

        row = QHBoxLayout()
        b = QPushButton("تنفيذ الاسترداد")
        b.setObjectName("btn_danger")
        b.clicked.connect(self._recover_action)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)

        self._rec_log = QPlainTextEdit()
        self._rec_log.setReadOnly(True)
        v.addWidget(self._rec_log, 1)
        self._stack.addWidget(page)

    def _rec_hint_update(self, *_):
        mode = self._rec_mode.currentData()
        self._rec_hint.setText(REC_MODE_AR.get(mode, mode or ""))

    def _recover_action(self):
        did = self._rec_dev.currentData()
        mode = self._rec_mode.currentData()
        mfa = self._rec_mfa.text().strip()
        if not did or not mode:
            self._err("الاسترداد", "اختر الجهاز والوضع.")
            return
        if not mfa:
            self._err("الاسترداد", "رمز TOTP مطلوب للاسترداد.")
            return
        self._busy_start("جاري تنفيذ الاسترداد…")
        self._task("recover", self.ctl.recover, did, mode, mfa,
                   approver_user=self._rec_aprv_u.text().strip(),
                   approver_mfa=self._rec_aprv_t.text().strip(),
                   reason=self._rec_reason.text().strip(),
                   exec_=True)

    # ------------------------------------------------------------------
    # الصفحة: السجلات
    # ------------------------------------------------------------------
    def _build_audit(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        row = QHBoxLayout()
        row.addWidget(QLabel("عدد السجلات:"))
        self._audit_tail = QSpinBox()
        self._audit_tail.setRange(5, 500)
        self._audit_tail.setValue(80)
        row.addWidget(self._audit_tail)
        b = QPushButton("تحديث السجلات")
        b.setObjectName("btn_acc")
        b.clicked.connect(self._audit_load)
        row.addWidget(b)
        b2 = QPushButton("فحص سلامة السلسلة (Tamper)")
        b2.clicked.connect(self._tamper_load)
        row.addWidget(b2)
        self._audit_status = QLabel("")
        row.addWidget(self._audit_status)
        row.addStretch(1)
        v.addLayout(row)

        self._audit_table = QTableWidget(0, 6)
        self._audit_table.setHorizontalHeaderLabels(
            ["#", "التاريخ", "المستخدم", "العملية", "النتيجة", "التفاصيل"])
        self._audit_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._audit_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeToContents)
        self._audit_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._audit_table.verticalHeader().setVisible(False)
        v.addWidget(self._audit_table, 1)
        self._stack.addWidget(page)

    def _audit_load(self):
        self._task("audit", self.ctl.audit, self._audit_tail.value())

    def _render_audit(self, rows):
        self._audit_table.setRowCount(0)
        for r in rows:
            i = self._audit_table.rowCount()
            self._audit_table.insertRow(i)
            vals = [str(r.get("entry_id", "")), tx(r, "created_at"),
                    tx(r, "username") or tx(r, "role_code"),
                    tx(r, "action"), tx(r, "result") or "-",
                    tx(r, "detail") or f'جهاز: {tx(r, "device_id") or "-"}']
            for c, val in enumerate(vals):
                self._audit_table.setItem(i, c, QTableWidgetItem(val))

    def _tamper_load(self):
        self._task("tamper", self.ctl.tamper_check)

    # ------------------------------------------------------------------
    # الصفحة: التقارير
    # ------------------------------------------------------------------
    def _build_reports(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        row = QHBoxLayout()
        row.addWidget(QLabel("توليد تقرير الجهاز المحدد:"))
        b = QPushButton("توليد التقرير")
        b.setObjectName("btn_acc")
        b.clicked.connect(self._report_action)
        row.addWidget(b)
        b2 = QPushButton("تحديث قائمة التقارير")
        b2.clicked.connect(self._reports_load)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)

        self._rep_tree = QTableWidget(0, 3)
        self._rep_tree.setHorizontalHeaderLabels(["الملف", "الحجم", "التاريخ"])
        self._rep_tree.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._rep_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rep_tree.verticalHeader().setVisible(False)
        v.addWidget(self._rep_tree, 1)
        self._stack.addWidget(page)

    def _reports_load(self):
        self._task("reports", self.ctl.reports_list, "")

    # ------------------------------------------------------------------
    # الصفحة: التشخيص
    # ------------------------------------------------------------------
    def _build_diagnostics(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("تشخيص المنصة والجهاز")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._diag_table = QTableWidget(0, 2)
        self._diag_table.setHorizontalHeaderLabels(["البنود", "النتيجة"])
        self._diag_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._diag_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._diag_table.verticalHeader().setVisible(False)
        v.addWidget(self._diag_table, 1)
        self._diagnostics_text = QLabel("")
        self._diagnostics_text.setObjectName("note")
        self._diagnostics_text.setWordWrap(True)
        v.addWidget(self._diagnostics_text)
        self._stack.addWidget(page)

    def _render_diagnostics(self, d: dict):
        self._diag_table.setRowCount(0)
        rows = [
            ("الإصدار / الوضع", "معبأ من بايثون (Frozen)" if d.get("frozen_mode") else "من المَصدر (Python)"),
            ("مسار البيانات", tx(d, "db_path")),
            ("قاعدة البيانات", "سليمة" if d.get("db_ok") is True else str(d.get("db_ok"))),
            ("عدد الجداول", str(d.get("db_tables"))),
            ("مسار ADB", tx(d, "adb_exe")),
            ("ADB جاهز", "نعم" if d.get("adb_configured") else "لا"),
            ("الأجهزة المتصلة", ", ".join(d.get("adb_devices") or []) or "لا يوجد"),
            ("يحتاج إنشاء المدير الأول", "نعم" if d.get("bootstrap_needed") else "لا"),
            ("منظومة السجلات (سلسلة التدقيق)", tx(d, "audit_chain")),
        ]
        for name, val in rows:
            r = self._diag_table.rowCount()
            self._diag_table.insertRow(r)
            it = QTableWidgetItem(name)
            it2 = QTableWidgetItem(val)
            if val.startswith("سليمة") or val == "نعم" or val == "OK":
                it2.setForeground(QColor("#1d8a4c"))
            elif val and any(k in val for k in ("فشل", "BROKEN", "لا")):
                it2.setForeground(QColor("#c0392b"))
            self._diag_table.setItem(r, 0, it)
            self._diag_table.setItem(r, 1, it2)
        self._diagnostics_text.setText(
            "القياس المذكور قراءة فعلية. إن كان ADB غير جاهز: ثبّت Platform-Tools "
            "واذكر المسار، أو اضبط متغير ALP_ADB.")

    # ------------------------------------------------------------------
    # الصفحة: الإعدادات
    # ------------------------------------------------------------------
    def _build_settings(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("الإعدادات")
        t.setObjectName("section_title")
        v.addWidget(t)
        self._set_table = QTableWidget(0, 2)
        self._set_table.setHorizontalHeaderLabels(["البنود", "القيمة"])
        self._set_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._set_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._set_table.verticalHeader().setVisible(False)
        v.addWidget(self._set_table, 1)

        row = QHBoxLayout()
        b = QPushButton("فتح مجلد البيانات")
        b.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(self._data_dir())))
        row.addWidget(b)
        b2 = QPushButton("حذف محلي آمن وغير مُتلف (تفريغ الجلسة)")
        b2.clicked.connect(self._reset_local)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)
        self._stack.addWidget(page)

    def _data_dir(self):
        from .paths import persist_dir, project_root
        if getattr(sys, "frozen", False):
            return persist_dir()
        return os.path.join(project_root())

    def _reset_local(self):
        try:
            self.ctl.logout()
        except Exception:
            pass
        self._session_label.setText("غير مسجّل الدخول")
        self._task("devices", self._snapshot)

    def _render_settings(self):
        from .paths import persist_dir, session_file, default_db
        rows = [
            ("وضع الحزمة", "معبأة (EXE)" if getattr(sys, "frozen", False) else "من المَصدر"),
            ("مجلد البيانات الدائمة", persist_dir()),
            ("قاعدة البيانات", str(default_db())),
            ("ملف الجلسة", session_file()),
            ("دليل التقارير", os.environ.get("ALP_REPORTS_DIR", "")),
        ]
        self._set_table.setRowCount(0)
        for name, val in rows:
            r = self._set_table.rowCount()
            self._set_table.insertRow(r)
            self._set_table.setItem(r, 0, QTableWidgetItem(name))
            self._set_table.setItem(r, 1, QTableWidgetItem(val))

    # ------------------------------------------------------------------
    # الصفحة: المساعدة
    # ------------------------------------------------------------------
    def _build_help(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText(
            "دليل الاستخدام المختصر\n"
            "=======================\n\n"
            "1) الاتصال وفحص الجهاز\n"
            "   - فعّل تصحيح الأخطاء (USB Debugging) في الجهاز وأذِن لهذا الكمبيوتر.\n"
            "   - من صفحة الأجهزة: أدخل الرقم التسلسلي (adb devices) ثم “تسجيل الجهاز”.\n"
            "   - اختر الجهاز ثم “فحص الجهاز (قراءة فعلية)” لعرض الهوية والقيود.\n\n"
            "2) إنشاء المدير الأول وتسجيل الدخول\n"
            "   - في الشريط العلوي اضغط “إنشاء المدير الأول” (اسم + كلمة مرور).\n"
            "   - سجّل رمز TOTP في تطبيق المصادقة ثم “دخول”.\n"
            "   - العمليات الحساسة (تطبيق/استرداد) تتطلب رمز TOTP حيًا.\n\n"
            "3) تطبيق السياسة\n"
            "   - من صفحة “تطبيق السياسة”: اختر الجهاز والسياسة وراجع المعاينة.\n"
            "   - المعاينة تعرض: الهدف، الحالة الحالية الفعلية، الإجراء، والمخاطرة.\n"
            "   - اضغط “تطبيق السياسة الآن” بعد إدخال رمز TOTP.\n"
            "   - النتيجة تعرض دائمًا نتيجة تحقق REAL_DEVICE مع evidence_id.\n\n"
            "4) التحقق والالتزام\n"
            "   - تحقق من صفحة “التحقق” (نتيجة آخر تطبيق) وصفحة “حالة الالتزام”.\n"
            "   - المحاكاة لا تمنح PASS — إن لم تتوفر قراءة فعلية تظهر “غير معروف”.\n\n"
            "5) الاسترداد\n"
            "   - R1 (نقطة الحفظ) يزيل التقييدات المطبّقة ويتطلب موافقة ثانية.\n"
            "   - R3 (فلاش المختبر) مرفوض دائمًا بقرار الحوكمة.\n\n"
            "6) متطلبات المصادر الحقيقية\n"
            "   - كل نجاح مبني على قراءة فعلية من الجهاز عبر ADB.\n"
            "   - إذا ظهرت “غير مدعومة” فهي نتيجة اكتشاف حقيقي وليست خطأ.\n")
        v.addWidget(box, 1)
        self._stack.addWidget(page)

    # ------------------------------------------------------------------
    # الصفحة: حول البرنامج
    # ------------------------------------------------------------------
    def _build_about(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        about = QPlainTextEdit()
        about.setReadOnly(True)
        about.setPlainText(
            f"{APP_TITLE}\nالإصدار: {__version__}\n"
            f"{APP_TITLE_EN}\n\n"
            "منصة مؤسسية مركزيّة لإدارة وتقييد أجهزة Android بشكل آمن وقابل للتحقق.\n\n"
            "المبادئ:\n"
            "- التحقق الفعلي Real-Device فقط — لا توجد نتائج وهمية.\n"
            "- اكتشاف القدرات أولًا ثم تطبيق المدعوم فقط.\n"
            "- متعددة الشركات والإصدارات (عبر سجل المصنّعين).\n"
            "- سجل تدقيق بسلسلة مقاومة للتلاعب (HMAC chaining).\n"
            "- صلاحيات إدارية: مشاهد/مشغّل/مدير/مدير أعلى مع مصادقة ثنائية (TOTP).\n")
        v.addWidget(about, 1)
        self._stack.addWidget(page)

    # ------------------------------------------------------------------
    # المهام في الخلفية والردود
    # ------------------------------------------------------------------
    def _task(self, tag, fn, *args, **kwargs):
        _POOL.start(Task(tag, fn, *args, **kwargs))

    def _busy_start(self, text):
        self._quick_status.setText(text)
        self.statusBar().showMessage(text)

    def _on_done(self, tag, res, err):
        handler = getattr(self, f"_h_{tag}", None)
        if handler:
            try:
                handler(res, err)
            except Exception as ex:  # noqa: BLE001
                self._quick_status.setText(f"خطأ داخلي في العرض: {ex}")
        if tag in ("devices",):
            self._quick_status.setText("")
            self.statusBar().showMessage("تم تحديث الأجهزة.")

    # مُعالجات النتائج
    def _h_bootstrap(self, res, err):
        if err:
            self._session_label.setText("فشل فحص الإعداد")
            return
        self._b_boot.setEnabled(bool(res))
        self._b_login.setEnabled(not res)
        self._busy_start("")

    def _h_devices(self, res, err):
        if err or not isinstance(res, dict):
            self._quick_status.setText("تعذر تحديث الأجهزة.")
            return
        devices = res.get("devices", [])
        adb = res.get("adb", {})
        attached = adb.get("devices", [])
        self._banner(attached)
        self._render_devices(devices)
        self._render_dashboard_cards(devices, attached)
        self._render_compliance(devices)
        self._populate_combos(devices)

    def _h_enroll(self, res, err):
        if err:
            self._dev_log.setPlainText(self._fmt_json(res))
            self._quick_status.setText("فشل تسجيل الجهاز")
            return
        self._dev_log.setPlainText(self._fmt_json(res))
        self._quick_status.setText("تم تسجيل الجهاز")
        self._task("devices", self._snapshot)

    def _h_probe(self, res, err):
        self._busy_start("")
        if err or not res.get("ok"):
            self._dev_log.setPlainText(self._fmt_json(res))
            return
        bundle = res["bundle"]
        serial = (bundle.get("identity") or {}).get("serial", "")
        self._last_probe[serial] = bundle
        self._dev_log.setPlainText(self._probe_pretty(serial, bundle))
        self._render_capabilities(bundle)
        self._refresh_details()
        self._quick_status.setText("اكتمل فحص الجهاز")

    def _h_cap_scan(self, res, err):
        self._busy_start("")
        if err or not res.get("ok"):
            self._cap_note.setText(self._fmt_json(res))
            return
        bundle = res["bundle"]
        serial = (bundle.get("identity") or {}).get("serial", "")
        self._last_probe[serial] = bundle
        self._render_capabilities(bundle)

    def _h_report(self, res, err):
        if err:
            self._dev_log.setPlainText(self._fmt_json(res))
            return
        self._dev_log.setPlainText(
            f"تم توليد التقرير:\n{res.get('path')}\n\n{res.get('text', '')}")
        self._task("reports", self.ctl.reports_list, "")

    def _h_reports(self, res, err):
        lst = res if isinstance(res, list) else []
        self._rep_tree.setRowCount(0)
        for item in lst[-200:]:
            r = self._rep_tree.rowCount()
            self._rep_tree.insertRow(r)
            for c, val in enumerate([tx(item, "path"), str(item.get("size", "")),
                                     tx(item, "mtime")]):
                self._rep_tree.setItem(r, c, QTableWidgetItem(val))

    def _h_policies(self, res, err):
        if isinstance(res, list):
            self._render_policies(res)

    def _h_preview(self, res, err):
        self._render_preview(res if isinstance(res, dict) else {})

    def _h_apply(self, res, err):
        self._busy_start("")
        self._last_apply = res
        self._apply_log.setPlainText(self._fmt_json(res))
        if isinstance(res, dict) and res.get("ok"):
            self._quick_status.setText("اكتمل التطبيق — تحقق فعلًا")
            self._task("devices", self._snapshot)
        else:
            self._quick_status.setText(
                str((res or {}).get("error", "فشل التطبيق"))[:90])

    def _h_recover(self, res, err):
        self._busy_start("")
        self._rec_log.setPlainText(self._fmt_json(res))
        self._quick_status.setText("نتيجة الاسترداد معروضة")
        self._task("devices", self._snapshot)

    def _h_audit(self, res, err):
        rows = res if isinstance(res, list) else []
        self._render_audit(rows)

    def _h_tamper(self, res, err):
        broken = bool(res.get("broken")) if isinstance(res, dict) else False
        self._audit_status.setText("السلسلة سليمة" if not broken else "*** السلسلة مكسورة ***")
        self._audit_status.setStyleSheet(
            "color:#1d8a4c;" if not broken else "color:#c0392b;")

    def _h_diagnostics(self, res, err):
        if isinstance(res, dict):
            self._render_diagnostics(res)

    def _h_session_in(self, res, err):
        if res.get("ok"):
            self._session_label.setText(
                f"مسجّل: {res.get('display_name')} ({res.get('role_id')})")
        else:
            self._session_label.setText(res.get("error", "فشل الدخول"))

    # ------------------------------------------------------------------
    # أدوات مساعدة
    # ------------------------------------------------------------------
    def _snapshot(self):
        return {"devices": self.ctl.devices(), "adb": self.ctl.adb_status()}

    def _auto_refresh(self):
        if self._busy or not self.isVisible():
            return
        self._task("devices", self._snapshot)
        self._task("diagnostics", self.ctl.diagnostics)

    def _banner(self, attached):
        self._no_device_banner.setVisible(not bool(attached))

    def _render_dashboard_cards(self, devices, attached):
        locked = sum(1 for d in devices if tx(d, "device_owner_state") == "ACTIVE")
        ok = sum(1 for d in devices if tx(d, "compliance_state") == "COMPLIANT")
        need = sum(1 for d in devices
                   if tx(d, "compliance_state") in ("NON_COMPLIANT", "PARTIAL"))
        for card, val in ((self._card_attached[1], len(attached)),
                          (self._card_locked[1], locked),
                          (self._card_ok[1], ok),
                          (self._card_need[1], need)):
            card.setText(str(val))

    def _render_compliance(self, devices):
        q = self.ctl
        _t = getattr(self, "_comp_table", None)
        if _t is None:
            return
        _t.setRowCount(0)
        for d in devices:
            r = _t.rowCount()
            _t.insertRow(r)
            vals = [tx(d, "device_id"), tx(d, "model"),
                    ar_state(d, "enrollment_state", ENROLL_AR),
                    ar_state(d, "device_owner_state", OWNER_AR),
                    ar_state(d, "compliance_state", COMPLIANCE_AR),
                    tx(d, "last_verification_at")]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 4:
                    it.setForeground(self._status_color(val))
                _t.setItem(r, c, it)

    def _populate_combos(self, devices):
        ids = [tx(d, "device_id") for d in devices]
        cur = self._apply_dev.currentData()
        self._apply_dev.blockSignals(True)
        self._apply_dev.clear()
        for d in devices:
            self._apply_dev.addItem(
                f"{tx(d, 'device_id')} [{tx(d, 'serial')}]", tx(d, "device_id"))
        self._apply_dev.blockSignals(False)
        if cur and cur in ids:
            self._apply_dev.setCurrentIndex(self._apply_dev.findData(cur))
        elif ids:
            self._apply_dev.setCurrentIndex(0)

        self._rec_dev.blockSignals(True)
        self._rec_dev.clear()
        for d in devices:
            self._rec_dev.addItem(tx(d, "device_id"), tx(d, "device_id"))
        self._rec_dev.blockSignals(False)
        for cb in (self._apply_dev, self._rec_dev):
            if cb.count() and cb.currentData() is None:
                cb.setCurrentIndex(0)

        pols = []
        try:
            pols = self.ctl.policies()
        except Exception:
            pols = []
        pol_ids = [f"{p['policy_id']} — {p['display_name']} ({tx(p, 'status')})"
                   for p in pols]
        curp = self._apply_pol.currentText()
        self._apply_pol.blockSignals(True)
        self._apply_pol.clear()
        self._apply_pol.addItems(pol_ids)
        self._apply_pol.blockSignals(False)
        if curp and curp in pol_ids:
            self._apply_pol.setCurrentText(curp)
        elif pol_ids:
            self._apply_pol.setCurrentText(pol_ids[0])
        self._render_policies(pols)
        self._render_apply_preview()

    # ------------------------------------------------------------------
    # مصادقة المدير
    # ------------------------------------------------------------------
    def _login(self):
        user = self._ui_user.text().strip()
        pw = self._ui_pass.text()
        totp = self._ui_totp.text().strip()
        if not user or not pw or not totp:
            self._err("دخول", "أدخل اسم المستخدم وكلمة المرور ورمز TOTP.")
            return
        self._task("session_in", self.ctl.login, user, pw, totp)

    def _bootstrap(self):
        user = self._ui_user.text().strip()
        pw = self._ui_pass.text()
        if not user or not pw:
            self._err("إنشاء المدير الأول", "أدخل اسم المستخدم وكلمة المرور أولًا.")
            return
        self._task("boot_do", self.ctl.bootstrap, user, pw)

    def _h_boot_do(self, res, err):
        if res.get("ok"):
            uri = res.get("totp_uri", "")
            QMessageBox.information(
                self, "اكتمل الإنشاء",
                "امسح/أدخل رمز TOTP في تطبيق المصادقة ثم سجّل الدخول.\n\n"
                + uri + "\n\nنسخة احتياطية للسرّ: " + res.get("secret", ""))
            self._task("bootstrap", self.ctl.needs_bootstrap)
        else:
            self._err("إنشاء المدير الأول", res.get("error", "فشل"))

    def _logout(self):
        self._task("logout_do", self.ctl.logout)

    def _h_logout_do(self, res, err):
        self._session_label.setText("غير مسجّل الدخول")

    # ------------------------------------------------------------------
    # عرض وإخفاء الأخطاء
    # ------------------------------------------------------------------
    def _err(self, title, text):
        QMessageBox.warning(self, title, text)

    @staticmethod
    def _fmt_json(obj):
        try:
            return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
        except Exception:
            return str(obj)

    @staticmethod
    def _probe_pretty(serial: str, bundle: dict) -> str:
        identity = bundle.get("identity") or {}
        lines = [f"=== قراءة فعلية للجهاز {serial} ===\n",
                 f"المصنّع: {identity.get('manufacturer') or '؟'}",
                 f"الطراز: {identity.get('model') or '؟'}",
                 f"إصدار أندرويد: {identity.get('android_version') or '؟'}",
                 f"مستوى API: {identity.get('api_level') or '؟'}",
                 f"البصمة: {identity.get('build_fingerprint') or '؟'}",
                 f"مُدار كمالك جهاز (Device Owner): "
                 "نعم" if identity.get("device_owner") else "لا",
                 f"مصدر الفحص: {bundle.get('source')}", ""]
        obs = bundle.get("observed") or {}
        if obs:
            lines.append("--- الحالة المرصودة ---")
            for feat, val in sorted(obs.items()):
                lines.append(f"  {FEATURE_AR.get(feat, feat)}: {OBSERVED_AR.get(val, val)}")
        res = bundle.get("restrictions") or {}
        if res:
            lines.append("--- قيود مثبتة (من قراءة أداة الإدارة) ---")
            for feat in res:
                lines.append(f"  {FEATURE_AR.get(feat, feat)}: مفعّلة")
        dpc = bundle.get("dpc")
        if dpc:
            lines.append("--- حالة وكيل الإدارة (DPC) ---")
            if dpc.get("raw"):
                lines.append(f"  غير محللة: {dpc['raw'][:200]}")
            else:
                lines.append(f"  آخر أمر: {dpc.get('cmd_id') or '؟'}")
                lines.append(f"  التطبيق نشط في DPM: "
                             "نعم" if dpc.get("admin_active") else "لا")
                lines.append(f"  المطبَّق: {', '.join(dpc.get('applied') or []) or 'لا شيء'}")
                if dpc.get("errors"):
                    lines.append(f"  أخطاء: {', '.join(dpc.get('errors'))}")
        if bundle.get("camera_disabled"):
            lines.append("  الكاميرا معطّلة من إدارة المؤسسة (مثبت) - CAMERA")
        return "\n".join(lines)

    def closeEvent(self, event):
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(event)


STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #22303f; }
QMainWindow, QWidget#qt_centralwidget { background: #f2f4f8; }
#header { background: #ffffff; border-bottom: 1px solid #e0e4ea; }
#app_title { color: #17324d; }
#app_tag { color: #6a7a8c; font-size: 9pt; }
#quick_status { color: #2f6fed; }
#session { color: #1d8a4c; font-weight: bold; }
#nav { background: #17263b; color: #dbe6f2; border: none; outline: 0; }
#nav::item { height: 38px; padding: 4px 14px; color: #c6d4e4; border-radius: 6px; }
#nav::item:selected { background: #2f6fed; color: #ffffff; }
#card { background: #ffffff; border: 1px solid #e0e4ea; border-radius: 10px; padding: 14px; }
#card_value { font-size: 26pt; font-weight: bold; color: #17324d; }
#card_caption { font-size: 10pt; color: #6a7a8c; }
#section_title { font-size: 13pt; font-weight: bold; color: #17324d; margin-top: 6px; }
#box { background: #ffffff; border: 1px solid #e0e4ea; border-radius: 8px; padding: 8px; }
#note { color: #5a6a7c; }
#banner_warn { background: #fff3cd; color: #7a5c00; border: 1px solid #e6cf8a;
               border-radius: 8px; padding: 10px; font-weight: bold; }
QTableWidget { background: #ffffff; alternate-background-color: #f6f8fb;
               border: 1px solid #e0e4ea; border-radius: 8px; gridline-color: #eef1f5; }
QHeaderView::section { background: #e9eef5; color: #33506b; font-weight: bold;
               border: none; padding: 6px; }
QPushButton { background: #eef2f7; border: 1px solid #d5dce6; border-radius: 6px;
              padding: 6px 12px; }
QPushButton:hover { background: #dfe7f1; }
#btn_acc { background: #2f6fed; color: #ffffff; border: none; }
#btn_acc:hover { background: #285ed0; }
#btn_danger { background: #c0392b; color: #ffffff; border: none; font-weight: bold; }
#btn_danger:hover { background: #a93226; }
#btn_ghost { background: transparent; color: #33506b; border: 1px solid #d5dce6; }
QLineEdit, QComboBox, QSpinBox { background: #ffffff; border: 1px solid #c9d3e0;
              border-radius: 6px; padding: 5px 8px; }
QPlainTextEdit { background: #ffffff; border: 1px solid #e0e4ea; border-radius: 6px;
              font-family: 'Segoe UI'; }
QListWidget { outline: 0; }
"""


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(STYLE)
    win = App()
    win.show()
    win._task("policies", lambda: win.ctl.policies())
    win._task("reports", win.ctl.reports_list, "")
    win._render_settings()
    win._task("audit", win.ctl.audit, 80)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())