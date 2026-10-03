package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * Android-side envelope gate: loads the embedded Ed25519 PUBLIC key and the
 * replay store, then delegates the cryptographic verification to
 * EnvelopeGuardCore (kept Android-free so the identical code path is compiled
 * and exercised on a plain JVM by the self-check harness).
 *
 * The private key never exists on the device, so even a rooted user cannot
 * forge an unlock/rollback command.
 */
final class EnvelopeGuard {
    private EnvelopeGuard() {
    }

    static final String TAG = "ALP";
    private static final String PREFS_REPLAY = "alp_guard";

    private static byte[] publicKey = null;

    /** 32-byte public key embedded at build time (hex text in a raw asset). */
    static synchronized byte[] publicKey(Context context) {
        if (publicKey == null) {
            try {
                InputStream is = context.getResources().openRawResource(R.raw.alp_pubkey);
                byte[] hex = new byte[is.available()];
                if (is.read(hex) != hex.length || is.available() > 0) {
                    throw new IllegalStateException("truncated pubkey asset");
                }
                is.close();
                publicKey = EnvelopeGuardCore.fromHex(new String(hex, StandardCharsets.US_ASCII));
            } catch (Exception e) {
                android.util.Log.e(TAG, "unable to load embedded public key", e);
                publicKey = new byte[0];
            }
        }
        return publicKey;
    }

    /**
     * @return null when the envelope is authorized, else a rejection reason.
     */
    static String check(Context context, String envelopeJson, String action) {
        String reason = EnvelopeGuardCore.check(envelopeJson, action, publicKey(context));
        if (reason != null) {
            return reason;
        }
        // Authorized — now guard against replays with a per-cmd_id nonce store.
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
        String cmdId = CanonicalJson.asString(env.get("cmd_id"));
        String nonce = CanonicalJson.asString(env.get("nonce"));
        if (!consumeNonce(context, cmdId, nonce)) {
            return "replay";
        }
        return null;
    }

    /**
     * Reject a nonce/cmd_id pair already consumed (matches the server-side
     * one-time-use store in backend/command.py).
     */
    private static boolean consumeNonce(Context context, String cmdId, String nonce) {
        if (cmdId == null || nonce == null) {
            return false;
        }
        SharedPreferences prefs =
                context.getSharedPreferences(PREFS_REPLAY, Context.MODE_PRIVATE);
        String remembered = prefs.getString("v2_" + cmdId, null);
        if (nonce.equals(remembered)) {
            return false; // replay
        }
        prefs.edit().putString("v2_" + cmdId, nonce).apply();
        trimReplayStore(prefs);
        return true;
    }

    private static void trimReplayStore(SharedPreferences prefs) {
        if (prefs.getAll().size() < 2000) {
            return;
        }
        SharedPreferences.Editor ed = prefs.edit();
        for (String k : prefs.getAll().keySet()) {
            ed.remove(k);
        }
        ed.commit(); // sync: called off the hot path only
    }
}