package com.alp.agent;

import java.nio.charset.StandardCharsets;

/**
 * Constant-time byte/string comparison.
 *
 * Deliberately NOT java.security.MessageDigest.isEqual: on some Android builds
 * (reproduced on API 22 / Android 5.1.1) that call reports two unequal
 * byte arrays as equal, which silently turned every credential gate in this
 * app into a no-op — an arbitrary 8-digit string satisfied the offline
 * recovery code, and by extension any PIN compared with it.
 *
 * This compare folds length and every byte into one accumulator and only then
 * tests it, so it both compares in time independent of where the first
 * difference is and returns true only for genuinely identical inputs.
 */
final class Cmp {
    private Cmp() {
    }

    static boolean equals(String a, String b) {
        if (a == null || b == null) {
            return a == b;
        }
        return equals(a.getBytes(StandardCharsets.UTF_8),
                b.getBytes(StandardCharsets.UTF_8));
    }

    static boolean equals(byte[] x, byte[] y) {
        if (x == null || y == null) {
            return x == y;
        }
        int diff = x.length ^ y.length;
        int n = x.length > y.length ? x.length : y.length;
        for (int i = 0; i < n; i++) {
            byte xb = i < x.length ? x[i] : 0;
            byte yb = i < y.length ? y[i] : 0;
            diff |= xb ^ yb;
        }
        return diff == 0;
    }
}