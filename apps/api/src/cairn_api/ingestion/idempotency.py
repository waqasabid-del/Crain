"""The idempotency key — one name for one inbound event, stable across
redelivery.

No provider offers exactly-once delivery. GitHub documents duplicates and gaps
as normal; Slack retries an event three times on any non-2xx (md/02 §9). So
every provider needs one value that is *identical* on a redelivery and
*different* on a genuinely new event, written with a unique constraint before
the work is enqueued.

Two ways to get one, and the choice is per provider:

**Provider-supplied** (`from_provider`). GitHub's ``X-GitHub-Delivery`` is a
GUID that is reused verbatim on every retry of that delivery — exactly the
property wanted, and taken as-is.

**Derived** (`derive`). Not every source has one. Slack's Events API carries an
``event_id`` in the JSON envelope and md/02 §9 chooses it as the key, but it
lives in the *body* rather than in a header, and Slack's other inbound surfaces
— slash commands, interactivity — carry no event id at all, only an
``X-Slack-Retry-Num`` that says *that* this is a retry without saying which
event it is a retry of. Google Chat's app events are the same shape. For those,
the key is a SHA-256 over the provider, the external account, the event type and
the exact verified bytes.

Why the bytes, and what it assumes: a retry is a byte-identical resend of a
payload we have already verified, so the digest matches and the second copy is
suppressed. Two genuinely distinct events are never byte-identical in practice
because every provider stamps its own timestamp into the payload (Slack's
``event_ts``, Chat's ``eventTime``) — that assumption is the price of not having
a provider-supplied id, and it is stated here rather than left implicit. The
account and event type are mixed in so that one provider's digest can never
collide with another's, and the derivation is pure: the same bytes give the same
key on any process, in any order, after any restart.

The key is deliberately *not* content. It is either an opaque provider id or a
hex digest, which is what makes it safe to log and to put on a span.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass

#: Longest key any store must hold. `webhook_deliveries.delivery_id` is
#: `String(255)`; a derived key is 71 characters, and a provider id that exceeds
#: this is a provider we have not met.
MAX_KEY_LENGTH = 255

_DERIVED_PREFIX = "sha256:"


class KeySource(enum.StrEnum):
    """Where the key came from — recorded so an operator can tell a provider's
    own id from one we computed for it."""

    PROVIDER = "provider"
    DERIVED = "derived"


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """The value a delivery is recorded under, and how it was obtained."""

    value: str
    source: KeySource

    def __post_init__(self) -> None:
        if not self.value:
            msg = "An idempotency key cannot be empty"
            raise ValueError(msg)
        if len(self.value) > MAX_KEY_LENGTH:
            msg = f"Idempotency keys are limited to {MAX_KEY_LENGTH} characters"
            raise ValueError(msg)

    @classmethod
    def from_provider(cls, delivery_id: str) -> IdempotencyKey:
        """Take the provider's own delivery id, unchanged.

        Unchanged on purpose: it is the value an operator sees in GitHub's
        deliveries UI, and a decorated copy would not be greppable against it.
        """
        return cls(value=delivery_id, source=KeySource.PROVIDER)

    @classmethod
    def derive(
        cls, *, provider: str, external_account_id: str | None, event_type: str, body: bytes
    ) -> IdempotencyKey:
        """Compute a key for a provider that supplies none. See the module
        docstring for what this assumes about redelivery."""
        digest = hashlib.sha256()
        # Length-prefixed rather than concatenated: joining fields directly lets
        # two different field splits produce one digest, which is a collision
        # somebody has to debug at 3am.
        for part in (provider, external_account_id or "", event_type):
            encoded = part.encode("utf-8")
            digest.update(str(len(encoded)).encode("ascii"))
            digest.update(b":")
            digest.update(encoded)
        digest.update(body)
        return cls(value=f"{_DERIVED_PREFIX}{digest.hexdigest()}", source=KeySource.DERIVED)
