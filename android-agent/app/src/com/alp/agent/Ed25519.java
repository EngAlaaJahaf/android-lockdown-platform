package com.alp.agent;

import java.math.BigInteger;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * Pure-Java Ed25519 verification (RFC 8032), a line-by-line mirror of
 * backend/ed25519.py so the console and the agent agree byte-for-byte.
 *
 * The agent only ever VERIFIES — the private key never exists on-device —
 * so only the verification path is implemented here. Arithmetic is affine and
 * uses Fermat modular inverses exactly like the Python reference (identical
 * exceptional-case handling, including the identity corner).
 */
final class Ed25519 {
    private Ed25519() {
    }

    private static final BigInteger P = BigInteger.ONE.shiftLeft(255)
            .subtract(BigInteger.valueOf(19));
    private static final BigInteger L = BigInteger.ONE.shiftLeft(252)
            .add(new BigInteger("27742317777372353535851937790883648493"));
    // d = -121665/121666 mod p
    private static final BigInteger D = new BigInteger("-121665")
            .multiply(new BigInteger("121666").modInverse(P)).mod(P);
    // i = sqrt(-1) = 2^((p-1)/4)
    private static final BigInteger I = BigInteger.valueOf(2).modPow(
            P.subtract(BigInteger.ONE).divide(BigInteger.valueOf(4)), P);

    private static final BigInteger BX = new BigInteger(
            "15112221349535400772501151409588531511454012693041857206046113283949847762202");
    private static final BigInteger BY = new BigInteger(
            "46316835694926478169428394003475163141307993866256225615783033603165251855960");
    private static final EP B = new EP(BX, BY);

    // Identity is represented as `null`; a corner is a pair of field elements.
    private static final class EP {
        final BigInteger x;
        final BigInteger y;

        EP(BigInteger x, BigInteger y) {
            this.x = x;
            this.y = y;
        }
    }

    private static BigInteger feInv(BigInteger a) {
        return a.modPow(P.subtract(BigInteger.valueOf(2)), P);
    }

    private static EP add(EP a, EP b) {
        if (a == null) {
            return b;
        }
        if (b == null) {
            return a;
        }
        BigInteger x1y2 = a.x.multiply(b.y).mod(P);
        BigInteger y1x2 = a.y.multiply(b.x).mod(P);
        BigInteger xy = a.x.multiply(b.x).multiply(a.y).multiply(b.y).mod(P);
        BigInteger denX = BigInteger.ONE.add(D.multiply(xy)).mod(P);
        BigInteger denY = BigInteger.ONE.subtract(D.multiply(xy)).mod(P);
        if (denX.equals(BigInteger.ZERO) || denY.equals(BigInteger.ZERO)) {
            return null;
        }
        BigInteger x3 = x1y2.add(y1x2).multiply(feInv(denX)).mod(P);
        BigInteger y3 = a.y.multiply(b.y).add(a.x.multiply(b.x))
                .multiply(feInv(denY)).mod(P);
        return new EP(x3, y3);
    }

    private static EP scalarmult(EP point, BigInteger e) {
        EP r = null;
        while (!e.equals(BigInteger.ZERO)) {
            if (e.testBit(0)) {
                r = add(r, point);
            }
            point = add(point, point);
            e = e.shiftRight(1);
        }
        return r;
    }

    private static BigInteger xrecover(BigInteger y) {
        BigInteger xx = y.multiply(y).subtract(BigInteger.ONE)
                .multiply(feInv(D.multiply(y.multiply(y)).add(BigInteger.ONE)))
                .mod(P);
        BigInteger x = xx.modPow(P.add(BigInteger.valueOf(3)).shiftRight(3), P);
        if (!x.multiply(x).subtract(xx).mod(P).equals(BigInteger.ZERO)) {
            x = x.multiply(I).mod(P);
        }
        if (!x.multiply(x).subtract(xx).mod(P).equals(BigInteger.ZERO)) {
            return null;
        }
        return x;
    }

    private static byte[] encodePoint(EP point) {
        if (point == null) {
            byte[] marker = new byte[32];
            marker[0] = 0x01;
            return marker;
        }
        BigInteger val = point.y
                .or(point.x.testBit(0) ? BigInteger.ONE.shiftLeft(255)
                        : BigInteger.ZERO);
        byte[] out = new byte[32];
        byte[] raw = val.toByteArray(); // big-endian, may carry a 0 sign byte
        int n = raw.length;
        int off = (n > 32 && raw[0] == 0) ? 1 : 0;
        n -= off;
        for (int i = 0; i < n; i++) {
            out[i] = raw[raw.length - 1 - i];
        }
        return out;
    }

    private static EP decodePoint(byte[] s) {
        if (s == null || s.length != 32) {
            return null;
        }
        BigInteger buf = littleEndian(s);
        boolean sign = buf.testBit(255);
        BigInteger y = buf.and(BigInteger.ONE.shiftLeft(255)
                .subtract(BigInteger.ONE));
        if (y.compareTo(P) >= 0) {
            return null;
        }
        BigInteger x = xrecover(y);
        if (x == null) {
            return null;
        }
        if (x.testBit(0) != sign) {
            x = P.subtract(x);
        }
        return new EP(x, y);
    }

    private static byte[] compress(BigInteger val) {
        return val.toByteArray();
    }

    private static BigInteger littleEndian(byte[] b) {
        BigInteger v = BigInteger.ZERO;
        for (int i = b.length - 1; i >= 0; i--) {
            v = v.shiftLeft(8).or(BigInteger.valueOf(b[i] & 0xff));
        }
        return v;
    }

    private static byte[] littleEndianBytes(BigInteger v, int size) {
        byte[] out = new byte[size];
        byte[] raw = v.toByteArray();
        for (int i = 0; i < raw.length && i < size; i++) {
            out[i] = raw[raw.length - 1 - i];
        }
        return out;
    }

    /** RFC 8032 verification (cofactorless, exact mirror of the Python). */
    static boolean verify(byte[] publicKey, byte[] sig, byte[] message) {
        if (publicKey == null || publicKey.length != 32
                || sig == null || sig.length != 64) {
            return false;
        }
        byte[] rEnc = new byte[32];
        byte[] sEnc = new byte[32];
        System.arraycopy(sig, 0, rEnc, 0, 32);
        System.arraycopy(sig, 32, sEnc, 0, 32);
        EP A = decodePoint(publicKey);
        EP R = decodePoint(rEnc);
        if (A == null || R == null) {
            return false;
        }
        BigInteger S = littleEndian(sEnc);
        if (S.compareTo(L) >= 0) {
            return false;
        }
        BigInteger k = littleEndian(sha512v(rEnc, publicKey, message)).mod(L);
        byte[] lhs = encodePoint(scalarmult(B, S));
        byte[] rhs = encodePoint(add(R, scalarmult(A, k)));
        return java.util.Arrays.equals(lhs, rhs);
    }

    private static byte[] sha512v(byte[] rEnc, byte[] pub, byte[] msg) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-512");
            md.update(rEnc);
            md.update(pub);
            if (msg != null) {
                md.update(msg);
            }
            return md.digest();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}