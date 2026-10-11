"""Replace the Control-link row with a real Sync Server check.

Everything between the "Header row" marker and the toggleRow javadoc is
rewritten: the row now reaches the LOCAL control panel over the USB tether,
records the timestamp only on success, and reports the outcome.
"""
import io
import os

P = os.path.join("android-agent", "app", "src", "com", "alp", "agent",
                 "MainActivity.java")

START = "/** Header row: tappable to verify the link to the control platform. */"
END = "/** A list row with a real switch widget on the trailing side. */"

NEW = r'''    /**
     * Sync Server row: reaches the LOCAL control panel over the reverse USB
     * tether (gnirehtet) - never over Wi-Fi and never over the internet. The
     * subtitle is the timestamp of the last SUCCESSFUL check; a failed check
     * leaves it untouched so the displayed time cannot drift forward.
     */
    private void syncRow(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(10), 0, dp(14));

        LinearLayout txt = new LinearLayout(this);
        txt.setOrientation(LinearLayout.VERTICAL);
        txt.setLayoutParams(new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        TextView k = new TextView(this);
        k.setText("Sync Server");
        k.setTextSize(16);
        k.setTextColor(INK);
        k.setTypeface(k.getTypeface(), android.graphics.Typeface.BOLD);
        k.setGravity(Gravity.END);
        txt.addView(k);
        final TextView v = new TextView(this);
        v.setText(syncLabel());
        v.setTextSize(13);
        v.setTextColor(MUTED);
        v.setGravity(Gravity.END);
        v.setPadding(0, dp(3), 0, 0);
        txt.addView(v);
        row.addView(txt);

        FrameLayout badge = new FrameLayout(this);
        GradientDrawable d = new GradientDrawable();
        d.setColor(BADGE_BG);
        d.setCornerRadius(dp(10));
        badge.setBackground(d);
        badge.setLayoutParams(new LinearLayout.LayoutParams(dp(44), dp(44)));
        final ImageView glyph = new ImageView(this);
        glyph.setImageResource(R.drawable.ic_sync);
        badge.addView(glyph, new FrameLayout.LayoutParams(dp(24), dp(24), Gravity.CENTER));
        row.addView(badge);

        row.setClickable(true);
        row.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                runSync(v, glyph);
            }
        });

        parent.addView(row);
        View sep = new View(this);
        sep.setBackgroundColor(LINE);
        sep.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
        parent.addView(sep);
    }

    /** "\u2014" until the panel has answered once, otherwise that success. */
    private String syncLabel() {
        String at = SyncCheck.lastSyncAt(this);
        if (at == null || at.isEmpty()) {
            return "\u2014";
        }
        return at.replace("T", " ").replace("Z", " UTC");
    }

    /**
     * Ask the panel and report the outcome. The timestamp is written by
     * SyncCheck only when the panel answers, so a failed check restores the
     * previous value and the operator is told plainly what happened.
     */
    private void runSync(final TextView label, final ImageView glyph) {
        final String before = label.getText().toString();
        label.setText("Syncing\u2026");
        label.setTextColor(MUTED);
        glyph.setAlpha(140);
        SyncCheck.check(this, new SyncCheck.Callback() {
            @Override
            public void onResult(final boolean reachable, final String text) {
                if (reachable) {
                    label.setText(syncLabel());
                    label.setTextColor(GREEN);
                    glyph.setAlpha(255);
                } else {
                    label.setText(before);
                    label.setTextColor(AMBER);
                    glyph.setAlpha(140);
                }
                note(text);
                Toast.makeText(MainActivity.this, text, Toast.LENGTH_SHORT).show();
            }
        });
    }

'''

with io.open(P, "r", encoding="utf-8", newline="") as fh:
    lines = fh.read().split("\n")

try:
    s = next(i for i, ln in enumerate(lines) if ln.strip() == START)
    e = next(i for i, ln in enumerate(lines) if ln.strip() == END)
except StopIteration:
    raise SystemExit("marker not found")

if not s < e:
    raise SystemExit("markers out of order: %d %d" % (s, e))

lines[s:e] = NEW.rstrip("\n").split("\n")

with io.open(P, "w", encoding="ascii", newline="") as fh:
    fh.write("\n".join(lines))

print("replaced lines %d..%d (%d lines)" % (s + 1, e, e - s))
