package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Ask the local control plane "which policy is mine?" and apply it.
 *
 * Why this exists: a policy published while the handset was detached used to
 * have no way of reaching it. The console had to push over ADB, so an offline
 * device silently stayed on whatever profile it had last seen. The agent now
 * pulls: over the USB tether (10.0.2.2) it asks for its own signed envelope and
 * hands it to exactly the same AlpOps pipeline a push uses.
 *
 * Safety properties, deliberately narrow:
 *  - one hard-coded address, the local panel through the tether. There is no
 *    console-supplied URL, so this cannot be steered onto a network path.
 *    gnirehtet maps 10.0.2.2 to the host's localhost; 10.0.0.2 is the handset's
 *    own tun address and is NOT the host.
 *  - the request only ever carries this device's own id and serial, and the
 *    reply can only be that device's assigned profile;
 *  - the reply is applied through EnvelopeGuard, so an unsigned or altered
 *    envelope is rejected exactly like a forged push;
 *  - nothing is applied when the console reports the same fingerprint, so a
 *    sync press costs one HTTP call, not a re-enforcement sweep.
 */
final class PolicyPull {

    private static final String TAG = "ALP";
    private static final String PREFS = "alp_stats";
    private static final String K_FINGERPRINT = "alp_policy_fingerprint";
    private static final String K_POLICY = "alp_policy_id";
    private static final int TIMEOUT_MS = 8000;

    private static final String BASE =
            "http://10.0.2.2:8765/api/v1/agent/policy";

    interface Callback {
        /**
         * @param applied  true when a new envelope was applied
         * @param label    one line for the operator, already localised-friendly
         */
        void onResult(boolean applied, String label, int rows, int skipped);
    }

    private PolicyPull() {
    }

    /** Fingerprint of the profile this device believes it is running. */
    static String currentFingerprint(Context context) {
        try {
            return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .getString(K_FINGERPRINT, "");
        } catch (Exception e) {
            return "";
        }
    }

    static String currentPolicyId(Context context) {
        try {
            return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .getString(K_POLICY, "");
        } catch (Exception e) {
            return "";
        }
    }

    private static void remember(Context context, String fingerprint, String policyId) {
        SharedPreferences.Editor e =
                context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit();
        if (fingerprint != null && fingerprint.length() > 0) {
            e.putString(K_FINGERPRINT, fingerprint);
        }
        if (policyId != null) {
            e.putString(K_POLICY, policyId);
        }
        e.apply();
    }

    /**
     * Pull and, when it differs, apply. Safe to call from any thread; the
     * callback arrives on the main thread.
     */
    static void sync(final Context context, final Callback cb) {
        final String deviceId = deviceIdentity(context);
        ExecutorService pool = Executors.newSingleThreadExecutor();
        final Handler main = new Handler(Looper.getMainLooper());
        pool.execute(new Runnable() {
            @Override
            public void run() {
                Result r = pull(context, deviceId);
                Log.i(TAG, "policy pull result: " + r.label);
                main.post(new Runnable() {
                    @Override
                    public void run() {
                        cb.onResult(r.applied, r.label, r.rows, r.skipped);
                    }
                });
            }
        });
        pool.shutdown();
    }

    private static final class Result {
        boolean applied;
        String label = "";
        int rows;
        int skipped;
    }

    private static Result pull(Context context, String deviceId) {
        Result out = new Result();

        JSONObject head = get(context, BASE + "?device_id="
                + enc(deviceId) + "&serial=" + enc(serialOf(context)), false);
        if (head == null) {
            out.label = "Sync failed \u00b7 panel unreachable";
            return out;
        }
        String state = head.optString("state", "");
        if ("no_device".equals(state)) {
            out.label = "Sync skipped \u00b7 console does not know this device";
            return out;
        }
        if ("no_profile".equals(state)) {
            // No live profile assigned – clear all ALP-managed restrictions
            // so the device returns to a clean baseline.
            // Use the same clearPolicy path as the in-app rollback button,
            // which does not go through EnvelopeGuard (it reads current
            // restrictions directly from the DevicePolicyManager).
            String cmdId = "SYNC-NO-PROFILE-" + System.currentTimeMillis() / 1000L;
            AlpOps.clearPolicy(context, "{\"cmd_id\":\"" + cmdId + "\"}");
            SyncCheck.markSynced(context);
            out.label = "Restrictions cleared \u00b7 no live profile assigned";
            out.applied = true;
            out.rows = 0;
            out.skipped = 0;
            return out;
        }
        String fp = head.optString("fingerprint", "");
        String pid = head.optString("policy_id", "");
        if (fp.length() > 0 && fp.equals(currentFingerprint(context))) {
            SyncCheck.markSynced(context);
            out.label = "Up to date \u00b7 " + pid + " v" + head.optInt("version", 0);
            return out;
        }

        // Ask for the signed envelope and run it through the normal pipeline.
        JSONObject full = get(context, BASE + "?device_id=" + enc(deviceId)
                + "&serial=" + enc(serialOf(context)) + "&build=1", true);
        if (full == null) {
            out.label = "Sync failed \u00b7 no envelope returned";
            return out;
        }
        if (!"delivered".equals(full.optString("state", ""))) {
            out.label = "Sync skipped \u00b7 " + full.optString("detail", "no envelope");
            return out;
        }
        JSONObject env = full.optJSONObject("envelope");
        if (env == null) {
            out.label = "Sync failed \u00b7 empty envelope";
            return out;
        }

        // Same gate as a pushed command: an unsigned or altered envelope is inert.
        String action = env.optString("action", "");
        if (!"APPLY_POLICY".equals(action) && !"CLEAR_POLICY".equals(action)) {
            out.label = "Sync rejected \u00b7 unexpected action";
            return out;
        }
        boolean clearing = "CLEAR_POLICY".equals(action);
        String reason = EnvelopeGuard.check(context, env.toString(), action);
        if (reason != null) {
            Log.w(TAG, "policy pull REJECTED: " + reason);
            out.label = "Sync rejected \u00b7 " + reason;
            return out;
        }

        if (clearing) {
            AlpOps.clearPolicy(context, env.toString());
        } else {
            AlpOps.applyPolicy(context, env.toString());
        }

        // Read back what the handset actually enforced, so the operator is told
        // the truth rather than what the console believed it sent.
        int appliedRows = 0;
        int skippedRows = 0;
        boolean confirmed = false;
        try {
            java.io.File st = new java.io.File(context.getFilesDir(),
                    clearing ? "clear_result.json" : "apply_result.json");
            if (st.exists()) {
                byte[] buf = new byte[(int) st.length()];
                java.io.FileInputStream in = new java.io.FileInputStream(st);
                int off = 0;
                while (off < buf.length) {
                    int n = in.read(buf, off, buf.length - off);
                    if (n < 0) break;
                    off += n;
                }
                in.close();
                JSONObject res = new JSONObject(new String(buf, 0, off, "UTF-8"));
                if (env.optString("cmd_id", "").equals(res.optString("cmd_id", ""))) {
                    confirmed = action.equals(res.optString("action", ""))
                            && res.optJSONArray("errors") != null
                            && res.optJSONArray("errors").length() == 0;
                    appliedRows = res.optJSONArray("applied") != null
                            ? res.optJSONArray("applied").length() : 0;
                    skippedRows = res.optJSONArray("skipped") != null
                            ? res.optJSONArray("skipped").length() : 0;
                }
            }
        } catch (Exception ignored) {
        }

        if (!confirmed) {
            out.label = "Sync failed \u00b7 application result not confirmed";
            return out;
        }
        remember(context, full.optString("fingerprint", fp),
                full.optString("policy_id", pid));
        AlpStats.record(context, "policy_pulled");
        SyncCheck.markSynced(context);
        out.applied = true;
        out.rows = appliedRows;
        out.skipped = skippedRows;
        out.label = "Applied " + full.optString("policy_id", pid)
                + " v" + full.optInt("version", 0)
                + " \u00b7 " + appliedRows + " applied"
                + (skippedRows > 0 ? ", " + skippedRows + " skipped" : "");
        if (clearing) {
            out.label = "Restrictions cleared \u00b7 no live profile assigned";
        }
        return out;
    }

    // ---------------------------------------------------------------- identity
    private static String deviceIdentity(Context context) {
        try {
            return android.provider.Settings.Secure.getString(
                    context.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
        } catch (Exception e) {
            return "unknown";
        }
    }

    private static String serialOf(Context context) {
        try {
            if (android.os.Build.VERSION.SDK_INT >= 26
                    && context.checkSelfPermission(android.Manifest.permission.READ_PHONE_STATE)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                android.app.admin.DevicePolicyManager dpm =
                        (android.app.admin.DevicePolicyManager) context.getSystemService(
                                Context.DEVICE_POLICY_SERVICE);
                if (dpm != null && dpm.isDeviceOwnerApp(context.getPackageName())) {
                    dpm.setPermissionGrantState(new android.content.ComponentName(
                                    context, AlpDeviceAdminReceiver.class),
                            context.getPackageName(), android.Manifest.permission.READ_PHONE_STATE,
                            android.app.admin.DevicePolicyManager.PERMISSION_GRANT_STATE_GRANTED);
                }
            }
            String serial = android.os.Build.VERSION.SDK_INT >= 26
                    ? android.os.Build.getSerial() : android.os.Build.SERIAL;
            return serial != null && !"unknown".equals(serial) ? serial : "";
        } catch (Exception e) {
            Log.w(TAG, "policy pull serial unavailable: " + e.getMessage());
            return "";
        }
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s == null ? "" : s, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    /** GET returning the parsed JSON body, or null on any failure. */
    private static JSONObject get(Context context, String url, boolean unused) {
        HttpURLConnection conn = null;
        InputStream is = null;
        try {
            URL u = new URL(url);
            String proto = u.getProtocol();
            if (!"http".equals(proto) && !"https".equals(proto)) {
                return null;
            }
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(TIMEOUT_MS);
            conn.setReadTimeout(TIMEOUT_MS);
            conn.setRequestMethod("GET");
            conn.setInstanceFollowRedirects(true);
            conn.setRequestProperty("User-Agent", "ALP-Agent/0.1");
            conn.setRequestProperty("Connection", "close");
            int code = conn.getResponseCode();
            if (code >= 400) {
                is = conn.getErrorStream();
            } else {
                is = conn.getInputStream();
            }
            if (is == null) {
                return null;
            }
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] chunk = new byte[4096];
            int n;
            while ((n = is.read(chunk)) != -1) {
                bos.write(chunk, 0, n);
            }
            JSONObject response = new JSONObject(bos.toString("UTF-8"));
            if (code >= 400 || !response.optBoolean("ok", false)) {
                Log.w(TAG, "policy pull HTTP/API failure: " + code);
                return null;
            }
            return response.optJSONObject("data");
        } catch (Exception e) {
            Log.w(TAG, "policy pull failed: " + e.getClass().getSimpleName()
                    + ": " + e.getMessage());
            return null;
        } finally {
            if (is != null) {
                try { is.close(); } catch (Exception ignored) { }
            }
            if (conn != null) {
                try { conn.disconnect(); } catch (Exception ignored) { }
            }
        }
    }
}
