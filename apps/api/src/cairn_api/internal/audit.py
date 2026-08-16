"""Recording staff actions so the record can exonerate.

md/15 §5.2: when a customer asks whether staff read their data, an answer staff
could have edited is worth nothing. Two independent mechanisms:

**The chain.** Each entry hashes its own content together with its predecessor's
hash, so altering or removing one entry invalidates every hash after it.
`verify` walks the chain and names the first break.

**The grants.** `cairn_app` has INSERT and SELECT on this table and nothing
else, so a compromise of the application role can append but never rewrite.

Deferred, and named in the migration: storage separate from this database, which
would make suppression impossible rather than detectable.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.staff_models import InternalAuditEntry

logger = structlog.get_logger(__name__)

#: The hash the first entry chains from. Any value works; a constant makes the
#: genesis entry verifiable rather than special-cased.
GENESIS_HASH = "0" * 64

#: The advisory-lock key that serialises appends.
#:
#: Appending reads the last hash and then inserts. Without a lock, two staff
#: actions at the same moment both read the same predecessor, both commit, and
#: the chain is permanently broken by ordinary concurrent use rather than by an
#: attacker. Transaction-scoped, so it releases on commit or rollback with no
#: unlock path to forget.
CHAIN_LOCK_KEY = 8_531_207_441_990_113


def compute_hash(
    *,
    previous_hash: str,
    occurred_at: datetime,
    actor_user_id: uuid.UUID,
    action: str,
    tenant_id: uuid.UUID | None,
    reason: str,
    detail: dict[str, Any],
) -> str:
    """The hash covering one entry and its predecessor.

    `occurred_at` is inside the hash. Without it, an attacker with database
    access can move when an action appears to have happened — the difference
    between "support opened this account during the incident" and "an hour
    after it" — and verification would still pass.

    Canonical JSON with sorted keys: two runs must produce the same hash for the
    same content, or verification fails on entries nobody touched.
    """
    payload = json.dumps(
        {
            "previous_hash": previous_hash,
            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            "actor_user_id": str(actor_user_id),
            "action": action,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "reason": reason,
            "detail": detail,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def record(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    reason: str,
    tenant_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> InternalAuditEntry:
    """Append one entry to the chain.

    Appends are serialised by an advisory lock held to the end of the
    transaction. Two staff acting at the same instant would otherwise read the
    same predecessor hash and both commit, breaking the chain through ordinary
    use rather than through an attack.

    The caller decides when to commit. `audited` commits immediately, so the
    record survives a handler that then fails.
    """
    detail = detail or {}

    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK_KEY})

    last = await session.scalar(
        select(InternalAuditEntry).order_by(InternalAuditEntry.sequence.desc()).limit(1)
    )
    previous_hash = last.entry_hash if last is not None else GENESIS_HASH

    # Assigned here rather than by the column default: the value has to be known
    # to be hashed, and a server default is only visible after the insert.
    occurred_at = datetime.now(UTC)

    entry = InternalAuditEntry(
        occurred_at=occurred_at,
        actor_user_id=actor_user_id,
        action=action,
        tenant_id=tenant_id,
        reason=reason,
        detail=detail,
        previous_hash=previous_hash,
        entry_hash=compute_hash(
            previous_hash=previous_hash,
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            action=action,
            tenant_id=tenant_id,
            reason=reason,
            detail=detail,
        ),
    )
    session.add(entry)
    await session.flush()

    await logger.ainfo(
        "internal.action",
        action=action,
        # Ids only. The reason is customer-adjacent free text and the log store
        # has its own retention.
        actor_user_id=str(actor_user_id),
        tenant_id=str(tenant_id) if tenant_id else None,
    )
    return entry


@dataclass(frozen=True, slots=True)
class Verification:
    """The result of walking the chain."""

    entries: int
    intact: bool

    #: The sequence number of the first entry that failed, if any. Named rather
    #: than reported as a boolean so an investigation has somewhere to start.
    broken_at: int | None = None
    reason: str | None = None


async def verify(session: AsyncSession) -> Verification:
    """Walk the chain from the start, checking every link.

    Two failures are possible and are distinguished: an entry whose own hash
    does not match its content (it was edited), and an entry whose
    `previous_hash` does not match the entry before it (one was removed, or the
    order was changed).
    """
    entries = list(
        await session.scalars(select(InternalAuditEntry).order_by(InternalAuditEntry.sequence))
    )

    expected_previous = GENESIS_HASH
    for entry in entries:
        if entry.previous_hash != expected_previous:
            return Verification(
                entries=len(entries),
                intact=False,
                broken_at=entry.sequence,
                reason="an entry is missing, or the order changed",
            )

        recomputed = compute_hash(
            previous_hash=entry.previous_hash,
            occurred_at=entry.occurred_at,
            actor_user_id=entry.actor_user_id,
            action=entry.action,
            tenant_id=entry.tenant_id,
            reason=entry.reason,
            detail=entry.detail,
        )
        if recomputed != entry.entry_hash:
            return Verification(
                entries=len(entries),
                intact=False,
                broken_at=entry.sequence,
                reason="an entry's contents were changed after it was written",
            )

        expected_previous = entry.entry_hash

    return Verification(entries=len(entries), intact=True)
