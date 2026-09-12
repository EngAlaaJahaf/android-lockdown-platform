package com.alp.agent;

import android.app.admin.DeviceAdminReceiver;
import android.content.Context;
import android.content.Intent;

public class AlpDeviceAdminReceiver extends DeviceAdminReceiver {

    @Override
    public void onEnabled(Context context, Intent intent) {
        AlpStats.record(context, "device_owner_active");
    }

    @Override
    public void onDisabled(Context context, Intent intent) {
        AlpStats.record(context, "device_owner_inactive");
    }
}