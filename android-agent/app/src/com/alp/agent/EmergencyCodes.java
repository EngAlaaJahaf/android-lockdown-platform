package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * Offline emergency codes — the memdm "Device Access Recovery Key" logic.
 *
 * One random per-device secret is exchanged while a trusted channel exists
 * (provisioned from the console inside a SIGNED envelope, exactly like the
 * rollback PIN). Afterwards either side derives the same time-bound code
 * with NO channel at all:
 *
 *   code = truncate(HMAC-SHA256(secret, "ALP-EMG-V1" || purpose || counter))
 *   counter = floor(unix_time / 300), 8 decimal digits, RFC-4226-style
 *   dynamic truncation.
 *
 * This MUST stay byte-identical to backend/emergency.py (_offline_code_for);
 * the cross-implementation vector test pins the formula, and any drift here
 * silently breaks offline verification. Accepted windows: current ±1 step
 * (wrong phone clocks tolerated). Each (purpose, counter) burns after first
 * use, so a shoulder-surfed code cannot be replayed later in its window.
 * Five consecutive mistakes lock code entry with the same backoff as the PIN.
 *
 * Purposes mirror the console: "rollback" lifts restrictions,
 * "withdraw_uninstall" additionally drops Device Owner so the package can
 * be uninstalled with no cable and no network.
 */
final class EmergencyCodes {
    private EmergencyCodes() {
    }

    static final long STEP_SECONDS = 300L;
    static final int WINDOW = 1;
    static final int DIGITS = 8;

    private static final String PREFS = "alp_emergency";
    private static final String K_SECRET = "secret_b64";
    private static final String K_USED = "used_counters";
    private static final String K_FAILS = "fails";
    private static final String K_LOCK_UNTIL = "lock_until";
    private static final int MAX_FAILS = 5;
    private static final long BASE_LOCK_MS = 5 * 60 * 1000L;
    private static final long CAP_LOCK_MS = 60 * 60 * 1000L;

    static boolean configured(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return p.contains(K_SECRET);
    }

    static long counterFor(long nowMs) {
        return nowMs / 1000L / STEP_SECONDS;
    }

    static String codeFor(byte[] secret, String purpose, long counter) {
        try {
            byte[] purposeBytes = purpose.getBytes(StandardCharsets.UTF_8);
            byte[] domain = "ALP-EMG-V1".getBytes(StandardCharsets.US_ASCII);
            ByteBuffer msg = ByteBuffer.allocate(
                    domain.length + purposeBytes.length + 8);
            msg.order(ByteOrder.BIG_ENDIAN);
            msg.put(domain);
            msg.put(purposeBytes);
            msg.putLong(counter);
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            byte[] digest = mac.doFinal(msg.array());
            int offset = digest[digest.length - 1] & 0x0F;
            int code = ((digest[offset] & 0x7F) << 24)
                    | ((digest[offset + 1] & 0xFF) << 16)
                    | ((digest[offset + 2] & 0xFF) << 8)
                    | (digest[offset + 3] & 0xFF);
            int mod = 1;
            for (int i = 0; i < DIGITS; i++) {
                mod *= 10;
            }
            String s = Integer.toString(code % mod);
            while (s.length() < DIGITS) {
                s = "0" + s;
            }
            return s;
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * Store the console-provisioned secret from a signed envelope.
     *
     * @return null on success, else a reason string.
     */
    static String storeSecret(Context context, String envelopeJson) {
        if (envelopeJson == null) {
            return "missing envelope";
        }
        final Object root;
        try {
            root = CanonicalJson.parse(envelopeJson);
        } catch (IllegalArgumentException e) {
            return "malformed json";
        }
        java.util.Map<String, Object> env = CanonicalJson.asMap(root);
        if (env == null) {
            return "malformed envelope";
        }
        Object bodyObj = env.get("body");
        java.util.Map<String, Object> body = CanonicalJson.asMap(bodyObj);
        if (body == null) {
            return "missing secret body";
        }
        String b64 = CanonicalJson.asString(body.get("secret_b64"));
        if (b64 == null || b64.isEmpty()) {
            return "envelope has no secret_b64";
        }
        byte[] secret;
        try {
            secret = Base64.decode(b64, Base64.DEFAULT);
        } catch (IllegalArgumentException e) {
            return "secret is not base64";
        }
        if (secret == null || secret.length < 16) {
            return "secret too short";
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString(K_SECRET, Base64.encodeToString(secret, Base64.NO_WRAP))
                .apply();
        android.util.Log.d("ALP", "emergency secret provisioned");
        return null;
    }

    static long lockRemainingSeconds(Context context) {
        long until = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getLong(K_LOCK_UNTIL, 0L);
        long left = until - System.currentTimeMillis();
        return left > 0 ? (left + 999L) / 1000L : 0L;
    }

    static int fails(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getInt(K_FAILS, 0);
    }

    private static void recordFail(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        int fails = p.getInt(K_FAILS, 0) + 1;
        SharedPreferences.Editor ed = p.edit().putInt(K_FAILS, fails);
        if (fails >= MAX_FAILS) {
            int lockouts = p.getInt("lockouts", 0);
            long backoff = Math.min(BASE_LOCK_MS << lockouts, CAP_LOCK_MS);
            ed.putLong(K_LOCK_UNTIL, System.currentTimeMillis() + backoff);
            ed.putInt("lockouts", lockouts + 1);
        }
        ed.apply();
    }

    private static void resetFails(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putInt(K_FAILS, 0).putInt("lockouts", 0)
                .putLong(K_LOCK_UNTIL, 0L).apply();
    }

    /**
     * Verify a typed code for a purpose.
     *
     * @return null on success (counter burned), else a user-facing reason.
     */
    static String verify(Context context, String purpose, String code) {
        if (!"rollback".equals(purpose) && !"withdraw_uninstall".equals(purpose)
                && !"pause_kiosk".equals(purpose) && !"reset_password".equals(purpose)) {
            return "unsupported purpose on this build";
        }
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String b64 = p.getString(K_SECRET, null);
        if (b64 == null) {
            return "no emergency secret on this device";
        }
        long lockedFor = lockRemainingSeconds(context);
        if (lockedFor > 0) {
            return "locked — retry later";
        }
        byte[] secret;
        try {
            secret = Base64.decode(b64, Base64.DEFAULT);
        } catch (IllegalArgumentException e) {
            return "secret store corrupt";
        }
        String want = (code == null ? "" : code.trim());
        long now = counterFor(System.currentTimeMillis());
        Set<String> used = new HashSet<>(p.getStringSet(K_USED, new HashSet<String>()));
        for (long c = now - WINDOW; c <= now + WINDOW; c++) {
            String mark = purpose + ":" + c;
            if (used.contains(mark)) {
                continue;
            }
            String expect = codeFor(secret, purpose, c);
            if (expect != null && constantEquals(expect, want)) {
                used.add(mark);
                p.edit().putStringSet(K_USED, used).apply();
                resetFails(context);
                android.util.Log.d("ALP", "emergency code accepted purpose="
                        + purpose + " counter=" + c);
                return null;
            }
        }
        recordFail(context);
        return "wrong code";
    }

    private static boolean constantEquals(String a, String b) {
        return Cmp.equals(a, b);
    }
}
