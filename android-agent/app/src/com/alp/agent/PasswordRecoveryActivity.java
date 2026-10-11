package com.alp.agent;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputFilter;
import android.text.InputType;
import android.text.TextWatcher;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Passcode recovery challenge.
 *
 * Laid out to mirror the reference console: a speech bubble carrying the
 * masked passcode, a red "!" badge on its edge, the "Incorrect Passcode!"
 * headline, the "contact your IT administrator" hint, the recovery-key field
 * and a single Next action.
 */
public class PasswordRecoveryActivity extends Activity {

    // ---- palette -----------------------------------------------------
    private static final int BG = 0xFFF4F6FA;
    private static final int BUBBLE_FILL = 0xFFFFF6F6;
    private static final int BUBBLE_STROKE = 0xFFF2B4B4;
    private static final int BADGE = 0xFFE03A34;
    private static final int DOT = 0xFFE8EAEF;
    private static final int DOT_STAR = 0xFF525A66;
    private static final int SPARK = 0xFFF0A9A9;
    private static final int TITLE = 0xFF111827;
    private static final int SUB = 0xFF6B7280;
    private static final int INPUT_BG = 0xFFFFFFFF;
    private static final int INPUT_BORDER = 0xFFD9DDE4;
    private static final int INPUT_HINT = 0xFF9AA1AC;
    private static final int ERR = 0xFFD64545;
    private static final int BTN = 0xFF2563EB;
    private static final int BTN_OFF_BG = 0xFFE8EAEE;
    private static final int BTN_OFF_FG = 0xFF9AA0A6;
    private static final int LINK = 0xFF94A3B8;
    private static final int CODE_DIGITS = 8;
    /** Target rendered heights, in dp. */
    private static final int FIELD_H = 42;
    private static final int BUTTON_H = 42;

    private LinearLayout card;
    private TextView title;
    private TextView subtitle;

    private EditText codeInput;
    private TextView errorText;
    private Button nextBtn;

    private EditText newPinInput;
    private EditText confirmPinInput;
    private TextView step2ErrorText;
    private Button savePinBtn;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                            | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                            | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);
        }

        try {
            if (getActionBar() != null) {
                getActionBar().hide();
            }
        } catch (Exception ignored) {
        }

        setContentView(buildScreen());
    }

    @Override
    public void onBackPressed() {
        // The challenge is never mandatory: back leaves it, the device and the
        // app stay fully usable, and the notification remains as the way back.
        PasswordRecovery.releaseScreenOn(this);
        finish();
    }

    @Override
    protected void onDestroy() {
        PasswordRecovery.releaseScreenOn(this);
        super.onDestroy();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (!hasFocus) {
            // Nothing here should take this screen down; log it so an
            // unexpected dismissal is visible instead of silent.
            android.util.Log.d("ALP", "recovery window lost focus");
        }
    }

    @Override
    protected void onStop() {
        super.onStop();
        // Only the user may dismiss the challenge — but the restore below
        // deliberately re-launches this activity, and that re-entry lands in
        // onStart() again. Guarding on isFinishing() alone is not enough:
        // the app's own MainActivity steals the foreground on every policy
        // sync, which parked this screen behind it and made the challenge look
        // as if it had closed itself. Restoring once is the fix; restoring in a
        // loop would fight every legitimate hand-off (e.g. the system passcode
        // screen we deliberately open).
        if (!isFinishing() && !isChangingConfigurations()) {
            android.util.Log.d("ALP", "recovery screen hidden by another "
                    + "activity — restoring");
            try {
                Intent back = new Intent(this, PasswordRecoveryActivity.class);
                back.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                startActivity(back);
            } catch (Exception e) {
                android.util.Log.d("ALP", "recovery restore refused: "
                        + e.getClass().getSimpleName());
            }
        }
    }

    // ------------------------------------------------------------------
    // screen
    // ------------------------------------------------------------------
    private View buildScreen() {
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(BG);
        scroll.setFillViewport(true);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);
        col.setPadding(dp(28), dp(40), dp(28), dp(32));

        // speech bubble + red badge
        BubbleView bubble = new BubbleView(this);
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(150));
        blp.bottomMargin = dp(6);
        bubble.setLayoutParams(blp);
        col.addView(bubble);

        title = text("Incorrect Passcode!", 21, TITLE, true);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        tlp.topMargin = dp(18);
        title.setLayoutParams(tlp);
        col.addView(title);

        subtitle = text("Contact your IT Administrator to reset the passcode"
                + " and unlock the device", 13, SUB, false);
        subtitle.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        slp.topMargin = dp(12);
        subtitle.setLayoutParams(slp);
        col.addView(subtitle);

        card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        clp.topMargin = dp(22);
        card.setLayoutParams(clp);
        col.addView(card);

        buildStep1(card);

        scroll.addView(col);
        return scroll;
    }

    private void buildStep1(LinearLayout box) {
        box.removeAllViews();

        codeInput = new EditText(this);
        codeInput.setHint("Enter the recovery key");
        codeInput.setHintTextColor(INPUT_HINT);
        codeInput.setTextColor(TITLE);
        codeInput.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        codeInput.setSingleLine(true);
        codeInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        codeInput.setFilters(new InputFilter[]{new InputFilter.LengthFilter(CODE_DIGITS)});
        codeInput.setPadding(dp(14), padV(FIELD_H), dp(14), padV(FIELD_H));
        codeInput.setBackground(rounded(INPUT_BG, INPUT_BORDER, 6, 1));
        codeInput.setLayoutParams(fill(FIELD_H));
        box.addView(codeInput);

        errorText = text("", 12, ERR, false);
        errorText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams elp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        elp.topMargin = dp(8);
        errorText.setLayoutParams(elp);
        errorText.setVisibility(View.GONE);
        box.addView(errorText);

        nextBtn = button("Next", BTN_OFF_BG, BTN_OFF_FG);
        LinearLayout.LayoutParams nlp = fill(BUTTON_H);
        nlp.topMargin = dp(12);
        nextBtn.setLayoutParams(nlp);
        nextBtn.setEnabled(false);
        nextBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                verify();
            }
        });
        box.addView(nextBtn);

        // Explicit, discreet exit: the challenge must never be a trap.
        TextView cancel = text("Cancel", 13, LINK, false);
        cancel.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams clp2 = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        clp2.topMargin = dp(14);
        cancel.setLayoutParams(clp2);
        cancel.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });
        box.addView(cancel);

        codeInput.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int a, int b, int c) {
            }

            @Override
            public void onTextChanged(CharSequence s, int a, int b, int c) {
            }

            @Override
            public void afterTextChanged(Editable s) {
                boolean ready = s.length() == CODE_DIGITS;
                if (nextBtn.isEnabled() != ready) {
                    nextBtn.setEnabled(ready);
                    nextBtn.setTextColor(ready ? Color.WHITE : BTN_OFF_FG);
                    nextBtn.setBackground(roundable(ready ? BTN : BTN_OFF_BG, 8));
                }
                if (ready) {
                    errorText.setVisibility(View.GONE);
                }
            }
        });
    }

    // ------------------------------------------------------------------
    // behaviour
    // ------------------------------------------------------------------
    private void verify() {
        String code = codeInput.getText().toString().trim();
        if (code.length() < CODE_DIGITS) {
            fail("Enter all " + CODE_DIGITS + " digits of the recovery key");
            return;
        }
        errorText.setVisibility(View.GONE);
        nextBtn.setEnabled(false);

        String err = PasswordRecovery.verifyRecoveryCode(this, code);
        if (err != null) {
            fail("Incorrect recovery key — " + err);
            return;
        }

        // A valid key means one thing only: this person is authorised. What
        // happens next is the user's, in the system screen.
        //
        // There is deliberately NO "enter a new passcode" step here. Since
        // Android 11 a DPC may not call resetPassword() at all (it throws
        // "Device admin can no longer call resetPassword()" for apps targeting
        // API 24+), so any PIN typed into this app could only be discarded. The
        // old two-step flow asked for a passcode that was never applied, left
        // the old lock standing, then re-prompted for the recovery key once the
        // gate expired — confusing, and it looked as if the reset had worked.
        if (!PasswordRecovery.openSystemSetPassword(this)) {
            fail("Recovery key accepted. Open Settings > Security to change "
                    + "the screen lock.");
            return;
        }

        PasswordRecovery.completeHandoff(this);
        Toast.makeText(this, "Set your new passcode in the system screen",
                Toast.LENGTH_LONG).show();
        finish();
    }

    private void fail(String message) {
        errorText.setText(message);
        errorText.setVisibility(View.VISIBLE);
        codeInput.setText("");
        nextBtn.setEnabled(false);
        nextBtn.setTextColor(BTN_OFF_FG);
        nextBtn.setBackground(roundable(BTN_OFF_BG, 8));
    }

    private void showStep2() {
        title.setText("Set a new passcode");
        subtitle.setText("Your recovery key was accepted. Choose a new passcode"
                + " for this device.");

        card.removeAllViews();

        newPinInput = pinField("New passcode (4-16 digits)");
        LinearLayout.LayoutParams nlp = fill(FIELD_H);
        newPinInput.setLayoutParams(nlp);
        card.addView(newPinInput);

        confirmPinInput = pinField("Confirm new passcode");
        LinearLayout.LayoutParams clp = fill(FIELD_H);
        clp.topMargin = dp(10);
        confirmPinInput.setLayoutParams(clp);
        card.addView(confirmPinInput);

        step2ErrorText = text("", 12, ERR, false);
        step2ErrorText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams elp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        elp.topMargin = dp(8);
        step2ErrorText.setLayoutParams(elp);
        step2ErrorText.setVisibility(View.GONE);
        card.addView(step2ErrorText);

        savePinBtn = button("Save and unlock", BTN, Color.WHITE);
        LinearLayout.LayoutParams slp = fill(BUTTON_H);
        slp.topMargin = dp(12);
        savePinBtn.setLayoutParams(slp);
        savePinBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                applyPin();
            }
        });
        card.addView(savePinBtn);

        TextView back = text("Cancel", 13, LINK, false);
        back.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams blp2 = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        blp2.topMargin = dp(14);
        back.setLayoutParams(blp2);
        back.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });
        card.addView(back);
    }

    private EditText pinField(String hint) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setHintTextColor(INPUT_HINT);
        e.setTextColor(TITLE);
        e.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        e.setSingleLine(true);
        e.setInputType(InputType.TYPE_CLASS_NUMBER
                | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        e.setFilters(new InputFilter[]{new InputFilter.LengthFilter(16)});
        e.setPadding(dp(14), padV(FIELD_H), dp(14), padV(FIELD_H));
        e.setBackground(rounded(INPUT_BG, INPUT_BORDER, 6, 1));
        return e;
    }

    private void applyPin() {
        String p1 = newPinInput.getText().toString().trim();
        String p2 = confirmPinInput.getText().toString().trim();

        if (p1.length() < 4) {
            step2ErrorText.setText("The passcode must be at least 4 digits");
            step2ErrorText.setVisibility(View.VISIBLE);
            return;
        }
        if (!p1.equals(p2)) {
            step2ErrorText.setText("The two passcodes do not match");
            step2ErrorText.setVisibility(View.VISIBLE);
            return;
        }
        step2ErrorText.setVisibility(View.GONE);
        savePinBtn.setEnabled(false);

        String err = PasswordRecovery.applyNewPassword(this, p1);
        if (err == null) {
            Toast.makeText(this, "Passcode updated", Toast.LENGTH_SHORT).show();
            finish();
        } else if (PasswordRecovery.SYSTEM_UI_REQUIRED.equals(err)) {
            // Android 11+ refuses resetPassword() to apps targeting API 24+.
            // The credential is therefore set by the user in the system screen
            // we just opened — never cleared, and never chosen by the app.
            Toast.makeText(this,
                    "Set your new passcode in the system screen",
                    Toast.LENGTH_LONG).show();
            finish();
        } else {
            // The gate stays open so the user can retry without re-entering
            // the recovery code.
            step2ErrorText.setText(err);
            step2ErrorText.setVisibility(View.VISIBLE);
            savePinBtn.setEnabled(true);
        }
    }

    // ------------------------------------------------------------------
    // small view helpers
    // ------------------------------------------------------------------
    private TextView text(String s, float sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setGravity(Gravity.CENTER);
        if (bold) {
            t.setTypeface(Typeface.DEFAULT_BOLD);
        }
        return t;
    }

    private Button button(String label, int bg, int fg) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextColor(fg);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        b.setAllCaps(false);
        b.setGravity(Gravity.CENTER);
        // A Button reports a taller box than the text it draws; the inset comes
        // from the platform button background, so the height is pinned to keep
        // it visually level with the text fields above it.
        b.setPadding(dp(12), dp(7), dp(12), dp(7));
        b.setMinHeight(0);
        b.setMinWidth(0);
        b.setIncludeFontPadding(false);
        // The Material button theme injects its own insets, which on a tall
        // handset inflate the control far past the requested height.
        b.setBackground(roundable(bg, 6));
        b.setStateListAnimator(null);
        return b;
    }

    private GradientDrawable roundable(int color, int radiusDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(radiusDp));
        return g;
    }

    private GradientDrawable rounded(int fill, int stroke, int radiusDp, int strokeDp) {
        GradientDrawable g = roundable(fill, radiusDp);
        g.setStroke(dp(strokeDp), stroke);
        return g;
    }

    /**
     * Full-width row whose visual height comes from the control's own vertical
     * padding, never from a layout height.
     *
     * Requesting an explicit height here did not hold: the platform adds the
     * theme's minimum height of the button / text-field on top of it, which
     * rendered these controls at double the requested size on tall handsets.
     * WRAP_CONTENT plus explicit padding is what actually takes effect.
     */
    private LinearLayout.LayoutParams fill(int heightDp) {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    /**
     * Vertical padding for a compact control.
     *
     * WRAP_CONTENT measures padding + the single line of text, so the padding
     * is what actually shrinks these controls: ~14dp of text plus 7dp on each
     * side lands at roughly 28dp rendered, instead of the 50-80dp the theme's
     * minimum height produced.
     */
    private int padV(int heightDp) {
        return dp(7);
    }

    private int dp(float v) {
        return (int) TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    // ------------------------------------------------------------------
    // the reference speech bubble
    // ------------------------------------------------------------------
    /**
     * Draws the masked-passcode speech bubble, its tail, the red "!" badge that
     * straddles the top edge, and the small pink accents around it.
     */
    private static final class BubbleView extends View {

        private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint badge = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint star = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint spark = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path path = new Path();
        private final RectF r = new RectF();
        private final float d;

        BubbleView(Context c) {
            super(c);
            d = getResources().getDisplayMetrics().density;

            fill.setStyle(Paint.Style.FILL);
            fill.setColor(BUBBLE_FILL);

            stroke.setStyle(Paint.Style.STROKE);
            stroke.setStrokeWidth(1.4f * d);
            stroke.setColor(BUBBLE_STROKE);
            stroke.setStrokeJoin(Paint.Join.ROUND);

            badge.setStyle(Paint.Style.FILL);
            badge.setColor(BADGE);

            dot.setStyle(Paint.Style.FILL);
            dot.setColor(DOT);

            star.setColor(DOT_STAR);
            star.setTextAlign(Paint.Align.CENTER);
            star.setTypeface(Typeface.DEFAULT_BOLD);
            star.setTextSize(15f * d);

            spark.setStyle(Paint.Style.STROKE);
            spark.setStrokeWidth(1.8f * d);
            spark.setStrokeCap(Paint.Cap.ROUND);
            spark.setColor(SPARK);
        }

        @Override
        protected void onDraw(Canvas cv) {
            float w = getWidth();
            float h = getHeight();

            float side = 46f * d;          // bubble side padding
            float top = 30f * d;           // room for the badge
            float tailH = 15f * d;
            float radius = 12f * d;

            float left = side;
            float right = w - side;
            float bottom = h - tailH;

            // speech bubble: rounded box + downward tail, one continuous path
            path.reset();
            path.moveTo(left + radius, top);
            path.lineTo(right - radius, top);
            path.quadTo(right, top, right, top + radius);
            path.lineTo(right, bottom - radius);
            path.quadTo(right, bottom, right - radius, bottom);

            float cx = w / 2f;
            float tailHalf = 15f * d;
            path.lineTo(cx + tailHalf, bottom);
            path.lineTo(cx, bottom + tailH);
            path.lineTo(cx - tailHalf, bottom);

            path.lineTo(left + radius, bottom);
            path.quadTo(left, bottom, left, bottom - radius);
            path.lineTo(left, top + radius);
            path.quadTo(left, top, left + radius, top);
            path.close();

            cv.drawPath(path, fill);
            cv.drawPath(path, stroke);

            // masked passcode: five dots with an asterisk in each
            int n = 5;
            float dotR = 13f * d;
            float gap = 12f * d;
            float span = n * dotR * 2 + (n - 1) * gap;
            float startX = cx - span / 2f + dotR;
            float cy = top + (bottom - top) / 2f;
            Paint.FontMetrics fm = star.getFontMetrics();
            float baseline = cy - (fm.ascent + fm.descent) / 2f;

            for (int i = 0; i < n; i++) {
                float x = startX + i * (dotR * 2 + gap);
                cv.drawCircle(x, cy, dotR, dot);
                cv.drawText("*", x, baseline, star);
            }

            // red "!" badge straddling the top edge
            float br = 15f * d;
            float by = top;
            cv.drawCircle(cx, by, br, badge);
            Paint fg = new Paint(Paint.ANTI_ALIAS_FLAG);
            fg.setColor(Color.WHITE);
            fg.setTextAlign(Paint.Align.CENTER);
            fg.setTypeface(Typeface.DEFAULT_BOLD);
            fg.setTextSize(20f * d);
            Paint.FontMetrics f2 = fg.getFontMetrics();
            cv.drawText("!", cx, by - (f2.ascent + f2.descent) / 2f, fg);

            // pink accents
            cross(cv, cx - 68f * d, top - 12f * d, 4f * d);
            cross(cv, cx + 70f * d, top - 6f * d, 3.5f * d);
            cross(cv, cx - 78f * d, bottom + 2f * d, 3f * d);
            cross(cv, cx + 80f * d, bottom + 6f * d, 3f * d);
            cv.drawCircle(cx - 86f * d, top + 14f * d, 1.8f * d, spark);
            cv.drawCircle(cx + 88f * d, top + 26f * d, 1.8f * d, spark);
            cv.drawCircle(cx - 58f * d, top + 34f * d, 1.5f * d, spark);
            cv.drawCircle(cx + 62f * d, top + 40f * d, 1.5f * d, spark);
        }

        private void cross(Canvas cv, float x, float y, float arm) {
            cv.drawLine(x - arm, y, x + arm, y, spark);
            cv.drawLine(x, y - arm, x, y + arm, spark);
        }
    }
}