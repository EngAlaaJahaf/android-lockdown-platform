package com.alp.agent;

import android.app.admin.DevicePolicyManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.os.UserManager;

/**
 * Snap-back enforcement for the Wi-Fi quick-settings tile.
 *
 * Several vendor builds (LT-8110 AOSP generic observed) do NOT honor the
 * DISALLOW_CONFIG_WIFI restriction from the quick-settings tile: tapping the
 * Wi-Fi icon calls WifiManager.setWifiEnabled(true) with SystemUI identity and
 * the radio comes back ON (observed in dumpsys wifi as packageName=com.android.
 * systemui toggleState=true). The tile stays interactive and the user sees the
 * icon lit while Wi-Fi remains non-functional.
 *
 * This receiver listens for the framework's WIFI_STATE_CHANGED broadcast and,
 * whenever the radio actually reaches ENABLED while the DISALLOW_CONFIG_WIFI
 * restriction is provably ACTIVE, turns it straight back OFF. The net effect
 * for the user is exactly a CSS "disabled" button: any tap flashes for a moment
 * and the wifi icon always settles back to the OFF state — the toggle never
 * persists. It only acts while the restriction is active, so devices without
 * WIFI blocked keep a fully enabled Wi-Fi.
 */
public class WifiLockdownReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String act = intent == null ? "" : (intent.getAction() + "");
        if (!WifiManager.WIFI_STATE_CHANGED_ACTION.equals(act)) {
            return;
        }
        int state = intent.getIntExtra(WifiManager.EXTRA_WIFI_STATE,
                WifiManager.WIFI_STATE_UNKNOWN);
        if (state != WifiManager.WIFI_STATE_ENABLED) {
            return;
        }
        DevicePolicyManager dpm =
                (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, AlpDeviceAdminReceiver.class);
        if (dpm == null || !dpm.isDeviceOwnerApp(context.getPackageName())) {
            return;
        }
        Bundle cur = dpm.getUserRestrictions(admin);
        if (cur != null && cur.getBoolean(UserManager.DISALLOW_CONFIG_WIFI)) {
            android.util.Log.d("ALP", "wifi radio ENABLED while blocked — snapping back OFF");
            AlpOps.ensureWifiOff(context);
        }
    }
}