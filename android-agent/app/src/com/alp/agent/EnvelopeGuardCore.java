package com.alp.agent;

import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * Android-free envelope verification — the exact gate the agent applies to
 * every policy command. Extracted from EnvelopeGuard so the production code
 * path (canonicalization + Ed25519) is compiled and exercised on a plain JVM
 * by the cross-language self-check harness.
 *
 * The signature covers the canonical payload with the two signature fields
 * removed — byte-identical to backend.command._canonical.
 */
final class EnvelopeGuardCore {
    private EnvelopeGuardCore() {
    }

    static final long MAX_FUTURE_SKEW_SECONDS = 300L;

    /**
     * @return null when the envelope is authorized, else a rejection reason.
     */
    static String check(String envelopeJson, String action, byte[] publicKey) {
        if (envelopeJson == null || envelopeJson.trim().isEmpty()) {
            return "missing envelope";
        }
        final Object root;
        try {
            root = CanonicalJson.parse(envelopeJson);
        } catch (IllegalArgumentException e) {
            return "malformed json";
        }
        Map<String, Object> env = CanonicalJson.asMap(root);
        if (env == null) {
            return "malformed json";
        }

        String envelopeAction = CanonicalJson.asString(env.get("action"));
        if (envelopeAction == null || !envelopeAction.equals(shortAction(action))) {
            return "action mismatch";
        }

        String sigHex = CanonicalJson.asString(env.get("sig_ed25519"));
        if (sigHex == null || sigHex.isEmpty()) {
            return "unsigned envelope";
        }
        byte[] sig = EnvelopeGuardCore.fromHex(sigHex);
        if (sig == null || sig.length != 64) {
            return "bad sig encoding";
        }

        long now = System.currentTimeMillis() / 1000L;
        long issued = CanonicalJson.asLong(env.get("issued_at"), 0L);
        long expires = CanonicalJson.asLong(env.get("expires_at"), 0L);
        if (issued > now + MAX_FUTURE_SKEW_SECONDS) {
            return "issued in the future";
        }
        if (expires > 0L && expires < now) {
            return "expired";
        }

        if (publicKey == null || publicKey.length != 32) {
            return "no embedded public key";
        }
        Object stripped = stripSignatures(root);
        byte[] canonical = CanonicalJson.canonical(stripped)
                .getBytes(StandardCharsets.UTF_8);
        if (!Ed25519.verify(publicKey, sig, canonical)) {
            return "bad signature";
        }
        return null; // authorized; replay handling happens in EnvelopeGuard
    }

    static String shortAction(String action) {
        if (action == null) {
            return "";
        }
        int dot = action.lastIndexOf('.');
        return dot >= 0 ? action.substring(dot + 1) : action;
    }

    /**
     * Signature covers every envelope field EXCEPT the two signature fields,
     * mirroring backend.command._canonical.
     */
    static Object stripSignatures(Object root) {
        Map<String, Object> env = CanonicalJson.asMap(root);
        if (env == null) {
            return root;
        }
        java.util.LinkedHashMap<String, Object> out =
                new java.util.LinkedHashMap<String, Object>();
        for (Map.Entry<String, Object> e : env.entrySet()) {
            String k = e.getKey();
            if ("signature".equals(k) || "sig_ed25519".equals(k)) {
                continue;
            }
            out.put(k, e.getValue());
        }
        return out;
    }

    /** RFC 4648-lenient hex decode; returns null on any malformed input. */
    static byte[] fromHex(String hex) {
        if (hex == null) {
            return null;
        }
        String h = hex.trim().toLowerCase(java.util.Locale.US);
        if (h.length() % 2 != 0) {
            return null;
        }
        byte[] out = new byte[h.length() / 2];
        for (int i = 0; i < out.length; i++) {
            int hi = Character.digit(h.charAt(i * 2), 16);
            int lo = Character.digit(h.charAt(i * 2 + 1), 16);
            if (hi < 0 || lo < 0) {
                return null;
            }
            out[i] = (byte) ((hi << 4) | lo);
        }
        return out;
    }
}