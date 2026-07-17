"""Salted-hash helpers for API keys.

Uses PBKDF2-HMAC-SHA256 (stdlib only, no extra dependency) rather than
a plain sha256(salt + key): PBKDF2's iteration count makes brute-forcing
a leaked keys.json meaningfully more expensive, at negligible cost for
the rare "check one API key on a request" operation. Iteration count
follows OWASP's current PBKDF2-HMAC-SHA256 guidance.

Stored format is self-describing, so the algorithm/iteration count can
change later without breaking already-issued keys:

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

The raw key itself is never stored anywhere - only this salted hash.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000  # OWASP 2023 guidance for PBKDF2-HMAC-SHA256
SALT_BYTES = 16


def generate_raw_key() -> str:
    """Generate a new high-entropy API key, e.g. for a freshly issued key."""
    return secrets.token_urlsafe(32)


def hash_key(raw_key: str) -> str:
    """Salt and hash a raw API key. Returns the self-describing stored string."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", raw_key.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_key(raw_key: str, stored_hash: str) -> bool:
    """Check a raw key against a previously stored salted_key_hash.

    Uses a constant-time comparison (hmac.compare_digest) so a failed
    check doesn't leak timing information about how much of the hash
    matched.
    """
    try:
        algorithm, iterations_str, salt_hex, digest_hex = stored_hash.split("$")
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False

    iterations = int(iterations_str)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", raw_key.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)
