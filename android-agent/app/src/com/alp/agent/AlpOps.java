package com.alp.agent;

import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Bundle;
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

    private static final String PREFS_LAST = "alp_processed";

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
        if (!alreadyDone(context, ENV_APPLY)) {
            android.util.Log.d(TAG, "processPending APPLY file pending");
            handle(context, CommandReceiver.ACTION_APPLY_POLICY, readFile(ENV_APPLY), ENV_APPLY);
        }
        if (!alreadyDone(context, ENV_CLEAR)) {
            android.util.Log.d(TAG, "processPending CLEAR file pending");
            handle(context, CommandReceiver.ACTION_CLEAR_POLICY, readFile(ENV_CLEAR), ENV_CLEAR);
        }
        if (!alreadyDone(context, ENV_STATE)) {
            android.util.Log.d(TAG, "processPending GET_STATE file pending");
            handle(context, CommandReceiver.ACTION_GET_STATE, readFile(ENV_STATE), ENV_STATE);
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
            if (CommandReceiver.ACTION_APPLY_POLICY.equals(action)) {
                applyPolicy(context, envelopeJson);
            } else if (CommandReceiver.ACTION_CLEAR_POLICY.equals(action)) {
                clearPolicy(context, envelopeJson);
            } else if (CommandReceiver.ACTION_GET_STATE.equals(action)) {
                getState(context, envelopeJson);
            } else if (CommandReceiver.ACTION_REPORT.equals(action)) {
                AlpStats.record(context, "report_requested");
            }
            if (file != null) {
                markDone(context, file, envelopeJson);
            }
        }
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
        AlpStats.record(context, "policy_applied:" + applied.size());
    }

    private static boolean applyRow(Context context, DevicePolicyManager dpm, ComponentName admin,
                                    String feature, String desired) {
        if (feature == null || desired == null) {
            return false;
        }
        switch (desired) {
            case "BLOCK":
                if ("CAMERA".equals(feature)) {
                    setCameraLock(context, dpm, admin, true);   // device-owner camera control
                    return true;
                }
                String key = MANAGED.get(feature);
                if (key == null) {
                    return false;
                }
                dpm.addUserRestriction(admin, key);
                return true;
            case "ALLOW":
                clearRestrictions(context, dpm, admin, feature);
                return true;
            default:
                return false;
        }
    }

    private static void clearRestrictions(Context context, DevicePolicyManager dpm,
                                           ComponentName admin, String feature) {
        if ("CAMERA".equals(feature)) {
            setCameraLock(context, dpm, admin, false);
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
    static void clearPolicy(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            envelopeJson = readFile(ENV_CLEAR);
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
        } catch (JSONException e) {
            errors.add("json: " + e.getMessage());
        }
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
        }
        AlpStats.writeState(context, cmdId, active, new ArrayList<String>(),
                            new ArrayList<String>(), utcNow(), adminActive);
        AlpStats.record(context, "state_delivered");
    }
}