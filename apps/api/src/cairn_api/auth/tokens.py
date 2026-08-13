"""Token generation, hashing and password handling.

Two different problems, deliberately solved differently.

**Session and invitation tokens** are 256 bits of entropy that we generate.
There is nothing for an attacker to guess, so they are stored as a plain
SHA-256 — fast, because it runs on every authenticated request, and sufficient,
because brute-forcing 2^256 is not a threat model.

**Passwords** are human-chosen and therefore guessable, so they get Argon2id,
which is deliberately slow and memory-hard. Using a fast hash here would be a
serious defect; using a slow hash for session tokens would be a needless cost on
every request. The distinction matters and is easy to get backwards.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

#: 32 bytes → 43 URL-safe characters. Comfortably beyond guessing.
TOKEN_BYTES = 32

#: Argon2id with the reference parameters. `time_cost` and `memory_cost` are the
#: knobs to raise as hardware improves; because the parameters are encoded in
#: the hash string, existing hashes remain verifiable and are upgraded on the
#: user's next successful login.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
)


def generate_token() -> str:
    """Return a new URL-safe secret token.

    ``secrets`` rather than ``random``: the latter is a Mersenne Twister seeded
    predictably enough that observing a few outputs reveals the rest, which is
    fine for shuffling a list and catastrophic for a session token.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hash a token for storage.

    Returns a hex SHA-256 digest. Deterministic, so a lookup can find the row by
    hashing the presented token — which a salted hash would not permit.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(presented: str, stored_hash: str) -> bool:
    """Compare a presented token against a stored hash in constant time.

    ``compare_digest`` rather than ``==``: a plain comparison returns as soon as
    it finds a differing byte, and that timing difference is measurable enough
    to let an attacker recover a token one character at a time.
    """
    return hmac.compare_digest(hash_token(presented), stored_hash)


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against its stored hash.

    Returns ``False`` rather than raising on a malformed hash. A corrupted row
    should deny access, not produce a 500 that tells an attacker their input
    reached something unusual.
    """
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Whether a hash was made with outdated parameters.

    Checked after a successful login so that hardening the parameters upgrades
    existing accounts naturally, rather than requiring a password reset for
    everyone.
    """
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
