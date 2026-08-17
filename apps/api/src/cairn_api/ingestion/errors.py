"""What can go wrong before a provider's event becomes work.

Four distinct failures, because the caller answers each one differently and a
single ``IngestionError`` would force every provider to parse strings to tell
them apart:

* the body was too big to be worth hashing — refuse it (413);
* it did not verify — refuse it, undifferentiated (401);
* it verified but does not say which delivery or which account it is — refuse
  it the same way, since a request that cannot name itself cannot be recorded
  idempotently;
* it verified and names an account nobody has connected — acknowledge it, but
  attribute it to nothing.

The last one is the one worth being careful about. "Unknown account" must be a
refusal, never a guess: the alternative is an inbound webhook choosing which
workspace a stranger's activity lands in.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base for every refusal on the inbound path."""


class PayloadTooLargeError(IngestionError):
    """The body exceeded the provider's cap, and was refused unhashed."""


class VerificationError(IngestionError):
    """The request did not prove it came from the provider.

    One exception for every mode — missing signature, wrong algorithm, wrong
    secret, altered bytes — so no caller can accidentally tell a forger which
    part of their forgery was wrong.
    """


class SourceMetadataError(IngestionError):
    """Verified, but it does not identify itself.

    Distinct from `VerificationError` so a provider can log the two differently
    while still answering both with the same undifferentiated rejection.
    """


class UnknownAccountError(IngestionError):
    """No tenant is connected to the account this event came from."""


class UnverifiedEventError(IngestionError):
    """Someone tried to construct a `VerifiedEvent` without verifying anything.

    A programming error, not an inbound one. It exists so that the guarantee
    "everything downstream of this type has been verified" is enforced by the
    runtime as well as by the type checker.
    """
