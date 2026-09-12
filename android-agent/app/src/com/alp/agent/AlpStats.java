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
        try {
            JSONStringer s = new JSONStringer();
            s.object();
            s.key("cmd_id").value(cmdId);
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
            FileOutputStream fos = new FileOutputStream(f);
            OutputStreamWriter w = new OutputStreamWriter(fos, StandardCharsets.UTF_8);
            w.write(s.toString());
            w.flush();
            w.close();
            record(context, "state_written");
        } catch (Exception e) {
            record(context, "state_write_error");
        }
    }
}