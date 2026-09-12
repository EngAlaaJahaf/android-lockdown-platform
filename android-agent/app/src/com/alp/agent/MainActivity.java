package com.alp.agent;

import android.app.admin.DevicePolicyManager;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        DevicePolicyManager dpm = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(this, AlpDeviceAdminReceiver.class);
        boolean owner = dpm.isDeviceOwnerApp(getPackageName());
        boolean active = dpm.isAdminActive(admin);
        TextView tv = new TextView(this);
        tv.setText("ALP agent\npackage=" + getPackageName() + "\ndevice_owner=" + owner
                + "\nadmin_active=" + active);
        setContentView(tv);
    }

    @Override
    protected void onResume() {
        super.onResume();
        android.util.Log.d("ALP", "MainActivity onResume");
        // Activity-nudge path: the management app starts this launcher after it
        // drops an envelope; onResume fires both on first launch and when the
        // top-most activity is re-delivered. AlpOps dedupes by cmd_id.
        AlpOps.processPending(this);
    }
}