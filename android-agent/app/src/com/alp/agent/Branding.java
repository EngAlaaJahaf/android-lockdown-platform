package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.json.JSONObject;

/**
 * Server-driven in-app branding: the ManageEngine-style "rebranding" that
 * works without rebuilding. This covers ONLY the logo shown INSIDE the app
 * (Home header) - the launcher icon can never change at runtime on stock
 * Android (Samsung Knox aside), so no code here even attempts it.
 *
 * Flow: after a successful Sync the agent asks GET /api/v1/branding for the
 * current logo version; when it differs from the cached one the PNG is
 * downloaded (same USB-tethered host, size-capped, magic-checked) and stored
 * under the app files dir. A failed fetch keeps the previous logo, so the
 * header can never break or blank out because of the network.
 */
final class Branding {

    static final String PREFS = "alp_stats";
    static final String K_VER = "alp_brand_ver";

    static final String HOST = "http://10.0.2.2:8765";
    static final String INFO_PATH = "/api/v1/branding";

    private static final int TIMEOUT_MS = 6000;
    private static final int MAX_BYTES = 512 * 1024;
    private static final byte[] PNG_MAGIC =
            {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', (byte) 0x1A, '\n'};

    interface Callback {
        void onDone(boolean changed);
    }

    private Branding() {
    }

    /** Cached logo file, or where it will live after the first Sync. */
    static File logoFile(Context context) {
        return new File(new File(context.getFilesDir(), "branding"), "logo.png");
    }

    /** Version string of the cached logo, or "" when never fetched. */
    static String version(Context context) {
        try {
            SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            String v = p.getString(K_VER, "");
            return v == null ? "" : v;
        } catch (Exception e) {
            return "";
        }
    }

    /** Refresh off the UI thread; reports back on the main thread. */
    static void refresh(final Context context, final Callback cb) {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        final Handler main = new Handler(Looper.getMainLooper());
        pool.execute(new Runnable() {
            @Override
            public void run() {
                final boolean changed = doRefresh(context);
                main.post(new Runnable() {
                    @Override
                    public void run() {
                        cb.onDone(changed);
                    }
                });
            }
        });
        pool.shutdown();
    }

    private static boolean doRefresh(Context context) {
        try {
            String body = getText(HOST + INFO_PATH);
            if (body == null) {
                return false;
            }
            JSONObject info = new JSONObject(body);
            if (!info.optBoolean("ok", false)) {
                return false;
            }
            JSONObject data = info.optJSONObject("data");
            if (data == null) {
                return false;
            }
            String ver = data.optString("version", "");
            String url = data.optString("logo_url", "");
            if (ver.isEmpty() || url.isEmpty()) {
                return false;
            }
            if (ver.equals(version(context)) && logoFile(context).exists()) {
                return false;
            }
            byte[] png = getBytes(HOST + url);
            if (png == null || png.length < 33 || png.length > MAX_BYTES) {
                return false;
            }
            for (int i = 0; i < PNG_MAGIC.length; i++) {
                if (png[i] != PNG_MAGIC[i]) {
                    return false;
                }
            }
            File dest = logoFile(context);
            File dir = dest.getParentFile();
            if (dir != null) {
                dir.mkdirs();
            }
            File tmp = new File(dir, "logo.tmp");
            FileOutputStream fos = new FileOutputStream(tmp);
            try {
                fos.write(png);
            } finally {
                fos.close();
            }
            if (!tmp.renameTo(dest)) {
                tmp.delete();
                return false;
            }
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                    .putString(K_VER, ver)
                    .apply();
            return true;
        } catch (Exception e) {
            android.util.Log.w("ALP", "branding refresh failed: "
                    + e.getClass().getSimpleName());
            return false;
        }
    }

    private static HttpURLConnection open(String rawUrl) throws Exception {
        URL u = new URL(rawUrl);
        if (!"http".equals(u.getProtocol()) && !"https".equals(u.getProtocol())) {
            throw new IllegalArgumentException("bad protocol");
        }
        HttpURLConnection conn = (HttpURLConnection) u.openConnection();
        conn.setConnectTimeout(TIMEOUT_MS);
        conn.setReadTimeout(TIMEOUT_MS);
        conn.setRequestMethod("GET");
        conn.setInstanceFollowRedirects(true);
        conn.setRequestProperty("User-Agent", "ALP-Agent/0.1");
        conn.setRequestProperty("Connection", "close");
        return conn;
    }

    private static byte[] readCapped(HttpURLConnection conn) throws Exception {
        InputStream is = null;
        try {
            int code = conn.getResponseCode();
            is = (code >= 400) ? conn.getErrorStream() : conn.getInputStream();
            if (code >= 400 || is == null) {
                return null;
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int total = 0;
            while (true) {
                int n = is.read(buf);
                if (n < 0) {
                    break;
                }
                total += n;
                if (total > MAX_BYTES + 1) {
                    return null;
                }
                out.write(buf, 0, n);
            }
            return out.toByteArray();
        } finally {
            if (is != null) {
                try {
                    is.close();
                } catch (Exception ignored) {
                }
            }
            try {
                conn.disconnect();
            } catch (Exception ignored) {
            }
        }
    }

    private static String getText(String rawUrl) {
        try {
            HttpURLConnection conn = open(rawUrl);
            byte[] data = readCapped(conn);
            if (data == null) {
                return null;
            }
            return new String(data, "UTF-8");
        } catch (Exception e) {
            return null;
        }
    }

    private static byte[] getBytes(String rawUrl) {
        try {
            HttpURLConnection conn = open(rawUrl);
            return readCapped(conn);
        } catch (Exception e) {
            return null;
        }
    }
}
