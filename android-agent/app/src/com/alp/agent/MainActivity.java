package com.alp.agent;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;

/**
 * Enterprise device console (original ALP UI).
 *
 * Home is a 2-column card grid; detail screens are list / empty states with a
 * white brand bar and a centered title with the back chevron on the trailing
 * edge (RTL convention).
 *
 * The user-facing screen shows display-safe data only. Management internals
 * (package name, command ids, restriction lists, PIN state, owner/admin flags)
 * stay in files/state.json for the console (run-as).
 *
 * Hidden admin gesture: 5 consecutive taps on the home app bar open the
 * PIN popup. There is no visible rollback/unlock button.
 */
public class MainActivity extends Activity {

    private static final int INK = 0xFF323232;
    private static final int MUTED = 0xFF666666;
    private static final int FAINT = 0xFF999999;
    private static final int PAGE_BG = 0xFFF5F5F5;
    private static final int CARD_BG = 0xFFFFFFFF;
    private static final int GREEN = 0xFF089949;
    private static final int GREEN_BG = 0xFFE3F3E9;
    private static final int AMBER = 0xFFB7791F;
    private static final int AMBER_BG = 0xFFFBF1DC;
    private static final int LINE = 0xFFE0E0E0;
    private static final int BADGE_BG = 0xFFF0F4FA;

    private static final int S_HOME = 0;
    private static final int S_COMPLIANCE = 1;
    private static final int S_DEVICE = 2;
    private static final int S_SUPPORT = 3;
    private static final int S_PLACEHOLDER = 4;
    private static final int S_PRIVACY = 5;

    private int screen = S_HOME;
    private int phIcon;
    private String phScreenTitle = "";
    private String phTitle = "";
    private String phMsg = "";

    private TextView statusLine;

    // Hidden admin gesture (home app bar only): 5 consecutive taps open
    // the PIN popup. No visible rollback button exists anywhere.
    private int headerTaps = 0;
    private long lastHeaderTap = 0L;
    private static final long TAP_WINDOW_MS = 2000L;
    private static final int TAP_COUNT = 5;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            if (getActionBar() != null) {
                getActionBar().hide();
            }
        } catch (Exception ignored) {
        }
        startWifiEnforcementService();
        render();
    }

    @Override
    protected void onResume() {
        super.onResume();
        android.util.Log.d("ALP", "MainActivity onResume");
        // NOTE: the passcode-recovery challenge is deliberately NOT forced here.
        // It belongs to the lock screen (it arms when the failed-attempt
        // threshold is crossed) and is re-entered from its own notification.
        // Hijacking normal app entry with a mandatory recovery screen was
        // never asked for and made the console unusable while armed.
        // Activity-nudge path: the management app starts this launcher after it
        // drops an envelope; onResume fires both on first launch and when the
        // top-most activity is re-delivered. AlpOps dedupes by cmd_id and
        // EnvelopeGuard validates every signed envelope.
        AlpOps.processPending(this);
        render();

        // First-connect path: a profile published while this handset was away
        // has to land by itself. Pulling is cheap and idempotent - an unchanged
        // fingerprint answers "up to date" without re-enforcing anything - so it
        // runs once per launch, and only when the console already knows this
        // handset (enrollment exists). The guard is device-owner status, not a
        // locally committed policy: a device whose rows were all RESTRICT used
        // to have an empty commit list and would skip syncing forever.
        if (managed()) {
            final Handler main = new Handler(Looper.getMainLooper());
            main.postDelayed(new Runnable() {
                @Override
                public void run() {
                    PolicyPull.sync(MainActivity.this, new PolicyPull.Callback() {
                        @Override
                        public void onResult(boolean applied, String text,
                                             int rows, int skipped) {
                            if (applied) {
                                note(text);
                            }
                            render();
                        }
                    });
                }
            }, 1500);
        }
    }

    @Override
    public void onBackPressed() {
        if (screen != S_HOME) {
            screen = S_HOME;
            render();
            return;
        }
        super.onBackPressed();
    }

    private void render() {
        switch (screen) {
            case S_COMPLIANCE:
                setContentView(wrapDetail("Compliance", buildCompliance()));
                break;
            case S_DEVICE:
                setContentView(wrapDetail("Device Details", buildDeviceRows()));
                break;
            case S_SUPPORT:
                setContentView(wrapDetail("Support", buildSupport()));
                break;
            case S_PRIVACY:
                setContentView(wrapDetail("Privacy Policy", buildPrivacy()));
                break;
            case S_PLACEHOLDER:
                setContentView(wrapDetail(phScreenTitle, buildPlaceholder()));
                break;
            default:
                setContentView(buildHome());
                break;
        }
    }

    // ------------------------------------------------------------------
    // Home grid
    // ------------------------------------------------------------------
    private View buildHome() {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setBackgroundColor(PAGE_BG);
        page.addView(buildHomeBar());

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(14), dp(14), dp(14), dp(20));

        int[][] cards = {
                {R.drawable.ic_content, 0},
                {R.drawable.ic_grid, 1},
                {R.drawable.ic_shield, 2},
                {R.drawable.ic_mega, 3},
                {R.drawable.ic_phone, 4},
                {R.drawable.ic_lock, 5},
                {R.drawable.ic_headset, 6},
        };
        String[] titles = {"Content Catalog", "App Catalog", "Compliance",
                "Announcements", "Device Details", "Privacy Policy", "Support"};
        String[] subs = {"View and download the\ncontent shared",
                "View and install work\napps",
                "The policies &\nconfigurations your\ndevice is adhering to",
                "Updates & notifications\nfrom your organization",
                "Information about\nthe device",
                "Know more about the\nprivacy settings",
                "Get instant resolution to\nyour queries"};

        for (int r = 0; r < 4; r++) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            for (int c = 0; c < 2; c++) {
                int idx = r * 2 + c;
                if (idx < cards.length) {
                    row.addView(homeCard(idx, cards[idx][0], titles[idx],
                            subs[idx]));
                } else {
                    View spacer = new View(this);
                    spacer.setLayoutParams(new LinearLayout.LayoutParams(0,
                            LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
                    row.addView(spacer);
                }
            }
            body.addView(row);
        }

        statusLine = new TextView(this);
        statusLine.setTextSize(11);
        statusLine.setTextColor(FAINT);
        statusLine.setGravity(Gravity.CENTER);
        statusLine.setPadding(0, dp(8), 0, 0);
        body.addView(statusLine);

        scroll.addView(body);
        page.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.MATCH_PARENT, 1f));
        return page;
    }

    private View homeCard(final int idx, int iconRes, String title, String sub) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER_HORIZONTAL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(CARD_BG);
        bg.setCornerRadius(dp(12));
        card.setBackground(bg);
        if (Build.VERSION.SDK_INT >= 21) {
            card.setElevation(dp(2));
        }
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        int m = dp(6);
        lp.setMargins(m, m, m, m);
        card.setLayoutParams(lp);
        card.setMinimumHeight(dp(158));
        card.setPadding(dp(10), dp(18), dp(10), dp(16));

        ImageView iv = new ImageView(this);
        iv.setImageResource(iconRes);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(dp(44), dp(44));
        ip.setMargins(0, 0, 0, dp(10));
        iv.setLayoutParams(ip);
        card.addView(iv);

        TextView t = new TextView(this);
        t.setText(title);
        t.setTextSize(15);
        t.setTextColor(INK);
        t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        t.setGravity(Gravity.CENTER);
        card.addView(t);

        TextView s = new TextView(this);
        s.setText(sub);
        s.setTextSize(12);
        s.setTextColor(MUTED);
        s.setGravity(Gravity.CENTER);
        s.setPadding(0, dp(2), 0, 0);
        card.addView(s);

        card.setClickable(true);
        card.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openCard(idx);
            }
        });
        return card;
    }

    private void openCard(int idx) {
        switch (idx) {
            case 2:
                screen = S_COMPLIANCE;
                break;
            case 4:
                screen = S_DEVICE;
                break;
            case 6:
                screen = S_SUPPORT;
                break;
            case 5:
                screen = S_PRIVACY;
                break;
            case 0:
                showPlaceholder(R.drawable.ic_content, "Content Catalog",
                        "No content available!",
                        "Content shared by your organization appears here.");
                break;
            case 1:
                showPlaceholder(R.drawable.ic_grid, "App Catalog",
                        "No apps available!",
                        "Apps distributed by your organisation are available here "
                                + "for download.");
                break;
            default:
                showPlaceholder(R.drawable.ic_mega, "Announcements",
                        "No announcements",
                        "Updates and notifications from your organization "
                                + "appear here.");
                break;
        }
        render();
    }

    private void showPlaceholder(int icon, String screenTitle, String headline,
                                 String body) {
        phIcon = icon;
        phScreenTitle = screenTitle;
        phTitle = headline;
        phMsg = body;
        screen = S_PLACEHOLDER;
    }

    private View buildHomeBar() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(CARD_BG);
        bar.setPadding(dp(20), dp(16) + statusBarHeight(), dp(20), dp(16));
        if (Build.VERSION.SDK_INT >= 21) {
            bar.setElevation(dp(4));
        }

        TextView name = new TextView(this);
        name.setText("ALP Enterprise");
        name.setTextSize(19);
        name.setTextColor(INK);
        name.setTypeface(name.getTypeface(), android.graphics.Typeface.BOLD);
        name.setLayoutParams(new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        // Server-driven brand mark (Branding.java): shown when a logo has
        // been fetched at Sync, otherwise the header stays text-only.
        File brandLogo = Branding.logoFile(this);
        if (brandLogo.exists()) {
            try {
                android.graphics.Bitmap mark =
                        android.graphics.BitmapFactory.decodeFile(
                                brandLogo.getAbsolutePath());
                if (mark != null) {
                    ImageView logo = new ImageView(this);
                    logo.setImageBitmap(mark);
                    LinearLayout.LayoutParams lp =
                            new LinearLayout.LayoutParams(dp(40), dp(40));
                    lp.setMargins(0, 0, dp(12), 0);
                    logo.setLayoutParams(lp);
                    bar.addView(logo);
                }
            } catch (Exception ignored) {
            }
        }
        bar.addView(name);

        final TextView pill = pill(managed() ? "MANAGED" : "NOT ENROLLED",
                managed() ? GREEN_BG : AMBER_BG, managed() ? GREEN : AMBER);
        bar.addView(pill);

        bar.setClickable(true);
        bar.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onHeaderTap();
            }
        });

        LinearLayout wrap = new LinearLayout(this);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.addView(bar);
        View sep = new View(this);
        sep.setBackgroundColor(LINE);
        sep.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
        wrap.addView(sep);
        return wrap;
    }

    // ------------------------------------------------------------------
    // Detail screens
    // ------------------------------------------------------------------
    private View wrapDetail(String title, View content) {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setBackgroundColor(PAGE_BG);

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(CARD_BG);
        int barH = dp(56) + statusBarHeight();
        bar.setPadding(dp(8), statusBarHeight(), dp(20), 0);
        bar.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, barH));
        if (Build.VERSION.SDK_INT >= 21) {
            bar.setElevation(dp(4));
        }

        TextView t = new TextView(this);
        t.setText(title);
        t.setTextSize(18);
        t.setTextColor(INK);
        t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        t.setGravity(Gravity.CENTER);
        bar.addView(t, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.MATCH_PARENT, 1f));
        // RTL detail bar: balanced spacer on the leading edge, chevron trailing.
        bar.addView(new View(this), new LinearLayout.LayoutParams(dp(40), dp(1)));

        TextView back = new TextView(this);
        back.setText("\u2039");
        back.setTextSize(30);
        back.setTextColor(INK);
        back.setGravity(Gravity.CENTER);
        back.setClickable(true);
        back.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                screen = S_HOME;
                render();
            }
        });
        bar.addView(back, new LinearLayout.LayoutParams(dp(44),
                LinearLayout.LayoutParams.MATCH_PARENT));
        page.addView(bar);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(0), dp(10), dp(0), dp(20));
        body.addView(content);
        scroll.addView(body);
        scroll.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        page.addView(scroll);
        return page;
    }

    private View buildCompliance() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER_HORIZONTAL);
        box.setPadding(dp(32), dp(150), dp(32), dp(20));

        ImageView iv = new ImageView(this);
        iv.setImageResource(R.drawable.ic_shield);
        iv.setLayoutParams(new LinearLayout.LayoutParams(dp(64), dp(64)));
        box.addView(iv);

        TextView msg = new TextView(this);
        msg.setTextSize(15);
        msg.setTextColor(MUTED);
        msg.setGravity(Gravity.CENTER);
        msg.setPadding(0, dp(18), 0, 0);
        int errs = errorCount();
        if (!managed()) {
            msg.setText("This device is not enrolled.\nContact your IT administrator.");
        } else if (errs == 0) {
            msg.setText("Your device is compliant with all the policies of "
                    + "your organization.");
        } else {
            msg.setText(errs + (errs == 1 ? " policy item needs" : " policy items need")
                    + " attention.\nContact your IT administrator.");
        }
        box.addView(msg);
        return box;
    }

    private View buildDeviceRows() {
        LinearLayout card = listCard();
        syncRow(card);
        listRow(card, R.drawable.ic_phone, "Device Name", deviceName());
        listRow(card, R.drawable.ic_user, "User Name", userName());
        listRow(card, R.drawable.ic_info, "App Version", appVersion());
        listRow(card, R.drawable.ic_server, "UDID", deviceId());
        listRow(card, R.drawable.ic_calendar, "App Installation Date", installDate());
        listRow(card, R.drawable.ic_doc, "Registration Status",
                managed() ? "Enrolled" : "Not enrolled");
        listRow(card, R.drawable.ic_shield, "Device Owner", "Your organization");
        listRow(card, R.drawable.ic_folder, "App Log Directory", "On this device only");
        return card;
    }

    /** Privacy policy - two labelled sections, the Log Privacy row carries a switch. */
    private View buildPrivacy() {
        LinearLayout wrap = new LinearLayout(this);
        wrap.setOrientation(LinearLayout.VERTICAL);

        wrap.addView(sectionLabel("User's personal information"));
        LinearLayout c1 = listCard();
        listRow(c1, R.drawable.ic_doc, "App Information",
                "Your IT admin collects information on the installed apps for "
                        + "inventory and deploying configurations.");
        listRow(c1, R.drawable.ic_call, "Phone Number",
                "Your IT admin collects phone number for inventory and "
                        + "generating reports.");
        listRow(c1, R.drawable.ic_pin, "Location",
                "Your IT admin collects the device location for Geo-tracking "
                        + "and generating reports.");
        listRow(c1, R.drawable.ic_wifi, "MAC Address",
                "Your IT admin collects the Bluetooth, Wi-Fi MAC addresses "
                        + "for inventory and generating reports.");
        toggleRow(c1, R.drawable.ic_shield, "Log Privacy",
                "Enable to mask your personal data");
        wrap.addView(c1);

        wrap.addView(sectionLabel("Remote commands"));
        LinearLayout c2 = listCard();
        listRow(c2, R.drawable.ic_monitor, "Remote View",
                "User permission required to remotely view device.");
        listRow(c2, R.drawable.ic_trash, "Complete Wipe",
                "User permission not required for wiping device data");
        wrap.addView(c2);
        return wrap;
    }

    private TextView sectionLabel(String text) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(15);
        t.setTextColor(INK);
        t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        t.setGravity(Gravity.END);
        t.setPadding(dp(20), dp(16), dp(20), dp(8));
        return t;
    }

    private View buildSupport() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);

        TextView toast = new TextView(this);
        toast.setText("Verify network connectivity");
        toast.setTextSize(13);
        toast.setTextColor(Color.WHITE);
        toast.setGravity(Gravity.CENTER);
        toast.setBackgroundColor(0xFF5A5A5A);
        toast.setPadding(dp(12), dp(10), dp(12), dp(10));
        box.addView(toast);

        LinearLayout c = listCard();
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        clp.setMargins(dp(14), dp(12), dp(14), dp(14));
        c.setLayoutParams(clp);
        listRow(c, R.drawable.ic_mail, "Send logs via E-mail",
                "Device logs is mailed to Support team");
        box.addView(c);
        return box;
    }

    private View buildPlaceholder() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER_HORIZONTAL);
        box.setPadding(dp(32), dp(150), dp(32), dp(20));

        ImageView iv = new ImageView(this);
        iv.setImageResource(phIcon);
        iv.setLayoutParams(new LinearLayout.LayoutParams(dp(64), dp(64)));
        box.addView(iv);

        TextView head = new TextView(this);
        head.setText(phTitle);
        head.setTextSize(16);
        head.setTextColor(INK);
        head.setTypeface(head.getTypeface(), android.graphics.Typeface.BOLD);
        head.setGravity(Gravity.CENTER);
        head.setPadding(0, dp(18), 0, 0);
        box.addView(head);

        TextView msg = new TextView(this);
        msg.setText(phMsg);
        msg.setTextSize(13);
        msg.setTextColor(MUTED);
        msg.setGravity(Gravity.CENTER);
        msg.setPadding(0, dp(8), 0, 0);
        box.addView(msg);
        return box;
    }

    private LinearLayout listCard() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(CARD_BG);
        bg.setCornerRadius(dp(12));
        card.setBackground(bg);
        if (Build.VERSION.SDK_INT >= 21) {
            card.setElevation(dp(2));
        }
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(dp(14), dp(6), dp(14), dp(6));
        card.setLayoutParams(lp);
        card.setPadding(dp(18), dp(8), dp(18), dp(8));
        return card;
    }

    private void listRow(LinearLayout parent, int iconRes, String label, String value) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(14), 0, dp(14));

        LinearLayout txt = new LinearLayout(this);
        txt.setOrientation(LinearLayout.VERTICAL);
        txt.setLayoutParams(new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        TextView k = new TextView(this);
        k.setText(label);
        k.setTextSize(16);
        k.setTextColor(INK);
        k.setTypeface(k.getTypeface(), android.graphics.Typeface.BOLD);
        k.setGravity(Gravity.END);
        txt.addView(k);
        TextView v = new TextView(this);
        v.setText(value);
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
        if (iconRes != 0) {
            ImageView iv = new ImageView(this);
            iv.setImageResource(iconRes);
            FrameLayout.LayoutParams ip = new FrameLayout.LayoutParams(
                    dp(24), dp(24), Gravity.CENTER);
            badge.addView(iv, ip);
        }
        row.addView(badge);

        parent.addView(row);
        View sep = new View(this);
        sep.setBackgroundColor(LINE);
        sep.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
        parent.addView(sep);
    }

    /**
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

    /**
     * Render a stored UTC instant ("yyyy-MM-dd'T'HH:mm:ss'Z'") in the
     * device's own timezone, so the display matches the device clock -
     * and the server clock whenever both machines keep correct local
     * time. Storage stays UTC everywhere; only the display converts.
     */
    private String localTime(String isoUtc) {
        if (isoUtc == null || isoUtc.isEmpty()) {
            return "\u2014";
        }
        try {
            java.text.SimpleDateFormat in =
                    new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'",
                            java.util.Locale.US);
            in.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
            java.util.Date d = in.parse(isoUtc);
            if (d == null) {
                return isoUtc.replace("T", " ").replace("Z", " UTC");
            }
            java.text.SimpleDateFormat out =
                    new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss",
                            java.util.Locale.US);
            out.setTimeZone(java.util.TimeZone.getDefault());
            return out.format(d);
        } catch (Exception e) {
            return isoUtc.replace("T", " ").replace("Z", " UTC");
        }
    }

    /** "\u2014" until the panel has answered once, otherwise that success. */
    private String syncLabel() {
        return localTime(SyncCheck.lastSyncAt(this));
    }

    /**
     * Ask the panel and report the outcome. PolicyPull records the timestamp
     * after confirmed application or an up-to-date reply; failures preserve it.
     */
    private void runSync(final TextView label, final ImageView glyph) {
        final String before = label.getText().toString();
        label.setText("Syncing\u2026");
        label.setTextColor(MUTED);
        glyph.setAlpha(140);

        // Pull first: a profile published while this handset was detached has
        // to reach it here, not only when the console happens to push over ADB.
        // The reply is a signed envelope and goes through the same guard as a
        // push, so this cannot apply anything the console would not have sent.
        PolicyPull.sync(this, new PolicyPull.Callback() {
            @Override
            public void onResult(final boolean applied, final String text,
                                  final int rows, final int skipped) {
                render();                       // show the new state at once
                if (applied) {
                    label.setText(syncLabel());
                    label.setTextColor(GREEN);
                    glyph.setAlpha(255);
                    // Report what the handset actually enforced, including the
                    // rows it could not, instead of claiming a clean apply.
                    note("Synced \u00b7 " + rows + " applied"
                            + (skipped > 0 ? ", " + skipped + " not enforceable" : ""));
                    if (skipped > 0) {
                        note("Not enforced here: " + skipped
                                + " restriction(s) have no mechanism on this device.");
                    }
                } else {
                    label.setText(before);
                    label.setTextColor(AMBER);
                    glyph.setAlpha(140);
                    note(text);
                }
                Toast.makeText(MainActivity.this, text, Toast.LENGTH_SHORT).show();
                Branding.refresh(MainActivity.this, new Branding.Callback() {
                    @Override
                    public void onDone(boolean changed) {
                        if (changed) {
                            Toast.makeText(MainActivity.this,
                                    "Logo updated", Toast.LENGTH_SHORT).show();
                        }
                    }
                });
            }
        });
    }
    /** A list row with a real switch widget on the trailing side. */
    private void toggleRow(LinearLayout parent, int iconRes, String label, String sub) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(14), 0, dp(14));

        LinearLayout txt = new LinearLayout(this);
        txt.setOrientation(LinearLayout.VERTICAL);
        txt.setLayoutParams(new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        TextView k = new TextView(this);
        k.setText(label);
        k.setTextSize(16);
        k.setTextColor(INK);
        k.setTypeface(k.getTypeface(), android.graphics.Typeface.BOLD);
        k.setGravity(Gravity.END);
        txt.addView(k);
        TextView v = new TextView(this);
        v.setText(sub);
        v.setTextSize(13);
        v.setTextColor(MUTED);
        v.setGravity(Gravity.END);
        v.setPadding(0, dp(3), 0, 0);
        txt.addView(v);
        row.addView(txt);

        Switch sw = new Switch(this);
        sw.setChecked(true);
        row.addView(sw);
        parent.addView(row);
        View sep = new View(this);
        sep.setBackgroundColor(LINE);
        sep.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
        parent.addView(sep);
    }

    // ------------------------------------------------------------------
    // Data (display-safe subset only - internals stay in state.json)
    // ------------------------------------------------------------------
    private boolean managed() {
        try {
            DevicePolicyManager dpm = (DevicePolicyManager)
                    getSystemService(Context.DEVICE_POLICY_SERVICE);
            ComponentName admin = new ComponentName(this,
                    AlpDeviceAdminReceiver.class);
            return dpm != null && (dpm.isDeviceOwnerApp(getPackageName())
                    || dpm.isAdminActive(admin));
        } catch (Exception e) {
            return false;
        }
    }

    private int errorCount() {
        try {
            File f = new File(getFilesDir(), "state.json");
            String raw = AlpOps.readFile(f.getAbsolutePath());
            if (raw == null) {
                return 0;
            }
            JSONArray arr = new JSONObject(raw).optJSONArray("errors");
            return arr == null ? 0 : arr.length();
        } catch (Exception ignored) {
            return 0;
        }
    }

    private String lastSync() {
        try {
            File f = new File(getFilesDir(), "state.json");
            String raw = AlpOps.readFile(f.getAbsolutePath());
            if (raw == null) {
                return "\u2014";
            }
            String at = new JSONObject(raw).optString("applied_at", "");
            return localTime(at);
        } catch (Exception ignored) {
            return "\u2014";
        }
    }

    private String appVersion() {
        try {
            PackageInfo pi = getPackageManager().getPackageInfo(getPackageName(), 0);
            return pi.versionName == null ? "\u2014" : pi.versionName;
        } catch (Exception e) {
            return "\u2014";
        }
    }

    private String userName() {
        String n = android.os.Build.USER;
        return (n == null || n.isEmpty()) ? "Not set" : n;
    }

    private String deviceName() {
        String m = Build.MODEL == null ? "" : Build.MODEL.trim();
        return m.isEmpty() ? "Android device" : m;
    }

    /** Per-install device identifier (not a credential, safe to display). */
    private String deviceId() {
        try {
            String id = android.provider.Settings.Secure.getString(
                    getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
            return id == null || id.isEmpty() ? "\u2014" : id;
        } catch (Exception e) {
            return "\u2014";
        }
    }

    private String installDate() {
        try {
            long t = getPackageManager().getPackageInfo(getPackageName(), 0).firstInstallTime;
            if (t <= 0L) {
                return "\u2014";
            }
            java.text.SimpleDateFormat f = new java.text.SimpleDateFormat(
                    "yyyy-MM-dd", java.util.Locale.US);
            return f.format(new java.util.Date(t));
        } catch (Exception e) {
            return "\u2014";
        }
    }

    // ------------------------------------------------------------------
    // Hidden admin gesture + PIN popup (behavior unchanged)
    // ------------------------------------------------------------------
    private void onHeaderTap() {
        long now = System.currentTimeMillis();
        if (now - lastHeaderTap > TAP_WINDOW_MS) {
            headerTaps = 0;
        }
        lastHeaderTap = now;
        headerTaps++;
        if (headerTaps >= TAP_COUNT) {
            headerTaps = 0;
            openAdminUnlock();
        }
    }

    private void openAdminUnlock() {
        final boolean pinOk = PinGuard.configured(MainActivity.this);
        final boolean emgOk = EmergencyCodes.configured(MainActivity.this);
        if (!pinOk && !emgOk) {
            note("No unlock method provisioned yet.");
            return;
        }
        if (pinOk && !emgOk) {
            showPinDialog();
            return;
        }
        if (!pinOk && emgOk) {
            showEmergencyDialog();
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Admin unlock")
                .setItems(new String[]{"Unlock with PIN", "Offline emergency code"},
                        new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface dialog, int which) {
                                if (which == 0) {
                                    showPinDialog();
                                } else {
                                    showEmergencyDialog();
                                }
                            }
                        })
                .setNegativeButton("Cancel", null)
                .show();
    }



    private void showEmergencyDialog() {
        final String[] purposes = {"rollback", "withdraw_uninstall"};
        final String[] labels = {"\u0631\u0641\u0639 \u0627\u0644\u0642\u064a\u0648\u062f",
                                 "\u0633\u062d\u0628 \u0627\u0644\u0625\u062f\u0627\u0631\u0629 "
                                 + "\u0648\u062d\u0630\u0641 \u0627\u0644\u062a\u0637\u0628\u064a\u0642"};
        new AlertDialog.Builder(this)
                .setTitle("\u0631\u0645\u0632 \u0627\u0644\u0637\u0648\u0627\u0631\u0626")
                .setItems(labels,
                        new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface dialog, int which) {
                                showEmergencyCodeDialog(purposes[which]);
                            }
                        })
                .setNegativeButton("\u0625\u0644\u063a\u0627\u0621", null)
                .show();
    }

    private void showEmergencyCodeDialog(final String purpose) {
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_NUMBER);
        long lockedFor = EmergencyCodes.lockRemainingSeconds(this);
        String msg = "\u0623\u062f\u062e\u0644 \u0631\u0645\u0632 \u0627\u0644\u0637\u0648\u0627\u0631\u0626 "
                + "\u0627\u0644\u0645\u0648\u0644\u062f \u0645\u0646 \u0644\u0648\u062d\u0629 \u0627\u0644\u062a\u062d\u0643\u0645 "
                + "(8 \u0623\u0631\u0642\u0627\u0645)."
                + (lockedFor > 0
                        ? "\n\u0645\u0642\u0641\u0644 \u062d\u0627\u0644\u064a\u0627."
                        : "");
        new AlertDialog.Builder(this)
                .setTitle("\u0631\u0645\u0632 \u0627\u0644\u0637\u0648\u0627\u0631\u0626")
                .setMessage(msg)
                .setView(input)
                .setPositiveButton("\u062a\u0623\u0643\u064a\u062f",
                        new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface dialog, int which) {
                                String result = EmergencyCodes.verify(MainActivity.this,
                                        purpose, input.getText().toString());
                                if (result == null) {
                                    runEmergencyPurpose(purpose);
                                } else {
                                    note(result);
                                }
                            }
                        })
                .setNegativeButton("\u0625\u0644\u063a\u0627\u0621", null)
                .show();
    }

    private void runEmergencyPurpose(String purpose) {
        AlpOps.localRollback(MainActivity.this);
        if ("withdraw_uninstall".equals(purpose)) {
            AlpOps.withdrawDeviceOwnerWithToken(MainActivity.this);
            try {
                Intent un = new Intent(Intent.ACTION_DELETE,
                        android.net.Uri.parse("package:" + getPackageName()));
                startActivity(un);
            } catch (Exception e) {
                note("Withdrawn.");
                render();
                return;
            }
        }
        render();
        note("Emergency code accepted - done offline.");
    }

    private void showPinDialog() {
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_NUMBER);
        long lockedFor = PinGuard.lockRemainingSeconds(this);
        int left = Math.max(0, 5 - PinGuard.fails(this));
        String msg = "\u0623\u062f\u062e\u0644 \u0631\u0645\u0632 \u0627\u0644\u0645\u0633\u0624\u0648\u0644 "
                + "\u0627\u0644\u0635\u0627\u062f\u0631 \u0645\u0646 \u0648\u062d\u062f\u0629 \u0627\u0644\u062a\u062d\u0643\u0645 "
                + "\u0644\u0625\u0644\u063a\u0627\u0621 \u0627\u0644\u0625\u062f\u0627\u0631\u0629 \u0645\u0646 \u0647\u0630\u0627 "
                + "\u0627\u0644\u062c\u0647\u0627\u0632."
                + (lockedFor > 0
                        ? "\n\u0645\u0642\u0641\u0644 \u062d\u0627\u0644\u064a\u0627 \u2014 \u062d\u0627\u0648\u0644 "
                        + "\u0628\u0639\u062f " + lockedFor + " \u062b\u0627\u0646\u064a\u0629."
                        : "\n\u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0627\u062a \u0627\u0644\u0645\u062a\u0628\u0642\u064a\u0629: "
                        + left + " \u0645\u0646 5.");
        new AlertDialog.Builder(this)
                .setTitle("\u0625\u0644\u063a\u0627\u0621 \u0627\u0644\u0625\u062f\u0627\u0631\u0629 \u2014 "
                        + "\u0623\u062f\u062e\u0644 \u0631\u0645\u0632 PIN")
                .setMessage(msg)
                .setView(input)
                .setPositiveButton("\u062a\u0623\u0643\u064a\u062f",
                        new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface dialog, int which) {
                                String result = PinGuard.verify(MainActivity.this,
                                        input.getText().toString());
                                if (result == null) {
                                    AlpOps.localRollback(MainActivity.this);
                                    render();
                                    note("Rolled back via PIN \u2014 restrictions cleared.");
                                } else {
                                    note(result);
                                }
                            }
                        })
                .setNegativeButton("\u0625\u0644\u063a\u0627\u0621", null)
                .show();
    }

    // ------------------------------------------------------------------
    // Widget helpers
    // ------------------------------------------------------------------
    private void note(String msg) {
        if (statusLine != null) {
            statusLine.setText(msg);
        }
    }

    private int dp(int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                getResources().getDisplayMetrics());
    }

    private int statusBarHeight() {
        try {
            int id = getResources().getIdentifier(
                    "status_bar_height", "dimen", "android");
            if (id > 0) {
                return getResources().getDimensionPixelSize(id);
            }
        } catch (Exception ignored) {
        }
        return 0;
    }

    private TextView pill(String text, int bg, int fg) {
        TextView p = new TextView(this);
        setPill(p, text, bg, fg);
        return p;
    }

    private void setPill(TextView p, String text, int bg, int fg) {
        p.setText(text);
        p.setTextSize(12);
        p.setTextColor(fg);
        p.setTypeface(p.getTypeface(), android.graphics.Typeface.BOLD);
        p.setGravity(Gravity.CENTER);
        GradientDrawable d = new GradientDrawable();
        d.setColor(bg);
        d.setCornerRadius(dp(20));
        p.setPadding(dp(14), dp(8), dp(14), dp(8));
        p.setBackground(d);
    }

    static void startWifiEnforcementService(Context context) {
        try {
            if (android.os.Build.VERSION.SDK_INT >= 26) {
                context.startForegroundService(
                        new Intent(context, AlpForegroundService.class));
            } else {
                // startForegroundService does not exist before API 26;
                // calling it would throw NoSuchMethodError (an Error, not
                // an Exception) and kill the launch. Plain startService is
                // the correct legacy entry point.
                context.startService(
                        new Intent(context, AlpForegroundService.class));
            }
        } catch (Exception e) {
            android.util.Log.d("ALP", "startForegroundService failed: "
                    + e.getClass().getSimpleName());
        }
    }

    private void startWifiEnforcementService() {
        startWifiEnforcementService(this);
    }
}
