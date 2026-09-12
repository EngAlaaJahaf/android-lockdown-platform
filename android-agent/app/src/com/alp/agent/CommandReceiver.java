package com.alp.agent;

import android.app.admin.DevicePolicyManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.UserManager;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

public class CommandReceiver extends BroadcastReceiver {

    public static final String ACTION_APPLY_POLICY = "com.alp.agent.APPLY_POLICY";
    public static final String ACTION_REPORT = "com.alp.agent.REPORT_CAPABILITY";
    public static final String EXTRA_ENVELOPE = "envelope";

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (ACTION_APPLY_POLICY.equals(action)) {
            String env = intent.getStringExtra(EXTRA_ENVELOPE);
            applyPolicy(context, env);
        } else if (ACTION_REPORT.equals(action)) {
            AlpStats.record(context, "report_requested");
        }
    }

    private static String readEnvelopeFile() {
        try {
            File f = new File("/data/local/tmp/alp_envelope.json");
            if (!f.exists()) {
                return null;
            }
            java.io.InputStream is = new java.io.FileInputStream(f);
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

    private void applyPolicy(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            envelopeJson = readEnvelopeFile();
        }
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        if (envelopeJson == null || !dpm.isAdminActive(admin)) {
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
                        if (applyRow(dpm, admin, feature, desired)) {
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

        String iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
                .format(new Date());
        iso = getUtcNow();

        AlpStats.writeState(context, cmdId, applied, skipped, errors, iso, dpm.isAdminActive(admin));
        AlpStats.record(context, "policy_applied:" + applied.size());
    }

    private String getUtcNow() {
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
        return fmt.format(new Date());
    }

    private boolean applyRow(DevicePolicyManager dpm, ComponentName admin,
                             String feature, String desired) {
        Map<String, String> restrictions = new HashMap<>();
        if (desired == null) {
            return false;
        }
        switch (desired) {
            case "BLOCK":
                switch (feature) {
                    case "WIFI":
                        restrictions.put(UserManager.DISALLOW_CONFIG_WIFI, "wifi");
                        break;
                    case "BLUETOOTH":
                        restrictions.put(UserManager.DISALLOW_BLUETOOTH, "bluetooth");
                        break;
                    case "HOTSPOT":
                    case "TETHERING":
                        restrictions.put(UserManager.DISALLOW_CONFIG_TETHERING, "tether");
                        break;
                    case "USB_NETWORKING":
                        restrictions.put(UserManager.DISALLOW_USB_FILE_TRANSFER, "usb_net");
                        break;
                    case "VPN":
                        restrictions.put(UserManager.DISALLOW_CONFIG_VPN, "vpn");
                        break;
                    case "ETHERNET":
                        return false;
                    case "MICROPHONE":
                        restrictions.put(UserManager.DISALLOW_UNMUTE_MICROPHONE, "mic");
                        break;
                    case "ADB":
                    case "DEVELOPER_OPTIONS":
                        restrictions.put(UserManager.DISALLOW_DEBUGGING_FEATURES, "debug");
                        break;
                    case "SAFE_BOOT":
                        restrictions.put(UserManager.DISALLOW_SAFE_BOOT, "safe_boot");
                        break;
                    case "FACTORY_RESET":
                        restrictions.put(UserManager.DISALLOW_FACTORY_RESET, "factory_reset");
                        break;
                    case "APP_INSTALLATION":
                    case "UNKNOWN_SOURCES":
                        restrictions.put(UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES, "install_src");
                        break;
                    case "USB":
                        restrictions.put(UserManager.DISALLOW_USB_FILE_TRANSFER, "usb");
                        break;
                    case "ACCOUNTS":
                    case "USER_MANAGEMENT":
                        restrictions.put(UserManager.DISALLOW_MODIFY_ACCOUNTS, "modify_accounts");
                        break;
                    case "LOCATION":
                    case "GPS":
                        restrictions.put(UserManager.DISALLOW_SHARE_LOCATION, "location");
                        break;
                    default:
                        return false;
                }
                for (String key : restrictions.keySet()) {
                    dpm.addUserRestriction(admin, key);
                }
                return true;
            case "ALLOW":
                clearRestrictions(dpm, admin, feature);
                return true;
            default:
                return false;
        }
    }

    private void clearRestrictions(DevicePolicyManager dpm, ComponentName admin, String feature) {
        switch (feature) {
            case "WIFI":
                dpm.clearUserRestriction(admin, UserManager.DISALLOW_CONFIG_WIFI);
                break;
            case "BLUETOOTH":
                dpm.clearUserRestriction(admin, UserManager.DISALLOW_BLUETOOTH);
                break;
            case "ADB":
            case "DEVELOPER_OPTIONS":
                dpm.clearUserRestriction(admin, UserManager.DISALLOW_DEBUGGING_FEATURES);
                break;
            case "APP_INSTALLATION":
            case "UNKNOWN_SOURCES":
                dpm.clearUserRestriction(admin, UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES);
                break;
            default:
                break;
        }
    }
}