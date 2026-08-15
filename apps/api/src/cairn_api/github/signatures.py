"""Webhook signature verification: HMAC-SHA256, verified before parsing,
compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac

#: `X-Hub-Signature` (SHA-1) is deliberately not read.
SIGNATURE_HEADER = "X-Hub-Signature-256"

#: Unique per delivery; usable as an idempotency key.
DELIVERY_HEADER = "X-GitHub-Delivery"

#: The event name — `push`, `pull_request`, `installation`.
EVENT_HEADER = "X-GitHub-Event"

#: Present on installation-scoped events; absent on `ping`.
HOOK_INSTALLATION_TARGET_HEADER = "X-GitHub-Hook-Installation-Target-ID"

_PREFIX = "sha256="


class SignatureError(Exception):
    """A payload failed verification. One exception for every failure mode."""


def sign(payload: bytes, secret: str) -> str:
    """Produce the header value GitHub would send for this payload."""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{digest}"


def verify(payload: bytes, signature: str | None, secret: str) -> None:
    """Check a payload against its signature. `payload` must be the raw
    request body — a re-serialised model would change the bytes.
    """
    if not secret:
        msg = "No webhook secret configured; refusing to verify"
        raise SignatureError(msg)

    if signature is None:
        msg = "Missing signature header"
        raise SignatureError(msg)

    if not signature.startswith(_PREFIX):
        msg = "Signature is not sha256"
        raise SignatureError(msg)

    expected = sign(payload, secret)

    # compare_digest: constant-time, no timing leak.
    if not hmac.compare_digest(signature, expected):
        msg = "Signature does not match"
        raise SignatureError(msg)
