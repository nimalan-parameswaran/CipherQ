"""
Unit Tests for Security Primitives
Tests Argon2id hashing, session tokens, CSRF tokens, and sliding window rate limiting.
"""
import time
from backend.app.core.security import (
    hash_password,
    verify_password,
    generate_session_token,
    hash_session_token,
    generate_csrf_token,
    rate_limiter
)


def test_argon2id_password_hashing():
    """Verify Argon2id produces valid hashes and verifies correct passwords."""
    pwd = "UltraSecurePassword2026!"
    hashed = hash_password(pwd)

    assert hashed.startswith("$argon2id$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_session_token_and_hashing():
    """Verify session tokens are random and SHA-256 hashed correctly."""
    token1 = generate_session_token()
    token2 = generate_session_token()
    assert token1 != token2
    assert len(token1) >= 40

    hash1 = hash_session_token(token1)
    hash2 = hash_session_token(token2)
    assert len(hash1) == 64  # SHA-256 hex digest length
    assert hash1 != hash2
    assert hash1 == hash_session_token(token1)  # Deterministic hash


def test_csrf_token_generation():
    """Verify CSRF tokens are random strings with adequate entropy."""
    c1 = generate_csrf_token()
    c2 = generate_csrf_token()
    assert c1 != c2
    assert len(c1) >= 32


def test_sliding_window_rate_limiter():
    """Verify rate limiter allows up to limit and blocks subsequent calls."""
    client_ip = "192.168.1.100"
    action = "test_action"
    max_reqs = 3
    window_sec = 2

    assert rate_limiter.is_allowed(client_ip, action, max_reqs, window_sec) is True
    assert rate_limiter.is_allowed(client_ip, action, max_reqs, window_sec) is True
    assert rate_limiter.is_allowed(client_ip, action, max_reqs, window_sec) is True

    # 4th request exceeds limit
    assert rate_limiter.is_allowed(client_ip, action, max_reqs, window_sec) is False

    # Different IP should not be blocked
    other_ip = "192.168.1.101"
    assert rate_limiter.is_allowed(other_ip, action, max_reqs, window_sec) is True
