/**
 * ALP Internationalization & Localization Engine (alp-i18n.js)
 * Supports Arabic (RTL) & English (LTR) seamlessly.
 * Zero-dependency, offline-ready, instant reactive switching.
 */
(function (window) {
  'use strict';

  const STORAGE_KEY = 'alp_lang';
  const DEFAULT_LANG = 'en';

  const TRANSLATIONS = {
    en: {
      lang_name: "English",
      switch_to_lang: "العربية",
      nav: {
        home: "Home",
        device_mgmt: "Device Mgmt",
        inventory: "Inventory",
        enrollment: "Enrollment",
        reports: "Reports",
        admin: "Admin",
        support: "Support",
        branding: "Branding",
        manage: "Manage",
        groups_devices: "Groups & Devices",
        profiles: "Profiles",
        telecom_mgmt: "Telecom Expense Mgmt",
        certificates: "Certificates",
        alerts: "Alerts",
        content_mgmt: "Content Management",
        automate_updates: "Automate OS Updates",
        apps: "Apps",
        app_repository: "App Repository",
        app_update_policy: "App Update Policy",
        tools: "Tools",
        announcements: "Announcements",
        remote_control: "Remote Control",
        conditional_access: "Conditional Access",
        office_365: "Office 365",
        office_365_mam: "Office 365 MAM policy",
        geofencing: "Geofencing",
        fence_policy: "Fence Policy",
        fence_repo: "Fence Repository",
        quick_actions: "Quick Actions",
        need_features: "Need new features?",
        view_roadmap: "View Roadmap",
        roadmap_share_idea: "Share a new idea or prioritize your requirement in our roadmap",
        trial_banner: "Your Trial expires in 28 days.",
        license: "License",
        get_quote: "Get Quote",
        build_version: "Build Version",
        sign_out: "Sign Out",
        personalize: "Personalize",
        active_sessions: "Active Session(s)"
      },
      common: {
        actions: "Actions",
        save: "Save",
        cancel: "Cancel",
        delete: "Delete",
        edit: "Edit",
        modify: "Modify",
        close: "Close",
        search: "Search...",
        refresh: "Refresh",
        status: "Status",
        loading: "Hold on! Loading...",
        success: "Success",
        error: "Error",
        confirm: "Confirm",
        enabled: "Enabled",
        disabled: "Disabled",
        yes: "Yes",
        no: "No",
        offline: "Offline",
        online: "Online",
        active: "Active",
        inactive: "Inactive",
        looking_manage_calls: "Looking to manage calls?",
        devices: "Devices"
      },
      device_header: {
        platform: "Platform",
        os_version: "OS Version",
        rooted_device: "Rooted Device",
        last_scan_time: "Last Scan Time",
        next_contact_time: "Next Contact Time",
        device_model: "Device Model",
        username: "Username"
      },
      tabs: {
        summary: "Summary",
        device: "Device",
        installed_apps: "Installed Apps",
        certificates: "Certificates",
        restrictions: "Restrictions",
        alerts: "Alerts",
        geo_tracking: "Geo-Tracking",
        audit_logs: "Audit Logs"
      },
      device_subtabs: {
        device_info: "Device information",
        network_info: "Network Information",
        sim_info: "SIM Information",
        additional_info: "Additional Information"
      },
      actions_menu: {
        scan_now: "Scan Now",
        remote_lock: "Remote Lock",
        remote_control: "Remote Control",
        remote_alarm: "Remote Alarm",
        clear_passcode: "Clear Passcode",
        reset_passcode: "Reset Passcode",
        locate_device: "Locate device",
        enable_lost_mode: "Enable Lost Mode",
        restart_device: "Restart Device",
        pause_kiosk: "Pause Kiosk",
        request_bug_report: "Request Bug Report",
        clear_app_data: "Clear App Data",
        deprovision_wipe: "Deprovision (Wipe)"
      },
      popovers: {
        remote_control_disabled: "Remote Commands disabled through device privacy settings.",
        geo_tracking_disabled: "Geo-Tracking disabled!",
        enable_geo_tracking: "Enable Geo-Tracking to locate the managed devices."
      },
      restrictions: {
        restrictions_on_device: "Restrictions on Device",
        network_and_roaming: "Network and Roaming",
        security: "Security",
        application: "Application",
        camera: "Camera",
        allow_camera_lockscreen: "Allow camera in lock screen",
        video_recording: "Video Recording",
        microphone: "Microphone",
        audio_recording: "Audio Recording",
        firmware_recovery: "Firmware Recovery",
        os_upgrade: "OS upgrade",
        screen_capture: "Screen Capture",
        smart_clip_mode: "Smart Clip Mode",
        s_voice: "S Voice",
        add_accounts: "Add accounts",
        airplane_mode: "Airplane Mode",
        background_data: "Background data",
        wifi: "Wi-Fi",
        wifi_direct: "Wi-Fi Direct",
        connect_wifi_mdm_only: "Connect to Wi-Fi, only if distributed via MDM",
        vpn: "VPN",
        roaming_data: "Roaming data",
        sync_data_roaming: "Sync data while roaming",
        roaming_push: "Roaming push",
        voice_call_roaming: "Voice call while roaming",
        restore_factory_settings: "Restore Factory Settings",
        approved_apps_only: "Users can install only approved apps",
        nfc_bluetooth: "NFC and Bluetooth",
        sync_storage: "Sync and Storage",
        browser_restriction: "Browser Restriction",
        phone: "Phone",
        location_services: "Location services",
        tethering: "Tethering",
        miscellaneous: "Miscellaneous",
        restricted: "Restricted",
        user_controlled: "User Controlled",
        allowed: "Allowed"
      },
      summary_cards: {
        device_summary: "Device Summary",
        device_type: "Device Type",
        model_name: "Model Name",
        device_name: "Device Name",
        udid: "UDID",
        serial_number: "Serial Number",
        managed_status: "Managed Status",
        free_storage: "Free Storage Space",
        free_ram: "Free RAM",
        battery_level: "Battery Level",
        device_status: "Device Status",
        total_storage: "Total Storage",
        used_storage: "Used Storage"
      },
      tables: {
        device_id: "Device ID",
        serial: "Serial Number",
        model: "Device Model",
        username: "Assigned User",
        agent_status: "Agent Status",
        compliance: "Policy Compliance",
        total_items: "Total items",
        no_records: "No records found matching criteria"
      }
    },
    ar: {
      lang_name: "العربية",
      switch_to_lang: "English",
      nav: {
        home: "الرئيسية",
        device_mgmt: "إدارة الأجهزة",
        inventory: "المخزون والعتاد",
        enrollment: "تسجيل الأجهزة",
        reports: "التقارير",
        admin: "الإدارة",
        support: "الدعم الفني",
        branding: "العلامة التجارية",
        manage: "الإدارة والتحكم",
        groups_devices: "المجموعات والأجهزة",
        profiles: "ملفات التعريف (السياسات)",
        telecom_mgmt: "إدارة نفقات الاتصالات",
        certificates: "الشهادات الرقمية",
        alerts: "التنبيهات",
        content_mgmt: "إدارة المحتوى",
        automate_updates: "أتمتة تحديثات النظام",
        apps: "التطبيقات",
        app_repository: "مستودع التطبيقات",
        app_update_policy: "سياسة تحديث التطبيقات",
        tools: "الأدوات المساعدة",
        announcements: "التعميمات والإعلانات",
        remote_control: "التحكم عن بُعد",
        conditional_access: "الوصول المشروط",
        office_365: "مايكروسوفت Office 365",
        office_365_mam: "سياسة MAM لـ Office 365",
        geofencing: "السياج الجغرافي",
        fence_policy: "سياسات السياج",
        fence_repo: "مستودع المناطق الجغرافية",
        quick_actions: "إجراءات سريعة",
        need_features: "هل تحتاج ميزات جديدة؟",
        view_roadmap: "عرض خارطة الطريق",
        roadmap_share_idea: "شاركنا فكرة جديدة أو حدد أولويات متطلباتك في خارطة التطوير",
        trial_banner: "تنتهي الفترة التجريبية خلال 28 يوماً.",
        license: "الترخيص",
        get_quote: "طلب عرض أسعار",
        build_version: "إصدار البناء",
        sign_out: "تسجيل الخروج",
        personalize: "تخصيص",
        active_sessions: "الجلسات النشطة"
      },
      common: {
        actions: "الإجراءات",
        save: "حفظ",
        cancel: "إلغاء",
        delete: "حذف",
        edit: "تعديل",
        modify: "تعديل",
        close: "إغلاق",
        search: "بحث في السجلات...",
        refresh: "تحديث",
        status: "الحالة",
        loading: "جارٍ التحميل والتحديث...",
        success: "تمت العملية بنجاح",
        error: "حدث خطأ",
        confirm: "تأكيد الإجراء",
        enabled: "مفعل",
        disabled: "معطل",
        yes: "نعم",
        no: "لا",
        offline: "غير متصل",
        online: "متصل نشط",
        active: "نشط",
        inactive: "غير نشط",
        looking_manage_calls: "هل تبحث عن إدارة المكالمات؟",
        devices: "الأجهزة"
      },
      device_header: {
        platform: "نظام التشغيل",
        os_version: "إصدار النظام",
        rooted_device: "جهاز مكسور الحماية (Root)",
        last_scan_time: "وقت آخر فحص",
        next_contact_time: "وقت الاتصال القادم",
        device_model: "طراز الجهاز",
        username: "اسم المستخدم"
      },
      tabs: {
        summary: "الملخص",
        device: "مواصفات الجهاز",
        installed_apps: "التطبيقات المثبتة",
        certificates: "الشهادات الرقمية",
        restrictions: "القيود على الجهاز",
        alerts: "التنبيهات",
        geo_tracking: "التتبع الجغرافي",
        audit_logs: "سجلات التدقيق"
      },
      device_subtabs: {
        device_info: "معلومات الجهاز الأساسية",
        network_info: "معلومات الشبكة والاتصال",
        sim_info: "معلومات شريحة الاتصال (SIM)",
        additional_info: "معلومات ومواصفات إضافية"
      },
      actions_menu: {
        scan_now: "فحص ومزامنة الآن",
        remote_lock: "قفل الجهاز عن بُعد",
        remote_control: "التحكم بالجهاز عن بُعد",
        remote_alarm: "تشغيل إنذار صوتي",
        clear_passcode: "إزالة رمز القفل",
        reset_passcode: "إعادة تعيين رمز القفل",
        locate_device: "تحديد موقع الجهاز",
        enable_lost_mode: "تفعيل نمط الفقدان",
        restart_device: "إعادة تشغيل الجهاز",
        pause_kiosk: "إيقاف وضع الكشك مؤقتاً",
        request_bug_report: "طلب تقرير الأخطاء",
        clear_app_data: "مسح بيانات التطبيقات",
        deprovision_wipe: "تهيئة وحذف الجهاز بالكامل (Wipe)"
      },
      popovers: {
        remote_control_disabled: "أوامر التحكم عن بُعد معطلة من خلال إعدادات خصوصية الجهاز.",
        geo_tracking_disabled: "التتبع الجغرافي معطل حالياً!",
        enable_geo_tracking: "قم بتفعيل التتبع الجغرافي لتحديد مواقع الأجهزة المدارة."
      },
      restrictions: {
        restrictions_on_device: "القيود المطبقة على الجهاز",
        network_and_roaming: "إعدادات الشبكة والتجوال",
        security: "الأمان والحماية",
        application: "سياسات التطبيقات",
        camera: "استخدام الكاميرا",
        allow_camera_lockscreen: "السماح بالكاميرا في شاشة القفل",
        video_recording: "تسجيل الفيديو",
        microphone: "استخدام الميكروفون",
        audio_recording: "التسجيل الصوتي",
        firmware_recovery: "استعادة النظام الثابت (Firmware)",
        os_upgrade: "ترقية وتحديث نظام التشغيل",
        screen_capture: "التقاط صور الشاشة (Screenshot)",
        smart_clip_mode: "نمط القص الذكي (Smart Clip)",
        s_voice: "المساعد الصوتي (S Voice)",
        add_accounts: "إضافة حسابات مستخدمين جديدة",
        airplane_mode: "تشغيل نمط الطيران",
        background_data: "استهلاك بيانات الخلفية",
        wifi: "الاتصال بالواي فاي (Wi-Fi)",
        wifi_direct: "الاتصال المباشر (Wi-Fi Direct)",
        connect_wifi_mdm_only: "الاتصال فقط بشبكات Wi-Fi الموزعة من الإدارة",
        vpn: "استخدام الشبكات الافتراضية (VPN)",
        roaming_data: "استخدام البيانات أثناء التجوال",
        sync_data_roaming: "مزامنة البيانات أثناء التجوال",
        roaming_push: "إشعارات الدفع أثناء التجوال",
        voice_call_roaming: "إجراء المكالمات الصوتية أثناء التجوال",
        restore_factory_settings: "استعادة ضبط المصنع الافتراضي",
        approved_apps_only: "السماح بتثبيت التطبيقات المعتمدة فقط",
        nfc_bluetooth: "اتصال NFC والبلوتوث",
        sync_storage: "المزامنة والتخزين",
        browser_restriction: "قيود المتصفح",
        phone: "الهاتف والمكالمات",
        location_services: "خدمات تحديد الموقع",
        tethering: "نقطة الاتصال ومشاركة الإنترنت",
        miscellaneous: "قيود وإعدادات متنوعة",
        restricted: "مقيد (ممنوع)",
        user_controlled: "تحكم المستخدم",
        allowed: "مسموح"
      },
      summary_cards: {
        device_summary: "ملخص الجهاز",
        device_type: "نوع الجهاز",
        model_name: "اسم الطراز",
        device_name: "اسم الجهاز",
        udid: "معرف UDID",
        serial_number: "الرقم التسلسلي",
        managed_status: "حالة الإدارة",
        free_storage: "المساحة التخزينية المتاحة",
        free_ram: "الذاكرة العشوائية (RAM) المتاحة",
        battery_level: "مستوى شحن البطارية",
        device_status: "حالة تشغيل الجهاز",
        total_storage: "إجمالي السعة",
        used_storage: "المساحة المستخدمة"
      },
      tables: {
        device_id: "معرف الجهاز",
        serial: "الرقم التسلسلي",
        model: "طراز الجهاز",
        username: "المستخدم المعين",
        agent_status: "حالة العميل",
        compliance: "الامتثال للسياسات",
        total_items: "إجمالي السجلات",
        no_records: "لا توجد سجلات مطابقة للبحث"
      }
    }
  };

  let currentLang = DEFAULT_LANG;

  // 1. Initialize language from localStorage or default
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && (saved === 'ar' || saved === 'en')) {
      currentLang = saved;
    }
  } catch (e) {}

  function getLang() {
    return currentLang;
  }

  function isRTL() {
    return currentLang === 'ar';
  }

  /**
   * Translate a dotted key (e.g. 'nav.home', 'actions_menu.scan_now')
   */
  function t(key, fallback = '') {
    if (!key) return fallback;
    const parts = key.split('.');
    let cur = TRANSLATIONS[currentLang] || TRANSLATIONS.en;
    for (let i = 0; i < parts.length; i++) {
      if (cur && cur[parts[i]] !== undefined) {
        cur = cur[parts[i]];
      } else {
        // Fallback to English if key missing in current language
        let fb = TRANSLATIONS.en;
        for (let j = 0; j < parts.length; j++) {
          if (fb && fb[parts[j]] !== undefined) fb = fb[parts[j]];
          else return fallback || key;
        }
        return fb || fallback || key;
      }
    }
    return cur !== undefined ? cur : (fallback || key);
  }

  /**
   * Comprehensive mapping for headings, field names, and matrix cells (EN -> AR)
   */
  const LABELS_MAP = {
    // Headings (21)
    "Additional Information": "معلومات إضافية",
    "Application": "التطبيقات",
    "Browser Restriction": "قيود المتصفح",
    "Device Access Recovery Key": "مفتاح استرداد الوصول للجهاز",
    "Device Security": "أمان الجهاز",
    "Device Summary": "ملخص الجهاز",
    "Device information": "معلومات الجهاز",
    "Location services": "خدمات الموقع الجغرافي",
    "Miscellaneous": "قيود وإعدادات متنوعة",
    "NFC and Bluetooth": "الاتصال بالحقل القريب والبلوتوث (NFC & Bluetooth)",
    "Network Information": "معلومات الشبكة",
    "Network Summary": "ملخص الشبكة",
    "Network and Roaming": "إعدادات الشبكة والتجوال",
    "OS Summary": "ملخص نظام التشغيل",
    "Phone": "الهاتف والاتصالات",
    "Primary SIM Information": "معلومات شريحة الاتصال الأساسية",
    "Restrictions on Device": "القيود المطبقة على الجهاز",
    "SIM Information": "معلومات شريحة الاتصال",
    "Security": "الأمان والحماية",
    "Sync and Storage": "المزامنة ووحدة التخزين",
    "Tethering": "مشاركة الإنترنت ونقطة الاتصال (Tethering)",

    // Field labels (111 unique items)
    "Add accounts": "إضافة حسابات",
    "Air command": "الأمر الجوي (Air Command)",
    "Air view": "العرض الجوي (Air View)",
    "Airplane Mode": "نمط الطيران (Airplane Mode)",
    "Allow access to all apps in Managed Google Play": "السماح بالوصول لجميع التطبيقات في Google Play المُدار",
    "Allow camera in lock screen": "السماح بالكاميرا في شاشة القفل",
    "Android Beam": "مشاركة Android Beam",
    "Android Browser": "متصفح أندرويد",
    "Application Notification Mode": "وضع إشعارات التطبيقات",
    "Audio Recording": "التسجيل الصوتي",
    "Auto-sync Google accounts": "المزامنة التلقائية لحسابات Google",
    "Autofill": "الإكمال التلقائي",
    "Background data": "بيانات الخلفية",
    "Bluetooth": "البلوتوث (Bluetooth)",
    "Bluetooth MAC": "عنوان Bluetooth MAC",
    "Bluetooth data transfer": "نقل البيانات عبر البلوتوث",
    "Bluetooth discovery": "اكتشاف البلوتوث للأجهزة",
    "Bluetooth pairing": "الاقتران بالبلوتوث",
    "Bluetooth tethering": "مشاركة الإنترنت عبر البلوتوث",
    "Build Version": "إصدار البناء",
    "Camera": "استخدام الكاميرا",
    "Clipboard": "الحافظة (Clipboard)",
    "Clipboard Share": "مشاركة الحافظة",
    "Connect a USB storage device": "توصيل وحدة تخزين USB",
    "Connect to Wi-Fi, only if distributed via MDM": "الاتصال بالواي فاي فقط عبر شبكات MDM المعتمدة",
    "Connect to laptop/desktop via Bluetooth": "الاتصال بالحاسوب عبر البلوتوث",
    "Connections using USB": "الاتصال عبر منفذ USB",
    "Cookies": "ملفات تعريف الارتباط (Cookies)",
    "Developer Mode": "وضع المطورين (Developer Mode)",
    "Device Administrator": "مسؤول الجهاز (Device Admin)",
    "Device Manufacturer": "الشركة المصنعة",
    "Device Model": "طراز الجهاز",
    "Device Name": "اسم الجهاز",
    "Device Type": "نوع الجهاز",
    "Enforce SD Card encryption": "فرض تشفير بطاقة الذاكرة SD",
    "Enterprise Factory Reset Protection": "حماية إعادة ضبط المصنع للمؤسسات (FRP)",
    "Firmware Recovery": "استعادة النظام الثابت (Firmware Recovery)",
    "Fraud warning setting": "التحذير من المواقع الاحتيالية",
    "GPS": "نظام تحديد المواقع (GPS)",
    "Geo Fence": "السياج الجغرافي",
    "Global App Permission Policy": "سياسة أذونات التطبيقات الشاملة",
    "Google Maps": "خرائط Google",
    "Google Play Protect": "حماية Google Play Protect",
    "Google Voice search": "البحث الصوتي من Google",
    "IMEI Number": "رقم IMEI",
    "Incoming MMS": "رسائل الوسائط الواردة (MMS)",
    "Incoming SMS": "الرسائل النصية القصيرة الواردة (SMS)",
    "Incoming calls": "المكالمات الواردة",
    "Installing non-Market apps": "تثبيت التطبيقات من خارج المتجر (مصادر غير معروفة)",
    "JavaScript": "تشغيل جافاسكريبت (JavaScript)",
    "Last Security Update": "آخر تحديث أمني",
    "Last Updated": "آخر تحديث",
    "Lock Screen Notification Preference": "تفضيلات إشعارات شاشة القفل",
    "Make outgoing calls using Bluetooth": "إجراء مكالمات صادرة عبر البلوتوث",
    "Management Type": "نوع الإدارة",
    "Microphone": "استخدام الميكروفون",
    "Mock locations": "المواقع الوهمية (Mock Locations)",
    "Modify date/time": "تعديل التاريخ والوقت",
    "Modify default device settings": "تعديل إعدادات الجهاز الافتراضية",
    "Move apps to SD Card": "نقل التطبيقات إلى بطاقة الذاكرة SD",
    "NFC": "الاتصال بالحقل القريب (NFC)",
    "OS": "نظام التشغيل",
    "OS Version": "إصدار نظام التشغيل",
    "OS upgrade": "ترقية وتحديث نظام التشغيل",
    "Outgoing MMS": "رسائل الوسائط الصادرة (MMS)",
    "Outgoing SMS": "الرسائل النصية القصيرة الصادرة (SMS)",
    "Outgoing calls": "المكالمات الصادرة",
    "Passcode Compliant with Profiles": "رمز المرور متوافق مع السياسات",
    "Passcode Enabled": "رمز المرور مفعّل",
    "Phone Number": "رقم الهاتف",
    "Pop-ups": "النوافذ المنبثقة",
    "Product Name": "اسم المنتج",
    "Recovery Key": "مفتاح الاسترداد",
    "Report crash to Google": "إرسال تقارير الأعطال إلى Google",
    "Restore Factory Settings": "استعادة إعدادات المصنع",
    "Roaming Enabled": "التجوال مفعّل",
    "Roaming data": "بيانات التجوال",
    "Roaming push": "الإشعارات الفورية أثناء التجوال",
    "Rooted Device": "جهاز مكسور الحماية (Rooted)",
    "S Beam": "ميزة S Beam",
    "S Voice": "المساعد الصوتي S Voice",
    "SD Card": "بطاقة الذاكرة الخارجية (SD Card)",
    "Safe Mode": "الوضع الآمن (Safe Mode)",
    "Screen Capture": "التقاط صور الشاشة (Screenshot)",
    "Serial Number": "الرقم التسلسلي (Serial Number)",
    "Set device time": "ضبط وقت الجهاز",
    "Share List": "قائمة المشاركة",
    "Shared Device": "جهاز مشترك",
    "Slot": "منفذ الشريحة",
    "Smart Clip Mode": "نمط القص الذكي (Smart Clip)",
    "Smart Lock": "القفل الذكي (Smart Lock)",
    "Stop system apps": "إيقاف تطبيقات النظام",
    "Storage Encryption": "تشفير وحدة التخزين",
    "Store data in SD Card": "تخزين البيانات في بطاقة SD",
    "Subscriber Carrier Network": "شبكة مزود الخدمة",
    "Sync data while roaming": "مزامنة البيانات أثناء التجوال",
    "Terminate app on exiting": "إنهاء التطبيق عند الخروج",
    "Turn Off the device using Power Button": "إيقاف تشغيل الجهاز بزر الطاقة",
    "UDID": "المعرّف الفريد للجهاز (UDID)",
    "USB": "منفذ USB",
    "USB tethering": "مشاركة الإنترنت عبر كابل USB",
    "Uninstalling apps": "إلغاء تثبيت التطبيقات",
    "Users can install only approved apps": "تثبيت التطبيقات المعتمدة فقط",
    "VPN": "الشبكة الافتراضية الخاصة (VPN)",
    "Video Recording": "تسجيل الفيديو",
    "Voice call while roaming": "المكالمات الصوتية أثناء التجوال",
    "Wallpaper Change": "تغيير خلفية الشاشة",
    "Wi-Fi": "الواي فاي (Wi-Fi)",
    "Wi-Fi Direct": "واي فاي مباشر (Wi-Fi Direct)",
    "Wi-Fi MAC": "عنوان Wi-Fi MAC",
    "Wi-Fi tethering": "نقطة اتصال واي فاي المحمولة (Wi-Fi Tethering)"
  };

  /**
   * Apply translations to all DOM elements bearing data-i18n attributes
   */
  function applyTranslations(root = document) {
    if (!root || !root.querySelectorAll) return;

    // 1. Dotted key data-i18n text content
    const textEls = root.querySelectorAll('[data-i18n]');
    textEls.forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (key) {
        const tr = t(key);
        if (tr) {
          if (el.getAttribute('data-i18n-target') === 'prepend') {
            const firstText = Array.from(el.childNodes).find(n => n.nodeType === Node.TEXT_NODE);
            if (firstText) firstText.textContent = tr + ' ';
            else el.prepend(document.createTextNode(tr + ' '));
          } else if (el.children.length === 0) {
            el.textContent = tr;
          } else {
            const textNodes = Array.from(el.childNodes).filter(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length > 0);
            if (textNodes.length > 0) {
              textNodes[0].textContent = ' ' + tr + ' ';
            } else {
              el.prepend(document.createTextNode(tr + ' '));
            }
          }
        }
      }
    });

    // 2. Headings & Field Labels auto-translation (.zebra-table-fieldname, .main-box-fieldName, .main-box-heading)
    const labelSelectors = '.zebra-table-fieldname, .main-box-fieldName, .main-box-heading';
    root.querySelectorAll(labelSelectors).forEach(el => {
      if (el.hasAttribute('data-i18n')) return;

      const textNode = Array.from(el.childNodes).find(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length > 0);
      if (!textNode) return;

      if (!el.hasAttribute('data-orig-en')) {
        el.setAttribute('data-orig-en', textNode.textContent.trim());
      }

      const origEn = el.getAttribute('data-orig-en');
      if (origEn) {
        if (currentLang === 'ar') {
          const arText = LABELS_MAP[origEn];
          if (arText) {
            textNode.textContent = ' ' + arText + ' ';
          }
        } else {
          textNode.textContent = ' ' + origEn + ' ';
        }
      }
    });

    // 3. Titles / Tooltips
    const titleEls = root.querySelectorAll('[data-i18n-title]');
    titleEls.forEach(el => {
      const key = el.getAttribute('data-i18n-title');
      if (key) {
        const tr = t(key);
        if (tr) el.setAttribute('title', tr);
      }
    });

    // 4. Placeholders
    const phEls = root.querySelectorAll('[data-i18n-placeholder]');
    phEls.forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      if (key) {
        const tr = t(key);
        if (tr) el.setAttribute('placeholder', tr);
      }
    });


    // Update switcher button label if present
    const switcherLabel = document.getElementById('alpLangCurrentLabel');
    if (switcherLabel) {
      switcherLabel.textContent = currentLang === 'ar' ? 'English' : 'العربية';
    }
    const switcherBtn = document.getElementById('alpLangToggleBtn');
    if (switcherBtn) {
      switcherBtn.setAttribute('title', currentLang === 'ar' ? 'Switch to English' : 'التحويل إلى اللغة العربية');
    }
  }

  /**
   * Switch the active language and re-orient the document
   */
  function setLanguage(lang) {
    if (lang !== 'ar' && lang !== 'en') lang = DEFAULT_LANG;
    currentLang = lang;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {}

    const htmlEl = document.documentElement;
    const bodyEl = document.body;

    if (lang === 'ar') {
      htmlEl.setAttribute('dir', 'rtl');
      htmlEl.setAttribute('lang', 'ar');
      if (bodyEl) {
        bodyEl.classList.add('alp-rtl');
        bodyEl.classList.remove('alp-ltr');
      }
    } else {
      htmlEl.setAttribute('dir', 'ltr');
      htmlEl.setAttribute('lang', 'en');
      if (bodyEl) {
        bodyEl.classList.add('alp-ltr');
        bodyEl.classList.remove('alp-rtl');
      }
    }

    applyTranslations();

    // Trigger custom event for reactive components (tables, live views)
    window.dispatchEvent(new CustomEvent('alp:lang_changed', { detail: { lang, isRTL: lang === 'ar' } }));

    // Re-align tabs slider if active
    if (typeof window.switchCompTab === 'function' && window.CURRENT_COMP_TAB) {
      setTimeout(function () {
        try { window.switchCompTab(window.CURRENT_COMP_TAB); } catch (e) {}
      }, 50);
    }

    // Re-render active comprehensive device view if open
    if (typeof window.openComprehensiveDeviceDetails === 'function' && window.CURRENT_COMP_DID) {
      const wsComp = document.getElementById('workspaceComprehensiveDeviceDetails');
      if (wsComp && wsComp.style.display !== 'none') {
        window.openComprehensiveDeviceDetails(window.CURRENT_COMP_DID, window.CURRENT_COMP_TAB || 'summary', false, false);
      }
    }

    // Re-render devices table if active
    if (typeof window.populateDevices === 'function') {
      const wsGD = document.getElementById('workspaceGroupsDevices');
      if (wsGD && wsGD.style.display !== 'none') {
        window.populateDevices();
      }
    }
  }

  function toggleLanguage(e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    const nextLang = currentLang === 'ar' ? 'en' : 'ar';
    setLanguage(nextLang);
  }

  // Pre-init: set dir and lang attributes immediately to prevent visual flash
  (function initOnLoad() {
    const htmlEl = document.documentElement;
    if (currentLang === 'ar') {
      htmlEl.setAttribute('dir', 'rtl');
      htmlEl.setAttribute('lang', 'ar');
    } else {
      htmlEl.setAttribute('dir', 'ltr');
      htmlEl.setAttribute('lang', 'en');
    }

    document.addEventListener('DOMContentLoaded', function () {
      setLanguage(currentLang);
    });
  })();

  // Public API
  window.ALP_I18N = {
    getLang,
    isRTL,
    t,
    setLanguage,
    toggleLanguage,
    applyTranslations,
    TRANSLATIONS
  };
  window.t = t;
  window.toggleLanguage = toggleLanguage;

})(window);
