package com.alp.agent;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal JSON value model + a canonical serializer that reproduces Python's
 * `json.dumps(obj, sort_keys=True, ensure_ascii=False)` EXACTLY for the
 * envelope payloads the console produces.
 *
 * Canonicalization is the key used by the Ed25519 signature, so any divergence
 * from the Python reference breaks on-device verification. Number tokens are
 * kept verbatim (the JSON we receive is emitted by Python itself, so its number
 * tokens are already canonical); strings are decoded and re-encoded with the
 * Python escaping rules (raw UTF-8, `\n \t ...` short escapes, U+00XX for other
 * control chars); object keys are sorted by Unicode code point (ASCII in
 * practice). No Android APIs are used, so this compiles on a plain JVM.
 */
final class CanonicalJson {
    private CanonicalJson() {
    }

    static final Object NULL = new Object();

    /**
     * A numeric literal kept as the original token so canonical output is
     * byte-identical to what Python emitted (ints and well-formed floats).
     */
    static final class NumToken {
        final String raw;

        NumToken(String raw) {
            this.raw = raw;
        }
    }

    // ------------------------------------------------------------------
    // Parser (recursive descent).
    // ------------------------------------------------------------------

    private static final class Parser {
        private final String s;
        private int i;

        Parser(String s) {
            this.s = s;
        }

        Object parse() {
            ws();
            Object v = value();
            ws();
            if (i != s.length()) {
                throw new IllegalArgumentException("trailing data at " + i);
            }
            return v;
        }

        private void ws() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                    i++;
                } else {
                    break;
                }
            }
        }

        private Object value() {
            if (i >= s.length()) {
                throw new IllegalArgumentException("unexpected end");
            }
            char c = s.charAt(i);
            switch (c) {
                case '{':
                    return object();
                case '[':
                    return array();
                case '"':
                    return string();
                case 't':
                    literal("true");
                    return Boolean.TRUE;
                case 'f':
                    literal("false");
                    return Boolean.FALSE;
                case 'n':
                    literal("null");
                    return NULL;
                default:
                    return number();
            }
        }

        private void literal(String lit) {
            if (!s.regionMatches(i, lit, 0, lit.length())) {
                throw new IllegalArgumentException("bad literal at " + i);
            }
            i += lit.length();
        }

        private Map<String, Object> object() {
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            i++; // {
            ws();
            if (i < s.length() && s.charAt(i) == '}') {
                i++;
                return m;
            }
            while (true) {
                ws();
                if (i >= s.length() || s.charAt(i) != '"') {
                    throw new IllegalArgumentException("expected key at " + i);
                }
                String key = string();
                ws();
                if (i >= s.length() || s.charAt(i) != ':') {
                    throw new IllegalArgumentException("expected ':' at " + i);
                }
                i++;
                ws();
                m.put(key, value());
                ws();
                if (i >= s.length()) {
                    throw new IllegalArgumentException("unterminated object");
                }
                char c = s.charAt(i);
                i++;
                if (c == '}') {
                    return m;
                }
                if (c != ',') {
                    throw new IllegalArgumentException("expected ',' at " + (i - 1));
                }
            }
        }

        private List<Object> array() {
            List<Object> l = new ArrayList<Object>();
            i++; // [
            ws();
            if (i < s.length() && s.charAt(i) == ']') {
                i++;
                return l;
            }
            while (true) {
                ws();
                l.add(value());
                ws();
                if (i >= s.length()) {
                    throw new IllegalArgumentException("unterminated array");
                }
                char c = s.charAt(i);
                i++;
                if (c == ']') {
                    return l;
                }
                if (c != ',') {
                    throw new IllegalArgumentException("expected ',' at " + (i - 1));
                }
            }
        }

        private String string() {
            if (i >= s.length() || s.charAt(i) != '"') {
                throw new IllegalArgumentException("expected string at " + i);
            }
            i++;
            StringBuilder sb = new StringBuilder();
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == '"') {
                    i++;
                    return sb.toString();
                }
                if (c == '\\') {
                    i++;
                    if (i >= s.length()) {
                        throw new IllegalArgumentException("dangling escape");
                    }
                    char e = s.charAt(i);
                    i++;
                    switch (e) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'u': {
                            if (i + 4 > s.length()) {
                                throw new IllegalArgumentException("bad \\u");
                            }
                            sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                            i += 4;
                            break;
                        }
                        default:
                            throw new IllegalArgumentException("bad escape \\" + e);
                    }
                } else {
                    sb.append(c);
                    i++;
                }
            }
            throw new IllegalArgumentException("unterminated string");
        }

        private Object number() {
            int start = i;
            boolean sawDot = false;
            boolean sawExp = false;
            if (i < s.length() && (s.charAt(i) == '-' || s.charAt(i) == '+')) {
                i++;
            }
            while (i < s.length()) {
                char c = s.charAt(i);
                if ((c >= '0' && c <= '9') || c == '.'
                        || c == 'e' || c == 'E' || c == '-' || c == '+') {
                    if (c == '.') {
                        sawDot = true;
                    }
                    if (c == 'e' || c == 'E') {
                        sawExp = true;
                    }
                    i++;
                } else {
                    break;
                }
            }
            if (i == start) {
                throw new IllegalArgumentException("expected number at " + start);
            }
            String tok = s.substring(start, i);
            // Reject malformed numbers ('--', '..', trailing '-') the same way
            // a strict parser would — the console only produces valid ones.
            try {
                if (sawDot || sawExp) {
                    Double.parseDouble(tok);
                } else {
                    Long.parseLong(tok);
                }
            } catch (NumberFormatException e) {
                throw new IllegalArgumentException("bad number " + tok);
            }
            return new NumToken(tok);
        }
    }

    static Object parse(String json) {
        return new Parser(json).parse();
    }

    // ------------------------------------------------------------------
    // Accessors.
    // ------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    static Map<String, Object> asMap(Object v) {
        return v instanceof Map ? (Map<String, Object>) v : null;
    }

    @SuppressWarnings("unchecked")
    static List<Object> asList(Object v) {
        return v instanceof List ? (List<Object>) v : null;
    }

    static String asString(Object v) {
        return v instanceof String ? (String) v : null;
    }

    static Long asLong(Object v, long dflt) {
        if (v == null) {
            return dflt;
        }
        if (v instanceof NumToken) {
            try {
                return Long.parseLong(((NumToken) v).raw);
            } catch (NumberFormatException e) {
                return dflt;
            }
        }
        if (v instanceof Long || v instanceof Integer) {
            return ((Number) v).longValue();
        }
        if (v instanceof Double) {
            return ((Number) v).longValue();
        }
        if (v instanceof String) {
            try {
                return Long.parseLong((String) v);
            } catch (NumberFormatException e) {
                return dflt;
            }
        }
        return dflt;
    }

    static boolean asBool(Object v) {
        return Boolean.TRUE.equals(v);
    }

    // ------------------------------------------------------------------
    // Canonical emitter (mirrors json.dumps(sort_keys=True, ensure_ascii=False)).
    // ------------------------------------------------------------------

    static String canonical(Object value) {
        StringBuilder sb = new StringBuilder();
        emit(value, sb);
        return sb.toString();
    }

    private static void emit(Object v, StringBuilder sb) {
        if (v == null || v == NULL) {
            sb.append("null");
            return;
        }
        if (v instanceof Boolean) {
            sb.append(Boolean.TRUE.equals(v) ? "true" : "false");
            return;
        }
        if (v instanceof NumToken) {
            sb.append(((NumToken) v).raw);
            return;
        }
        if (v instanceof String) {
            emitString((String) v, sb);
            return;
        }
        if (v instanceof Map) {
            emitObject(asMap(v), sb);
            return;
        }
        if (v instanceof List) {
            emitArray((List<?>) v, sb);
            return;
        }
        throw new IllegalArgumentException("unknown value type " + v.getClass());
    }

    private static void emitObject(Map<String, Object> m, StringBuilder sb) {
        List<String> keys = new ArrayList<String>(m.keySet());
        Collections.sort(keys);
        sb.append('{');
        boolean first = true;
        for (String k : keys) {
            if (!first) {
                sb.append(", ");
            }
            first = false;
            emitString(k, sb);
            sb.append(": ");
            emit(m.get(k), sb);
        }
        sb.append('}');
    }

    private static void emitArray(List<?> a, StringBuilder sb) {
        sb.append('[');
        boolean first = true;
        for (Object v : a) {
            if (!first) {
                sb.append(", ");
            }
            first = false;
            emit(v, sb);
        }
        sb.append(']');
    }

    private static void emitString(String s, StringBuilder sb) {
        sb.append('"');
        for (int j = 0; j < s.length(); j++) {
            char c = s.charAt(j);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }
}