package com.alp.agent;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class SecretCodeReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if ("android.provider.Telephony.SECRET_CODE".equals(intent.getAction())) {
            Intent open = new Intent(context, MainActivity.class);
            open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                context.startActivity(open);
            } catch (Exception e) {
                android.util.Log.d("ALP", "secret-code open failed: "
                        + e.getClass().getSimpleName());
            }
        }
    }
}