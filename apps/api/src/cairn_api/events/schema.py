"""The ``ActivityEvent`` schema — the narrowest waist in the system.

Four producers above it (code, chat, meetings, documents), one Understanding
layer below. Everything else encodes assumptions about this shape, which is why
getting it right is cheap now and expensive later.

**Built on CloudEvents**, the CNCF specification, rather than invented here. That
buys native Pub/Sub compatibility, W3C trace correlation, a solved versioning
convention, and — not least — no schema for us to maintain and document
ourselves (md/12 §1).

This module is the **single source of truth**. TypeScript types are generated
from the JSON Schema this emits, so the two languages cannot drift; a test
fails if the checked-in types fall out of date.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator


class Certainty(StrEnum):
    """How much CAIRN trusts a claim.

    Categorical, never numeric. A "73% confident" badge looks rigorous, means
    nothing to a non-technical reader, and invites false precision. Internal
    numeric confidence exists for thresholds and evaluation, but it never
    reaches this field or the interface (md/05 §A.2.1).
    """

    VERIFIED = "verified"
    """Unambiguous source — a merged pull request, an explicit command."""

    OBSERVED = "observed"
    """Clear discussion, or corroborated across more than one source."""

    SUGGESTED = "suggested"
    """Single-source inference, typically meeting-derived. Always hedged."""


class ActivityCategory(StrEnum):
    """The four capture pillars every source normalizes into."""

    CODE = "code"
    CONVERSATION = "conversation"
    MEETING = "meeting"
    DOCUMENT = "document"


class Actor(BaseModel):
    """Who did the thing."""

    model_config = ConfigDict(extra="forbid")

    raw_identity: str = Field(
        min_length=1,
        description="Identity as the source reported it — an email, handle or user ID.",
    )

    resolved_person_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "CAIRN person this resolves to. Null before identity resolution runs. "
            "One human may appear under several raw identities — a work email, a "
            "personal email, a GitHub handle — and treating those as different "
            "people would fragment their contribution record."
        ),
    )

    display_name: str | None = None

    is_bot: bool = Field(
        default=False,
        description=(
            "Bot activity is retained as project context but excluded from human "
            "attribution. Dependabot can out-commit every human on a team, so "
            "filtering at the schema level means the rule cannot be forgotten by "
            "one consumer downstream."
        ),
    )

    co_actors: list[uuid.UUID] = Field(
        default_factory=list,
        description=(
            "Additional contributors, first-class rather than an afterthought. "
            "Squash merges collapse a branch into one commit, so pair and mob "
            "work is systematically erased unless co-authorship is modelled "
            "explicitly (md/01 §5.1)."
        ),
    )


class Activity(BaseModel):
    """What happened."""

    model_config = ConfigDict(extra="forbid")

    category: ActivityCategory
    action: str = Field(min_length=1, description="Source-specific verb: merged, sent, decided.")
    summary: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "One-line human-readable description. Embedded for retrieval rather "
            "than the raw content — summarising before embedding cuts retrieval "
            "failures substantially (md/09 §4.4)."
        ),
    )
    project_ref: str | None = None


class Provenance(BaseModel):
    """Where the claim came from, and how much to trust it."""

    model_config = ConfigDict(extra="forbid")

    source_url: AnyUrl | None = Field(
        default=None,
        description="Something a human can open. Provenance is a product feature, not a debug aid.",
    )

    source_timestamp_ref: str | None = Field(
        default=None,
        description=(
            "Transcript offset for meeting-derived events, enabling one-click "
            "verification (md/03 §6). Null for other sources."
        ),
    )

    certainty: Certainty


class Content(BaseModel):
    """Optional payload detail.

    Frequently absent by design. Raw diffs stay out of the pipeline by default
    (md/01 §6.3) and non-work-relevant chat is excluded entirely (md/02 §7.1),
    so **missing content is the normal case, not a degraded one.**
    """

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivityPayload(BaseModel):
    """The CAIRN-defined ``data`` section of the CloudEvent."""

    model_config = ConfigDict(extra="forbid")

    actor: Actor
    activity: Activity
    provenance: Provenance
    content: Content = Field(default_factory=Content)


class ActivityEvent(BaseModel):
    """A CloudEvents 1.0 envelope carrying a CAIRN activity payload."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # ------------------------------------------------------------- CloudEvents
    specversion: Literal["1.0"] = "1.0"

    id: str = Field(
        min_length=1,
        description=(
            "Unique per event. Combined with `source`, this is the idempotency "
            "key — webhook redelivery is normal, so duplicates must upsert "
            "rather than create a second record (md/01 §4.1)."
        ),
    )

    source: str = Field(
        min_length=1,
        description="Producer URI-reference, e.g. /github/12345 or /slack/T0001.",
    )

    type: str = Field(
        min_length=1,
        pattern=r"^ai\.cairn\.[a-z0-9_]+\.[a-z0-9_.]+\.v\d+$",
        description=(
            "Reverse-DNS with a version suffix, per the CloudEvents convention: "
            "ai.cairn.github.pull_request.merged.v1. The version lives in the "
            "type so a breaking change produces a new type rather than silently "
            "altering the meaning of an existing one (md/12 §4)."
        ),
    )

    subject: str | None = Field(
        default=None,
        description="Entity acted upon — repository, channel or meeting identifier.",
    )

    time: datetime = Field(
        description=(
            "When the activity **happened**, not when CAIRN received it. Every "
            "user-facing view orders by this. Conflating it with ingestion time "
            "produces a brief claiming today's work that actually happened in "
            "March (md/12 §3.2)."
        )
    )

    datacontenttype: Literal["application/json"] = "application/json"

    dataschema: str | None = None

    data: ActivityPayload

    # -------------------------------------------------------- CAIRN extensions
    tenantid: uuid.UUID = Field(
        description=(
            "Owning workspace. Mandatory on every event, no exceptions. This "
            "lives on the envelope rather than inside the payload so that a "
            "background job cannot lose tenant context — the context is "
            "structurally inseparable from the event (md/06 §4.3)."
        )
    )

    actorid: uuid.UUID | None = Field(
        default=None,
        description="Resolved person, mirrored onto the envelope for cheap filtering.",
    )

    ingestedat: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description=(
            "When CAIRN received the event. Diverges from `time` routinely — "
            "backfill imports 90 days in minutes. Operational views order by "
            "this; user-facing views never do."
        ),
    )

    traceparent: str | None = Field(
        default=None,
        description="W3C trace context, correlating this event with its cause (md/10 §7).",
    )

    # ------------------------------------------------------------- validation
    @model_validator(mode="after")
    def reject_nil_tenant(self) -> Self:
        """Refuse the all-zero UUID.

        It parses cleanly and looks like a valid tenant, making it exactly what
        an uninitialised variable produces. Caught at the boundary rather than
        becoming an event attributed to a workspace that does not exist.
        """
        if self.tenantid.int == 0:
            msg = "tenantid must be a real tenant, not the nil UUID"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def require_timezone_aware_timestamps(self) -> Self:
        """Reject naive datetimes.

        A timestamp without an offset is a wall-clock reading with no meaning
        outside the machine that produced it. Ordering silently breaks once two
        regions write events or a daylight-saving boundary passes — surfacing as
        a brief reporting the wrong day's work, and very hard to trace back.
        """
        if self.time.tzinfo is None:
            msg = "time must be timezone-aware"
            raise ValueError(msg)
        if self.ingestedat.tzinfo is None:
            msg = "ingestedat must be timezone-aware"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def require_provenance_for_uncertain_claims(self) -> Self:
        """A hedged claim must be verifiable.

        Certainty tiers only earn trust if a reader can check them. A
        meeting-derived commitment presented as "suggested" with nothing to open
        asks the user to take an unreliable claim on faith — worse than not
        surfacing it at all (md/03 §6).
        """
        uncertain = self.data.provenance.certainty in {Certainty.OBSERVED, Certainty.SUGGESTED}
        has_reference = (
            self.data.provenance.source_url is not None
            or self.data.provenance.source_timestamp_ref is not None
        )
        if uncertain and not has_reference:
            msg = (
                f"certainty '{self.data.provenance.certainty}' requires a source_url or "
                "source_timestamp_ref so the claim can be verified in one click"
            )
            raise ValueError(msg)
        return self


#: Idempotency key. Producers must guarantee `id` is stable across redelivery.
type EventKey = Annotated[tuple[str, str], "source, id"]


def event_key(event: ActivityEvent) -> tuple[str, str]:
    """Return the deduplication key for an event."""
    return (event.source, event.id)
