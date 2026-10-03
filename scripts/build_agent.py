"""PHASE 3: build the ALP Android DPC/Agent APK with raw SDK tools.

Pipeline (no Gradle, no Docker daemon):
    aapt2 compile -> aapt2 link -> javac (bootclasspath android.jar)
    -> d8 (dex) -> inject classes.dex -> zipalign -> apksigner sign

Output: android-agent/alp-agent.apk (+ build/ artifacts under android-agent/build)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = os.path.join(ROOT, "android-agent")
APP = os.path.join(AGENT, "app")
BUILD = os.path.join(AGENT, "build")
PKG = "com.alp.agent"

SDK = os.environ.get("ANDROID_HOME") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")
BT = os.path.join(SDK, "build-tools", "35.0.1")
PLATFORM = os.path.join(SDK, "platforms", "android-35")
ANDROID_JAR = os.path.join(PLATFORM, "android.jar")

AAPT2 = os.path.join(BT, "aapt2.exe")
D8 = os.path.join(BT, "d8.bat")
APKSIGNER = os.path.join(BT, "apksigner.bat")
ZIPALIGN = os.path.join(BT, "zipalign.exe")

KEYSTORE = os.path.join(AGENT, "alp-debug.keystore")
KEYSTORE_PASS = os.environ.get("ALP_KEYSTORE_PASS", "alp-agent")
KEY_ALIAS = "alp"
OUT_APK = os.path.join(AGENT, "alp-agent.apk")


def run(cmd, **kw):
    print("  $", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(cmd)}")
    return r


def ensure_keystore():
    if os.path.exists(KEYSTORE):
        return
    run(["keytool", "-genkeypair", "-v",
         "-keystore", KEYSTORE, "-storepass", KEYSTORE_PASS,
         "-alias", KEY_ALIAS, "-keypass", KEYSTORE_PASS,
         "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
         "-dname", "CN=ALP Agent, OU=ALP, O=ALP, C=JO"])


def embed_public_key():
    """Write the console Ed25519 PUBLIC key into res/raw/alp_pubkey.bin so the
    on-device EnvelopeGuard can verify commands. The private half never enters
    the APK — a keyfile mismatch here means every agent command is rejected."""
    pub_hex = os.environ.get("ALP_ED_PUB", "").strip()
    if not pub_hex:
        pub_file = os.path.join(ROOT, "android-agent", "alp_pubkey.hex")
        if os.path.exists(pub_file):
            with open(pub_file, "r", encoding="utf-8") as fh:
                pub_hex = fh.read().strip()
    if not pub_hex:
        raise SystemExit(
            "missing Ed25519 public key — run `python scripts/gen_agent_key.py`"
            " (or set ALP_ED_PUB) before building the agent")
    raw = os.path.join(APP, "res", "raw")
    os.makedirs(raw, exist_ok=True)
    with open(os.path.join(raw, "alp_pubkey.bin"), "w", encoding="ascii") as fh:
        fh.write(pub_hex)
    print(f"  embedded Ed25519 public key ({len(pub_hex)} hex chars)")


def write_release_manifest() -> str:
    """Strip android:testOnly AND the launcher icon from the manifest.

    A testOnly APK cannot be claimed as Device Owner (`dpm set-device-owner`
    refuses: "testOnly apps cannot be set as device owner") and it is why
    `adb install` demands -t. debuggable is kept on purpose: the backend
    reads on-device evidence via `adb shell run-as com.alp.agent`.

    Removing the MAIN/LAUNCHER filter hides the app from the app drawer. The
    agent is then reachable only via the dialer secret code (#*#*2026#*#*,
    Telephony.SECRET_CODE) or the console (backend/channel.py wakes it with
    `am start` before delivering envelopes — so the activity stays exported;
    a non-exported MainActivity breaks the console apply path).
    """
    import re
    src = os.path.join(APP, "AndroidManifest.xml")
    with open(src, "r", encoding="utf-8") as fh:
        xml = fh.read()
    if "android:testOnly" not in xml:
        raise SystemExit("release manifest requested but android:testOnly not found")
    release = xml.replace(' android:testOnly="true"', "")

    activity_re = re.compile(
        r'<activity android:name="\.MainActivity"[^>]*>.*?</activity>', re.S)
    m = activity_re.search(release)
    if not m:
        raise SystemExit("release manifest: MainActivity block not found")
    block = m.group(0)
    cleaned = re.sub(
        r'<intent-filter>\s*<action android:name="android\.intent\.action\.MAIN" />'
        r'\s*<category android:name="android\.intent\.category\.LAUNCHER" />'
        r'\s*</intent-filter>', "", block)
    release = release.replace(block, cleaned)

    out = os.path.join(BUILD, "AndroidManifest.release.xml")
    os.makedirs(BUILD, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(release)
    return out


def main() -> None:
    os.chdir(AGENT)
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD)
    for p in (AAPT2, ANDROID_JAR, D8, APKSIGNER, ZIPALIGN):
        if not os.path.exists(p):
            raise SystemExit(f"missing tool: {p}")

    import argparse
    ap = argparse.ArgumentParser(description="build the ALP agent APK")
    ap.add_argument("--release", action="store_true",
                    help="drop android:testOnly so the APK can become Device "
                         "Owner (dpm set-device-owner) + plain `adb install`")
    ap.add_argument("--apk", default=OUT_APK,
                    help=f"output APK path (default {OUT_APK})")
    args = ap.parse_args()

    ensure_keystore()
    embed_public_key()
    manifest = write_release_manifest() if args.release else os.path.join(
        APP, "AndroidManifest.xml")

    res_zip = os.path.join(BUILD, "res.zip")
    run([AAPT2, "compile", "--dir", os.path.join(APP, "res"), "-o", res_zip])

    gen = os.path.join(BUILD, "gen")
    os.makedirs(gen)
    base_apk = os.path.join(BUILD, "base.apk")
    run([AAPT2, "link",
         "-o", base_apk,
         "-I", ANDROID_JAR,
         "--manifest", manifest,
         "--min-sdk-version", "24",
         "--target-sdk-version", "35",
         "--version-code", "1",
         "--version-name", "0.1.0",
         "--java", gen,
         "--auto-add-overlay",
         res_zip])

    classes_dir = os.path.join(BUILD, "classes")
    os.makedirs(classes_dir)
    import glob as _glob
    sources = _glob.glob(os.path.join(APP, "src", "**", "*.java"), recursive=True)
    sources += _glob.glob(os.path.join(gen, "**", "*.java"), recursive=True)
    run(["javac", "-source", "8", "-target", "8",
         "-bootclasspath", ANDROID_JAR,
         "-encoding", "UTF-8",
         "-d", classes_dir] + sources)

    dex_out = os.path.join(BUILD, "dex")
    os.makedirs(dex_out)
    run([D8, "--lib", ANDROID_JAR, "--min-api", "24",
         "--output", dex_out,
         "--release"] + _glob.glob(os.path.join(classes_dir, "**", "*.class"), recursive=True))

    dex_file = os.path.join(dex_out, "classes.dex")
    if not os.path.exists(dex_file):
        raise SystemExit("d8 did not emit classes.dex")

    with zipfile.ZipFile(base_apk, "a") as z:
        z.write(dex_file, "classes.dex")

    aligned = os.path.join(BUILD, "aligned.apk")
    run([ZIPALIGN, "-f", "4", base_apk, aligned])

    if os.path.exists(args.apk):
        os.remove(args.apk)
    run([APKSIGNER, "sign", "--ks", KEYSTORE,
         "--ks-pass", "pass:" + KEYSTORE_PASS,
         "--key-pass", "pass:" + KEYSTORE_PASS,
         "--ks-key-alias", KEY_ALIAS,
         "--out", args.apk, aligned])
    run([APKSIGNER, "verify", "--print-certs", args.apk])

    size = os.path.getsize(args.apk)
    print(f"APK built: {args.apk} ({size} bytes, release={bool(args.release)})")


if __name__ == "__main__":
    main()