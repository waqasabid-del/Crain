"""Token generation, hashing and password handling.

Tokens are 256-bit random, stored as plain SHA-256; passwords use Argon2id (slow, memory-hard). Do not swap the two.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

TOKEN_BYTES = 32

#: Params are encoded in the hash string, so raising them later doesn't invalidate existing hashes.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
)


def generate_token() -> str:
    """Via ``secrets`` (CSPRNG, unlike ``random``)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(presented: str, stored_hash: str) -> bool:
    """Compare a presented token against a stored hash in constant time."""
    return hmac.compare_digest(hash_token(presented), stored_hash)


#: Cap on password length (CPU-amplification vector otherwise); use the ``_async`` wrappers.
MAX_PASSWORD_BYTES = 1024


def hash_password(password: str) -> str:
    """Blocking — prefer :func:`hash_password_async`."""
    _reject_oversized(password)
    return _hasher.hash(password)


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, stored_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, stored_hash)


def _reject_oversized(password: str) -> None:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        msg = f"Password exceeds {MAX_PASSWORD_BYTES} bytes"
        raise ValueError(msg)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password; returns ``False`` (not a raise) on a malformed hash."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Whether a hash used outdated params — checked post-login to upgrade in place."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
