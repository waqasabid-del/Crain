"""The inbound types, and the one place a verified event can be made.

The central idea of this module is that **"unverified" is not representable**.
There is no `verified: bool` on the event and no "did you check the signature?"
step somebody can forget: a `VerifiedEvent` can only be produced by
`verify_and_mint`, which runs the provider's verifier first and refuses to
construct anything if it raises. Every function downstream — tenant resolution,
the idempotency ledger, the enqueue — is typed against `VerifiedEvent`, so
"nothing unverified reaches the queue" is a property of the signatures rather
than a rule in a review checklist.

The proof object is what enforces it. It is module-private and constructed
exactly once; `VerifiedEvent.__post_init__` compares by identity, so a caller
who builds the dataclass directly gets `UnverifiedEventError` rather than an
event that merely looks verified.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final, Protocol, final

from cairn_api.ingestion.errors import UnverifiedEventError
from cairn_api.ingestion.idempotency import IdempotencyKey


@dataclass(frozen=True, slots=True)
class InboundRequest:
    """A request as it arrived: the exact bytes, and the headers.

    The bytes are kept raw and un-parsed because a signature covers *those*
    bytes — a re-serialised model, however equivalent, hashes differently and
    would fail verification for a reason nobody could see.
    """

    body: bytes
    headers: Mapping[str, str]

    def __post_init__(self) -> None:
        # Normalised once, at the edge. HTTP header names are case-insensitive
        # and every ASGI server presents them differently; a provider matching
        # on `X-Slack-Signature` while the server produced `x-slack-signature`
        # is a verification bypass that looks like a typo.
        object.__setattr__(self, "headers", {k.lower(): v for k, v in self.headers.items()})

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Where an event came from — identifiers and categories, nothing else.

    Deliberately nothing that describes a person or quotes a message: this is
    the part of an event that ends up in logs, and (for `provider`) on spans.
    """

    #: `github`, `slack`, `google_chat`. Stable, lowercase, ours.
    provider: str

    #: The provider's own name for the kind of event — `push`, `message`.
    event_type: str

    #: The installation / team / space identifier the event belongs to. Absent
    #: until the verified body has been decoded for providers that carry it
    #: there rather than in a header — see `VerifiedEvent.attributed_to`.
    external_account_id: str | None = None

    #: The provider's delivery id, where it has one.
    external_event_id: str | None = None


@final
class _VerificationProof:
    """Evidence that a verifier ran and did not raise.

    Private, unexported, and instantiated once below. Nothing outside this
    module can obtain the instance, which is what makes `VerifiedEvent`
    unconstructable elsewhere.
    """

    __slots__ = ()


_PROOF: Final = _VerificationProof()


@dataclass(frozen=True, slots=True)
class VerifiedEvent:
    """An inbound event that has proved it came from the provider it claims.

    Frozen: it is passed to tenant resolution, an idempotency ledger and the
    queue, and a mutable copy would let a later stage edit the thing an earlier
    stage authenticated.
    """

    #: See `_VerificationProof`. First and positional so it cannot be omitted.
    proof: _VerificationProof

    source: SourceMetadata

    idempotency_key: IdempotencyKey

    #: The verified bytes. Kept so a provider can decode its own payload once,
    #: rather than each stage re-reading the request.
    body: bytes

    #: The unit of work this event started, minted at receipt and carried onto
    #: every envelope published from it (md/10 §7 and `telemetry/correlation.py`).
    correlation_id: str

    def __post_init__(self) -> None:
        if self.proof is not _PROOF:
            msg = (
                "A VerifiedEvent may only be produced by ingestion.verify_and_mint. "
                "Constructing one directly would assert an authenticity nobody checked."
            )
            raise UnverifiedEventError(msg)

    def attributed_to(self, external_account_id: str) -> VerifiedEvent:
        """The same event, now naming the account it belongs to.

        A second step because several providers put the installation or team id
        in the body, which may only be decoded *after* verification. The copy
        carries the same proof: attribution does not weaken authenticity, and
        re-verifying identical bytes would only be theatre.
        """
        return replace(self, source=replace(self.source, external_account_id=external_account_id))


class InboundProvider(Protocol):
    """The provider-specific half of ingestion — and the only part that is.

    Verification differs per provider (GitHub signs the body with HMAC-SHA256,
    Slack signs a versioned string including a timestamp, Google Chat sends a
    bearer JWT), as does where the delivery id and event type live. Everything
    after this protocol — idempotency, tenancy, the envelope, retry,
    dead-lettering, correlation — is shared.
    """

    def verify(self, request: InboundRequest) -> None:
        """Prove the request came from the provider, or raise `VerificationError`.

        Called on the raw bytes, before anything parses them.
        """
        ...

    def read_source(self, request: InboundRequest) -> SourceMetadata:
        """Name the event, or raise `SourceMetadataError`.

        Called only after `verify`, so a request that omits its headers is
        refused for the same undifferentiated reason a forged one is, and header
        absence cannot be used to probe.
        """
        ...

    def idempotency_key(self, request: InboundRequest, source: SourceMetadata) -> IdempotencyKey:
        """The key this event is recorded under. See `idempotency.py`."""
        ...


def verify_and_mint(
    request: InboundRequest, provider: InboundProvider, *, correlation_id: str
) -> VerifiedEvent:
    """Verify, then name. The only constructor of `VerifiedEvent`.

    Order is load-bearing and is the reason this is one function rather than
    three call sites: verification runs against the raw bytes before anything
    reads them, and nothing that follows can run without it having passed.
    """
    provider.verify(request)

    source = provider.read_source(request)
    key = provider.idempotency_key(request, source)

    return VerifiedEvent(
        _PROOF,
        source=source,
        idempotency_key=key,
        body=request.body,
        correlation_id=correlation_id,
    )
