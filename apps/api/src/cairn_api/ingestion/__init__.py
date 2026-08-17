"""Provider-neutral ingestion: how anything outside CAIRN becomes work inside it.

Extracted from the GitHub webhook path, which is its first and (until Slack and
Google Chat arrive) only caller — so the contract describes a receipt path that
runs in production rather than one somebody imagined.

A provider supplies exactly one thing: an `InboundProvider` that can verify its
requests and name them. Everything after verification is shared and is not
re-decided per provider —

* **`VerifiedEvent`** (`inbound.py`) — unconstructable without verification, so
  "did anyone check the signature?" is a question the type system answers.
* **`IdempotencyKey`** (`idempotency.py`) — the provider's delivery id where one
  exists, a documented deterministic digest where it does not.
* **`ResolvedTenant`** (`tenancy.py`) — resolved from the account identifier
  against a mapping only an authenticated connect flow may write; never from
  anything the body claims.
* **`SourceMetadata`** (`inbound.py`) — provider, external account, event type.
  Identifiers and categories; no message, address or payload.
* **`enqueue`** (`receipt.py`) — a `JobEnvelope` on the existing queue, so
  retries, dead-lettering and tenant scoping are the ones `jobs/worker.py`
  already guarantees rather than a parallel set.
* **correlation and trace propagation** — the id is minted before verification
  and travels to the worker on the envelope.

Step 32 implements `InboundProvider` for Slack and for Google Chat, a
`TenantResolver` over each one's own installation table, and an
`IdempotencyLedger` over its own delivery table. Nothing else should need
writing.
"""

from __future__ import annotations

from cairn_api.ingestion.errors import (
    IngestionError,
    PayloadTooLargeError,
    SourceMetadataError,
    UnknownAccountError,
    UnverifiedEventError,
    VerificationError,
)
from cairn_api.ingestion.idempotency import IdempotencyKey, KeySource
from cairn_api.ingestion.inbound import (
    InboundProvider,
    InboundRequest,
    SourceMetadata,
    VerifiedEvent,
    verify_and_mint,
)
from cairn_api.ingestion.receipt import (
    DEFAULT_MAX_BODY_BYTES,
    IdempotencyLedger,
    Ingestor,
    enqueue,
    job_payload,
)
from cairn_api.ingestion.tenancy import ResolvedTenant, TenantResolver, resolve_tenant

__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "IdempotencyKey",
    "IdempotencyLedger",
    "InboundProvider",
    "InboundRequest",
    "IngestionError",
    "Ingestor",
    "KeySource",
    "PayloadTooLargeError",
    "ResolvedTenant",
    "SourceMetadata",
    "SourceMetadataError",
    "TenantResolver",
    "UnknownAccountError",
    "UnverifiedEventError",
    "VerificationError",
    "VerifiedEvent",
    "enqueue",
    "job_payload",
    "resolve_tenant",
    "verify_and_mint",
]
