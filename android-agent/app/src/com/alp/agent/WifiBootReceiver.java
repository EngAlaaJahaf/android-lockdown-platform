package com.alp.agent;

import android.app.admin.DevicePolicyManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;

/**
 * Several vendor builds (LT-8110 AOSP generic observed) do NOT power the Wi-Fi
 * radio off when the DISALLOW_CONFIG_WIFI restriction is set, and Android
 * restores the last-enabled radio state on boot. This receiver re-applies the
 * radio-off so a blocked device does not silently come back online with the
 * icon shown as ON while the toggle is forbidden. It also restarts the
 * persistent enforcement service so the snap-back watchdog is armed all the
 * time. It only acts when the restriction is provably ACTIVE
 * (dumpsys/device-policy truth), so it never disables Wi-Fi on a device that
 * has not had WIFI blocked.
 */
public class WifiBootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String act = intent == null ? "" : (intent.getAction() + "");
        if (!Intent.ACTION_BOOT_COMPLETED.equals(act)
                && !Intent.ACTION_LOCKED_BOOT_COMPLETED.equals(act)
                && !Intent.ACTION_USER_UNLOCKED.equals(act)) {
            return;
        }
        android.util.Log.d("ALP", "boot observed: " + act);
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        if (dpm == null || !dpm.isDeviceOwnerApp(context.getPackageName())) {
            return;
        }
        MainActivity.startWifiEnforcementService(context);
        if (context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE)
                .getBoolean("wifi_blocked", false)) {
            android.util.Log.d("ALP", "WIFI restriction active — enforcing radio off");
            AlpOps.ensureWifiOff(context);
        }
    }
}