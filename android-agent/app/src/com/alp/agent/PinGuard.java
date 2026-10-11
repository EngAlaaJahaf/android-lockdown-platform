package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import java.security.SecureRandom;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/**
 * Device-bound unlock PIN. Provisioned ONLY via a signed PROVISION_PIN envelope
 * from the console (never typed directly into a datastore a local app can
 * write). Stored as a PBKDF2 hash with a per-device salt; five consecutive
 * mistakes lock the rollback button for a backoff window (5 min, doubling, cap
 * 1 h). The PIN gives the admin an offline release path WITHOUT a forged
 * command — the rollback button stays but is useless to anyone who does not
 * know the console-provisioned PIN.
 */
final class PinGuard {
    private PinGuard() {
    }

    private static final String TAG = "ALP";
    private static final String PREFS = "alp_stats";
    private static final int MAX_FAILS = 5;
    private static final long BASE_LOCK_MS = 5 * 60 * 1000L;
    private static final long CAP_LOCK_MS = 60 * 60 * 1000L;
    private static final int ITERATIONS = 100_000;
    private static final int KEY_BYTES = 32;

    // Keys in 'alp_stats'.
    private static final String K_SALT = "pin_salt_b64";
    private static final String K_HASH = "pin_hash_b64";
    private static final String K_FAILS = "pin_fails";
    private static final String K_LOCK_UNTIL = "pin_lock_until";
    private static final String K_LOCKOUTS = "pin_lockouts";

    static boolean configured(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return p.contains(K_SALT) && p.contains(K_HASH);
    }

    /**
     * @return null on success, else a reason string.
     */
    static String provision(Context context, String envelopeJson) {
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
            return "malformed json";
        }
        Object bodyObj = env.get("body");
        java.util.Map<String, Object> body = CanonicalJson.asMap(bodyObj);
        if (body == null) {
            return "missing pin body";
        }
        String pin = CanonicalJson.asString(body.get("pin"));
        if (pin == null || pin.length() < 4 || pin.length() > 12
                || !pin.matches("[0-9]+")) {
            return "bad pin format";
        }
        try {
            byte[] salt = new byte[16];
            new SecureRandom().nextBytes(salt);
            byte[] hash = pbkdf2(pin, salt, ITERATIONS, KEY_BYTES);
            SharedPreferences.Editor e = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .edit();
            e.putString(K_SALT, Base64.encodeToString(salt, Base64.NO_WRAP));
            e.putString(K_HASH, Base64.encodeToString(hash, Base64.NO_WRAP));
            e.putInt(K_FAILS, 0);
            e.putLong(K_LOCK_UNTIL, 0L);
            e.putInt(K_LOCKOUTS, 0);
            e.apply();
            AlpStats.record(context, "pin_provisioned");
            return null;
        } catch (Exception ex) {
            android.util.Log.e(TAG, "pin provision failed", ex);
            return "provision error";
        }
    }

    /**
     * @return null when the PIN opens the rollback, else a reason string.
     */
    static String verify(Context context, String pin) {
        if (pin == null || pin.isEmpty()) {
            return "enter pin";
        }
        if (!configured(context)) {
            return "pin not configured";
        }
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long now = System.currentTimeMillis();
        long lockUntil = p.getLong(K_LOCK_UNTIL, 0L);
        if (now < lockUntil) {
            return "locked: retry in " + ((lockUntil - now) / 1000L) + "s";
        }
        try {
            byte[] salt = Base64.decode(p.getString(K_SALT, ""), Base64.NO_WRAP);
            byte[] want = Base64.decode(p.getString(K_HASH, ""), Base64.NO_WRAP);
            byte[] got = pbkdf2(pin, salt, ITERATIONS, KEY_BYTES);
            if (Cmp.equals(want, got)) {
                p.edit()
                        .putInt(K_FAILS, 0)
                        .putLong(K_LOCK_UNTIL, 0L)
                        .putInt(K_LOCKOUTS, 0)
                        .apply();
                AlpStats.record(context, "pin_ok");
                return null;
            }
        } catch (Exception ex) {
            android.util.Log.e(TAG, "pin verify error", ex);
            return "verify error";
        }
        int fails = p.getInt(K_FAILS, 0) + 1;
        if (fails >= MAX_FAILS) {
            int lockouts = p.getInt(K_LOCKOUTS, 0) + 1;
            long backoff = Math.min(CAP_LOCK_MS, BASE_LOCK_MS << (lockouts - 1));
            p.edit()
                    .putInt(K_FAILS, fails)
                    .putLong(K_LOCK_UNTIL, now + backoff)
                    .putInt(K_LOCKOUTS, lockouts)
                    .apply();
            AlpStats.record(context, "pin_locked");
            return "locked: retry in " + (backoff / 1000L) + "s";
        }
        p.edit().putInt(K_FAILS, fails).apply();
        AlpStats.record(context, "pin_fail");
        int left = MAX_FAILS - fails;
        return left <= 0 ? "locked" : "wrong pin (" + left + " tries left)";
    }

    /** Remaining lockout delay in seconds for the UI, 0 when not locked. */
    static long lockRemainingSeconds(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long until = p.getLong(K_LOCK_UNTIL, 0L);
        long remain = until - System.currentTimeMillis();
        return remain > 0 ? remain / 1000L : 0L;
    }

    static int fails(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getInt(K_FAILS, 0);
    }

    private static byte[] pbkdf2(String pin, byte[] salt, int iters, int len)
            throws Exception {
        // PBKDF2WithHmacSHA1 covers every API >= 24 (SHA256 variant needs 26+).
        SecretKeyFactory f = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA1");
        PBEKeySpec spec = new PBEKeySpec(pin.toCharArray(), salt, iters, len * 8);
        return f.generateSecret(spec).getEncoded();
    }
}