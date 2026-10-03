"""Finish the patch and force the Java source to pure ASCII (\\uXXXX escapes)."""
import io
import os

P = os.path.join("android-agent", "app", "src", "com", "alp", "agent",
                 "MainActivity.java")

with io.open(P, "r", encoding="utf-8", newline="") as fh:
    t = fh.read()

if "import android.widget.Switch;" not in t:
    t = t.replace("import android.widget.ScrollView;",
                  "import android.widget.ScrollView;\nimport android.widget.Switch;")

if "private String userName()" not in t:
    helper = (
        "    private String userName() {\n"
        "        String n = android.os.Build.USER;\n"
        "        return (n == null || n.isEmpty()) ? \"Not set\" : n;\n"
        "    }\n\n"
        "    private String deviceName() {"
    )
    t = t.replace("    private String deviceName() {", helper, 1)

out = []
for ch in t:
    cp = ord(ch)
    out.append("\\u%04X" % cp if cp > 127 else ch)
t = "".join(out)

with io.open(P, "w", encoding="ascii", newline="") as fh:
    fh.write(t)

print("Switch import:", "import android.widget.Switch;" in t)
print("userName helper:", "private String userName()" in t)
print("pure ASCII written")