"""One-off repair: restore Arabic UI strings mangled by a cp1252 round-trip.

Lines are replaced with pure-ASCII Java literals using \\uXXXX escapes so the
source file can never be corrupted by a shell/text round-trip again.
"""
import io
import os

P = os.path.join("android-agent", "app", "src", "com", "alp", "agent",
                 "MainActivity.java")

REPL = {
    475: '                + "\\u0647\\u0644 \\u062a\\u062d\\u062a\\u0627\\u062c \\u0645\\u0633\\u0627\\u0639\\u062f\\u0629\\u061f \\u062a\\u0648\\u0627\\u0635\\u0644 \\u0645\\u0639 \\u0645\\u0633\\u0624\\u0648\\u0644 \\u062a\\u0642\\u0646\\u064a\\u0629 \\u0627\\u0644\\u0645\\u0639\\u0644\\u0648\\u0645\\u0627\\u062a.");',
    732: '            note("\\u0627\\u0644\\u0628\\u0631\\u0646\\u0627\\u0645\\u062c \\u0628\\u062f\\u0648\\u0646 PIN \\u0645\\u0639\\u0631\\u0641 \\u2014 \\u0648\\u062d\\u062f\\u0629 \\u0627\\u0644\\u062a\\u062d\\u0643\\u0645 \\u0647\\u064a \\u0645\\u0646 \\u062a\\u0646\\u0634\\u0626\\u0647");',
    743: '        String msg = "\\u0623\\u062f\\u062e\\u0644 \\u0631\\u0645\\u0632 \\u0627\\u0644\\u0645\\u0633\\u0624\\u0648\\u0644 \\u0627\\u0644\\u0635\\u0627\\u062f\\u0631 \\u0645\\u0646 \\u0648\\u062d\\u062f\\u0629 \\u0627\\u0644\\u062a\\u062d\\u0643\\u0645 \\u0644\\u0625\\u0644\\u063a\\u0627\\u0621 \\u0627\\u0644\\u0625\\u062f\\u0627\\u0631\\u0629 \\u0645\\u0646 \\u0647\\u0630\\u0627 \\u0627\\u0644\\u062c\\u0647\\u0627\\u0632."',
    745: '                        + "\\n\\u0645\\u0642\\u0641\\u0644 \\u062d\\u0627\\u0644\\u064a\\u0627 \\u2014 \\u062d\\u0627\\u0648\\u0644 \\u0628\\u0639\\u062f " + lockedFor + " \\u062b\\u0627\\u0646\\u064a\\u0629."',
    746: '                        : "\\n\\u0627\\u0644\\u0645\\u062d\\u0627\\u0648\\u0644\\u0627\\u062a \\u0627\\u0644\\u0645\\u062a\\u0628\\u0642\\u064a\\u0629: " + left + " \\u0645\\u0646 5.");',
    748: '                .setTitle("\\u0625\\u0644\\u063a\\u0627\\u0621 \\u0627\\u0644\\u0625\\u062f\\u0627\\u0631\\u0629 \\u2014 \\u0623\\u062f\\u062e\\u0644 \\u0631\\u0645\\u0632 PIN")',
    751: '                .setPositiveButton("\\u062a\\u0623\\u0643\\u064a\\u062f", new android.content.DialogInterface.OnClickListener() {',
    765: '                .setNegativeButton("\\u0625\\u0644\\u063a\\u0627\\u0621", null)',
}

with io.open(P, "r", encoding="utf-8", newline="") as fh:
    lines = fh.read().split("\n")

for ln, new in REPL.items():
    old = lines[ln - 1]
    lines[ln - 1] = new
    print("line %d fixed" % ln)

out = "\n".join(lines)
assert "�" not in out, "replacement chars remain"
with io.open(P, "w", encoding="ascii", newline="") as fh:
    fh.write(out)
print("written: pure ASCII, %d lines" % len(lines))