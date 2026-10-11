"""Pure-Python Ed25519 (RFC 8032) for the agent command barrier.

Used to sign command envelopes on the console side: the agent APK ships only
the PUBLIC key, so nothing on-device can ever forge a valid envelope. No
third-party dependency (consistent with the hand-rolled scrypt/TOTP/HKDF/GCM
modules in this codebase).

Verification semantics mirror RFC 8032 section 5.1.7 (cofactorless check with
the small-order guards needed for public-key validation).
"""
from __future__ import annotations

import hashlib
import os

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)

_Bx = 15112221349535400772501151409588531511454012693041857206046113283949847762202
_By = 46316835694926478169428394003475163141307993866256225615783033603165251855960
_B = (_Bx, _By)


def _point_add(P, Q):
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    x1y2 = x1 * y2 % _P
    y1x2 = y1 * x2 % _P
    xy = x1 * x2 * y1 * y2 % _P
    den_x = (1 + _D * xy) % _P
    den_y = (1 - _D * xy) % _P
    if den_x == 0 or den_y == 0:
        # Result is the identity (Q == -P), or an exceptional divisor — the
        # group is prime-order so adding non-opposite points never hits 0/0;
        # the negated-check keeps the identity case explicit and safe.
        return None
    x3 = (x1y2 + y1x2) * pow(den_x, _P - 2, _P) % _P
    y3 = (y1 * y2 + x1 * x2) * pow(den_y, _P - 2, _P) % _P
    return x3, y3


def _scalarmult(P, e):
    if e < 0:
        raise ValueError("negative scalar")
    R = None
    while e:
        if e & 1:
            R = _point_add(R, P)
        P = _point_add(P, P)
        e >>= 1
    return R


def _xrecover(y):
    """Recover x from y on -x^2 + y^2 = 1 + d x^2 y^2 (p = 5 mod 8)."""
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = x * _I % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("not a square")
    return x % _P


def encode_point(P):
    if P is None:
        return b"\x01" + b"\x00" * 31
    x, y = P
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8))
                 for i in range(32))


def decode_point(s):
    if len(s) != 32:
        raise ValueError("bad point length")
    buf = int.from_bytes(s, "little")
    sign = (buf >> 255) & 1
    y = buf & ((1 << 255) - 1)
    if y >= _P:
        raise ValueError("y out of range")
    x = _xrecover(y)
    if x & 1 != sign:
        x = _P - x
    return x % _P, y


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _clamp(seed: bytes) -> int:
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a


def public_from_seed(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    return encode_point(_scalarmult(_B, _clamp(seed)))


def keygen() -> tuple[bytes, bytes]:
    """Return (private_seed, public) raw bytes."""
    seed = os.urandom(32)
    pub = public_from_seed(seed)
    return seed, pub


def sign(seed: bytes, message: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = _sha512(seed)
    a = _clamp(seed)
    prefix = h[32:]
    pub = public_from_seed(seed)
    r = int.from_bytes(_sha512(prefix + message), "little") % _L
    R = encode_point(_scalarmult(_B, r))
    k = int.from_bytes(_sha512(R + pub + message), "little") % _L
    S = (r + k * a) % _L
    return R + S.to_bytes(32, "little")


def verify(pub: bytes, sig: bytes, message: bytes) -> bool:
    if len(pub) != 32 or len(sig) != 64:
        return False
    try:
        A = decode_point(pub)
        R = decode_point(sig[:32])
    except ValueError:
        return False
    S = int.from_bytes(sig[32:], "little")
    if S >= _L:
        return False
    k = int.from_bytes(_sha512(sig[:32] + pub + message), "little") % _L
    lhs = encode_point(_scalarmult(_B, S))
    rhs = encode_point(_point_add(R, _scalarmult(A, k)))
    return lhs == rhs


# ---------------------------------------------------------------------------
# Hex convenience wrappers used by the command channel + tooling.
# ---------------------------------------------------------------------------

def keygen_hex() -> tuple[str, str]:
    priv, pub = keygen()
    return priv.hex(), pub.hex()


def public_from_seed_hex(seed_hex: str) -> str:
    return public_from_seed(bytes.fromhex(seed_hex)).hex()


def sign_hex(seed_hex: str, message: bytes) -> str:
    return sign(bytes.fromhex(seed_hex), message).hex()


def verify_hex(pub_hex: str, sig_hex: str, message: bytes) -> bool:
    return verify(bytes.fromhex(pub_hex), bytes.fromhex(sig_hex), message)