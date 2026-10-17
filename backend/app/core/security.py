"""
CipherQ Core Security & Authentication Module
Provides Argon2id password hashing, constant-time verification,
secure session token generation and hashing, and in-memory rate limiting.
"""
import time
import hashlib
import secrets
from collections import defaultdict
from typing import Dict, List, Tuple
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

# Argon2id hasher configured per recommendations:
# memory_cost=65536 (64MB), time_cost=3, parallelism=4
ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32
)


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an Argon2id hash in constant time."""
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_session_token() -> str:
    """Generate a high-entropy cryptographically secure random session token."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Hash a session token with SHA-256 before database storage to prevent token theft."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Generate a high-entropy random CSRF token."""
    return secrets.token_urlsafe(32)


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter per client IP address."""

    def __init__(self):
        # Maps (key, action) -> list of timestamp floats
        self._history: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    def is_allowed(self, client_id: str, action: str, max_requests: int, window_seconds: int) -> bool:
        """Return True if the request is within rate limits, False otherwise."""
        now = time.time()
        record_key = (client_id, action)
        timestamps = self._history[record_key]

        # Evict timestamps outside the sliding window
        threshold = now - window_seconds
        valid_timestamps = [t for t in timestamps if t > threshold]
        self._history[record_key] = valid_timestamps

        if len(valid_timestamps) >= max_requests:
            return False

        valid_timestamps.append(now)
        return True

    def reset(self) -> None:
        """Reset rate limiter state (useful for tests)."""
        self._history.clear()


rate_limiter = SlidingWindowRateLimiter()
