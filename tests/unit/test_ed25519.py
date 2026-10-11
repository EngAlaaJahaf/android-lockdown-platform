"""RFC 8032 Ed25519 test vectors — validate the pure-Python implementation."""
import pytest

from backend import ed25519


def _h(x: str) -> bytes:
    return bytes.fromhex(x)


# RFC 8032 §7.1 test 1: empty message.
VEC1_PRIV = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
VEC1_PUB = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
VEC1_SIG = (
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)

# RFC 8032 §7.1 test 2: 1-byte message 0x72.
VEC2_PRIV = "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
VEC2_PUB = "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
VEC2_SIG = (
    "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
    "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
)
VEC2_MSG = _h("72")


@pytest.mark.parametrize("priv,pub", [
    (VEC1_PRIV, VEC1_PUB),
    (VEC2_PRIV, VEC2_PUB),
])
def test_rfc8032_public_key(priv, pub):
    assert ed25519.public_from_seed_hex(priv) == pub


def test_rfc8032_sign_empty():
    sig = ed25519.sign_hex(VEC1_PRIV, b"")
    assert sig == VEC1_SIG
    assert ed25519.verify_hex(VEC1_PUB, VEC1_SIG, b"")


def test_rfc8032_sign_one_byte():
    sig = ed25519.sign_hex(VEC2_PRIV, VEC2_MSG)
    assert sig == VEC2_SIG
    assert ed25519.verify_hex(VEC2_PUB, sig, VEC2_MSG)


def test_verify_rejects_tampered_message():
    assert not ed25519.verify_hex(VEC1_PUB, VEC1_SIG, b"tampered")
    assert ed25519.verify_hex(VEC1_PUB, VEC1_SIG, b"")


def test_verify_rejects_tampered_signature():
    sig = bytearray.fromhex(VEC1_SIG)
    sig[0] ^= 0x01
    assert not ed25519.verify_hex(VEC1_PUB, sig.hex(), b"")


def test_verify_rejects_wrong_public_key():
    other_pub = ed25519.public_from_seed_hex(VEC2_PRIV)
    assert not ed25519.verify_hex(other_pub, VEC1_SIG, b"")


def test_keygen_roundtrip():
    priv, pub = ed25519.keygen_hex()
    assert ed25519.public_from_seed_hex(priv) == pub
    msg = b"round trip message"
    assert ed25519.verify_hex(pub, ed25519.sign_hex(priv, msg), msg)


def test_verify_bad_lengths():
    assert not ed25519.verify_hex(VEC1_PUB, VEC1_SIG[:60].ljust(128, "0"), b"")
    assert not ed25519.verify_hex("aa", VEC1_SIG, b"")


def test_verify_rejects_large_scalar_S():
    # S >= L must be rejected (malleability guard).
    sig = bytearray.fromhex(VEC1_SIG)
    L = 2 ** 252 + 27742317777372353535851937790883648493
    sig[32:] = (L + 1).to_bytes(32, "little")
    assert not ed25519.verify_hex(VEC1_PUB, sig.hex(), b"")


# ---------------------------------------------------------------------------
# command-channel integration: envelopes carry sig_ed25519 when a key exists.
# ---------------------------------------------------------------------------

def _priv_pub_env():
    from backend import config, ed25519, command
    priv, pub = ed25519.keygen_hex()
    old_env, old_file = config.ED25519_PRIV, config.ED25519_KEY_FILE
    config.ED25519_PRIV = priv
    try:
        env = command.new_command(7, "DEV-9", "CLEAR_POLICY", {"reason": "x"})
    finally:
        config.ED25519_PRIV = old_env
        config.ED25519_KEY_FILE = old_file
    assert env.get("sig_ed25519")
    return env, priv, pub


def test_command_env_signed_when_key_configured():
    env, _priv, _pub = _priv_pub_env()
    assert len(env["sig_ed25519"]) == 128
    # HMAC signature still present and valid (compat layer intact) when the
    # envelope carries no Ed25519 field.
    from backend import command
    env2 = dict(env)
    env2.pop("sig_ed25519")
    command.verify_envelope(env2, "DEV-9")


def test_command_env_verifies_ed25519():
    env, _priv, pub = _priv_pub_env()
    from backend import command
    assert env["sig_ed25519"]
    # Agent-style check against the public key over unsigned canonical.
    canon = command._canonical(
        {k: v for k, v in env.items() if k not in ("signature", "sig_ed25519")})
    assert ed25519.verify_hex(pub, env["sig_ed25519"], canon)


def test_command_env_rejects_tampered_body():
    env, _priv, _pub = _priv_pub_env()
    from backend import command
    env["body"]["reason"] = "evil mutation"
    with pytest.raises(command.CommandRejected):
        command.verify_envelope(env, "DEV-9")


def test_command_env_verify_requires_ed_when_requested():
    env, _priv, _pub = _priv_pub_env()
    from backend import command, config
    old = config.ED25519_PRIV
    config.ED25519_PRIV = ""
    try:
        with pytest.raises(command.CommandRejected):
            command.verify_envelope(env, "DEV-9", require_ed=True)
    finally:
        config.ED25519_PRIV = old