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
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit,
    QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl

from backend.recovery import RECOVERY_MODES
from backend.workflows import classify_device
from .controller import Controller
from . import logger

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
    "R0_WITHDRAW": "سحب DeviceOwner (إلغاء المالك من الوكيل)",
    "R1_RESTORE_POINT": "استعادة نقطة الحفظ (إزالة التقييدات المطبّقة)",
    "R2_REPROVISION": "إعادة التسجيل (خطة فقط)",
    "R3_LAB_FLASH": "فلاش مختبر للبرنامج الثابت (مرفوض دائمًا)",
    "R4_DIAGNOSTIC": "تشخيص (قراءة فقط + تقرير)",
}
FEATURE_AR = {
    "WIFI": "شبكة Wi-Fi", "BLUETOOTH": "البلوتوث", "MOBILE_DATA": "بيانات الجوال",
    "LOCATION": "الموقع الجغرافي", "CAMERA": "الكاميرا", "MICROPHONE": "الميكروفون",
    "TETHERING": "نقطة الاتصال (Hotspot)", "HOTSPOT": "المشاركة (Hotspot)",
    "USB": "نقل الملفات عبر USB", "VPN": "شبكات VPN", "ADB": "تصحيح الأخطاء (ADB)",
    "SAFE_BOOT": "الإقلاع الآمن", "FACTORY_RESET": "إعادة الضبط المصنعية",
    "APP_INSTALLATION": "تثبيت التطبيقات", "ACCOUNTS": "إدارة الحسابات",
    "ETHERNET": "شبكة إيثرنت", "DEVELOPER_OPTIONS": "خيارات المطور",
    "SCREEN_CAPTURE": "لقطات الشاشة", "GPS": "GPS", "BROWSER": "المتصفح",
    "PLAY_STORE": "متجر التطبيقات", "UNKNOWN_SOURCES": "المصادر غير المعروفة",
    "USB_NETWORKING": "شبكة USB", "BLUETOOTH_PAN": "تقاسم بلوتوث",
    "USER_MANAGEMENT": "إدارة المستخدمين", "LOCK_TASK": "وضع القفل (Kiosk)",
    "APPLICATIONS": "السماح بالتطبيقات",
}

# ميزات تُعرض في مُنشئ السياسة المخصصة (قابلة للتقييد BLOCK) — الحوكمة
# (FACTORY_RESET_RECOVERY / REFLAH_FIRMWARE) لا تعرض لأنها مشروطة بالمختبر فقط.
CUSTOM_POLICY_BLOCKABLE = (
    "WIFI", "BLUETOOTH", "MOBILE_DATA", "LOCATION", "GPS", "CAMERA",
    "MICROPHONE", "USB", "USB_NETWORKING", "ADB", "DEVELOPER_OPTIONS",
    "SAFE_BOOT", "FACTORY_RESET", "APP_INSTALLATION", "UNKNOWN_SOURCES",
    "BROWSER", "PLAY_STORE", "HOTSPOT", "TETHERING", "ACCOUNTS",
    "USER_MANAGEMENT", "SCREEN_CAPTURE", "LOCK_TASK", "APPLICATIONS",
    "ETHERNET", "VPN", "BLUETOOTH_PAN",
)
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
            logger.log_error(f"task:{self.tag}", ex)
            BUS.done.emit(self.tag, {"ok": False, "error": f"{type(ex).__name__}: {ex}"}, True)
        else:
            BUS.done.emit(self.tag, res, False)


class FullLockdownWizard(QDialog):
    """معالج القفل الكامل — خطوات واضحة: الاسم ← مراجعة الميزات المقيّدة ← إنشاء.

    ينشئ سياسة FULL_LOCKDOWN مخصصة (POL-CUST-*) من مجموعة أمنية قياسية قابلة
    للتعديل. التطبيق على الجهاز يحدث لاحقًا عبر صفحة «تطبيق السياسة» بفحص
    مسبق حقيقي — لا يُدّعى هنا أن شيئًا طُبِّق فعلًا.
    """

    DEFAULT_FULL_LOCKDOWN = (
        "WIFI", "BLUETOOTH", "MOBILE_DATA", "LOCATION", "GPS", "CAMERA",
        "MICROPHONE", "USB", "ADB", "DEVELOPER_OPTIONS", "SAFE_BOOT",
        "FACTORY_RESET", "APP_INSTALLATION", "UNKNOWN_SOURCES", "BROWSER",
        "PLAY_STORE", "HOTSPOT", "TETHERING", "ACCOUNTS", "USER_MANAGEMENT",
        "SCREEN_CAPTURE", "VPN", "ETHERNET", "USB_NETWORKING", "BLUETOOTH_PAN",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("معالج القفل الكامل")
        self.resize(620, 520)
        self.selected = []
        self.name = ""

        lay = QVBoxLayout(self)
        intro = QLabel(
            "سيرشدك هذا المعالج في إنشاء سياسة «قفل كامل» مخصصة:\n"
            "1) اسم السياسة (اختياري)    2) مراجعة الميزات المقيّدة    3) إنشاء.")
        intro.setWordWrap(True)
        intro.setObjectName("note")
        lay.addWidget(intro)

        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("اسم السياسة:"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("مثال: قفل كامل — بعثة «الربيع» (اتركه فارغًا للافتراضي)")
        nrow.addWidget(self._name, 1)
        lay.addLayout(nrow)

        lbl = QLabel("الميزات المراد تقييدها (Block):")
        lay.addWidget(lbl)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        grid = QGridLayout(holder)
        self._checks = {}
        for i, feat in enumerate(self.DEFAULT_FULL_LOCKDOWN):
            cb = QCheckBox(FEATURE_AR.get(feat, feat))
            cb.setToolTip(feat)
            cb.setChecked(True)
            self._checks[feat] = cb
            grid.addWidget(cb, i // 3, i % 3)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)

        note = QLabel(
            "يبقى الاتصال الهاتفي (CALLS/SMS/CONTACTS) مسموحًا. التطبيق الفعلي "
            "على الجهاز يتم لاحقًا من صفحة «تطبيق السياسة» بفحص مسبق حقيقي — "
            "هذه الخطوة تنشئ السياسة فقط.")
        note.setObjectName("note")
        note.setWordWrap(True)
        lay.addWidget(note)

        btns = QHBoxLayout()
        ok = QPushButton("إنشاء السياسة")
        ok.setObjectName("btn_acc")
        ok.clicked.connect(self._accept)
        btns.addWidget(ok)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        lay.addLayout(btns)

    def _accept(self):
        feats = [f for f, cb in self._checks.items() if cb.isChecked()]
        if not feats:
            QMessageBox.warning(self, "القفل الكامل",
                                "اختر ميزة واحدة على الأقل لتقييدها.")
            return
        self.selected = feats
        self.name = self._name.text().strip()
        self.accept()


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ctl = Controller()
        self._last_probe = {}          # serial -> bundle
        self._last_apply = None
        self._busy = False
        self._session_label = None
        self._quick_status = None
        self._active = None            # active device context {device_id, serial, model}
        self._sensitive_busy = False
        self._last_dev_sig = None
        self._last_devices = {}        # device_id -> row (for confirm dialog)
        self._sensitive_widgets = []
        self._pols_cache = []
        self._pols_loaded = False
        self._pending_apply = False
        self._last_recover = None

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
            ("apps", "التطبيقات"),
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
        self._build_apps()
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

        self._active_lbl = QLabel("الجهاز المحدد: —")
        self._active_lbl.setObjectName("active_device")
        self._active_lbl.setWordWrap(False)
        lay.addWidget(self._active_lbl)

        lay.addSpacing(14)
        self._quick_status = QLabel("")
        self._quick_status.setObjectName("quick_status")
        lay.addWidget(self._quick_status)

        lay.addSpacing(14)
        self._session_label = QLabel("وضع المشغّل المحلي — لا تسجيل دخول تفاعلي")
        self._session_label.setObjectName("session_mode")
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

        cards2 = QHBoxLayout()
        self._card_unknown = self._card("حالة الالتزام غير معروفة")
        self._card_unscanned = self._card("غير مفحوصة (لا قراءة فعلية)")
        self._card_adb = self._card("ADB")
        self._card_lastop = self._card("آخر عملية")
        for c in (self._card_unknown, self._card_unscanned,
                  self._card_adb, self._card_lastop):
            cards2.addWidget(c[0])
        v.addLayout(cards2)

        self._dash_status = QLabel("")
        self._dash_status.setObjectName("note")
        self._dash_status.setWordWrap(True)
        v.addWidget(self._dash_status)

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
        dash = getattr(self, "_table_dash", None)
        if dash is not None:
            self._fill_device_table(dash, devices)
        self._dev_cache = devices
        self._apply_device_filter()

    def _fill_device_table(self, tbl, devices):
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

    def _apply_device_filter(self):
        tbl = getattr(self, "_table_dev", None)
        if tbl is None:
            return
        q = (self._dev_search.text() or "").strip().lower()
        src = getattr(self, "_dev_cache", []) or []
        rows = (src if not q else
                [d for d in src
                 if q in (tx(d, "device_id") + " " + tx(d, "serial") + " " +
                          tx(d, "model") + " " +
                          ar_state(d, "enrollment_state", ENROLL_AR) + " " +
                          ar_state(d, "compliance_state", COMPLIANCE_AR)).lower()])
        tbl.setRowCount(0)
        self._fill_device_table(tbl, rows)

    def _status_color(self, text) -> QColor:
        if text in ("متوافق", "فعّال", "نجح التحقق", "سليمة"):
            return QColor("#1d8a4c")
        if text in ("غير متوافق", "فشل", "مرفوض", "فشل التحقق"):
            return QColor("#c0392b")
        if text in ("متوافق جزئيًا", "جزئي", "تحقق جزئي", "محظور"):
            return QColor("#c07a00")
        if text == "مقيّد بإدارة المؤسسة":
            return QColor("#2f6fed")
        if text in ("غير معروف", "تحذير"):
            return QColor("#c07a00")
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

        self._detect_lbl = QLabel("")
        self._detect_lbl.setObjectName("detect_summary")
        self._detect_lbl.setWordWrap(True)
        self._detect_lbl.hide()
        v.addWidget(self._detect_lbl)

        dt = QLabel("الأجهزة المكتشفة تلقائيًا (ADB) — اختر جهازًا ثم اضغط «فتح الجهاز» لتحديده")
        dt.setObjectName("section_title")
        v.addWidget(dt)
        self._detect_table = QTableWidget(0, 5)
        self._detect_table.setHorizontalHeaderLabels(
            ["الجهاز", "الرقم التسلسلي", "الحالة", "الاتصال", "التسجيل"])
        self._detect_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._detect_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._detect_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._detect_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._detect_table.setMaximumHeight(170)
        self._detect_table.itemDoubleClicked.connect(lambda *_: self._open_device())
        v.addWidget(self._detect_table)

        discover = QHBoxLayout()
        b_open = QPushButton("فتح الجهاز (تحديد)")
        b_open.setObjectName("btn_acc")
        b_open.clicked.connect(self._open_device)
        discover.addWidget(b_open)
        b_rescan = QPushButton("إعادة البحث (ADB)")
        b_rescan.clicked.connect(lambda: self._task("devices", self._snapshot))
        discover.addWidget(b_rescan)
        discover.addStretch(1)
        v.addLayout(discover)
        self._sensitive_widgets.extend([b_open, self._detect_table])

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

        v.addWidget(QLabel("بحث / تصفية: اكتب معرّفًا أو تسلسلًا أو طرازًا أو حالة"))
        self._dev_search = QLineEdit()
        self._dev_search.setPlaceholderText("مثال: SM-J337P أو AVD-… أو «مسجّل»")
        self._dev_search.textChanged.connect(self._apply_device_filter)
        v.addWidget(self._dev_search)

        self._dev_log = QPlainTextEdit()
        self._dev_log.setPlaceholderText("نتائج عمليات الأجهزة…")
        self._dev_log.setMaximumHeight(190)
        v.addWidget(self._dev_log)
        self._stack.addWidget(page)

    # ------------------------------------------------------------------
    # الصفحة: التطبيقات (قراءة فعلية عبر ADB — حزم مثبّتة فقط)
    # ------------------------------------------------------------------
    def _build_apps(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("التطبيقات المثبّتة — قراءة فعلية عبر ADB (pm list packages)")
        t.setObjectName("section_title")
        v.addWidget(t)

        row = QHBoxLayout()
        b = QPushButton("فحص تطبيقات الجهاز المحدد")
        b.setObjectName("btn_acc")
        b.clicked.connect(self._apps_scan)
        row.addWidget(b)
        self._apps_search = QLineEdit()
        self._apps_search.setPlaceholderText("بحث في أسماء الحزم…")
        self._apps_search.textChanged.connect(self._filter_apps)
        row.addWidget(self._apps_search, 1)
        self._apps_lbl = QLabel("")
        self._apps_lbl.setObjectName("note")
        row.addWidget(self._apps_lbl)
        v.addLayout(row)

        self._apps_table = QTableWidget(0, 3)
        self._apps_table.setHorizontalHeaderLabels(
            ["اسم الحزمة", "النوع", "مصدر القراءة"])
        self._apps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._apps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._apps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._apps_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._apps_table.verticalHeader().setVisible(False)
        v.addWidget(self._apps_table, 1)

        n = QLabel(
            "هذه القائمة مرجع قراءة فقط: حظر/إخفاء التطبيقات على مستوى السياسات "
            "يُنفَّذ من خلال وكيل DPC بعد تفعيل Device Owner — لا تدّعي هذه الصفحة "
            "تطبيقًا أو إزالةً لأي تطبيق.")
        n.setObjectName("note")
        n.setWordWrap(True)
        v.addWidget(n)
        self._stack.addWidget(page)

    def _apps_scan(self):
        serial = (self._active or {}).get("serial") or \
            (self._selected_device_row() or {}).get("serial")
        if not serial:
            self._err("التطبيقات",
                      'حدّد جهازًا (من الأجهزة المكتشفة أو القائمة) ثم اضغط "فحص تطبيقات الجهاز المحدد".')
            return
        self._busy_start("جاري قراءة التطبيقات المثبّتة…")
        self._task("apps", self.ctl.apps, serial)

    def _h_apps(self, res, err):
        self._busy_start("")
        if err or not res.get("ok"):
            self._apps_lbl.setText(self._fmt_json(res))
            return
        a = res["apps"]
        self._apps_cache = a
        self._apps_lbl.setText(
            f"الإجمالي: {a['count']} — طرف ثالث: {a['third_party_count']} — "
            f"النظام: {a['system_count']}  |  {a['serial']}")
        self._filter_apps()

    def _filter_apps(self):
        tbl = getattr(self, "_apps_table", None)
        if tbl is None:
            return
        a = getattr(self, "_apps_cache", None)
        if not a:
            tbl.setRowCount(0)
            return
        q = (self._apps_search.text() or "").strip().lower()
        tp = set(a.get("third_party") or [])
        all_pkgs = (a.get("third_party") or []) + (a.get("system") or [])
        rows = [p for p in all_pkgs if not q or q in p.lower()]
        tbl.setRowCount(0)
        for pkg in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            it0 = QTableWidgetItem(pkg)
            it1 = QTableWidgetItem("طرف ثالث" if pkg in tp else "النظام")
            it1.setForeground(QColor("#2f6fed" if pkg in tp else "#5a6a7c"))
            it2 = QTableWidgetItem("ADB — pm list packages")
            tbl.setItem(r, 0, it0)
            tbl.setItem(r, 1, it1)
            tbl.setItem(r, 2, it2)

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
            if d.get("device_id"):
                self._set_active(device_id=d["device_id"])
            self._render_apply_preview()

    # ------------------------------------------------------------------
    # سياق الجهاز المحدد (الجهاز النشط) — يظهر في الشريط العلوي عبر كل الصفحات
    # ------------------------------------------------------------------
    def _set_active(self, device_id="", serial=""):
        r = self.ctl.set_active_device(device_id=device_id, serial=serial)
        if r.get("ok"):
            self._active = r
            self._render_active_banner()
        return bool(r.get("ok"))

    def _render_active_banner(self):
        a = self._active
        if a and a.get("device_id"):
            text = (f"الجهاز المحدد: {a.get('model') or '؟'} "
                    f"[{a.get('device_id')}] — {a.get('serial') or ''}")
        else:
            text = "لا يوجد جهاز محدد — اختر من صفحة الأجهزة"
        self._active_lbl.setText(text)

    def _sync_active(self, devices):
        if self._active is not None and not any(
                tx(d, "device_id") == self._active.get("device_id") for d in devices):
            self._active = None
        if self._active is None:
            a = self.ctl.active_device()
            if a.get("ok") and any(tx(d, "device_id") == a.get("device_id")
                                   for d in devices):
                self._active = a
        self._render_active_banner()
        active_id = self._active.get("device_id") if self._active else None
        idx = self._apply_dev.findData(active_id)
        if idx >= 0:
            self._apply_dev.setCurrentIndex(idx)
        idx2 = self._rec_dev.findData(active_id)
        if idx2 >= 0:
            self._rec_dev.setCurrentIndex(idx2)

    def _open_device(self):
        if self._sensitive_busy:
            return
        tbl = self._detect_table
        sel = tbl.selectionModel().selectedRows()
        if not sel:
            self._err("فتح الجهاز", "اختر جهازًا من قائمة الأجهزة المكتشفة أولًا.")
            return
        r = sel[0].row()
        it = tbl.item(r, 0)
        if it is None:
            return
        serial = it.data(Qt.UserRole) or ""
        model = it.text()
        registered = bool(tbl.item(r, 4)) and tbl.item(r, 4).text() == "مسجّل"
        self._dev_serial.setText(serial)
        if serial and not registered:
            self._quick_status.setText(f"تسجيل الجهاز {model or serial}…")
            self._task("open_device", self.ctl.enroll, serial, "", False)
        else:
            ok = self._set_active(serial=serial or "")
            if ok:
                self._quick_status.setText("تم تحديد الجهاز")
                self._task("devices", self._snapshot)
            else:
                self._err("فتح الجهاز", "الجهاز غير مسجّل بعد — جرّب «تسجيل الجهاز».")

    def _enroll(self):
        serial = self._dev_serial.text().strip()
        if not serial:
            self._err("تسجيل الجهاز", "الرقم التسلسلي مطلوب")
            return
        did = self._dev_did.text().strip()
        lab = self._dev_lab.currentIndex() == 1
        self._task("enroll", self.ctl.enroll, serial, did, lab)

    def _probe_action(self):
        d = None
        if self._active and self._active.get("serial"):
            d = self._active
        else:
            d = self._selected_device_row()
        serial = (d or {}).get("serial")
        if not serial:
            self._err("فحص الجهاز",
                      'حدّد جهازًا أولًا (من الأجهزة المكتشفة أو القائمة) ثم اضغط "فحص الجهاز".')
            return
        self._busy_start("فحص الجهاز…")
        self._task("probe", self.ctl.probe, serial)

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
        serial = (self._active or {}).get("serial") or \
            (self._selected_device_row() or {}).get("serial")
        if not serial:
            self._err("فحص القدرات", "اختر جهازًا أولًا.")
            return
        self._busy_start("جاري فحص القدرات…")
        self._task("cap_scan", self.ctl.probe, serial)

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
        self._pol_table.setMaximumHeight(170)
        v.addWidget(self._pol_table)

        t2 = QLabel("مُنشئ سياسة مخصصة (تحديد الميزات المراد تقييدها)")
        t2.setObjectName("section_title")
        v.addWidget(t2)

        builder = QFrame()
        builder.setObjectName("box")
        bl = QVBoxLayout(builder)
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("الاسم:"))
        self._cp_name = QLineEdit()
        self._cp_name.setPlaceholderText("مثال: تقييد بعثة «الربيع»")
        row0.addWidget(self._cp_name, 1)
        row0.addWidget(QLabel("الفئة:"))
        self._cp_cat = QComboBox()
        for cat, lbl in (("CORPORATE_DEFAULT", "الوضع المؤسسي"),
                         ("PHONE_ONLY", "الهاتف فقط"),
                         ("PARTIAL_LOCKDOWN", "تقييد جزئي"),
                         ("FULL_LOCKDOWN", "القفل الكامل"),
                         ("MAINTENANCE", "الصيانة"),
                         ("QUARANTINE", "حجر صحي")):
            self._cp_cat.addItem(f"{lbl} ({cat})", cat)
        row0.addWidget(self._cp_cat)
        row0.addWidget(QLabel("المخاطرة:"))
        self._cp_risk = QComboBox()
        for r in ("MEDIUM", "HIGH", "CRITICAL", "LOW"):
            self._cp_risk.addItem(RISK_AR.get(r, r), r)
        row0.addWidget(self._cp_risk)
        bl.addLayout(row0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(150)
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        self._cp_checks = {}
        for i, feat in enumerate(CUSTOM_POLICY_BLOCKABLE):
            cb = QCheckBox(FEATURE_AR.get(feat, feat))
            cb.setToolTip(feat)
            self._cp_checks[feat] = cb
            grid.addWidget(cb, i // 3, i % 3)
        scroll.setWidget(grid_holder)
        bl.addWidget(scroll)

        rowbtn = QHBoxLayout()
        b_create = QPushButton("إنشاء السياسة المخصصة")
        b_create.setObjectName("btn_acc")
        b_create.clicked.connect(self._custom_policy_action)
        rowbtn.addWidget(b_create)
        b_full = QPushButton("معالج القفل الكامل (Full Lockdown)")
        b_full.setObjectName("btn_danger")
        b_full.clicked.connect(self._full_lockdown_wizard)
        rowbtn.addWidget(b_full)
        rowbtn.addStretch(1)
        bl.addLayout(rowbtn)
        v.addWidget(builder)
        self._pol_note = QLabel("")
        self._pol_note.setObjectName("note")
        self._pol_note.setWordWrap(True)
        v.addWidget(self._pol_note)
        v.addStretch(1)
        self._stack.addWidget(page)

    def _selected_block_features(self):
        return [f for f, cb in self._cp_checks.items() if cb.isChecked()]

    def _custom_policy_action(self):
        name = self._cp_name.text().strip()
        feats = self._selected_block_features()
        if not feats:
            self._pol_note.setText("اختر ميزة واحدة على الأقل لتقييدها قبل الإنشاء.")
            self._err("سياسة مخصصة", "اختر ميزة واحدة على الأقل لتقييدها.")
            return
        cat = self._cp_cat.currentData()
        risk = self._cp_risk.currentData()
        self._pol_note.setText("جاري إنشاء السياسة…")
        self._task("policy_create", self.ctl.create_policy, name, cat,
                   feats, risk)

    def _full_lockdown_wizard(self):
        wiz = FullLockdownWizard(self)
        if not wiz.exec():
            return
        name = wiz.name or "القفل الكامل"
        self._pol_note.setText("معالج القفل الكامل: جاري إنشاء السياسة…")
        self._task("policy_create_full", self.ctl.create_policy, name,
                   "FULL_LOCKDOWN", wiz.selected, "CRITICAL")

    def _h_policy_create(self, res, err):
        self._pol_note.setText("")
        if err or not res.get("ok"):
            self._pol_note.setText(self._fmt_json(res))
            self._err("سياسة مخصصة", str((res or {}).get("error", "تعذر الإنشاء")))
            return
        self._pols_cache = None
        self._pols_loaded = False
        self._just_created_policy_id = res.get("policy_id")
        self._task("devices", self._snapshot)
        self._task("policies", self.ctl.policies)
        self._pol_note.setText(
            f"تم إنشاء السياسة {res['policy_id']} — تشمل {res['features']} ميزة. "
            "افتح صفحة «تطبيق السياسة» لتجربتها على جهاز.")
        self._quick_status.setText(f"سياسة جديدة: {res['policy_id']}")

    def _h_policy_create_full(self, res, err):
        self._h_policy_create(res, err)
        if not err and res.get("ok"):
            self._set_flow("القفل الكامل جاهز للتطبيق — افتح صفحة التطبيق للتحقق المسبق")

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
        fl.addWidget(QLabel("بيان الاسترداد:"))
        self._apply_rec = QLabel("يُفحص من هذه الوحدة قبل التنفيذ")
        self._apply_rec.setObjectName("note")
        fl.addWidget(self._apply_rec)
        fl.addWidget(QLabel("الميزات (اختياري، مفصولة بفاصلة):"))
        self._apply_sub = QLineEdit()
        self._apply_sub.setMaximumWidth(160)
        fl.addWidget(self._apply_sub)
        v.addWidget(form)
        self._apply_dev.activated.connect(self._apply_rec_refresh)
        self._apply_dev.activated.connect(self._apply_dev_changed)

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

        t2 = QLabel("الفحص المسبق قبل التطبيق (من قراءة فعلية للجهاز والحسابات)")
        t2.setObjectName("section_title")
        v.addWidget(t2)
        self._pref_table = QTableWidget(0, 3)
        self._pref_table.setHorizontalHeaderLabels(["الحالة", "البند", "التفاصيل"])
        self._pref_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._pref_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pref_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pref_table.setMaximumHeight(170)
        v.addWidget(self._pref_table)

        self._flow_lbl = QLabel("")
        self._flow_lbl.setObjectName("flow")
        v.addWidget(self._flow_lbl)

        row = QHBoxLayout()
        b = QPushButton("تطبيق السياسة الآن (يسبقه فحص مسبق + تأكيد)")
        b.setObjectName("btn_danger")
        b.clicked.connect(self._apply_action)
        row.addWidget(b)
        b2 = QPushButton("تشغيل الفحص المسبق فقط")
        b2.clicked.connect(self._preflight_action)
        row.addWidget(b2)
        b3 = QPushButton("تحديث المعاينة")
        b3.clicked.connect(self._render_apply_preview)
        row.addWidget(b3)
        row.addStretch(1)
        v.addLayout(row)
        self._sensitive_widgets.extend([self._apply_dev, self._apply_pol,
                                        self._apply_sub, b, b2, b3])

        self._apply_log = QPlainTextEdit()
        self._apply_log.setReadOnly(True)
        v.addWidget(self._apply_log, 1)

        pin_form = QFrame()
        pin_form.setObjectName("box")
        pf = QHBoxLayout(pin_form)
        pf.addWidget(QLabel("توفير رمز PIN لزر التراجع:"))
        self._pin_dev = QComboBox()
        self._pin_dev.setMinimumWidth(260)
        pf.addWidget(self._pin_dev)
        self._pin_edit = QLineEdit()
        self._pin_edit.setPlaceholderText("4–12 أرقام — اتركه فارغاً لتوليد عشوائي")
        self._pin_edit.setMaximumWidth(220)
        pf.addWidget(self._pin_edit)
        b_pin = QPushButton("توفير الرمز")
        b_pin.clicked.connect(self._pin_provision_action)
        pf.addWidget(b_pin)
        v.addWidget(pin_form)
        self._sensitive_widgets.extend([self._pin_dev, self._pin_edit, b_pin])

        self._stack.addWidget(page)

    def _pin_provision_action(self):
        did = self._pin_dev.currentData()
        if not did:
            self._err("توفير الرمز", "اختر الجهاز أولًا.")
            return
        pin = self._pin_edit.text().strip()
        if pin and not (pin.isdigit() and 4 <= len(pin) <= 12):
            self._err("توفير الرمز", "الرمز يجب أن يكون 4–12 رقماً.")
            return
        msg = (f"توفير رمز PIN للجهاز {did} — يوقَّع توقيع Ed25519 من هذه الوحدة.\n\n"
               + (f"الرمز المحدد: {pin}" if pin else
                  "سيُولَّد رمز عشوائي من 6 أرقام ويُعرض مرة واحدة."))
        ret = QMessageBox.question(self, "توفير رمز PIN", msg,
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.No)
        if ret != QMessageBox.Yes:
            self._set_flow("أُلغي توفير الرمز")
            return
        self._busy_start("جارٍ توقيع وتوصيل الرمز…")
        self._set_flow("توقيع PROVISION_PIN وإرساله عبر ADB…")
        self._lock_sensitive(True)
        self._task("pin", self.ctl.provision_pin, did, pin)

    def _h_pin(self, res, err):
        self._lock_sensitive(False)
        if err:
            self._set_flow("توفير الرمز فشل")
            self._err("توفير الرمز", str(err))
            return
        if not res.get("ok"):
            self._set_flow("توفير الرمز فشل")
            self._err("توفير الرمز", res.get("error", "فشل غير معروف"))
            return
        self._apply_log.appendPlainText(self._fmt_json(res))
        self._pin_edit.setPlaceholderText("4–12 أرقام — اتركه فارغاً لتوليد عشوائي")
        self._pin_edit.setText(res.get("pin", ""))
        self._set_flow("تم توفير الرمز ✓ — احفظه الآن (يُعرض مرة واحدة)")
        self._busy_start("تم توفير الرمز للجهاز")
        QMessageBox.information(
            self, "توفير الرمز",
            f"تم توقيع وتوصيل رمز PIN للجهاز {self._pin_dev.currentData()}.\n\n"
            f"الرمز: {res.get('pin', '')}\n\n"
            "احفظه الآن — لا يُعرض إلا مرة واحدة. سيُسأل عنه الزر "
            "«تراجع» في التطبيق على الجهاز (مع قفل بعد 5 محاولات).")

    def _apply_dev_changed(self, *_):
        did = self._apply_dev.currentData()
        if did and not self._sensitive_busy:
            self._set_active(device_id=did)
            idx = self._rec_dev.findData(did)
            if idx >= 0:
                self._rec_dev.blockSignals(True)
                self._rec_dev.setCurrentIndex(idx)
                self._rec_dev.blockSignals(False)
        self._render_apply_preview()

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
        if not did or not pol:
            self._err("تطبيق السياسة", "اختر الجهاز والسياسة.")
            return
        self._apply_rec_refresh()
        self._pending_apply = True
        self._set_flow("معاينة ✓ — تشغيل الفحص المسبق…")
        self._lock_sensitive(True)
        self._task("preflight", self.ctl.preflight, did, pol.split()[0])

    def _preflight_action(self):
        did = self._apply_dev.currentData()
        pol = self._apply_pol.currentText()
        if not did or not pol:
            self._err("الفحص المسبق", "اختر الجهاز والسياسة أولًا.")
            return
        self._pending_apply = False
        self._set_flow("معاينة ✓ — تشغيل الفحص المسبق…")
        self._lock_sensitive(True)
        self._task("preflight", self.ctl.preflight, did, pol.split()[0])

    def _h_preflight(self, res, err):
        self._busy_start("")
        if err or not isinstance(res, dict) or not res.get("ok"):
            self._apply_log.setPlainText(self._fmt_json(res or {}))
            self._set_flow("الفحص المسبق: فشل")
            self._quick_status.setText("فشل الفحص المسبق")
            self._lock_sensitive(False)
            return
        self._render_preflight(res)
        if not res.get("can_apply"):
            self._apply_log.setPlainText(self._fmt_json(res))
            self._set_flow("الفحص المسبق: محظور — لن يُنفَّذ التطبيق")
            self._quick_status.setText(res.get("reason", "الفحص المسبق منع التطبيق"))
            self._lock_sensitive(False)
            self._err("تطبيق السياسة", res.get("reason", "التطبيق محظور"))
            return
        if not self._pending_apply:
            v = res.get("verdict")
            self._set_flow("الفحص المسبق: "
                           + ("جاهز ✓" if v == "PASS" else "تحذيرات — لم يُنفَّذ التطبيق"))
            self._quick_status.setText("الفحص المسبق اكتمل (بدون تنفيذ)")
            self._lock_sensitive(False)
            return
        verdict_ar = {"PASS": "جاهز", "CONDITIONAL": "تحذيرات (غير محظور)"}.get(
            res.get("verdict"), res.get("verdict"))
        msg = ("سيتم تطبيق السياسة فعليًا على الجهاز ثم التحقق منه بقراءة فعلية "
               "(REAL_DEVICE) مع رقم دليل evidence_id.\n\n"
               f"الجهاز: {res.get('device_id')}\n"
               f"السياسة: {self._apply_pol.currentText()}\n"
               f"الفحص المسبق: {verdict_ar}\n\n"
               + self._preflight_summary(res) +
               "\n\nمتابعة التنفيذ؟")
        ret = QMessageBox.question(self, "تأكيد التطبيق", msg,
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.No)
        if ret != QMessageBox.Yes:
            self._apply_log.setPlainText("أُلغي التطبيق بعد الفحص المسبق.")
            self._set_flow("الفحص المسبق ✓ — أُلغي التنفيذ")
            self._lock_sensitive(False)
            return
        self._set_flow("الفحص المسبق ✓ — تنفيذ التطبيق والتحقق…")
        sub = self._apply_sub.text().strip()
        self._task("apply", self.ctl.apply, res.get("device_id"),
                   res.get("policy"), True, sub)

    def _render_preflight(self, res):
        self._pref_table.setRowCount(0)
        labels = {"PASS": "جاهز", "FAIL": "محظور", "WARN": "تحذير",
                  "UNKNOWN": "غير معروف"}
        colors = {"PASS": "#1d8a4c", "FAIL": "#c0392b", "WARN": "#c07a00",
                  "UNKNOWN": "#5a6a7c"}
        for c in res.get("checks", []):
            r = self._pref_table.rowCount()
            self._pref_table.insertRow(r)
            status = c.get("status", "")
            it0 = QTableWidgetItem(labels.get(status, status))
            it0.setForeground(QColor(colors.get(status, "#4a4a4a")))
            self._pref_table.setItem(r, 0, it0)
            self._pref_table.setItem(r, 1, QTableWidgetItem(c.get("name", "")))
            self._pref_table.setItem(r, 2, QTableWidgetItem(c.get("detail", "")))

    @staticmethod
    def _preflight_summary(res) -> str:
        marks = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "UNKNOWN": "؟"}
        return "\n".join(
            f"{marks.get(c.get('status'), '·')} {c.get('name', '')}: "
            f"{c.get('detail', '')}" for c in res.get("checks", []))

    def _set_flow(self, text):
        if self._flow_lbl is not None and text:
            self._flow_lbl.setText(text)

    def _lock_sensitive(self, locked):
        """الجهاز يُقفَل أثناء العمليات الحساسة: لا يجوز تغيير الاختيار أو
        تكرار التنفيذ حتى تكتمل العملية."""
        self._busy = locked
        self._sensitive_busy = locked
        for w in self._sensitive_widgets:
            w.setEnabled(not locked)
        if locked:
            self._quick_status.setText(
                "عملية حساسة قيد التنفيذ — اختيار الجهاز/السياسة مغلق مؤقتًا")

    def _apply_rec_refresh(self, *_):
        """عرض حالة بيان الاسترداد (عامل الحيازة) للجهاز المحدد — لا يكشف السر."""
        did = self._apply_dev.currentData()
        if not did:
            return
        try:
            st = self.ctl.recovery_status(did)
        except Exception as ex:  # noqa: BLE001
            self._apply_rec.setText(f"تعذّر الفحص: {ex}")
            return
        if not st.get("ok"):
            self._apply_rec.setText(f"غير متاح: {st.get('error', '')}")
            return
        rid = st.get("recovery_id", "")
        txt = (f"جاهز (Recovery ID: {rid})" if st.get("recovery") == "Configured"
               else f"{st.get('recovery', '')} — يلزم إصدار البيان أولًا")
        self._apply_rec.setText(txt)

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
        self._verify_table = QTableWidget(0, 2)
        self._verify_table.setHorizontalHeaderLabels(["البنود", "القيمة"])
        self._verify_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._verify_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._verify_table.verticalHeader().setVisible(False)
        self._verify_table.setMaximumHeight(280)
        v.addWidget(self._verify_table)
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
        self._rec_rec = QLabel("")
        self._rec_rec.setObjectName("note")
        fl.addWidget(self._rec_rec)
        v.addWidget(form)

        form2 = QFrame()
        form2.setObjectName("box")
        fl2 = QHBoxLayout(form2)
        fl2.addWidget(QLabel("الموافِق الأول (الاسم):"))
        self._rec_aprv1 = QLineEdit()
        self._rec_aprv1.setMaximumWidth(130)
        fl2.addWidget(self._rec_aprv1)
        fl2.addWidget(QLabel("الموافِق الثاني (الاسم، R1/R2):"))
        self._rec_aprv2 = QLineEdit()
        self._rec_aprv2.setMaximumWidth(130)
        fl2.addWidget(self._rec_aprv2)
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
        self._sensitive_widgets.extend([self._rec_dev, self._rec_mode,
                                        self._rec_aprv1, self._rec_aprv2,
                                        self._rec_reason, b])

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
        if not did or not mode:
            self._err("الاسترداد", "اختر الجهاز والوضع.")
            return
        self._rec_rec_refresh()
        self._set_flow("استرداد: " + REC_MODE_AR.get(mode, mode))
        self._lock_sensitive(True)
        self._busy_start("جاري تنفيذ الاسترداد…")
        self._task("recover", self.ctl.recover, did, mode,
                   approver1=self._rec_aprv1.text().strip(),
                   approver2=self._rec_aprv2.text().strip(),
                   reason=self._rec_reason.text().strip(),
                   exec_=True)

    def _rec_rec_refresh(self, *_):
        """عرض حالة بيان الاسترداد (عامل الحيازة) — لا يكشف السر."""
        did = self._rec_dev.currentData()
        if not did:
            return
        try:
            st = self.ctl.recovery_status(did)
        except Exception as ex:  # noqa: BLE001
            self._rec_rec.setText(f"تعذّر الفحص: {ex}")
            return
        if not st.get("ok"):
            self._rec_rec.setText(f"غير متاح: {st.get('error', '')}")
            return
        rid = st.get("recovery_id", "")
        txt = (f"بيان الاسترداد: جاهز (Recovery ID: {rid})"
               if st.get("recovery") == "Configured"
               else f"بيان الاسترداد: {st.get('recovery', '')} — سيُعترض بدون حيازة")
        self._rec_rec.setText(txt)

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
        self._session_label.setText("وضع المشغّل المحلي — لا تسجيل دخول تفاعلي")
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
            "2) وضع المشغّل المحلي وبيان الاسترداد\n"
            "   - المنصة لا تستخدم تسجيل دخول تفاعلي عند بدء التشغيل — تفتح "
            "اللوحة مباشرة.\n"
            "   - العمليات الحساسة (تطبيق/استرداد) محكومة ببيان استرداد "
            "للجهاز مولّد تلقائيًا\n"
            "   - ومخزّن مشفّرًا في هذه الوحدة، مع آلية صلاحيات وموافقات "
            "إدارية (قاعدتا موافقة).\n\n"
            "3) تطبيق السياسة\n"
            "   - من صفحة “تطبيق السياسة”: اختر الجهاز والسياسة وراجع المعاينة.\n"
            "   - المعاينة تعرض: الهدف، الحالة الحالية الفعلية، الإجراء، والمخاطرة.\n"
            "   - اضغط “تطبيق السياسة الآن” — يتطلب حيازة بيان الاسترداد للجهاز.\n"
            "   - النتيجة تعرض دائمًا نتيجة تحقق REAL_DEVICE مع evidence_id.\n\n"
            "4) التحقق والالتزام\n"
            "   - تحقق من صفحة “التحقق” (نتيجة آخر تطبيق) وصفحة “حالة الالتزام”.\n"
            "   - المحاكاة لا تمنح PASS — إن لم تتوفر قراءة فعلية تظهر “غير معروف”.\n\n"
            "5) الاسترداد\n"
            "   - R1 (نقطة الحفظ) يزيل التقييدات المطبّقة ويتطلب موافقتين "
            "باسمين مختلفين.\n"
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
            "- صلاحيات إدارية بآليات استرداد وموافقة (بدون تسجيل دخول تفاعلي).\n")
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
                logger.log_error(f"ui:{tag}", ex)
                self._quick_status.setText(f"خطأ داخلي في العرض: {ex}")
        if tag in ("devices",):
            self._quick_status.setText("")
            self.statusBar().showMessage("تم تحديث الأجهزة.")

    # مُعالجات النتائج
    def _h_bootstrap(self, res, err):
        if err:
            self._session_label.setText("فشل فحص الإعداد")
            return
        self._session_label.setText("وضع المشغّل المحلي — لا تسجيل دخول تفاعلي")
        self._busy_start("")

    def _h_devices(self, res, err):
        if err or not isinstance(res, dict):
            self._quick_status.setText("تعذر تحديث الأجهزة.")
            return
        devices = res.get("devices", [])
        self._last_devices = {tx(d, "device_id"): d for d in devices}
        adb = res.get("adb", {})
        attached = adb.get("devices", [])
        self._banner(attached)
        self._render_devices(devices)
        self._render_detected(res.get("detected") or [], devices)
        self._render_dashboard_cards(devices, attached)
        self._render_compliance(devices)
        sig = tuple(sorted(tx(d, "device_id") for d in devices))
        if sig != self._last_dev_sig or not getattr(self, "_pols_loaded", False):
            self._last_dev_sig = sig
            if not self._pols_loaded:
                try:
                    self._pols_cache = self.ctl.policies()
                    self._pols_loaded = True
                except Exception:
                    self._pols_cache = []
            self._populate_combos(devices)
        self._sync_active(devices)

    def _render_detected(self, detected, devices=None):
        if getattr(self, "_detect_table", None) is None:
            return
        self._detect_table.setRowCount(0)
        for d in detected:
            r = self._detect_table.rowCount()
            self._detect_table.insertRow(r)
            model = d.get("model") or "جهاز Android"
            state = d.get("state") or "unknown"
            conn = ("جاهز" if d.get("ready")
                    else ("فعّل تصحيح الأخطاء (USB debugging)" if state == "unauthorized"
                          else "غير جاهز / دون اتصال"))
            reg = "مسجّل" if d.get("registered") else "غير مسجّل"
            items = [QTableWidgetItem(model), QTableWidgetItem(d.get("serial") or ""),
                     QTableWidgetItem(state), QTableWidgetItem(conn),
                     QTableWidgetItem(reg)]
            items[0].setData(Qt.UserRole, d.get("serial") or "")
            if d.get("ready"):
                items[3].setForeground(QColor("#1d8a4c"))
                if not d.get("registered"):
                    items[4].setForeground(QColor("#c07a00"))
            elif state == "unauthorized":
                items[3].setForeground(QColor("#c07a00"))
            else:
                items[3].setForeground(QColor("#c0392b"))
            for c, it in enumerate(items):
                self._detect_table.setItem(r, c, it)
        fresh = [d for d in detected if not d["registered"]]
        if fresh:
            self._detect_lbl.show()
            any_ready = any(d["ready"] and not d["registered"] for d in detected)
            self._detect_lbl.setStyleSheet(
                "color:#1d8a4c; font-weight:600;" if any_ready
                else "color:#c07a00; font-weight:600;")
            parts = []
            for d in detected:
                label = d["model"] or d["serial"]
                if d["registered"]:
                    parts.append(f"{label} (مسجَّل)")
                elif d["ready"]:
                    parts.append(f"{label} — جاهز للتسجيل")
                else:
                    parts.append(f"{label} — فعِّل تصحيح الأخطاء (USB debugging)")
            self._detect_lbl.setText(
                "وُجد جهاز/أجهزة متصلة: " + " · ".join(parts) +
                ". اختر واحدًا واضغط «فتح الجهاز» لتسجيله وتحديده.")
            field = next((d["serial"] for d in detected
                          if d["ready"] and not d["registered"]), None)
            if field and self._dev_serial.text().strip() == "":
                self._dev_serial.setText(field)
        else:
            self._detect_lbl.hide()

    def _h_enroll(self, res, err):
        if err:
            self._dev_log.setPlainText(self._fmt_json(res))
            self._quick_status.setText("فشل تسجيل الجهاز")
            return
        self._dev_log.setPlainText(self._fmt_json(res))
        self._quick_status.setText("تم تسجيل الجهاز")
        self._task("devices", self._snapshot)

    def _h_open_device(self, res, err):
        if err or not (res or {}).get("ok"):
            self._dev_log.setPlainText(self._fmt_json(res or {}))
            self._quick_status.setText("تعذّر تسجيل/فتح الجهاز")
            return
        self._dev_log.setPlainText(self._fmt_json(res))
        info = res.get("device") or {}
        did = info.get("device_id", "")
        serial = info.get("serial", "")
        if did and self._set_active(device_id=did):
            self._quick_status.setText(f"تم فتح الجهاز {did}")
        elif serial and self._set_active(serial=serial):
            self._quick_status.setText("تم فتح الجهاز")
        else:
            self._quick_status.setText("تم تسجيل الجهاز — اختره من القائمة")
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
            self._pols_cache = res
            self._pols_loaded = True
            self._populate_combos(getattr(self, "_dev_cache", []) or [])
            just = getattr(self, "_just_created_policy_id", None)
            if just:
                self._just_created_policy_id = None
                for i in range(self._apply_pol.count()):
                    if (self._apply_pol.itemText(i) or "").startswith(f"{just} "):
                        self._apply_pol.setCurrentIndex(i)
                        self._render_apply_preview()
                        break

    def _h_preview(self, res, err):
        self._render_preview(res if isinstance(res, dict) else {})

    def _h_apply(self, res, err):
        self._busy_start("")
        self._lock_sensitive(False)
        self._last_apply = res
        self._apply_log.setPlainText(self._fmt_json(res))
        if isinstance(res, dict) and res.get("ok"):
            self._quick_status.setText("اكتمل التطبيق — تحقق فعليًا")
            self._render_verify(res)
            verdict = str(res.get("verification") or "")
            self._set_flow("التطبيق ✓ — التحقق: "
                           + VERDICT_AR.get(verdict, verdict or "غير معروف"))
            self._task("devices", self._snapshot)
        else:
            err_text = str((res or {}).get("error", "فشل التطبيق"))
            self._quick_status.setText(err_text[:90])
            self._set_flow("التطبيق: فشل — " + err_text[:80])

    def _render_verify(self, res):
        """بنية واضحة لنتيجة آخر تطبيق/تحقق (صفحة التحقق)."""
        if getattr(self, "_verify_table", None) is None:
            return
        verdict = str(res.get("verification") or "")
        compliance = str(res.get("compliance") or "")
        rows = [
            ("الجهاز", tx(res, "device_id")),
            ("السياسة", tx(res, "policy_id")),
            ("المرحلة", tx(res, "stage")),
            ("مصدر الأدلة", tx(res, "source")),
            ("نتيجة التحقق", VERDICT_AR.get(verdict, verdict or "غير معروف")),
            ("حالة الالتزام", COMPLIANCE_AR.get(compliance, compliance or "غير معروف")),
            ("رقم الدليل (evidence_id)", tx(res, "evidence_id") or "—"),
            ("رقم التدقيق (audit_id)", tx(res, "audit_id") or "—"),
            ("نزاهة النتيجة", "نعم — مبنية على قراءة فعلية" if res.get("honest") else "لا"),
            ("عدد الملاحظات المرصودة", str(len(res.get("observations") or {}))),
            ("حالة محول الشركة", str(res.get("vendor_adapter_status") or "—")),
        ]
        self._verify_table.setRowCount(0)
        for name, val in rows:
            r = self._verify_table.rowCount()
            self._verify_table.insertRow(r)
            self._verify_table.setItem(r, 0, QTableWidgetItem(name))
            it = QTableWidgetItem(val)
            if name == "نتيجة التحقق":
                it.setForeground(self._status_color(val))
            self._verify_table.setItem(r, 1, it)

    def _h_recover(self, res, err):
        self._busy_start("")
        self._lock_sensitive(False)
        self._last_recover = res if isinstance(res, dict) else {}
        self._rec_log.setPlainText(self._fmt_json(res))
        self._quick_status.setText("نتيجة الاسترداد معروضة")
        if isinstance(res, dict):
            self._set_flow("استرداد: " + REC_STATUS_AR.get(res.get("status", ""),
                                                           res.get("status", "")))
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
        try:
            detected = self.ctl.detected()
        except Exception:
            detected = []
        return {"devices": self.ctl.devices(), "adb": self.ctl.adb_status(),
                "detected": detected}

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
        unknown = sum(1 for d in devices
                      if tx(d, "compliance_state") in ("UNKNOWN", ""))
        unknown_vendor = 0
        for d in devices:
            try:
                dc = classify_device(
                    tx(d, "manufacturer"), tx(d, "model"),
                    int(float(tx(d, "android_version") or 0) or 0), 0,
                    tx(d, "build_fingerprint"))
                if dc.reference_tier == "UNKNOWN":
                    unknown_vendor += 1
            except Exception:  # noqa: BLE001 — classification must never break UI
                pass
        scanned = {tx(d, "serial") for d in devices
                   if tx(d, "last_verification_at")}
        unscanned = sum(1 for d in devices
                        if tx(d, "serial") not in scanned)
        for card, val in ((self._card_attached[1], len(attached)),
                          (self._card_locked[1], locked),
                          (self._card_ok[1], ok),
                          (self._card_need[1], need),
                          (self._card_unknown[1], unknown),
                          (self._card_unscanned[1], unscanned),
                          (self._card_adb[1], f"{len(attached)} متصل")):
            card.setText(str(val))
        last_bits = []
        if self._last_apply is not None:
            la = self._last_apply
            if la.get("ok"):
                last_bits.append(
                    f"آخر تطبيق: {tx(la, 'policy_id')} — {VERDICT_AR.get(str(la.get('verification') or ''), la.get('verification'))}")
            else:
                last_bits.append(f"آخر تطبيق: فشل — {str(la.get('error', ''))[:60]}")
        if self._last_recover is not None:
            lr = self._last_recover
            last_bits.append(f"آخر استرداد: {REC_STATUS_AR.get(str(lr.get('status') or ''), lr.get('status') or '—')}")
        if not last_bits:
            last_bits.append("لا توجد عمليات تطبيق/استرداد بعد في هذه الجلسة")
        if unknown_vendor:
            last_bits.append(f"شركات/طرز غير معروفة التصنيف: {unknown_vendor}")
        self._card_lastop[1].setText("—" if not last_bits else last_bits[0])
        self._dash_status.setText(" · ".join(last_bits))

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
        target = (self._active or {}).get("device_id")
        if target and target in ids:
            self._apply_dev.setCurrentIndex(self._apply_dev.findData(target))
        elif cur and cur in ids:
            self._apply_dev.setCurrentIndex(self._apply_dev.findData(cur))
        elif ids:
            self._apply_dev.setCurrentIndex(0)

        self._rec_dev.blockSignals(True)
        self._rec_dev.clear()
        for d in devices:
            self._rec_dev.addItem(tx(d, "device_id"), tx(d, "device_id"))
        self._rec_dev.blockSignals(False)
        if target and self._rec_dev.findData(target) >= 0:
            self._rec_dev.setCurrentIndex(self._rec_dev.findData(target))

        self._pin_dev.blockSignals(True)
        self._pin_dev.clear()
        for d in devices:
            self._pin_dev.addItem(
                f"{tx(d, 'device_id')} [{tx(d, 'serial')}]", tx(d, "device_id"))
        self._pin_dev.blockSignals(False)
        if target and self._pin_dev.findData(target) >= 0:
            self._pin_dev.setCurrentIndex(self._pin_dev.findData(target))

        for cb in (self._apply_dev, self._rec_dev, self._pin_dev):
            if cb.count() and cb.currentData() is None:
                cb.setCurrentIndex(0)

        pols = getattr(self, "_pols_cache", None)
        if not pols:
            try:
                pols = self.ctl.policies()
                self._pols_cache = pols
                self._pols_loaded = True
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
        self._apply_rec_refresh()
        self._rec_rec_refresh()

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
                 f"تصحيح الأمان (Security Patch): {identity.get('security_patch') or '؟'}",
                 f"نواة النظام (Kernel): {identity.get('kernel_version') or '؟'}",
                 f"محمل الإقلاع (Bootloader): {identity.get('bootloader') or '؟'}",
                 f"التحقق من التمهيد (Verified Boot): {identity.get('verified_boot') or '؟'}",
                 f"تشفير الجهاز: {identity.get('encryption') or '؟'}",
                 f"النطاق الأساسي (Baseband): {identity.get('baseband') or '؟'}",
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
#active_device { background: #e8f4ec; color: #14532d; border: 1px solid #bfe3cb;
                 border-radius: 12px; padding: 3px 10px; font-weight: 600; }
#detect_summary { padding: 4px 8px; }
#flow { color: #2f6fed; font-weight: 600; padding: 4px 2px; }
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
    from . import logger
    logger.log_event("app", "start", version=__version__)
    app = None
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        app.setStyleSheet(STYLE)
        win = App()
        win.show()
        win._task("policies", lambda: win.ctl.policies())
        win._task("reports", win.ctl.reports_list, "")
        win._render_settings()
        win._task("audit", win.ctl.audit, 80)
        rc = app.exec()
        logger.log_event("app", "exit")
        return rc
    except BaseException as ex:  # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        logger.log_error("app", ex, "startup-crash")
        logger.log_startup_error(ex, tb)
        try:
            if app is None or not app.thread().isRunning():
                app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None, "خطأ عند بدء التشغيل",
                "تعذّر بدء المنصة.\n\n"
                f"{type(ex).__name__}: {ex}\n\n"
                "التفاصيل الكاملة محفوظة في:\n" + logger.log_dir())
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())