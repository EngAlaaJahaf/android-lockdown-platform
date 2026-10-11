package com.alp.agent;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONStringer;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.List;

final class AlpStats {
    private AlpStats() {
    }

    static void record(Context context, String event) {
        SharedPreferences prefs = context.getSharedPreferences("alp_stats", Context.MODE_PRIVATE);
        int n = prefs.getInt("count_" + event, 0) + 1;
        prefs.edit().putInt("count_" + event, n).apply();
    }

    static void writeState(Context context, String cmdId, List<String> applied,
                           List<String> skipped, List<String> errors,
                           String at, boolean adminActive) {
        writeState(context, cmdId, applied, skipped, errors, at, adminActive, "UNKNOWN");
    }

    static void writeState(Context context, String cmdId, List<String> applied,
                           List<String> skipped, List<String> errors,
                           String at, boolean adminActive, String action) {
        try {
            JSONStringer s = new JSONStringer();
            s.object();
            s.key("cmd_id").value(cmdId);
            s.key("action").value(action);
            s.key("applied_at").value(at);
            s.key("admin_active").value(adminActive);
            s.key("applied").array();
            for (String v : applied) {
                s.value(v);
            }
            s.endArray();
            s.key("skipped").array();
            for (String v : skipped) {
                s.value(v);
            }
            s.endArray();
            s.key("errors").array();
            for (String v : errors) {
                s.value(v);
            }
            s.endArray();
            s.endObject();
            File f = new File(context.getFilesDir(), "state.json");
            android.util.Log.d("ALP", "writeState cmd=" + cmdId + " applied=" + applied
                    + " errors=" + errors);
            write(f, s.toString());
            // A later probe (GET_STATE) overwrites state.json, which used to erase
            // the only record of what the policy apply really did. The last apply
            // outcome therefore gets its own file so the console can always name
            // the rows this handset refused.
            if ("APPLY_POLICY".equals(action)) {
                write(new File(context.getFilesDir(), "apply_result.json"), s.toString());
            }
            if ("CLEAR_POLICY".equals(action)) {
                write(new File(context.getFilesDir(), "clear_result.json"), s.toString());
            }
            record(context, "state_written");
        } catch (Exception e) {
            android.util.Log.e("ALP", "writeState failed", e);
            record(context, "state_write_error");
        }
    }

    private static void write(File f, String body) throws Exception {
        FileOutputStream fos = new FileOutputStream(f);
        OutputStreamWriter w = new OutputStreamWriter(fos, StandardCharsets.UTF_8);
        w.write(body);
        w.flush();
        w.close();
    }
}
