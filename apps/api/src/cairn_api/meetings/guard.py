"""The door every future meeting integration has to walk through.

`eligibility.check` is a pure function over rows somebody already loaded. That is
the right shape for a rule and the wrong shape for a *boundary*: a caller can
forget to call it, call it with the wrong rows, or read its answer and carry on
anyway. This module is the boundary — it loads the rows itself, asks the gate,
and either hands back a permit or raises.

**Every guarded operation goes through `permit_collection`.** Before a Meet or
Zoom integration may:

- retrieve artifact metadata from the provider,
- fetch a transcript or recording the platform produced,
- enqueue a meeting job,
- create a meeting-derived event or fact,
- or spend a model call on any of it,

it calls this, and does the work only with the `CollectionPermit` it returns. The
permit is not a boolean and cannot be constructed outside this module — the same
device `ingestion/inbound.VerifiedEvent` uses, and for the same reason: a
function that takes `permit: CollectionPermit` cannot be called by code that
never asked, and no amount of hurry produces one by accident.

**There is no bypass and no override argument.** Nothing here takes `force`,
`skip_consent`, or an already-computed verdict. A future caller under deadline
pressure has nothing to reach for, which is the only kind of safeguard that
survives a deadline.

Nothing in this module contacts a provider, and no provider exists yet. It is
deliberately written before the first integration rather than alongside it: a
gate added afterwards is a gate somebody has to remember to add.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.meeting_models import (
    MeetingCaptureRequest,
    MeetingConsent,
    MeetingParticipant,
    MeetingProvider,
)
from cairn_api.meetings import eligibility
from cairn_api.meetings.eligibility import Eligibility, ReasonCode

logger = structlog.get_logger(__name__)

#: Module-private. Held by no other module, so `CollectionPermit` cannot be
#: constructed anywhere else even by a caller that imports the class.
_PROOF: Final = object()


class CollectionRefusedError(Exception):
    """CAIRN may not collect this meeting.

    Carries the internal `reason` for operators and tests and the safe
    `public_message` for anything a person reads. Raising rather than returning
    a falsy value is deliberate: a refusal that must be checked is a refusal that
    can be ignored, and the operation being guarded here is one where being
    ignored means recording somebody who said no.
    """

    def __init__(self, verdict: Eligibility) -> None:
        self.reason = verdict.reason
        self.public_message = verdict.public_message
        super().__init__(f"collection refused: {verdict.reason.value}")


@final
@dataclass(frozen=True, slots=True)
class CollectionPermit:
    """Proof that consent was checked, for one meeting, at one moment.

    **Unconstructable outside this module.** `__post_init__` rejects any proof
    object that is not the module-private one, so a future integration cannot
    fabricate a permit to satisfy a signature — it has to ask.
    """

    meeting_id: uuid.UUID
    tenant_id: uuid.UUID
    provider: MeetingProvider
    external_meeting_ref: str
    checked_at: datetime
    proof: object

    def __post_init__(self) -> None:
        if self.proof is not _PROOF:
            msg = "A CollectionPermit may only be issued by meetings.guard.permit_collection."
            raise TypeError(msg)


async def permit_collection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    meeting_id: uuid.UUID,
    provider: MeetingProvider | None = None,
    now: datetime | None = None,
) -> CollectionPermit:
    """Load the meeting, ask the gate, and refuse unless everyone agreed.

    Loads the rows here rather than accepting them, so a caller cannot pass a
    stale participant list or forget the consents. Only **live** decisions are
    read — a superseded row is history, and reading history as though it were
    current is how a withdrawal gets ignored.

    The session must be tenant-scoped; `tenant_id` is passed to the gate as well,
    because a boundary that trusts its caller's scoping opens the moment one
    caller gets it wrong.

    Raises `CollectionRefusedError` on anything other than unanimous, current,
    unexpired agreement.
    """
    meeting = await db.scalar(
        select(MeetingCaptureRequest).where(MeetingCaptureRequest.id == meeting_id)
    )
    participants = list(
        (
            await db.scalars(
                select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
            )
        ).all()
    )
    consents = list(
        (
            await db.scalars(
                select(MeetingConsent).where(
                    MeetingConsent.meeting_id == meeting_id,
                    MeetingConsent.superseded_at.is_(None),
                )
            )
        ).all()
    )

    verdict = eligibility.check(
        meeting,
        participants,
        consents,
        tenant_id=tenant_id,
        provider=provider,
        now=now,
    )

    if not verdict.allowed or meeting is None:
        await logger.ainfo(
            "meeting.collection_refused",
            # A category and nothing else. No meeting id, no participant, no
            # purpose, no title — a refusal reason is an operational fact, and
            # everything that would make it identifying stays in the database.
            reason=verdict.reason.value,
        )
        raise CollectionRefusedError(verdict)

    await logger.ainfo("meeting.collection_permitted", reason=ReasonCode.ALLOWED.value)

    return CollectionPermit(
        meeting_id=meeting.id,
        tenant_id=meeting.tenant_id,
        provider=meeting.provider,
        external_meeting_ref=meeting.external_meeting_ref,
        checked_at=now or datetime.now(UTC),
        proof=_PROOF,
    )
