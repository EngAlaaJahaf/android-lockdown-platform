-- Migration 015: Authentic ManageEngine MDM Device Inventory & Telemetry Persistence
-- Reference: docs/reference/memdm/memdm-schema.sql (mddeviceinfo, mdnetworkinfo)

CREATE TABLE IF NOT EXISTS mddeviceinfo (
    resource_id                 INTEGER PRIMARY KEY,
    device_id                   TEXT NOT NULL UNIQUE,
    serial_number               TEXT,
    model_name                  TEXT,
    product_name                TEXT,
    manufacturer                TEXT,
    os_name                     TEXT DEFAULT 'Android',
    os_version                  TEXT,
    build_version               TEXT,
    security_patch_version      TEXT,
    kernel_version              TEXT,
    bootloader_version          TEXT,
    baseband_version            TEXT,
    battery_level               TEXT,
    battery_health              TEXT DEFAULT 'Good',
    cellular_technology         TEXT DEFAULT 'Wi-Fi only',
    imei                        TEXT,
    meid                        TEXT,
    udid                        TEXT,
    device_capacity             REAL DEFAULT 0,
    available_device_capacity   REAL DEFAULT 0,
    used_device_space           REAL DEFAULT 0,
    total_ram_memory            REAL DEFAULT 0,
    available_ram_memory        REAL DEFAULT 0,
    processor_type              TEXT,
    processor_name              TEXT,
    processor_speed             TEXT,
    processor_architecture      TEXT,
    processor_core_count        INTEGER DEFAULT 8,
    eas_device_identifier       TEXT,
    device_type                 TEXT DEFAULT 'SmartPhone',
    is_supervised               INTEGER DEFAULT 1,
    is_profileowner             INTEGER DEFAULT 0,
    is_rooted                   TEXT DEFAULT 'No',
    is_device_locator_enabled   INTEGER DEFAULT 0,
    is_cloud_backup_enabled     INTEGER DEFAULT 0,
    is_activation_lock_enabled  INTEGER DEFAULT 1,
    encryption_status           TEXT DEFAULT 'Encrypted',
    passcode_status             TEXT DEFAULT 'Configured',
    google_play_service_id      TEXT,
    db_updated_time             TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mddevinfo_did ON mddeviceinfo(device_id);

CREATE TABLE IF NOT EXISTS mdnetworkinfo (
    resource_id                 INTEGER PRIMARY KEY,
    device_id                   TEXT NOT NULL UNIQUE,
    wifi_mac                    TEXT,
    wifi_ip                     TEXT,
    wifi_ssid                   TEXT,
    bluetooth_mac               TEXT,
    ethernet_macs               TEXT,
    ethernet_ip                 TEXT,
    phone_number                TEXT,
    imsi                        TEXT,
    iccid                       TEXT,
    current_carrier_network     TEXT,
    subscriber_carrier_network  TEXT,
    carrier_setting_version     TEXT,
    voice_roaming_enabled       INTEGER DEFAULT 0,
    data_roaming_enabled        INTEGER DEFAULT 0,
    is_personal_hotspot_enabled INTEGER DEFAULT 0,
    db_updated_time             TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mdnetinfo_did ON mdnetworkinfo(device_id);

CREATE TABLE IF NOT EXISTS mddeviceinstalledapps (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id                   TEXT NOT NULL,
    app_name                    TEXT NOT NULL,
    package_name                TEXT NOT NULL,
    version_name                TEXT,
    version_code                INTEGER DEFAULT 1,
    app_type                    TEXT DEFAULT 'Third-Party App',
    status                      TEXT DEFAULT 'Installed',
    installed_size              INTEGER DEFAULT 0,
    updated_at                  TEXT DEFAULT (datetime('now')),
    UNIQUE(device_id, package_name)
);
CREATE INDEX IF NOT EXISTS idx_inst_apps_dev ON mddeviceinstalledapps(device_id);
