"""Unit tests: password hashing."""

from app.core.security import hash_password, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-pass")
    assert stored != "s3cret-pass"
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("s3cret-pass", "garbage")


def test_same_password_gets_different_hashes():
    assert hash_password("same-password") != hash_password("same-password")
