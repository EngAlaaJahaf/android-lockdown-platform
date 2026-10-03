package com.alp.agent;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Thin broadcast bridge into AlpOps. Envelope CONTENT is never read from the
 * intent: a locally installed app must not be able to inject a policy/cancel
 * command without the console's Ed25519 signature. Both the broadcast and the
 * activity-nudge path resolve envelopes from the /data/local/tmp files the
 * console pushes, and AlpOps.handle gates every one through EnvelopeGuard —
 * a forged broadcast with no (or invalid) envelope file is inert.
 */
public class CommandReceiver extends BroadcastReceiver {

    public static final String ACTION_APPLY_POLICY = "com.alp.agent.APPLY_POLICY";
    public static final String ACTION_CLEAR_POLICY = "com.alp.agent.CLEAR_POLICY";
    public static final String ACTION_GET_STATE = "com.alp.agent.GET_STATE";
    public static final String ACTION_REPORT = "com.alp.agent.REPORT_CAPABILITY";
    public static final String ACTION_WITHDRAW_DO = "com.alp.agent.WITHDRAW_DO";
    public static final String ACTION_PROVISION_PIN = "com.alp.agent.PROVISION_PIN";

    @Override
    public void onReceive(Context context, Intent intent) {
        // envelope payload deliberately ignored — files-only + signature.
        AlpOps.handle(context, intent.getAction(), null, null);
    }
}