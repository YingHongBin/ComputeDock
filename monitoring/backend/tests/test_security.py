from computedock_monitor.security import digest_secret, hash_password, verify_password


def test_password_hash_and_verify() -> None:
    encoded = hash_password("this-is-a-long-password")
    assert "this-is-a-long-password" not in encoded
    assert verify_password(encoded, "this-is-a-long-password")
    assert not verify_password(encoded, "wrong-password")


def test_token_digest() -> None:
    assert digest_secret("cdr_secret") == digest_secret("cdr_secret")
