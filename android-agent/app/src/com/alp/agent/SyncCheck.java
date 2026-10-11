package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Reachability check against the LOCAL control panel.
 *
 * This agent holds no internet path and joins no Wi-Fi: the link is reverse
 * USB tethering (gnirehtet), which forwards device traffic to the host over
 * the USB cable. gnirehtet maps 10.0.2.2 to the host's localhost (its own
 * `run` help states: "10.0.2.2 is mapped to the host 'localhost'"), so the
 * panel answers on 10.0.2.2:8765 through the USB cable alone - no wireless
 * broadcast, no upstream network.
 *
 * Verified on the bench: the handset pings 10.0.0.2 (its own tun address) but
 * the host alias for the panel is 10.0.2.2.
 *
 * The address is a hard-coded constant - never a console-provisioned or
 * remote one - so this class cannot be steered onto an internet path. A
 * timestamp is recorded ONLY on a successful response, so the displayed
 * "last sync" never advances when the check fails.
 */
final class SyncCheck {

    static final String PREFS = "alp_stats";
    static final String K_LAST_SYNC = "alp_last_sync_at";

    /**
     * The ONLY address this agent ever dials: the local control plane,
     * reached through the USB tether. gnirehtet maps 10.0.2.2 to the host's
     * localhost (same convention as the Android emulator), so nothing here
     * can leave the USB link - there is deliberately no console override,
     * because a remote URL would be an internet path this agent must not have.
     */
    static final String DEFAULT_URL = "http://10.0.2.2:8765/api/v1/health";

    private static final int TIMEOUT_MS = 6000;

    interface Callback {
        void onResult(boolean reachable, String label);
    }

    private SyncCheck() {
    }

    /** ISO-8601 UTC of the last SUCCESSFUL check, or "" when never synced. */
    static String lastSyncAt(Context context) {
        try {
            SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            String v = p.getString(K_LAST_SYNC, "");
            return v == null ? "" : v;
        } catch (Exception e) {
            return "";
        }
    }

    /** Record a successful probe or policy synchronization, never a failure. */
    static void markSynced(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString(K_LAST_SYNC, AlpOps.utcNow())
                .apply();
    }

    /** Run the probe off the UI thread and report back on the main thread. */
    static void check(final Context context, final Callback cb) {
        final String url = DEFAULT_URL;
        ExecutorService pool = Executors.newSingleThreadExecutor();
        final Handler main = new Handler(Looper.getMainLooper());
        pool.execute(new Runnable() {
            @Override
            public void run() {
                final int status = probe(url);
                final boolean ok = status > 0 && status < 500;
                main.post(new Runnable() {
                    @Override
                    public void run() {
                        if (ok) {
                            markSynced(context);
                            cb.onResult(true, "Synced \u00b7 HTTP " + status);
                        } else if (status > 0) {
                            cb.onResult(false, "Sync failed \u00b7 HTTP " + status);
                        } else {
                            cb.onResult(false, "Sync failed \u00b7 unreachable");
                        }
                    }
                });
            }
        });
        pool.shutdown();
    }

    /**
     * @return HTTP status code, or 0 when the panel could not be reached.
     */
    private static int probe(String rawUrl) {
        HttpURLConnection conn = null;
        java.io.InputStream is = null;
        try {
            URL u = new URL(rawUrl);
            if (!"http".equals(u.getProtocol()) && !"https".equals(u.getProtocol())) {
                return 0;
            }
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(TIMEOUT_MS);
            conn.setReadTimeout(TIMEOUT_MS);
            conn.setRequestMethod("GET");
            conn.setInstanceFollowRedirects(true);
            conn.setRequestProperty("User-Agent", "ALP-Agent/0.1");
            conn.setRequestProperty("Connection", "close");
            int code = conn.getResponseCode();
            try {
                is = (code >= 400) ? conn.getErrorStream() : conn.getInputStream();
                if (is != null) {
                    byte[] buf = new byte[256];
                    while (is.read(buf) != -1) {
                    }
                }
            } catch (Exception ignored) {
            }
            return code;
        } catch (Exception e) {
            android.util.Log.w("ALP", "sync probe failed: "
                    + e.getClass().getSimpleName() + ": " + e.getMessage());
            return 0;
        } finally {
            if (is != null) {
                try {
                    is.close();
                } catch (Exception ignored) {
                }
            }
            if (conn != null) {
                try {
                    conn.disconnect();
                } catch (Exception ignored) {
                }
            }
        }
    }
}
