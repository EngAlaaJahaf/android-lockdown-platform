package com.alp.agent;

import android.app.KeyguardManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.Log;

/**
 * Passcode recovery controller — ManageEngine-style recovery challenge.
 *
 * When an admin configures `recovery_attempts = N` (1..10, default 3) in the profile:
 * - DeviceAdminReceiver.onPasswordFailed increments the failed-attempt counter.
 * - Once attempts >= N, the recovery challenge is armed.
 * - The agent launches PasswordRecoveryActivity above the lock screen and posts a persistent banner.
 * - Step 1: User verifies with the 8-digit emergency recovery key (purpose="reset_password").
 * - Step 2: User sets their new passcode directly in the UI, and the agent calls
 *   DevicePolicyManager.resetPassword() and unlocks the device without wiping data.
 */
public final class PasswordRecovery {
    private PasswordRecovery() {
    }

    private static final String TAG = "ALP_Recovery";
    public static final String PREFS = "alp_password_recovery";
    public static final String K_THRESHOLD = "threshold";
    public static final String K_FAILS = "failed_attempts";
    public static final String K_ARMED = "armed";
    // One-shot session gate: step 2 (applyNewPassword) refuses unless step 1
    // (verifyRecoveryCode) succeeded in THIS process session. The flag is
    // consumed on first use, so nothing can jump straight to setting a PIN —
    // not even by re-entering this screen — without a fresh valid code.
    private static final String K_STEP1_OK = "step1_verified";
    // Wall-clock stamp of that verification. The gate is not a bare boolean:
    // a failed reset used to consume it, which left the user locked out of the
    // screen they had legitimately unlocked. It now expires instead, so an
    // abandoned session cannot be resumed hours later.
    private static final String K_STEP1_AT = "step1_verified_at";
    private static final long GATE_TTL_MS = 5 * 60 * 1000L;
    private static final String NOTIF_CHANNEL_ID = "alp_passcode_recovery_channel";
    private static final int NOTIF_ID = 202601;

    /**
     * Returned by applyNewPassword when the platform no longer lets a DPC set
     * the credential itself and the user must finish in the system UI.
     *
     * From Android 11 on, resetPassword() throws SecurityException for any app
     * targeting API 24+ ("Device admin can no longer call resetPassword()"), so
     * handing off to ACTION_SET_NEW_PASSWORD is the only remaining route. It is
     * also the safer one: the user picks their own passcode in a system screen
     * instead of the DPC writing it.
     */
    public static final String SYSTEM_UI_REQUIRED = "__system_passcode_ui__";

    /**
     * Apply the console-configured threshold.
     *
     * The failed-attempt counter and the armed flag are deliberately PRESERVED
     * when the threshold has not changed. APPLY_POLICY is re-delivered on every
     * agent resume, and zeroing the counter here silently disarmed an armed
     * challenge: the user mistyped three times, the challenge appeared, and the
     * very next policy sync wiped the evidence and closed it.
     */
    public static void configure(Context context, int threshold) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        int finalThreshold = threshold <= 0 ? 0 : Math.min(10, threshold);
        int previous = p.getInt(K_THRESHOLD, -1);
        SharedPreferences.Editor ed = p.edit().putInt(K_THRESHOLD, finalThreshold);
        if (previous != finalThreshold) {
            // A genuinely new threshold starts a fresh window.
            ed.putInt(K_FAILS, 0).putBoolean(K_ARMED, false);
        }
        ed.apply();
        Log.d(TAG, "passcode recovery configured: threshold=" + finalThreshold
                + " previous=" + previous
                + " counter=" + p.getInt(K_FAILS, 0)
                + " armed=" + p.getBoolean(K_ARMED, false));
    }

    public static void clear(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        p.edit().clear().apply();
        cancelNotification(context);
        Log.d(TAG, "passcode recovery cleared");
    }

    public static int getThreshold(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return p.getInt(K_THRESHOLD, 3);
    }

    public static int getFailedAttempts(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getInt(K_FAILS, 0);
    }

    public static boolean isArmed(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        int threshold = getThreshold(context);
        return threshold > 0 && (p.getBoolean(K_ARMED, false) || p.getInt(K_FAILS, 0) >= threshold);
    }

    public static void onPasswordFailed(Context context) {
        int threshold = getThreshold(context);
        if (threshold <= 0) {
            return;
        }
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        int fails = p.getInt(K_FAILS, 0) + 1;
        boolean wasArmed = p.getBoolean(K_ARMED, false);
        boolean armed = fails >= threshold;
        p.edit()
                .putInt(K_FAILS, fails)
                .putBoolean(K_ARMED, armed)
                .apply();
        Log.w(TAG, "onPasswordFailed: fails=" + fails + "/" + threshold + " armed=" + armed);
        AlpStats.record(context, "password_failed:" + fails + "/" + threshold);

        // Offer the challenge exactly ONCE, on the attempt that crosses the
        // threshold. Re-opening it on every later mistake would trap the user:
        // dismissing it and then mistyping once more would force it back.
        if (armed && !wasArmed) {
            AlpStats.record(context, "password_recovery_armed");
            launchRecoveryActivity(context);
        } else if (armed) {
            // Already offered (and possibly dismissed): keep the entry point
            // reachable from the notification, never hijack the screen again.
            postNotification(context);
        }
    }

    /**
     * A correct passcode clears the streak.
     *
     * The counter measures CONSECUTIVE failures, so this must reset it whether
     * or not the challenge is already armed — otherwise the count could only
     * ever climb (verified: it sat at 13 and a successful unlock left it at 13),
     * and the challenge stayed armed forever after a single mistake burst.
     */
    public static void onPasswordSucceeded(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        p.edit().putInt(K_FAILS, 0).putBoolean(K_ARMED, false).apply();
        AlpStats.record(context, "password_succeeded_counter_reset");
        Log.d(TAG, "onPasswordSucceeded: streak cleared");
    }

    public static void launchRecoveryActivity(Context context) {
        Intent intent = new Intent(context, PasswordRecoveryActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                | Intent.FLAG_ACTIVITY_CLEAR_TOP
                | Intent.FLAG_ACTIVITY_SINGLE_TOP);

        // 1. Direct Activity Start
        try {
            context.startActivity(intent);
        } catch (Exception e) {
            Log.e(TAG, "direct activity start note: " + e.getMessage());
        }

        // 2. Persistent banner = the way back in after the user dismisses it
        postNotification(context);

        // 3. Keep the screen awake while the challenge is on it. A 5 s wake
        //    lock let the panel time out and the screen looked like it had
        //    closed itself; the timeout here is the natural screen-off delay,
        //    and it is released the moment the user leaves.
        try {
            PowerManager pm = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            if (pm != null) {
                ScreenOnKeeper.release();
                PowerManager.WakeLock wl = pm.newWakeLock(
                        PowerManager.SCREEN_BRIGHT_WAKE_LOCK
                                | PowerManager.ACQUIRE_CAUSES_WAKEUP,
                        "alp:recovery_wakeup");
                wl.setReferenceCounted(false);
                wl.acquire(SCREEN_ON_MS);
                ScreenOnKeeper.hold(wl);
            }
        } catch (Exception ignored) {
        }
    }

    private static final long SCREEN_ON_MS = 10 * 60 * 1000L;

    /** Drops the keep-screen-on lock once the challenge is no longer showing. */
    public static void releaseScreenOn(Context context) {
        ScreenOnKeeper.release();
    }

    static final class ScreenOnKeeper {
        private static PowerManager.WakeLock lock;

        static void hold(PowerManager.WakeLock wl) {
            release();
            lock = wl;
        }

        static void release() {
            if (lock != null) {
                try {
                    if (lock.isHeld()) {
                        lock.release();
                    }
                } catch (Exception ignored) {
                }
                lock = null;
            }
        }
    }

    /**
     * The re-entry point once the one-shot prompt was dismissed. Dismissible on
     * purpose: the challenge must never be something the user cannot dismiss.
     */
    public static void postNotification(Context context) {
        try {
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) {
                return;
            }
            Intent intent = new Intent(context, PasswordRecoveryActivity.class);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                    | Intent.FLAG_ACTIVITY_CLEAR_TOP
                    | Intent.FLAG_ACTIVITY_SINGLE_TOP);

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                NotificationChannel chan = new NotificationChannel(
                        NOTIF_CHANNEL_ID,
                        "Passcode Recovery",
                        NotificationManager.IMPORTANCE_HIGH);
                chan.setDescription("Lock screen challenge for forgotten passcode recovery");
                chan.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
                nm.createNotificationChannel(chan);
            }

            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                flags |= PendingIntent.FLAG_IMMUTABLE;
            }
            PendingIntent pi = PendingIntent.getActivity(context, 2026, intent, flags);

            Notification.Builder builder;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                builder = new Notification.Builder(context, NOTIF_CHANNEL_ID);
            } else {
                builder = new Notification.Builder(context);
            }

            int fails = getFailedAttempts(context);
            builder.setSmallIcon(android.R.drawable.ic_lock_lock)
                    .setContentTitle("استرداد رمز المرور المقفل (Passcode Recovery)")
                    .setContentText("تم تأمين الجهاز بعد " + fails
                            + " محاولات خاطئة. اضغط هنا لإدخال رمز الاسترداد.")
                    .setFullScreenIntent(pi, true)
                    .setContentIntent(pi)
                    .setAutoCancel(true)
                    .setOngoing(false)
                    .setPriority(Notification.PRIORITY_MAX);

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                builder.setVisibility(Notification.VISIBILITY_PUBLIC)
                        .setCategory(Notification.CATEGORY_CALL);
            }
            nm.notify(NOTIF_ID, builder.build());
        } catch (Exception e) {
            Log.e(TAG, "failed to post recovery notification: " + e.getMessage());
        }
    }

    public static void cancelNotification(Context context) {
        try {
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.cancel(NOTIF_ID);
            }
        } catch (Exception ignored) {
        }
    }

    /**
     * Step 1: Verify the recovery code.
     *
     * The code is the ONLY gate: it is derived from the per-device secret
     * that only the console holds, is time-bound (±1 window), burns after
     * first use, and locks entry after 5 consecutive mistakes. A thief
     * typing random 8-digit numbers can never pass here.
     *
     * @return null on success (code valid, counter burned), or error string.
     */
    public static String verifyRecoveryCode(Context context, String code) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String err = EmergencyCodes.verify(context, "reset_password", code);
        if (err != null) {
            p.edit().putBoolean(K_STEP1_OK, false).apply();
            Log.w(TAG, "recovery code rejected: " + err);
            AlpStats.record(context, "password_recovery_code_invalid:" + err);
            return err;
        }
        p.edit()
                .putBoolean(K_STEP1_OK, true)
                .putLong(K_STEP1_AT, System.currentTimeMillis())
                .apply();
        Log.w(TAG, "recovery code accepted, step-2 gate opened");
        AlpStats.record(context, "password_recovery_code_verified");
        return null;
    }

    /**
     * @return true when step 1 succeeded recently enough to allow a reset.
     */
    public static boolean isGateOpen(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!p.getBoolean(K_STEP1_OK, false)) {
            return false;
        }
        long at = p.getLong(K_STEP1_AT, 0L);
        if (at <= 0L || System.currentTimeMillis() - at > GATE_TTL_MS) {
            p.edit().putBoolean(K_STEP1_OK, false).putLong(K_STEP1_AT, 0L).apply();
            return false;
        }
        return true;
    }

    private static void closeGate(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putBoolean(K_STEP1_OK, false)
                .putLong(K_STEP1_AT, 0L)
                .apply();
    }

    /**
     * Close the challenge once the user has been handed to the system screen.
     *
     * The key was already proven in verifyRecoveryCode, so the challenge has
     * done its job. Clearing the streak and the banner here is what stops the
     * screen coming back on the next mistake.
     */
    public static void completeHandoff(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        p.edit()
                .putInt(K_FAILS, 0)
                .putBoolean(K_ARMED, false)
                .putBoolean(K_STEP1_OK, false)
                .putLong(K_STEP1_AT, 0L)
                .apply();
        cancelNotification(context);
        dismissKeyguard(context);
        AlpStats.record(context, "password_recovery_handoff");
        Log.w(TAG, "recovery handed off to the system passcode screen");
    }

    /**
     * Programmatic reset, retained for handsets whose platform still allows it.
     *
     * Recovery ALWAYS ends with a lock in place: an empty PIN is refused, so
     * the device can never be left lockless through this screen. The gate is
     * NOT consumed on entry, so a failure leaves the caller able to retry.
     *
     * On Android 11+ every route below is refused for apps targeting API 24+,
     * so callers should prefer openSystemSetPassword / completeHandoff.
     *
     * @return null on success, SYSTEM_UI_REQUIRED when the user must finish in
     *         the system passcode screen, or an error string.
     */
    public static String applyNewPassword(Context context, String newPin) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!isGateOpen(context)) {
            Log.w(TAG, "applyNewPassword refused: no fresh step-1 verification");
            return "verification required — enter a valid recovery code first";
        }

        String passToSet = (newPin != null) ? newPin.trim() : "";
        if (passToSet.isEmpty()) {
            return "A new passcode is required — the device must stay locked";
        }

        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);

        if (dpm == null || !dpm.isAdminActive(admin)) {
            return "Device Admin is not active — re-activate the device admin, then retry";
        }

        // Preferred route: the token-based API, which is what replaced
        // resetPassword() and is still supported on current Android.
        if (tryTokenReset(context, dpm, admin, passToSet)) {
            return finishReset(context, p);
        }

        // Legacy route: still valid on older handsets that predate the
        // deprecation, and harmless where it is not.
        try {
            if (dpm.resetPassword(passToSet, 0)) {
                return finishReset(context, p);
            }
        } catch (Exception e) {
            Log.w(TAG, "resetPassword unavailable: " + e.getMessage());
        }

        // Neither programmatic route is permitted any more (Android 11+ blocks
        // resetPassword for apps targeting API 24+). Hand off to the system
        // passcode screen: the user sets their own credential there.
        Log.w(TAG, "handing passcode entry to the system UI");
        AlpStats.record(context, "password_recovery_system_ui");
        dismissKeyguard(context);
        if (openSystemSetPassword(context)) {
            return SYSTEM_UI_REQUIRED;
        }
        return "This device does not allow the app to set the passcode. "
                + "Set it in Settings > Security, or contact your administrator.";
    }

    /**
     * Reset the credential with the registered token, or set a new one.
     *
     * The token must already be ACTIVE — that only happens when the DPC called
     * setResetPasswordToken() itself, which is why ensureTokenRegistered() runs
     * at policy-apply time rather than here. Minting a token at recovery time
     * and immediately using it does not work: the platform treats a brand-new
     * token as inactive, which is exactly what "reset password token is not
     * active" in the logs was reporting.
     *
     * @param passToSet empty string clears the credential (what the reference
     *                  MDM client does); a value sets that passcode instead.
     * @return true when the platform accepted the reset.
     */
    private static boolean tryTokenReset(Context context, DevicePolicyManager dpm,
                                         ComponentName admin, String passToSet) {
        try {
            if (!dpm.isResetPasswordTokenActive(admin)) {
                if (!ensureTokenRegistered(context, dpm, admin)) {
                    Log.w(TAG, "no active reset-password token; cannot reset");
                    return false;
                }
            }
            byte[] token = ResetTokenStore.token(context);
            if (token == null) {
                Log.w(TAG, "reset token unavailable from storage");
                return false;
            }
            return dpm.resetPasswordWithToken(admin, passToSet, token, 0);
        } catch (Exception e) {
            Log.w(TAG, "token reset unavailable: " + e.getMessage());
            return false;
        }
    }

    /**
     * Register a token with the platform, once.
     *
     * Called from APPLY_POLICY so the capability exists long before it is needed;
     * by the time a passcode is forgotten the handset may be offline for days and
     * the console may be unreachable, which is the whole point of the offline
     * recovery key.
     *
     * @return true when a token is registered and active.
     */
    public static boolean ensureTokenRegistered(Context context,
                                                 DevicePolicyManager dpm,
                                                 ComponentName admin) {
        try {
            if (dpm == null || admin == null
                    || !dpm.isAdminActive(admin)) {
                Log.w(TAG, "token registration: admin not active");
                return false;
            }
            if (dpm.isResetPasswordTokenActive(admin)) {
                Log.w(TAG, "token registration: already active");
                return true;
            }
            byte[] token = ResetTokenStore.token(context);
            if (token == null) {
                Log.w(TAG, "cannot register token: no keystore on this build");
                return false;
            }
            boolean ok = dpm.setResetPasswordToken(admin, token);
            boolean active = dpm.isResetPasswordTokenActive(admin);
            Log.w(TAG, "setResetPasswordToken -> " + ok + " active=" + active);
            // Some builds accept the call but leave the token inactive; retrying
            // once with a fresh token is cheap and this is the only chance to get
            // it right, because a wrong guess here is invisible until recovery
            // days later.
            if (!active) {
                byte[] again = new byte[32];
                new java.security.SecureRandom().nextBytes(again);
                ok = dpm.setResetPasswordToken(admin, again);
                if (ok && dpm.isResetPasswordTokenActive(admin)) {
                    ResetTokenStore.replace(context, again);
                    Log.w(TAG, "retry registered the token");
                    return true;
                }
                Log.w(TAG, "token stays inactive after retry");
            }
            return ok && active;
        } catch (Exception e) {
            Log.w(TAG, "token registration unavailable: " + e.getMessage());
            return false;
        }
    }

    /** Success path: disarm the challenge and unlock. */
    private static String finishReset(Context context, SharedPreferences p) {
        p.edit()
                .putInt(K_FAILS, 0)
                .putBoolean(K_ARMED, false)
                .putBoolean(K_STEP1_OK, false)
                .putLong(K_STEP1_AT, 0L)
                .apply();
        cancelNotification(context);
        AlpStats.record(context, "password_recovery_success");
        dismissKeyguard(context);
        return null;
    }

    public static void dismissKeyguard(Context context) {
        try {
            KeyguardManager km = (KeyguardManager) context.getSystemService(Context.KEYGUARD_SERVICE);
            if (km != null) {
                KeyguardManager.KeyguardLock kl = km.newKeyguardLock("alp_recovery_unlock");
                kl.disableKeyguard();
            }
        } catch (Exception e) {
            Log.d(TAG, "disableKeyguard note: " + e.getMessage());
        }
    }

    /**
     * Open the system passcode screen so the user sets their own credential.
     * ACTION_SET_NEW_PASSWORD is admin-gated; the security-settings fallback
     * reaches the same screen on builds that hide the action.
     *
     * @return true when something was launched.
     */
    public static boolean openSystemSetPassword(Context context) {
        Intent[] attempts = new Intent[]{
                new Intent(DevicePolicyManager.ACTION_SET_NEW_PASSWORD),
                new Intent("android.app.action.SET_NEW_PASSWORD"),
                new Intent(Settings.ACTION_SECURITY_SETTINGS)
        };
        for (Intent it : attempts) {
            try {
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(it);
                return true;
            } catch (Exception ignored) {
            }
        }
        return false;
    }
}
