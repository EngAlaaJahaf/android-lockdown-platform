package com.alp.agent;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Thin broadcast bridge into AlpOps. On devices that reliably dispatch dynamic
 * broadcasts this is the primary wake path; on builds that vault background
 * broadcasts (standby-bucket RESTRICTED / app-freezer), MainActivity's
 * activity-nudge path processes the same envelope files instead. Both delegate
 * to AlpOps, so behavior is identical regardless of transport.
 */
public class CommandReceiver extends BroadcastReceiver {

    public static final String ACTION_APPLY_POLICY = "com.alp.agent.APPLY_POLICY";
    public static final String ACTION_CLEAR_POLICY = "com.alp.agent.CLEAR_POLICY";
    public static final String ACTION_GET_STATE = "com.alp.agent.GET_STATE";
    public static final String ACTION_REPORT = "com.alp.agent.REPORT_CAPABILITY";
    public static final String ACTION_WITHDRAW_DO = "com.alp.agent.WITHDRAW_DO";
    public static final String EXTRA_ENVELOPE = "envelope";

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        AlpOps.handle(context, action, intent.getStringExtra(EXTRA_ENVELOPE), null);
    }
}