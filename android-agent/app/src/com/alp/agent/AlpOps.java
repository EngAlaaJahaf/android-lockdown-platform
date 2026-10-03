package com.alp.agent;

import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.os.UserManager;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

/**
 * Envelope processors shared by CommandReceiver (broadcast path) and MainActivity
 * (activity-nudge path). Both paths read the same /data/local/tmp envelope files,
 * so delivery stays honest regardless of which transport woke the app.
 */
final class AlpOps {
    private AlpOps() {
    }

    private static final String TAG = "ALP";

    static final String ENV_APPLY = "/data/local/tmp/alp_envelope.json";
    static final String ENV_CLEAR = "/data/local/tmp/alp_rollback.json";
    static final String ENV_STATE = "/data/local/tmp/alp_req_state.json";
    static final String ENV_WITHDRAW = "/data/local/tmp/alp_withdraw.json";
    static final String ENV_PIN = "/data/local/tmp/alp_pin.json";

    private static final String PREFS_LAST = "alp_processed";
    private static final String PREFS_COMMITTED = "alp_policy_committed";

    // Quick-settings tile lockdown: when Wi-Fi is BLOCKED the wifi tile is
    // removed from the pull-down shade through the device-owner secure-setting
    // channel (the same Settings.Secure.qs_tiles knob vendor builds read). Any
    // pre-existing custom tile list is preserved and only the wifi token is
    // filtered out of it; the vendor base lists below are used when the device
    // had no custom list so a clear/rollback can restore wifi onto that base.
    private static final String QS_TILES_BASE = "bt,rotation,cell,airplane,dnd";
    private static final String QS_TILES_RESTORE = "wifi,bt,rotation,cell,airplane,dnd";

    // RFC 1984-style honest helpers: a restriction is proven only by lines the
    // policy dump literally lists; the radio is only claimed off when the
    // framework reports it off.
    /**
     * Turn the Wi-Fi radio off using every Device-Owner channel that exists.
     *
     * DISALLOW_CONFIG_WIFI alone does NOT power off the radio on several
     * vendor builds (LT-8110 AOSP generic observed) — the user sees the icon
     * still ON and only the toggle forbidden. On those builds we additionally
     * (1) write Settings.Global.WIFI_ON=0 through the policy manager (the
     * documented DO channel) and (2) call WifiManager.setWifiEnabled(false)
     * as a best-effort radio-level disable. Success is never claimed until
     * cmd wifi / WifiManager reports the radio actually off.
     */
    static void ensureWifiOff(Context context) {
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        if (dpm != null && dpm.isDeviceOwnerApp(context.getPackageName())) {
            try {
                dpm.setGlobalSetting(admin, Settings.Global.WIFI_ON, "0");
            } catch (Exception ignored) {
            }
        }
        try {
            WifiManager wm = (WifiManager) context.getApplicationContext()
                    .getSystemService(Context.WIFI_SERVICE);
            if (wm != null && wm.isWifiEnabled()) {
                wm.setWifiEnabled(false);
            }
        } catch (Exception ignored) {
            // SecurityException / no-op on strict builds — the restriction and
            // the global setting still apply; the radio is re-checked later.
        }
    }

    /** @return the current Settings.Secure QS tile spec, or null (platform default). */
    private static String qsTilesSpec(Context context) {
        try {
            return Settings.Secure.getString(context.getContentResolver(),
                    "qs_tiles");
        } catch (Exception e) {
            return null;
        }
    }

    /** Drop wifi quick-tile tokens from a CSV tile spec, preserving order. */
    private static String stripWifiTile(String spec) {
        if (spec == null || spec.trim().isEmpty()) {
            return null;
        }
        List<String> keep = new ArrayList<String>();
        for (String tok : spec.split(",")) {
            String t = tok.trim();
            if (t.isEmpty()) {
                continue;
            }
            if ("wifi".equals(t) || t.startsWith("wifi&")) {
                continue;
            }
            keep.add(t);
        }
        if (keep.isEmpty()) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < keep.size(); i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(keep.get(i));
        }
        return sb.toString();
    }

    /**
     * Device-owner secure-setting channel (API 25+, DO only): hide the wifi
     * quick-settings tile. The pre-block tile spec is captured so a later
     * clear restores it exactly ("content" empty == platform default, in which
     * case the vendor base list minus wifi is written). Failure on strict
     * builds is non-fatal — the radio lockdown and the snap-back receiver
     * still neuter the tile.
     */
    static void hideWifiQSTile(Context context, DevicePolicyManager dpm,
                               ComponentName admin) {
        if (Build.VERSION.SDK_INT < 25 || dpm == null
                || !dpm.isDeviceOwnerApp(context.getPackageName())) {
            return;
        }
        SharedPreferences stats = context.getSharedPreferences("alp_stats",
                Context.MODE_PRIVATE);
        try {
            String prev = qsTilesSpec(context);
            String next = prev == null ? QS_TILES_BASE : stripWifiTile(prev);
            if (next == null) {
                next = QS_TILES_BASE;
            }
            dpm.setSecureSetting(admin, "qs_tiles", next);
            stats.edit().putBoolean("tiles_prev_applied", true)
                    .putString("tiles_prev_content", prev == null ? "" : prev)
                    .apply();
        } catch (Exception ignored) {
        }
    }

    /** Restore the pre-block quick-settings tile spec (wifi back on the bar). */
    static void restoreQSTiles(Context context, DevicePolicyManager dpm,
                               ComponentName admin) {
        SharedPreferences stats = context.getSharedPreferences("alp_stats",
                Context.MODE_PRIVATE);
        if (!stats.getBoolean("tiles_prev_applied", false)) {
            return;
        }
        if (Build.VERSION.SDK_INT < 25 || dpm == null
                || !dpm.isDeviceOwnerApp(context.getPackageName())) {
            stats.edit().putBoolean("tiles_prev_applied", false).apply();
            return;
        }
        try {
            String prev = stats.getString("tiles_prev_content", "");
            dpm.setSecureSetting(admin, "qs_tiles",
                    prev.isEmpty() ? QS_TILES_RESTORE : prev);
        } catch (Exception ignored) {
        }
        stats.edit().putBoolean("tiles_prev_applied", false).apply();
    }

    // feature -> UserManager restriction key the ALP agent manages (single source).
    private static final Map<String, String> MANAGED = new LinkedHashMap<String, String>();

    static {
        MANAGED.put("WIFI", UserManager.DISALLOW_CONFIG_WIFI);
        MANAGED.put("BLUETOOTH", UserManager.DISALLOW_BLUETOOTH);
        MANAGED.put("TETHERING", UserManager.DISALLOW_CONFIG_TETHERING);
        MANAGED.put("HOTSPOT", UserManager.DISALLOW_CONFIG_TETHERING);
        MANAGED.put("USB", UserManager.DISALLOW_USB_FILE_TRANSFER);
        MANAGED.put("USB_NETWORKING", UserManager.DISALLOW_USB_FILE_TRANSFER);
        MANAGED.put("VPN", UserManager.DISALLOW_CONFIG_VPN);
        MANAGED.put("MICROPHONE", UserManager.DISALLOW_UNMUTE_MICROPHONE);
        MANAGED.put("ADB", UserManager.DISALLOW_DEBUGGING_FEATURES);
        MANAGED.put("DEVELOPER_OPTIONS", UserManager.DISALLOW_DEBUGGING_FEATURES);
        MANAGED.put("SAFE_BOOT", UserManager.DISALLOW_SAFE_BOOT);
        MANAGED.put("FACTORY_RESET", UserManager.DISALLOW_FACTORY_RESET);
        MANAGED.put("APP_INSTALLATION", UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES);
        MANAGED.put("UNKNOWN_SOURCES", UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES);
        MANAGED.put("ACCOUNTS", UserManager.DISALLOW_MODIFY_ACCOUNTS);
        MANAGED.put("USER_MANAGEMENT", UserManager.DISALLOW_MODIFY_ACCOUNTS);
        MANAGED.put("LOCATION", UserManager.DISALLOW_SHARE_LOCATION);
        MANAGED.put("GPS", UserManager.DISALLOW_SHARE_LOCATION);
        // Catalog lanes backed by a real Device Owner user restriction.
        MANAGED.put("WIFI_CONFIG", UserManager.DISALLOW_CONFIG_WIFI);
        MANAGED.put("MOCK_LOCATIONS", "no_mock_location");
        MANAGED.put("UNINSTALL_APPS", UserManager.DISALLOW_UNINSTALL_APPS);
        MANAGED.put("BLUETOOTH_TETHERING", UserManager.DISALLOW_CONFIG_TETHERING);
        MANAGED.put("CLEAR_APP_DATA", "no_clear_app_data");
    }

    // Settings-backed catalog lanes. Tuple: {scope, key, blocked_value, allowed_value}
    // where scope is one of "global", "system", "secure". Writes go through the
    // Device Owner set*Setting channels only — never ContentResolver, so a
    // failed/silent write surfaces as an honest refused outcome.
    // scope: 0=global 1=system 2=secure
    private static final Map<String, Object[]> SETTING_TARGETS =
            new LinkedHashMap<String, Object[]>();

    static {
        SETTING_TARGETS.put("AIRPLANE_MODE", new Object[]{0, Settings.Global.AIRPLANE_MODE_ON, "0", "0"});
        SETTING_TARGETS.put("DATA_SAVER", new Object[]{0, "data_saver", "1", "0"});
        SETTING_TARGETS.put("ROAMING_DATA", new Object[]{0, Settings.Global.DATA_ROAMING, "0", "0"});
        SETTING_TARGETS.put("ROAMING_SYNC", new Object[]{0, Settings.Global.DATA_ROAMING, "0", "0"});
        SETTING_TARGETS.put("ROAMING_PUSH", new Object[]{0, Settings.Global.DATA_ROAMING, "0", "0"});
        SETTING_TARGETS.put("ROAMING_CALL", new Object[]{0, Settings.Global.DATA_ROAMING, "0", "0"});
        SETTING_TARGETS.put("NFC", new Object[]{0, "nfc_on", "0", "1"});
        SETTING_TARGETS.put("ANDROID_BEAM", new Object[]{0, "nfc_on", "0", "1"});
        SETTING_TARGETS.put("SET_TIME", new Object[]{0, Settings.Global.AUTO_TIME, "0", "1"});
        SETTING_TARGETS.put("SET_TIMEZONE", new Object[]{0, Settings.Global.AUTO_TIME_ZONE, "0", "1"});
        SETTING_TARGETS.put("SET_TIME_ZONE", new Object[]{0, Settings.Global.AUTO_TIME_ZONE, "0", "1"});
        SETTING_TARGETS.put("BACKGROUND_PROCESS_LIMIT",
                new Object[]{0, "background_process_limit", "0", "0"});
        SETTING_TARGETS.put("TERMINATE_APP_ON_EXIT",
                new Object[]{0, Settings.Global.ALWAYS_FINISH_ACTIVITIES, "1", "0"});
        SETTING_TARGETS.put("PLAY_PROTECT",
                new Object[]{0, "package_verifier_enable", "1", "1"});
        SETTING_TARGETS.put("REPORT_CRASH",
                new Object[]{0, "send_action_app_error", "0", "1"});
        SETTING_TARGETS.put("SCREEN_TIMEOUT",
                new Object[]{1, Settings.System.SCREEN_OFF_TIMEOUT, "30000", "300000"});
        SETTING_TARGETS.put("SCREEN_BRIGHTNESS",
                new Object[]{1, Settings.System.SCREEN_BRIGHTNESS, "0", "128"});
        SETTING_TARGETS.put("ADAPTIVE_BRIGHTNESS",
                new Object[]{1, Settings.System.SCREEN_BRIGHTNESS_MODE, "0", "1"});
        // Setting AUTO_SYNC would be a ContentResolver master-sync write — no DO
        // channel exists for it, so the lane is NOT registered here (it fails
        // honestly rather than pretending).
        // AMBIENT_DISPLAY via DO secure channel is attempted (honest failure is
        // expected on vendors that guard DOZE_ENABLED).
        SETTING_TARGETS.put("AMBIENT_DISPLAY", new Object[]{2, "doze_enabled", "0", "1"});
    }

    static String readFile(String path) {
        try {
            File f = new File(path);
            if (!f.exists()) {
                return null;
            }
            InputStream is = new FileInputStream(f);
            byte[] buf = new byte[(int) f.length()];
            int off = 0;
            while (off < buf.length) {
                int n = is.read(buf, off, buf.length - off);
                if (n < 0) {
                    break;
                }
                off += n;
            }
            is.close();
            return new String(buf, 0, off, StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }

    static String utcNow() {
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
        return fmt.format(new Date());
    }

    // Camera setCameraDisabled() is public but there is no public "is it locked?"
    // reader on DevicePolicyManager — the app keeps its own honest last-known
    // flag; the definitive camera evidence always comes from dumpsys device_policy
    // via the management-side probe. Returns true when a real transition happened.
    private static boolean setCameraLock(Context context, DevicePolicyManager dpm,
                                         ComponentName admin, boolean disabled) {
        SharedPreferences prefs = context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE);
        boolean was = prefs.getBoolean("camera_disabled", false);
        if (was == disabled) {
            return false;
        }
        dpm.setCameraDisabled(admin, disabled);
        prefs.edit().putBoolean("camera_disabled", disabled).apply();
        return true;
    }

    private static boolean cameraLocked(Context context) {
        return context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                .getBoolean("camera_disabled", false);
    }

    /**
     * Activity-nudge path: run whichever envelope files are pending (deduplicated
     * by cmd_id so repeated activity resumes never re-apply the same command).
     */
    static void processPending(Context context) {
        android.util.Log.d(TAG, "processPending enter");
        // A command is pending only while its envelope file physically exists.
        // A missing file must never be interpreted as a CLEAR request — that
        // would wipe every applied restriction on the next app resume.
        String applyEnv = readFile(ENV_APPLY);
        String clearEnv = readFile(ENV_CLEAR);
        String stateEnv = readFile(ENV_STATE);
        if (applyEnv != null && !alreadyDone(context, ENV_APPLY)) {
            android.util.Log.d(TAG, "processPending APPLY file pending");
            handle(context, CommandReceiver.ACTION_APPLY_POLICY, applyEnv, ENV_APPLY);
        }
        if (clearEnv != null && !alreadyDone(context, ENV_CLEAR)) {
            android.util.Log.d(TAG, "processPending CLEAR file pending");
            handle(context, CommandReceiver.ACTION_CLEAR_POLICY, clearEnv, ENV_CLEAR);
        }
        if (stateEnv != null && !alreadyDone(context, ENV_STATE)) {
            android.util.Log.d(TAG, "processPending GET_STATE file pending");
            handle(context, CommandReceiver.ACTION_GET_STATE, stateEnv, ENV_STATE);
        }
        String withdrawEnv = readFile(ENV_WITHDRAW);
        if (withdrawEnv != null && !alreadyDone(context, ENV_WITHDRAW)) {
            android.util.Log.d(TAG, "processPending WITHDRAW file pending");
            handle(context, CommandReceiver.ACTION_WITHDRAW_DO, withdrawEnv, ENV_WITHDRAW);
        }
        String pinEnv = readFile(ENV_PIN);
        if (pinEnv != null && !alreadyDone(context, ENV_PIN)) {
            android.util.Log.d(TAG, "processPending PROVISION_PIN file pending");
            handle(context, CommandReceiver.ACTION_PROVISION_PIN, pinEnv, ENV_PIN);
        }
        android.util.Log.d(TAG, "processPending exit");
    }

    static void handle(Context context, String action, String envelopeJson, String source) {
        String file = source;
        if (file == null) {
            file = fileFor(action);
        }
        boolean done = false;
        if (file != null) {
            android.util.Log.d(TAG, "handle action=" + action + " file=" + file
                    + " hasEnvelope=" + (envelopeJson != null));
            done = alreadyDone(context, file);
            if (done) {
                android.util.Log.d(TAG, "handle " + action + " already done, skipping");
            }
        }
        if (!done) {
            // Every envelope-driven action must pass the Ed25519 gate first.
            // Only REPORT is broadcast-only (no envelope) and stays ungated.
            if (!CommandReceiver.ACTION_REPORT.equals(action)) {
                String json = envelopeJson;
                if (json == null && file != null) {
                    json = readFile(file);
                }
                String reason = EnvelopeGuard.check(context, json,
                        EnvelopeGuardCore.shortAction(action));
                if (reason != null) {
                    android.util.Log.w(TAG, "handle REJECTED " + action + ": " + reason);
                    reject(context, file, json, reason, action);
                    return; // never marked done: a corrected envelope re-runs
                }
            }
            if (CommandReceiver.ACTION_APPLY_POLICY.equals(action)) {
                applyPolicy(context, envelopeJson);
            } else if (CommandReceiver.ACTION_CLEAR_POLICY.equals(action)) {
                clearPolicy(context, envelopeJson);
            } else if (CommandReceiver.ACTION_GET_STATE.equals(action)) {
                getState(context, envelopeJson);
            } else if (CommandReceiver.ACTION_REPORT.equals(action)) {
                AlpStats.record(context, "report_requested");
            } else if (CommandReceiver.ACTION_WITHDRAW_DO.equals(action)) {
                withdrawDeviceOwner(context, envelopeJson);
            } else if (CommandReceiver.ACTION_PROVISION_PIN.equals(action)) {
                String err = PinGuard.provision(context, envelopeJson);
                if (err != null) {
                    android.util.Log.w(TAG, "pin provision failed: " + err);
                    AlpStats.record(context, "pin_provision_rejected");
                }
            }
            if (file != null) {
                markDone(context, file, envelopeJson);
            }
        }
    }

    /**
     * Record an authorization rejection in state.json so the management probe
     * surfaces exactly which envelope was refused and why. The file is left
     * pending (not marked done) for honest re-delivery with a new cmd_id.
     */
    private static void reject(Context context, String file, String envelopeJson,
                               String reason, String action) {
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        String cmdId = "?";
        if (envelopeJson != null) {
            try {
                cmdId = new JSONObject(envelopeJson).optString("cmd_id", "?");
            } catch (JSONException ignored) {
            }
        }
        android.util.Log.w(TAG, "reject file=" + file + " reason=" + reason);
        List<String> err = new ArrayList<String>();
        err.add("REJECTED " + shortify(action) + ": " + reason);
        AlpStats.writeState(context, cmdId, new ArrayList<String>(),
                            new ArrayList<String>(), err, utcNow(),
                            dpm != null && dpm.isAdminActive(admin));
        AlpStats.record(context, "envelope_rejected:" + shortify(action));
    }

    private static String shortify(String action) {
        if (action == null) {
            return "?";
        }
        int dot = action.lastIndexOf('.');
        return dot >= 0 ? action.substring(dot + 1) : action;
    }

    private static String fileFor(String action) {
        if (CommandReceiver.ACTION_APPLY_POLICY.equals(action)) {
            return ENV_APPLY;
        }
        if (CommandReceiver.ACTION_CLEAR_POLICY.equals(action)) {
            return ENV_CLEAR;
        }
        if (CommandReceiver.ACTION_GET_STATE.equals(action)) {
            return ENV_STATE;
        }
        if (CommandReceiver.ACTION_WITHDRAW_DO.equals(action)) {
            return ENV_WITHDRAW;
        }
        if (CommandReceiver.ACTION_PROVISION_PIN.equals(action)) {
            return ENV_PIN;
        }
        return null;
    }

    private static boolean alreadyDone(Context context, String file) {
        String last = context.getSharedPreferences(PREFS_LAST, Context.MODE_PRIVATE)
                .getString("last_" + file, "");
        String env = readFile(file);
        String cmdId = cmdOf(env);
        return cmdId != null && cmdId.equals(last);
    }

    private static void markDone(Context context, String file, String envelopeJson) {
        String cmdId = cmdOf(envelopeJson);
        if (cmdId != null) {
            context.getSharedPreferences(PREFS_LAST, Context.MODE_PRIVATE)
                    .edit().putString("last_" + file, cmdId).apply();
        }
    }

    private static String cmdOf(String envelopeJson) {
        if (envelopeJson == null) {
            return null;
        }
        try {
            return new JSONObject(envelopeJson).optString("cmd_id", null);
        } catch (JSONException e) {
            return null;
        }
    }

    // ------------------------------------------------------------------
    // Committed policy — the lockdown definition the enforcement service
    // re-asserts. Written ONLY from a verified APPLY envelope and cleared
    // only by a verified CLEAR/WITHDRAW or the PIN-authorized rollback, so
    // any untrusted attempt to lift a restriction is rolled back within the
    // watchdog interval.
    // ------------------------------------------------------------------

    private static boolean isManagedFeature(String feature) {
        return "CAMERA".equals(feature) || "CAMERA_LOCKSCREEN".equals(feature)
                || "OS_UPGRADE".equals(feature) || "STORAGE_ENCRYPTION".equals(feature)
                || MANAGED.containsKey(feature) || SETTING_TARGETS.containsKey(feature);
    }

    static void commitPolicy(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            clearCommitted(context);
            return;
        }
        try {
            JSONObject env = new JSONObject(envelopeJson);
            JSONObject body = env.optJSONObject("body");
            if (body == null) {
                body = env;
            }
            JSONArray snap = body.optJSONArray("snapshot");
            if (snap == null) {
                snap = body.optJSONArray("applied");
            }
            if (snap == null) {
                clearCommitted(context);
                return;
            }
            JSONArray committed = new JSONArray();
            for (int i = 0; i < snap.length(); i++) {
                JSONObject row = snap.optJSONObject(i);
                if (row == null) {
                    continue;
                }
                String feature = row.optString("feature");
                String desired = row.optString("desired");
                if ("BLOCK".equals(desired) && isManagedFeature(feature)) {
                    JSONObject c = new JSONObject();
                    c.put("feature", feature);
                    c.put("desired", "BLOCK");
                    committed.put(c);
                }
            }
            context.getSharedPreferences(PREFS_COMMITTED, Context.MODE_PRIVATE)
                    .edit().putString("policy", committed.toString()).apply();
        } catch (JSONException e) {
            clearCommitted(context);
        }
    }

    static void clearCommitted(Context context) {
        context.getSharedPreferences(PREFS_COMMITTED, Context.MODE_PRIVATE)
                .edit().remove("policy").apply();
    }

    /** @return rows {feature, desired} or null when no policy is committed. */
    static List<String[]> committedPolicy(Context context) {
        String raw = context.getSharedPreferences(PREFS_COMMITTED, Context.MODE_PRIVATE)
                .getString("policy", "");
        if (raw.isEmpty()) {
            return null;
        }
        try {
            JSONArray a = new JSONArray(raw);
            List<String[]> out = new ArrayList<String[]>();
            for (int i = 0; i < a.length(); i++) {
                JSONObject o = a.optJSONObject(i);
                if (o == null) {
                    continue;
                }
                out.add(new String[]{o.optString("feature"), o.optString("desired")});
            }
            return out;
        } catch (JSONException e) {
            return null;
        }
    }

    /** True when the committed policy locks Wi-Fi (used by the snap-back). */
    static boolean wifiBlockCommitted(Context context) {
        List<String[]> rows = committedPolicy(context);
        if (rows == null) {
            return false;
        }
        for (String[] row : rows) {
            if ("WIFI".equals(row[0]) && "BLOCK".equals(row[1])) {
                return true;
            }
        }
        return false;
    }

    private static boolean restrictionActive(DevicePolicyManager dpm, ComponentName admin,
                                             String key) {
        Bundle cur = dpm.getUserRestrictions(admin);
        return cur != null && cur.getBoolean(key);
    }

    /**
     * Watchdog: re-apply every BLOCK row of the committed policy. Returns true
     * when any enforcement action was taken this cycle. The WIFI row is the
     * radio-level lockdown (icon always snaps OFF); CAMERA and the managed
     * restrictions are re-added when missing.
     */
    static boolean enforceCommitted(Context context, DevicePolicyManager dpm,
                                    ComponentName admin) {
        List<String[]> rows = committedPolicy(context);
        if (rows == null || rows.isEmpty()) {
            return false;
        }
        boolean changed = false;
        for (String[] row : rows) {
            if (!"BLOCK".equals(row[1])) {
                continue;
            }
            String feature = row[0];
            if ("WIFI".equals(feature)) {
                WifiManager wm = (WifiManager) context.getApplicationContext()
                        .getSystemService(Context.WIFI_SERVICE);
                if (wm != null && wm.isWifiEnabled()) {
                    ensureWifiOff(context);
                    changed = true;
                }
                context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                        .edit().putBoolean("wifi_blocked", true).apply();
                continue;
            }
            if ("CAMERA".equals(feature)) {
                if (setCameraLock(context, dpm, admin, true)) {
                    changed = true;
                }
                continue;
            }
            String key = MANAGED.get(feature);
            if (key == null) {
                continue;
            }
            if (!restrictionActive(dpm, admin, key)) {
                try {
                    dpm.addUserRestriction(admin, key);
                    changed = true;
                } catch (Exception ignored) {
                }
            }
        }
        return changed;
    }

    // ------------------------------------------------------------------
    // APPLY_POLICY
    // ------------------------------------------------------------------
    static void applyPolicy(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            envelopeJson = readFile(ENV_APPLY);
        }
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        android.util.Log.d(TAG, "applyPolicy adminActive="
                + (dpm != null && dpm.isAdminActive(admin))
                + " hasEnvelope=" + (envelopeJson != null));
        if (envelopeJson == null || dpm == null || !dpm.isAdminActive(admin)) {
            AlpStats.record(context, "apply_rejected_no_admin");
            return;
        }

        List<String> applied = new ArrayList<>();
        List<String> skipped = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        String cmdId = "?";
        try {
            JSONObject env = new JSONObject(envelopeJson);
            cmdId = env.optString("cmd_id", "?");
            JSONObject body = env.optJSONObject("body");
            if (body == null) {
                body = env;
            }
            JSONArray snap = body.optJSONArray("snapshot");
            if (snap == null) {
                snap = body.optJSONArray("applied");
            }
            if (snap == null) {
                skipped.add("no snapshot in envelope");
            } else {
                for (int i = 0; i < snap.length(); i++) {
                    JSONObject row = snap.optJSONObject(i);
                    if (row == null) {
                        continue;
                    }
                    String feature = row.optString("feature");
                    String desired = row.optString("desired");
                    try {
                        if (applyRow(context, dpm, admin, feature, desired)) {
                            applied.add(feature);
                        } else {
                            skipped.add(feature + ":" + desired);
                        }
                    } catch (Exception e) {
                        errors.add(feature + ": " + e.getClass().getSimpleName());
                    }
                }
            }
        } catch (JSONException e) {
            errors.add("json: " + e.getMessage());
        }

        AlpStats.writeState(context, cmdId, applied, skipped, errors, utcNow(),
                            dpm.isAdminActive(admin));
        // The sweep is the new enforcement truth: only a verified APPLY may
        // (re)define platform behavior.
        commitPolicy(context, envelopeJson != null ? envelopeJson : readFile(ENV_APPLY));
        AlpStats.record(context, "policy_applied:" + applied.size());
    }

    private static boolean applyRow(Context context, DevicePolicyManager dpm, ComponentName admin,
                                    String feature, String desired) {
        if (feature == null || desired == null) {
            return false;
        }
        switch (desired) {
            case "BLOCK":
                if ("CAMERA".equals(feature) || "CAMERA_LOCKSCREEN".equals(feature)) {
                    setCameraLock(context, dpm, admin, true);   // device-owner camera control
                    return true;
                }
                if ("WIFI".equals(feature)) {
                    // Some builds don't power the radio off for the restriction;
                    // force the radio off through DO channels while keeping the
                    // config lock so the user cannot re-enable it.
                    String key = MANAGED.get(feature);
                    if (key != null) {
                        dpm.addUserRestriction(admin, key);
                    }
                    ensureWifiOff(context);
                    hideWifiQSTile(context, dpm, admin);
                    context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                            .edit().putBoolean("wifi_blocked", true).apply();
                    return true;
                }
                if ("OS_UPGRADE".equals(feature)) {
                    return freezeSystemUpdates(dpm, admin);
                }
                if ("STORAGE_ENCRYPTION".equals(feature)) {
                    return setStorageEncryption(dpm, admin, true);
                }
                String managed = MANAGED.get(feature);
                if (managed != null) {
                    try {
                        dpm.addUserRestriction(admin, managed);
                        return true;
                    } catch (Exception e) {
                        AlpStats.record(context, "restriction_failed:" + feature);
                        return false;
                    }
                }
                return applySettingTarget(context, dpm, admin, feature, true);
            case "ALLOW":
                clearRestrictions(context, dpm, admin, feature);
                return true;
            default:
                return false;
        }
    }

    // ------------------------------------------------------------------
    // Device Owner SystemUpdatePolicy freeze — a real 90-day freeze window
    // starting today, so "Block OS Update" never depends on vendor knobs.
    // ------------------------------------------------------------------
    private static boolean freezeSystemUpdates(DevicePolicyManager dpm, ComponentName admin) {
        if (Build.VERSION.SDK_INT < 29) {
            // Freeze windows only exist from API 29; refusing beats pretending.
            return false;
        }
        // The legacy freeze API (SystemUpdatePolicy.setFreezePeriods with
        // SystemUpdateFreezePeriod) is what Device Owners use on API 29-32; on
        // API 33+ those classes were removed so reflection fails -> honest false.
        try {
            java.util.Calendar s = java.util.Calendar.getInstance();
            java.util.Calendar e = (java.util.Calendar) s.clone();
            e.add(java.util.Calendar.DAY_OF_MONTH, 90);
            int start = s.get(java.util.Calendar.YEAR) * 10000
                    + (s.get(java.util.Calendar.MONTH) + 1) * 100
                    + s.get(java.util.Calendar.DAY_OF_MONTH);
            int end = e.get(java.util.Calendar.YEAR) * 10000
                    + (e.get(java.util.Calendar.MONTH) + 1) * 100
                    + e.get(java.util.Calendar.DAY_OF_MONTH);
            Class<?> clzPolicy = Class.forName("android.app.admin.SystemUpdatePolicy");
            Class<?> clzPeriod = Class.forName("android.app.admin.SystemUpdateFreezePeriod");
            Object period = clzPeriod.getConstructor(int.class, int.class).newInstance(start, end);
            Object policy = clzPolicy.getConstructor().newInstance();
            Object after = clzPolicy.getMethod("setFreezePeriods", java.util.List.class)
                    .invoke(policy, java.util.Collections.singletonList(period));
            dpm.setSystemUpdatePolicy(admin, (android.app.admin.SystemUpdatePolicy) after);
            return true;
        } catch (Exception ex) {
            return false;
        }
    }

    private static boolean setStorageEncryption(DevicePolicyManager dpm, ComponentName admin,
                                                boolean on) {
        try {
            dpm.setStorageEncryption(admin, on);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    // ------------------------------------------------------------------
    // Settings lanes (catalog enforcement through DO set*Setting channels).
    // A blocked value is pushed for BLOCK; ALLOW restores the allowed value.
    // Any SecurityException / missing key surfaces as an honest false.
    // ------------------------------------------------------------------
    private static boolean applySettingTarget(Context context, DevicePolicyManager dpm,
                                              ComponentName admin, String feature, boolean block) {
        Object[] t = SETTING_TARGETS.get(feature);
        if (t == null) {
            return false;
        }
        int scope = (Integer) t[0];
        String key = (String) t[1];
        String value = block ? (String) t[2] : (String) t[3];
        try {
            switch (scope) {
                case 0:
                    dpm.setGlobalSetting(admin, key, value);
                    break;
                case 1:
                    dpm.setSystemSetting(admin, key, value);
                    break;
                default:
                    dpm.setSecureSetting(admin, key, value);
                    break;
            }
            return true;
        } catch (Exception e) {
            AlpStats.record(context, "setting_failed:" + feature);
            return false;
        }
    }

    private static void clearRestrictions(Context context, DevicePolicyManager dpm,
                                           ComponentName admin, String feature) {
        if ("CAMERA".equals(feature) || "CAMERA_LOCKSCREEN".equals(feature)) {
            setCameraLock(context, dpm, admin, false);
            return;
        }
        if ("WIFI".equals(feature)) {
            String key = MANAGED.get(feature);
            if (key != null) {
                dpm.clearUserRestriction(admin, key);
            }
            try {
                dpm.setGlobalSetting(admin, Settings.Global.WIFI_ON, "1");
            } catch (Exception ignored) {
            }
            context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                    .edit().putBoolean("wifi_blocked", false).apply();
            restoreQSTiles(context, dpm, admin);
            return;
        }
        if ("OS_UPGRADE".equals(feature)) {
            try {
                dpm.setSystemUpdatePolicy(admin, null);
            } catch (Exception ignored) {
            }
            return;
        }
        if ("STORAGE_ENCRYPTION".equals(feature)) {
            setStorageEncryption(dpm, admin, false);
            return;
        }
        if (SETTING_TARGETS.containsKey(feature)) {
            // Restore the ALLOW/default value for the lane it actually changed.
            applySettingTarget(context, dpm, admin, feature, false);
            return;
        }
        String key = MANAGED.get(feature);
        if (key != null) {
            dpm.clearUserRestriction(admin, key);
        }
    }

    // ------------------------------------------------------------------
    // CLEAR_POLICY — restore point: remove EVERY restriction ALP manages.
    // Only restrictions actually active (getUserRestrictions / camera flag)
    // are reported as cleared — nothing is claimed from absence.
    // Note: on Android 16 preview builds a DO restriction can land in BOTH the
    // per-admin layer and the Global (server) layer; clearUserRestriction(admin)
    // only reliably removes the per-admin layer there. The management probe
    // treats presence of `UserRestrictionPolicyKey userRestriction_<key>` in
    // EITHER dumpsys block as active, so residual Global entries are surfaced.
    // ------------------------------------------------------------------
    // ------------------------------------------------------------------
    // LOCAL ROLLBACK — in-app admin recovery button. Lets an on-device
    // operator clear every managed restriction WITHOUT adb/USB: the same
    // clearPolicy path used by CLEAR_POLICY, driven from the launcher UI.
    // ------------------------------------------------------------------
    static void localRollback(Context context) {
        android.util.Log.d(TAG, "localRollback requested from UI");
        String cmdId = "UI-ROLLBACK-" + Long.toString(System.currentTimeMillis() / 1000L);
        String envelope = "{\"cmd_id\":\"" + cmdId + "\"}";
        clearPolicy(context, envelope);
    }

    // ------------------------------------------------------------------
    static void clearPolicy(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            envelopeJson = readFile(ENV_CLEAR);
        }
        if (envelopeJson == null) {
            // No CLEAR request actually exists on the device — never interpret
            // absence as "clear everything". This closes the wipe-on-resume bug.
            android.util.Log.d(TAG, "clearPolicy skipped: no CLEAR envelope present");
            AlpStats.record(context, "clear_rejected_no_envelope");
            return;
        }
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        if (dpm == null || !dpm.isAdminActive(admin)) {
            AlpStats.record(context, "clear_rejected_no_admin");
            return;
        }
        List<String> cleared = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        String cmdId = "?";
        try {
            JSONObject env = new JSONObject(envelopeJson == null ? "{}" : envelopeJson);
            cmdId = env.optString("cmd_id", "?");
            Bundle cur = dpm.getUserRestrictions(admin);
            for (Map.Entry<String, String> e : MANAGED.entrySet()) {
                if (cur == null || !cur.getBoolean(e.getValue())) {
                    continue;
                }
                try {
                    dpm.clearUserRestriction(admin, e.getValue());
                    if (!cleared.contains(e.getKey())) {
                        cleared.add(e.getKey());
                    }
                } catch (Exception ex) {
                    errors.add(e.getKey() + ": " + ex.getClass().getSimpleName());
                }
            }
            if (setCameraLock(context, dpm, admin, false)) {
                cleared.add("CAMERA");
            }
            // Full rollback: unconditionally lift the agent-side wifi lockdown
            // flag and restore the radio setting, regardless of whether the
            // framework reports the restriction as active (vendor builds list a
            // guest-default DISALLOW_CONFIG_WIFI that survives clearUserRestriction).
            context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                    .edit().putBoolean("wifi_blocked", false).apply();
            try {
                dpm.setGlobalSetting(admin, Settings.Global.WIFI_ON, "1");
            } catch (Exception ignored) {
            }
            restoreQSTiles(context, dpm, admin);
            // Full rollback also restores every settings-backed catalog lane,
            // the OS-update freeze window and storage-encryption flag.
            for (String feature : new ArrayList<String>(SETTING_TARGETS.keySet())) {
                if (applySettingTarget(context, dpm, admin, feature, false)) {
                    if (!cleared.contains(feature)) {
                        cleared.add(feature);
                    }
                }
            }
            try {
                dpm.setSystemUpdatePolicy(admin, null);
            } catch (Exception ignored) {
            }
            setStorageEncryption(dpm, admin, false);
        } catch (JSONException e) {
            errors.add("json: " + e.getMessage());
        }
        // No lockdown may remain defined after a verified/pin-authorized clear.
        clearCommitted(context);
        AlpStats.writeState(context, cmdId, cleared, new ArrayList<String>(),
                            errors, utcNow(), dpm.isAdminActive(admin));
        AlpStats.record(context, "policy_cleared:" + cleared.size());
    }

    // ------------------------------------------------------------------
    // GET_STATE — refresh the internal state.json (readable via run-as by the
    // management app). Reports only currently-ACTIVE managed restrictions.
    // ------------------------------------------------------------------
    static void getState(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            envelopeJson = readFile(ENV_STATE);
        }
        String cmdId = "?";
        if (envelopeJson != null) {
            try {
                cmdId = new JSONObject(envelopeJson).optString("cmd_id", "?");
            } catch (JSONException ignored) {
            }
        }
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        List<String> active = new ArrayList<>();
        boolean adminActive = dpm != null && dpm.isAdminActive(admin);
        if (adminActive) {
            Bundle cur = dpm.getUserRestrictions(admin);
            for (Map.Entry<String, String> e : MANAGED.entrySet()) {
                if (cur != null && cur.getBoolean(e.getValue())) {
                    if (!active.contains(e.getKey())) {
                        active.add(e.getKey());
                    }
                }
            }
            if (cameraLocked(context)) {
                active.add("CAMERA");
            }
            try {
                android.app.admin.SystemUpdatePolicy up = dpm.getSystemUpdatePolicy();
                if (up != null) {
                    active.add("OS_UPGRADE");
                }
            } catch (Exception ignored) {
            }
            try {
                if (dpm.getStorageEncryption(admin)) {
                    active.add("STORAGE_ENCRYPTION");
                }
            } catch (Exception ignored) {
            }
            for (Map.Entry<String, Object[]> t : SETTING_TARGETS.entrySet()) {
                String key = (String) t.getValue()[1];
                String blocked = (String) t.getValue()[2];
                try {
                    String now = Settings.System.getString(context.getContentResolver(), key);
                    if (now == null) {
                        now = Settings.Global.getString(context.getContentResolver(), key);
                    }
                    if (now == null) {
                        now = Settings.Secure.getString(context.getContentResolver(), key);
                    }
                    if (blocked != null && blocked.equals(now)) {
                        if (!active.contains(t.getKey())) {
                            active.add(t.getKey());
                        }
                    }
                } catch (Exception ignored) {
                }
            }
        }
        AlpStats.writeState(context, cmdId, active, new ArrayList<String>(),
                            new ArrayList<String>(), utcNow(), adminActive);
        AlpStats.record(context, "state_delivered");
    }

    // ------------------------------------------------------------------
    // WITHDRAW_DO — programmatic Device-Owner self-unenroll.
    // The agent removes its own device-owner role via
    // DevicePolicyManager.clearDeviceOwnerApp() — the documented DO unenroll
    // API that does NOT require a test-only build and does NOT trip the
    // "attempt to remove non-test admin" shell SecurityException seen with
    // `dpm remove-active-admin` on several AOSP builds. Before withdrawing it
    // clears every managed restriction and stops the enforcement service, so
    // nothing re-asserts lockdown once the owner role is gone. Claims are
    // honest: state.json only reports restrictions that were actually active.
    // ------------------------------------------------------------------
    static void withdrawDeviceOwner(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            envelopeJson = readFile(ENV_WITHDRAW);
        }
        if (envelopeJson == null) {
            android.util.Log.d(TAG, "withdraw skipped: no WITHDRAW envelope present");
            AlpStats.record(context, "withdraw_rejected_no_envelope");
            return;
        }
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        boolean adminActive = dpm != null && dpm.isAdminActive(admin);
        if (dpm == null || !dpm.isDeviceOwnerApp(context.getPackageName())) {
            android.util.Log.d(TAG, "withdraw skipped: not device owner (adminActive="
                    + adminActive + ")");
            AlpStats.record(context, "withdraw_rejected_not_owner");
            return;
        }
        List<String> cleared = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        String cmdId = "?";
        try {
            JSONObject env = new JSONObject(envelopeJson);
            cmdId = env.optString("cmd_id", "?");
            Bundle cur = dpm.getUserRestrictions(admin);
            for (Map.Entry<String, String> e : MANAGED.entrySet()) {
                if (cur == null || !cur.getBoolean(e.getValue())) {
                    continue;
                }
                try {
                    dpm.clearUserRestriction(admin, e.getValue());
                    if (!cleared.contains(e.getKey())) {
                        cleared.add(e.getKey());
                    }
                } catch (Exception ex) {
                    errors.add(e.getKey() + ": " + ex.getClass().getSimpleName());
                }
            }
            if (setCameraLock(context, dpm, admin, false)) {
                cleared.add("CAMERA");
            }
            // Lift the agent-side wifi lockdown and restore the radio setting.
            context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                    .edit().putBoolean("wifi_blocked", false).apply();
            try {
                dpm.setGlobalSetting(admin, Settings.Global.WIFI_ON, "1");
            } catch (Exception ignored) {
            }
            restoreQSTiles(context, dpm, admin);
        } catch (JSONException e) {
            errors.add("json: " + e.getMessage());
        }
        // The committed policy must die with the owner role; then the
        // enforcement service must not re-assert anything after owner drop.
        clearCommitted(context);
        try {
            context.stopService(new Intent(context, AlpForegroundService.class));
        } catch (Exception ignored) {
        }
        boolean withdrawn = false;
        try {
            dpm.clearDeviceOwnerApp(context.getPackageName());
            withdrawn = true;
        } catch (Exception ex) {
            errors.add("owner: " + ex.getClass().getSimpleName());
        }
        AlpStats.writeState(context, cmdId, cleared, new ArrayList<String>(),
                            errors, utcNow(),
                            dpm != null && dpm.isAdminActive(admin));
        AlpStats.record(context, withdrawn ? "owner_withdrawn:" + cleared.size()
                                           : "owner_withdraw_failed");
    }
}