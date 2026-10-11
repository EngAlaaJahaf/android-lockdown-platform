package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.util.Log;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Persistent storage for the DevicePolicyManager reset-password token.
 *
 * resetPasswordWithToken() only accepts a token the DPC itself registered with
 * setResetPasswordToken(), and is the ONLY way a device owner can change the
 * screen lock on Android 11+ (resetPassword() is refused outright for apps
 * targeting API 24+). The token must therefore be minted once and kept: minting
 * it at recovery time is useless, because a fresh token is not yet active.
 *
 * The token is the capability that lets this app clear or replace the passcode,
 * so it is stored encrypted rather than in the clear. The AES key lives in the
 * Android keystore (non-exportable, hardware-backed where the device has it),
 * which means the ciphertext in shared_prefs is useless if it is copied off
 * the handset — unlike the recovery-key secret, which must stay readable so
 * the agent can derive codes with no console connection.
 */
final class ResetTokenStore {
    private ResetTokenStore() {
    }

    private static final String TAG = "ALP_Recovery";
    private static final String PREFS = "alp_reset_token";
    private static final String K_CT = "token_ct";
    private static final String KS_ALIAS = "alp_reset_token_key";
    private static final String TRANSFORM = "AES/GCM/NoPadding";
    private static final int TOKEN_LEN = 32;

    /**
     * The registered token, creating and persisting one on first use.
     *
     * @return the 32 raw bytes, or null when no keystore is available (API 23
     *         and below cannot hold a non-exportable key).
     */
    static byte[] token(Context context) {
        SharedPreferences p = prefs(context);
        String stored = p.getString(K_CT, null);
        if (stored != null) {
            byte[] plain = decrypt(context, stored);
            if (plain != null && plain.length == TOKEN_LEN) {
                return plain;
            }
            // Keystore key lost or invalidated (e.g. after a restore): drop the
            // stale ciphertext and mint a new token rather than failing later.
            Log.w(TAG, "reset token unreadable — re-minting");
        }
        byte[] fresh = new byte[TOKEN_LEN];
        new SecureRandom().nextBytes(fresh);
        String ct = encrypt(context, fresh);
        if (ct != null) {
            p.edit().putString(K_CT, ct).apply();
        }
        return fresh;
    }

    /** Whether a token has already been persisted on this device. */
    static boolean hasToken(Context context) {
        return prefs(context).getString(K_CT, null) != null;
    }

    /**
     * Overwrite the stored token.
     *
     * Used when the platform rejected the first token as inactive: the DPC
     * re-registers, so the copy kept here must be the same bytes that were
     * accepted, or every later resetPasswordWithToken() would fail.
     */
    static void replace(Context context, byte[] token) {
        String ct = encrypt(context, token);
        if (ct != null) {
            prefs(context).edit().putString(K_CT, ct).apply();
        }
    }

    static void clear(Context context) {
        prefs(context).edit().remove(K_CT).apply();
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static SecretKey key(Context context) {
        try {
            KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
            ks.load(null);
            KeyStore.Entry e = ks.getEntry(KS_ALIAS, null);
            if (e instanceof KeyStore.SecretKeyEntry) {
                return ((KeyStore.SecretKeyEntry) e).getSecretKey();
            }
            KeyGenerator kg = KeyGenerator.getInstance(
                    KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            kg.init(new KeyGenParameterSpec.Builder(KS_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build());
            return kg.generateKey();
        } catch (Exception e) {
            Log.w(TAG, "keystore unavailable: " + e.getClass().getSimpleName());
            return null;
        }
    }

    private static String encrypt(Context context, byte[] plain) {
        try {
            SecretKey k = key(context);
            if (k == null) {
                return null;
            }
            Cipher c = Cipher.getInstance(TRANSFORM);
            c.init(Cipher.ENCRYPT_MODE, k);
            byte[] iv = c.getIV();
            byte[] out = c.doFinal(plain);
            byte[] packed = new byte[iv.length + out.length];
            System.arraycopy(iv, 0, packed, 0, iv.length);
            System.arraycopy(out, 0, packed, iv.length, out.length);
            return Base64.encodeToString(packed, Base64.NO_WRAP);
        } catch (Exception e) {
            Log.w(TAG, "token encrypt failed: " + e.getClass().getSimpleName());
            return null;
        }
    }

    private static byte[] decrypt(Context context, String b64) {
        try {
            SecretKey k = key(context);
            if (k == null) {
                return null;
            }
            byte[] packed = Base64.decode(b64, Base64.NO_WRAP);
            int ivLen = 12;
            if (packed.length <= ivLen) {
                return null;
            }
            byte[] iv = new byte[ivLen];
            System.arraycopy(packed, 0, iv, 0, ivLen);
            byte[] body = new byte[packed.length - ivLen];
            System.arraycopy(packed, ivLen, body, 0, body.length);
            Cipher c = Cipher.getInstance(TRANSFORM);
            c.init(Cipher.DECRYPT_MODE, k, new GCMParameterSpec(128, iv));
            return c.doFinal(body);
        } catch (Exception e) {
            Log.w(TAG, "token decrypt failed: " + e.getClass().getSimpleName());
            return null;
        }
    }
}