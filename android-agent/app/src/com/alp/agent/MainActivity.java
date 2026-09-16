package com.alp.agent;

import android.app.Activity;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        startWifiEnforcementService();
        DevicePolicyManager dpm = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(this, AlpDeviceAdminReceiver.class);
        boolean owner = dpm.isDeviceOwnerApp(getPackageName());
        boolean active = dpm.isAdminActive(admin);

        TextView tv = new TextView(this);
        tv.setText("ALP agent\npackage=" + getPackageName() + "\ndevice_owner=" + owner
                + "\nadmin_active=" + active);

        Button btn = new Button(this);
        btn.setText("ROLLBACK / \u0625\u0644\u063a\u0627\u0621 \u0627\u0644\u0642\u064a\u0648\u062f");
        btn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                AlpOps.localRollback(MainActivity.this);
                tv.append("\nrollback triggered \u2014 see files/state.json");
            }
        });

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 24, 24, 24);
        root.addView(tv);
        root.addView(btn);
        setContentView(root);
    }

    static void startWifiEnforcementService(Context context) {
        try {
            context.startForegroundService(
                    new Intent(context, AlpForegroundService.class));
        } catch (Exception e) {
            android.util.Log.d("ALP", "startForegroundService failed: "
                    + e.getClass().getSimpleName());
        }
    }

    private void startWifiEnforcementService() {
        startWifiEnforcementService(this);
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