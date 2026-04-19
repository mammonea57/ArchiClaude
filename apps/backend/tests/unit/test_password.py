import pytest
from core.auth.password import hash_password, verify_password


def test_hash_password_produces_bcrypt():
    h = hash_password("my_secret_123")
    assert h.startswith("$2b$")  # bcrypt prefix
    assert len(h) >= 60


def test_verify_correct_password():
    h = hash_password("correct_password")
    assert verify_password("correct_password", h) is True


def test_verify_wrong_password():
    h = hash_password("correct_password")
    assert verify_password("wrong_password", h) is False


def test_hash_is_deterministic_with_same_input_differs():
    """Bcrypt uses a random salt — same password hashes differently."""
    h1 = hash_password("abc")
    h2 = hash_password("abc")
    assert h1 != h2
    assert verify_password("abc", h1)
    assert verify_password("abc", h2)
