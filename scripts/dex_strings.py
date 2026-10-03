"""Static string extraction from the app's DEX files, filtered for
control-plane (server/API) endpoint candidates.

Pure read-only analysis of strings held in the APK's classes*.dex.
"""
import io
import os
import re
import sys
import zipfile

APK = os.path.join("extracted-apks", "manageengine-mdm", "manageengine-mdm.apk")

STR_RE = re.compile(rb"[\x20-\x7e]{4,}")

INTERESTING = re.compile(
    r"(/(api|agent|mdm|rest|servlet)/|/v\d/|/command|/enroll|/enrollment"
    r"|/device|/config|/settings|/profile|/policy|/remote|/report|/sync"
    r"|\.php|\.json|\.do\b)", re.I)

DOMAINISH = re.compile(r"^[a-zA-Z0-9\.\-]+\.(com|net|org|io|cn|co|me)$")


def strings_from(data, limit=400000):
    out = []
    for m in STR_RE.finditer(data):
        try:
            out.append(m.group().decode("ascii"))
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def main():
    z = zipfile.ZipFile(APK)
    dex_names = [n for n in z.namelist()
                 if re.match(r"classes\d*\.dex$", n)]
    print("dex files:", dex_names)

    hits = {}
    domains = {}
    for name in dex_names:
        data = z.read(name)
        for s in strings_from(data):
            if INTERESTING.search(s) and len(s) < 120:
                hits.setdefault(s, set()).add(name)
            if DOMAINISH.match(s) and 4 < len(s) < 60:
                domains.setdefault(s, set()).add(name)

    print("\n=== endpoint-like strings (%d unique) ===" % len(hits))
    for s in sorted(hits)[:120]:
        dexes = ",".join(sorted(hits[s]))
        print("  %-72s [%s]" % (s, dexes))

    print("\n=== domain-like strings (%d unique) ===" % len(domains))
    for s in sorted(domains)[:60]:
        print("  %-50s [%s]" % (s, ",".join(sorted(domains[s]))))
    z.close()


if __name__ == "__main__":
    main()