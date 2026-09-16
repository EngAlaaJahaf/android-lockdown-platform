package com.alp.agent;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.admin.DevicePolicyManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/**
 * Persistent enforcement service for the Wi-Fi lockdown.
 *
 * The LT-8110 AOSP generic build treats wifi-state changers as "privileged":
 * WifiServiceImpl only applies the DISALLOW_CONFIG_WIFI restriction to non
 * privileged callers (observed: setWifiEnabled isPrivileged=true for both
 * shell and SystemUI), so tapping the quick-settings tile brings the radio
 * back ON even while the restriction is active. Manifest-declared receivers
 * for WIFI_STATE_CHANGED are not delivered on this build either, so a
 * "wake-on-change" trick is unreliable.
 *
 * This service keeps the agent process alive permanently (foreground service
 * with a persistent notification, the same pattern enterprise MDM agents use),
 * then enforces radio-off through two independent paths while the
 * DISALLOW_CONFIG_WIFI restriction is provably active:
 *   1. a runtime-registered receiver snaps the radio OFF the moment the
 *      framework reports ENABLED;
 *   2. a periodic re-assertion every few seconds guarantees the OFF state
 *      even if the ENABLED broadcast is missed.
 * The result is exactly a CSS "disabled" switch: any tap is rolled back in a
 * moment and the wifi icon always settles back to OFF. When the restriction is
 * not active the service stays silent and never touches the radio.
 */
public class AlpForegroundService extends Service {
    private static final String TAG = "ALP";
    private static final String CHANNEL_ID = "alp_lockdown";
    private static final int NOTIF_ID = 1001;
    private static final long REASSERT_MS = 3000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable reassert = new Runnable() {
        @Override
        public void run() {
            enforceIfBlocked();
            handler.postDelayed(this, REASSERT_MS);
        }
    };

    private final BroadcastReceiver snapBack = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!WifiManager.WIFI_STATE_CHANGED_ACTION.equals(intent.getAction())) {
                return;
            }
            int state = intent.getIntExtra(WifiManager.EXTRA_WIFI_STATE,
                    WifiManager.WIFI_STATE_UNKNOWN);
            if (state == WifiManager.WIFI_STATE_ENABLED) {
                if (!context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                        .getBoolean("wifi_blocked", false)) {
                    return;
                }
                android.util.Log.d(TAG, "snap-back: radio ENABLED while blocked");
                AlpOps.ensureWifiOff(context);
                AlpStats.record(context, "wifi_snapback");
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        setChannel();
        android.util.Log.d(TAG, "enforcement service started");
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTIF_ID, buildNotification());
        registerReceiver(snapBack,
                new IntentFilter(WifiManager.WIFI_STATE_CHANGED_ACTION));
        handler.removeCallbacks(reassert);
        handler.post(reassert);
        enforceIfBlocked();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(reassert);
        try {
            unregisterReceiver(snapBack);
        } catch (Exception ignored) {
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void enforceIfBlocked() {
        DevicePolicyManager dpm =
                (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(this, AlpDeviceAdminReceiver.class);
        WifiManager wm = (WifiManager) getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
        if (dpm == null || wm == null) {
            return;
        }
        if (!dpm.isDeviceOwnerApp(getPackageName())) {
            return;
        }
        if (!getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                .getBoolean("wifi_blocked", false)) {
            return;
        }
        if (wm.isWifiEnabled()) {
            android.util.Log.d(TAG, "re-assert: radio ON while blocked");
            AlpOps.ensureWifiOff(this);
            AlpStats.record(this, "wifi_reassert");
        }
    }

    private void setChannel() {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        NotificationChannel ch = new NotificationChannel(CHANNEL_ID,
                "ALP Lockdown", NotificationManager.IMPORTANCE_LOW);
        ch.setShowBadge(false);
        ch.enableVibration(false);
        nm.createNotificationChannel(ch);
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_lock_lock)
                .setContentTitle("ALP—Lockdown active")
                .setContentText("Device is under policy control")
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }
}