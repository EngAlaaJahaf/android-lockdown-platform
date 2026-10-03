"""Cross-language self-check for the on-device Ed25519 barrier.

Compiles the REAL production Java classes (Ed25519, CanonicalJson,
EnvelopeGuardCore) with a plain JDK and runs them against data signed by the
Python console side, proving that:

  1. canonicalization matches Python's _canonical byte-for-byte,
  2. a console-signed envelope verifies in Java via EnvelopeGuardCore,
  3. tampered / unsigned / RFC-compliant-edge signatures behave correctly.

Usage:
    python scripts/agent_jvm_selfcheck.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALP_SIGNING_KEY", "selfcheck-hmac-key-0001")

from backend import command  # noqa: E402
from backend import ed25519  # noqa: E402

SRC = os.path.join(ROOT, "android-agent", "app", "src", "com", "alp", "agent")
CLASSES = ["Ed25519.java", "CanonicalJson.java", "EnvelopeGuardCore.java"]

# RFC 8032 TEST 1 (empty message) + TEST 2 (1-byte message).
V1_PRIV = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
V1_PUB = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
V1_SIG = ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
          "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
V2_PRIV = "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
V2_MSG = bytes.fromhex("72")
V2_SIG = ("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
          "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")


def java_home() -> str:
    jh = os.environ.get("JAVA_HOME", "")
    if jh and os.path.exists(os.path.join(jh, "bin", "javac.exe")):
        return jh
    # Search the JDK used by build_agent (SDK tools dir may change).
    for cand in (
        r"C:\Program Files\Java",
        r"C:\Program Files\Eclipse Adoptium",
        r"C:\Program Files\Microsoft\jdk",
    ):
        if os.path.isdir(cand):
            for d in os.listdir(cand):
                p = os.path.join(cand, d, "bin", "javac.exe")
                if os.path.exists(p):
                    return os.path.dirname(os.path.dirname(p))
    raise SystemExit("no JDK with javac found (set JAVA_HOME)")


def main() -> int:
    jh = java_home()
    javac = os.path.join(jh, "bin", "javac.exe")

    # ---- build the genuine envelope + tampered/unsigned variants ---------
    priv, pub = ed25519.keygen_hex()
    body = {
        "snapshot": [
            {"feature": "WIFI", "desired": "BLOCK"},
            {"feature": "CAMERA", "desired": "BLOCK"},
            {"feature": "ADB", "desired": "BLOCK"},
        ],
        "reason": "e2e selfcheck \u0639\u0631\u0628\u064a should survive",
    }
    env = command.new_command(9, "DEV-JVM", "CLEAR_POLICY", body, ed_key=priv)
    env_json = json.dumps(env, ensure_ascii=False)
    canon = command._canonical({k: v for k, v in env.items()
                                if k not in ("signature", "sig_ed25519")})

    tampered = dict(env)
    tampered["body"] = dict(body)
    tampered["body"]["reason"] = "evil mutation"
    tampered_json = json.dumps(tampered, ensure_ascii=False)

    unsigned = {k: v for k, v in env.items()
                if k not in ("signature", "sig_ed25519")}
    unsigned_json = json.dumps(unsigned, ensure_ascii=False)

    wrong_action = dict(env)
    wrong_action["action"] = "APPLY_POLICY"
    wrong_action_json = json.dumps(wrong_action, ensure_ascii=False)

    # ---- emit the Java test source --------------------------------------
    tmpl = r"""
package com.alp.agent;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

public class TestMain {
    static int failures = 0;

    static void check(String name, boolean ok, boolean want) {
        boolean pass = ok == want;
        if (!pass) failures++;
        System.out.println((pass ? "PASS " : "FAIL ") + name);
    }

    static String read(String path) throws Exception {
        return new String(Files.readAllBytes(Paths.get(path)), StandardCharsets.UTF_8);
    }

    static byte[] hex(String h) {
        String s = h.trim().replaceAll("\\s", "");
        byte[] out = new byte[s.length() / 2];
        for (int i = 0; i < out.length; i++)
            out[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16);
        return out;
    }

    public static void main(String[] a) throws Exception {
        String dir = a[0];
        // 1. RFC 8032 vectors verify with the pure-Java implementation.
        check("rfc1_verify", Ed25519.verify(
                hex(read(dir + "/v1_pub.hex")), hex(read(dir + "/v1_sig.hex")), new byte[0]), true);
        check("rfc2_verify", Ed25519.verify(
                hex(read(dir + "/v2_pub.hex")), hex(read(dir + "/v2_sig.hex")),
                hex(read(dir + "/v2_msg.hex"))), true);
        // 2. malleability / tamper rejection.
        byte[] sig = hex(read(dir + "/v1_sig.hex"));
        sig[0] ^= 0x01;
        check("rfc1_tampered", Ed25519.verify(hex(read(dir + "/v1_pub.hex")), sig, new byte[0]), false);

        byte[] pub = hex(read(dir + "/pub.hex"));
        // 3. genuine envelope: canonical byte-match + guard accepts.
        String envJson = read(dir + "/env.json");
        Object root = CanonicalJson.parse(envJson);
        String canon = CanonicalJson.canonical(EnvelopeGuardCore.stripSignatures(root));
        check("canonical_match",
            java.util.Arrays.equals(canon.getBytes(StandardCharsets.UTF_8), hex(read(dir + "/canon.hex"))), true);
        check("genuine_guard", EnvelopeGuardCore.check(envJson, "CLEAR_POLICY", pub) == null, true);

        // 4. tampered body / unsigned / wrong-action envelopes are rejected.
        check("tampered_reject", EnvelopeGuardCore.check(read(dir + "/tampered.json"), "CLEAR_POLICY", pub) != null, true);
        check("unsigned_reject", EnvelopeGuardCore.check(read(dir + "/unsigned.json"), "CLEAR_POLICY", pub) != null, true);
        check("wrong_action", EnvelopeGuardCore.check(read(dir + "/wrong_action.json"), "CLEAR_POLICY", pub) != null, true);

        // 5. wrong embedded key rejects.
        byte[] otherPub = hex(read(dir + "/other_pub.hex"));
        check("wrong_key_reject", EnvelopeGuardCore.check(envJson, "CLEAR_POLICY", otherPub) != null, true);
        // 6. short-action mapping mirrors receiver constants.
        check("short_action", EnvelopeGuardCore.shortAction("com.alp.agent.CLEAR_POLICY").equals("CLEAR_POLICY"), true);

        System.out.println(failures == 0 ? "ALL PASS" : failures + " FAILURES");
        System.exit(failures == 0 ? 0 : 1);
    }
}
"""
    with tempfile.TemporaryDirectory(prefix="alp_selfcheck_") as work:
        wd = os.path.join(work, "com", "alp", "agent")
        os.makedirs(wd)
        for cls in CLASSES:
            shutil.copy(os.path.join(SRC, cls), wd)
        with open(os.path.join(wd, "TestMain.java"), "w", encoding="utf-8") as fh:
            fh.write(tmpl)

        with open(os.path.join(wd, "env.json"), "w", encoding="utf-8") as fh:
            fh.write(env_json)
        with open(os.path.join(wd, "canon.hex"), "w") as fh:
            fh.write(canon.hex())
        with open(os.path.join(wd, "pub.hex"), "w") as fh:
            fh.write(pub)
        with open(os.path.join(wd, "other_pub.hex"), "w") as fh:
            fh.write(ed25519.public_from_seed_hex(V1_PRIV))
        for name, content in (("v1_pub.hex", V1_PUB), ("v1_sig.hex", V1_SIG),
                              ("v2_pub.hex", ed25519.public_from_seed_hex(V2_PRIV)),
                              ("v2_sig.hex", V2_SIG), ("v2_msg.hex", V2_MSG.hex())):
            with open(os.path.join(wd, name), "w") as fh:
                fh.write(content)
        for name, content in (("tampered.json", tampered_json),
                              ("unsigned.json", unsigned_json),
                              ("wrong_action.json", wrong_action_json)):
            with open(os.path.join(wd, name), "w", encoding="utf-8") as fh:
                fh.write(content)

        sources = [os.path.join(wd, c) for c in CLASSES] + [os.path.join(wd, "TestMain.java")]
        comp = subprocess.run([javac, "--release", "8", "-encoding", "UTF-8",
                               "-d", work] + sources,
                              capture_output=True, text=True)
        if comp.returncode != 0:
            sys.stderr.write(comp.stdout + comp.stderr)
            raise SystemExit("javac failed")
        run = subprocess.run([os.path.join(jh, "bin", "java"), "-cp", work,
                              "com.alp.agent.TestMain", wd],
                             capture_output=True, text=True)
        sys.stdout.write(run.stdout)
        if run.stderr:
            sys.stderr.write(run.stderr)
        if run.returncode != 0:
            raise SystemExit("self-check FAILED")
    print("self-check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())