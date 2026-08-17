"""Request and response models.

Separate from the SQLAlchemy models on purpose. Serialising an ORM object
directly means every column added to the database appears in the API by default
— which is how password hashes and internal flags leak. Here, a field reaches a
client only because someone wrote it down.

**Field names are camelCase on the wire, snake_case in Python.** The alias
generator does the conversion once, so neither language writes the other's
convention by hand. Without it the generated TypeScript client is full of
`display_name`, and someone eventually "fixes" one endpoint and breaks the
contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from cairn_api.auth.service import MIN_PASSWORD_LENGTH
from cairn_api.auth.tokens import MAX_PASSWORD_BYTES
from cairn_api.db.fact_models import FactOrigin
from cairn_api.db.models import Region, TenantRole, WorkRole
from cairn_api.db.support_models import SupportScope, SupportSessionStatus
from cairn_api.domain import Certainty


class ApiModel(BaseModel):
    """Base for everything crossing the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        # Reject unknown fields rather than ignoring them. A client sending
        # `displayname` for `displayName` should be told, not silently given an
        # account with no name — and on an update endpoint, silently dropping an
        # unrecognised field means a user's change vanishes without an error.
        extra="forbid",
    )


# -- Requests ---------------------------------------------------------------


class PasswordField(ApiModel):
    """Shared password constraints.

    The maximum is not arbitrary: Argon2's cost scales with input length, so an
    unbounded password turns one unauthenticated request into seconds of CPU
    across 64 MiB. The service layer enforces this too — this exists so the
    rejection is a 422 naming the field rather than a 500.
    """

    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES)


class SignupRequest(PasswordField):
    email: EmailStr
    workspace_name: str = Field(min_length=1, max_length=100)
    workspace_slug: str = Field(
        min_length=3,
        max_length=63,
        # Lowercase, digits and single hyphens. Bounded to what is safe in a
        # subdomain, because that is where slugs end up, and a slug that cannot
        # be a hostname is a migration nobody wants later.
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    display_name: str | None = Field(default=None, max_length=100)


class LoginRequest(ApiModel):
    email: EmailStr
    # Deliberately unconstrained beyond a sane ceiling. Enforcing the minimum
    # length here would reject an old password that predates a policy change
    # with a validation error rather than "incorrect", telling an attacker their
    # guess was too short to be this account's password.
    password: str = Field(max_length=MAX_PASSWORD_BYTES)


class InviteRequest(ApiModel):
    email: EmailStr
    role: TenantRole = TenantRole.MEMBER


class VerifyEmailRequest(ApiModel):
    token: str = Field(min_length=1, max_length=256)


class ConnectGitHubRequest(ApiModel):
    """Bind a GitHub App installation to this workspace.

    The `installation_id` arrives as a query parameter on GitHub's post-install
    redirect. The caller must be an authenticated member with permission to
    connect integrations, which is the whole point: an inbound webhook must
    never be able to create this mapping, or whoever installed the app would
    have their activity bound to a workspace nobody chose.
    """

    installation_id: int = Field(gt=0)
    account_login: str = Field(min_length=1, max_length=255)
    account_type: str = Field(default="Organization", max_length=32)

    #: Repositories to import history for, as `owner/name`.
    repositories: list[str] = Field(default_factory=list, max_length=200)


class AcceptInvitationRequest(ApiModel):
    token: str = Field(min_length=1, max_length=256)
    email: EmailStr
    #: Required only when the invited person has no account yet.
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES
    )
    display_name: str | None = Field(default=None, max_length=100)


# -- Responses --------------------------------------------------------------


class UserResponse(ApiModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str | None

    #: Whether this person has proved they control the address.
    #:
    #: Exposed so the interface can prompt for it. Not a permission in itself —
    #: what verification gates is claiming an invitation someone else sent.
    email_verified: bool = False


class WorkspaceResponse(ApiModel):
    id: uuid.UUID
    name: str
    slug: str


class MembershipResponse(ApiModel):
    """A person's place in a workspace.

    Carries role and join date and nothing else — no activity counts, no last
    seen, no "engagement". Roles govern configuration; they do not govern how
    much is visible about a person (md/15 §2.2), and a members list is exactly
    where a visibility field would first appear.
    """

    user_id: uuid.UUID
    email: EmailStr
    display_name: str | None
    role: TenantRole
    joined_at: datetime


class SessionResponse(ApiModel):
    """Who the caller is, and where they can go."""

    user: UserResponse
    workspaces: list[WorkspaceMembershipResponse]


class WorkspaceMembershipResponse(ApiModel):
    workspace: WorkspaceResponse
    role: TenantRole

    #: What the person says they do, if they have said.
    #:
    #: Carried on the session rather than fetched separately, because it decides
    #: where the app opens — and a first screen that arrives one request late is
    #: a first screen the reader watches change under them.
    #:
    #: Null is normal. Every screen works without it.
    work_role: WorkRole | None = None


class InvitationResponse(ApiModel):
    """An issued invitation.

    **The token is not here.** It reaches the invitee by email and nowhere else.
    Returning it would let anyone who can issue an invitation also redeem it,
    collapsing the distinction between inviting an address and proving control
    of it — and would write a working credential into the API logs of every
    intermediary.
    """

    id: uuid.UUID
    email: EmailStr
    role: TenantRole
    expires_at: datetime


class GitHubInstallationResponse(ApiModel):
    """A connected installation."""

    id: uuid.UUID
    installation_id: int
    account_login: str
    account_type: str
    active: bool

    #: Backfill runs started for this connection, for the onboarding screen.
    backfill_runs: int


class HealthResponse(ApiModel):
    status: str
    environment: str


# Resolves the forward reference in SessionResponse.
SessionResponse.model_rebuild()


# -- The understanding layer ------------------------------------------------
#
# What the pipeline produced, on its way to a reader. Everything here carries
# provenance, because a claim a reader cannot check is one the product is not
# entitled to make (md/09 §5.1) — which is why there is no shape in this section
# that can be serialised without its sources.


class FactSourceResponse(ApiModel):
    """Where a fact came from, precisely enough to open."""

    source: str
    evidence_id: str

    #: The span the fact rests on, where the ingesting system gave us one.
    quote: str | None = None

    #: A resolvable location. This is what makes "open the source in one click"
    #: real rather than aspirational.
    url: str | None = None

    #: What this evidence was about — a repository full name, and later a
    #: channel or a document space. Null where the source names no project,
    #: which is normal rather than a gap: a filter therefore means "evidence
    #: that names this project" and nothing broader.
    project: str | None = None


class FactPersonResponse(ApiModel):
    """A person a fact concerns, resolved or not.

    `personId` is null for a mention the identity graph could not place
    unambiguously, and the raw mention is returned anyway. A name the system
    could not resolve is a question the workspace can answer; dropping it makes
    "who is Sam?" unanswerable.
    """

    mention: str
    person_id: uuid.UUID | None = None


class FactResponse(ApiModel):
    """One statement the pipeline asserts, with its validity interval."""

    id: uuid.UUID

    #: `delivery`, `decision`, `blocker`, `in_progress`, `open_question`.
    #:
    #: A string rather than an enum, matching the column. The taxonomy is
    #: expected to grow, and a generated client that refuses to deserialise a
    #: fact kind it has not been regenerated for would turn adding one into a
    #: coordinated deploy.
    kind: str

    statement: str

    #: Categorical, and with no numeric counterpart anywhere in this schema
    #: (md/05 §A.2.1). A confidence float that existed would eventually be
    #: rendered.
    certainty: Certainty

    #: `extracted` or `correction`. A human correction outranks an extracted
    #: fact, and the interface has to be able to say which it is looking at
    #: without inferring it from the presence of a user id.
    origin: FactOrigin

    #: When the activity happened, not when it was extracted. Null when the
    #: source did not timestamp it.
    occurred_at: datetime | None = None

    valid_from: datetime

    #: Null means currently valid. A non-null value with `supersededById` is a
    #: fact that has been replaced — kept, never deleted (md/12 §6).
    valid_until: datetime | None = None
    superseded_by_id: uuid.UUID | None = None
    supersession_reason: str | None = None

    sources: list[FactSourceResponse] = Field(default_factory=list)
    people: list[FactPersonResponse] = Field(default_factory=list)


class WorkRoleUpdate(ApiModel):
    """What the reader says they do.

    Nullable, because withdrawing the answer has to be as easy as giving it. A
    person who decides they would rather not say should not have to pick
    something inaccurate instead.
    """

    work_role: WorkRole | None = None


class WorkRoleResponse(ApiModel):
    work_role: WorkRole | None = None


class SupportAccessEventResponse(ApiModel):
    """One thing CAIRN staff actually opened during a session."""

    occurred_at: datetime
    scope: SupportScope
    description: str


class SupportSessionResponse(ApiModel):
    """A request by CAIRN staff to look at this workspace.

    Everything md/15 §5.2 requires the customer to be able to see: who asked,
    for what, why, who decided, when it started, when it ends, whether it was
    break-glass, and what was actually opened.

    Staff are identified by their email rather than an opaque id: "approved
    access for someone" is not an answer a person can act on.
    """

    id: uuid.UUID
    requested_by: EmailStr
    reason: str
    requested_scope: SupportScope
    approved_scope: SupportScope | None = None
    status: SupportSessionStatus

    #: Computed from the clock rather than stored, so an expiry that has passed
    #: is never reported as live access.
    active: bool

    requested_minutes: int
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: EmailStr | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    #: Who ended it, which is not necessarily who approved it. Reported
    #: separately because a record that names only the approver next to "ended
    #: early" attributes the ending to the wrong person. Null for sessions
    #: revoked before this was recorded — unknown is stated, never guessed.
    revoked_by: EmailStr | None = None

    #: Always false today. No break-glass path exists, and the field says so
    #: rather than leaving the question open — see md/16 Step 28.
    break_glass: bool = False

    #: An approval is permission; these are uses.
    events: list[SupportAccessEventResponse] = Field(default_factory=list)


class SupportSessionRequest(ApiModel):
    """What CAIRN staff are asking for.

    No expiry field: the duration is a number of minutes bounded server-side,
    because an expiry supplied by the person requesting access is one they chose.
    """

    reason: str = Field(min_length=10, max_length=500)
    scope: SupportScope = SupportScope.CONFIGURATION_DIAGNOSTICS
    minutes: int = Field(default=60, ge=1, le=240)


class SupportDecision(ApiModel):
    """A workspace's answer to a support request."""

    approve: bool


class PipelineHealth(ApiModel):
    """How ingestion is going, in counts and ages.

    Every field is a number or a timestamp. There is nowhere here to put a
    statement, a brief or a payload, which is the point: operations data leaves
    the product for dashboards and exporters that md/05's promises do not cover.
    """

    deliveries_last_hour: int
    deliveries_unprocessed: int
    oldest_unprocessed_minutes: float | None = None
    facts_last_hour: int
    workspaces_ingesting: int


class QueueHealth(ApiModel):
    """Queue state, from the durable record rather than from memory."""

    backfill_runs_active: int
    backfill_runs_failed: int
    deliveries_awaiting_processing: int

    #: True when the in-memory broker is configured. Jobs are lost on restart,
    #: silently, so an operator reading this screen has to know.
    in_memory_broker: bool

    #: Scheduler state. Zero on any other backend, because only the PostgreSQL
    #: scheduler holds a queue every replica can see the same way.
    scheduled_waiting: int = 0
    scheduled_running: int = 0

    #: Distinct workspaces with work eligible to run right now, and how long the
    #: one waiting longest has been waiting. Together they are the starvation
    #: signal: one tenant far above the rest means fairness is not holding.
    #:
    #: Counts of jobs, not of people. Nothing here measures anyone's output.
    tenants_waiting: int = 0
    longest_wait_minutes: float | None = None


class ModelSpendLine(ApiModel):
    """Spend for one stage, and how close it came to the ceiling.

    Tokens, calls and ratios. Never content, and never a workspace: which stage
    is running out of budget is an operations question, which workspace it
    belongs to is a support session's.
    """

    stage: str
    calls: int
    tokens: int

    #: Times a unit of work in this stage came within the warning fraction of
    #: its ceiling, and times the ceiling actually refused a call.
    warnings: int = 0
    refusals: int = 0

    #: The highest fraction of a ceiling any single unit of work reached here.
    #: `None` when no ceiling is configured — which is not the same as nothing
    #: having been spent, and reads very differently on a screen.
    #:
    #: Can exceed 1.0, and is not clamped. A ceiling is checked before a call
    #: and recorded after, because a call's cost is unknowable until it returns,
    #: so one call of overshoot is permitted by design. A value far above 1
    #: means one call costs more than the whole ceiling, which is a
    #: configuration error an operator has to be able to see.
    closest_approach: float | None = None


class ModelSpend(ApiModel):
    """What the model boundary cost, and whether the ceiling is being hit.

    Read from the same counters the pipeline records against, so this screen and
    the bill cannot disagree.

    Capping without signalling is how a ceiling that refuses work every day goes
    unnoticed until a customer asks why their briefs stopped. `warnings` and
    `refusals` are the two numbers OPERATIONS.md's cost row alerts on.
    """

    live: bool
    backend: str
    total_calls: int
    total_tokens: int
    by_stage: list[ModelSpendLine] = Field(default_factory=list)

    #: The configured per-tenant ceilings, so "how close" on each line has
    #: something to be close to. `None` means that ceiling is disabled.
    ceiling_tokens: int | None = None
    ceiling_calls: int | None = None

    #: Platform totals since this process started.
    warnings: int = 0
    refusals: int = 0

    #: Distinct workspaces that have had work refused, as a count. One is a
    #: backfill; many is a ceiling set too low for the platform. Neither answer
    #: needs anybody named.
    workspaces_refused: int = 0

    #: Why the numbers may be lower than the invoice. Served rather than printed
    #: by the client so every surface says the same thing.
    note: str | None = None


class SloObjective(ApiModel):
    """One service level objective, its target, and what it currently reads.

    `measured` is nullable and that is the point: an objective the current
    infrastructure cannot measure reports `measurable: false` with the reason,
    rather than a number nobody can defend.
    """

    key: str
    title: str
    rationale: str

    target: float
    unit: str
    direction: str
    window_minutes: float

    #: The exact column, pair of columns or instrument the number comes from.
    #: Without it a target is a slogan with a decimal point.
    measured_from: str

    measurable: bool
    measured: float | None = None

    #: `None` when there is no measurement. An unmeasured objective is neither
    #: met nor breached, and reporting it as met is how an outage shows green.
    met: bool | None = None

    #: Why there is no number, when there is none.
    note: str | None = None


class SloStatus(ApiModel):
    """Every objective, as of one moment.

    Counts of machine work only. There is deliberately no objective here about
    how quickly a person replies to anything — see md/05 §B.2.
    """

    measured_at: datetime
    objectives: list[SloObjective] = Field(default_factory=list)

    #: Objectives the current infrastructure cannot measure at all. Surfaced as
    #: its own number so that "four of five green" cannot be read as healthy
    #: when the fifth is availability.
    unmeasurable: int = 0
    breaching: int = 0


class EvaluationSummary(ApiModel):
    """The last recorded evaluation run.

    Scores and failure modes. The cases themselves stay in the repository, where
    they are reviewed by a person rather than exported to a dashboard.
    """

    available: bool
    cases: int = 0
    passed: int = 0
    failed: int = 0
    failure_modes: dict[str, int] = Field(default_factory=dict)
    note: str | None = None


class StaffTenantSummary(ApiModel):
    """One workspace as the back-office lists it.

    Configuration and size. No activity, no counts of work, nothing about a
    person — the fields this model does not have are what keeps staff out of
    customer content (md/15 §5.2).
    """

    id: uuid.UUID
    name: str
    slug: str
    region: Region
    created_at: datetime
    member_count: int


class StaffTenantDetail(StaffTenantSummary):
    """One workspace in enough detail to diagnose it.

    Ingestion health is reported as counts and timestamps. An operator can see
    that deliveries stopped four days ago without seeing what any of them said.
    """

    retention_days: int
    github_connected: int
    github_disconnected: int
    last_delivery_at: datetime | None = None
    unprocessed_deliveries: int
    running_backfills: int

    #: True when the last delivery is older than the staleness window. Computed
    #: server-side so every operator reads the same threshold.
    ingestion_stale: bool


class SubscriptionInspection(ApiModel):
    """Billing state as CAIRN holds it.

    md/15 screen 31: an operator answering "why were we charged this" should not
    have to open the payment provider and act on what they see there. Billing is
    not implemented, so this says so rather than inventing a subscription.
    """

    tenant_id: uuid.UUID
    seats_in_use: int
    plan: str
    provider_connected: bool
    note: str


class AuditEntryResponse(ApiModel):
    """One recorded staff action.

    `entryHash` is returned so a reader can verify the chain independently
    rather than trusting the server's own verdict on itself.
    """

    sequence: int
    occurred_at: datetime
    actor_user_id: uuid.UUID
    action: str
    tenant_id: uuid.UUID | None = None
    reason: str
    detail: dict[str, object] = Field(default_factory=dict)
    checksum: str


class AuditVerification(ApiModel):
    """Whether the audit chain is intact."""

    entries: int
    intact: bool

    #: The sequence number of the first entry that failed. Named rather than
    #: reported as a bare boolean, so an investigation has somewhere to start.
    broken_at: int | None = None
    reason: str | None = None


class RoleUpdate(ApiModel):
    """A member's new role.

    A role, and nothing else. A body that also carried, say, `email` would make
    this endpoint a general-purpose member editor, and the next field added to it
    would be added without anybody deciding an administrator should be able to
    change it.
    """

    role: TenantRole


class IntegrationResponse(ApiModel):
    """One source, and whether it is currently reading.

    Disconnected integrations are returned rather than filtered out: a gap in the
    feed is explained by "GitHub was disconnected on the 4th" and unexplained by
    silence.
    """

    #: `github`, and later `chat`, `meeting`, `document`.
    source: str

    #: The organisation or account it reads from.
    account: str

    #: GitHub's own identifier for the installation, which the disconnect route
    #: takes. Not a secret — it appears in the app's own install URL — and the
    #: alternative is an administrator who can see a connection and has no way to
    #: name it when switching it off.
    installation_id: int

    connected_at: datetime

    #: Null while it is still connected.
    disconnected_at: datetime | None = None

    #: GitHub reports an installation suspended without removing it. Suspended
    #: deliveries are not processed, so this is a reason a workspace's feed is
    #: quiet and not a cosmetic flag.
    suspended: bool = False

    # -- From the connector record (Step 31) -------------------------------
    #
    # Every field below is optional and stays null until the connector actually
    # knows. That is the contract the interface is built on: it renders a fact
    # or omits the row, and never fills a gap with something plausible. A
    # "Last synced 4 minutes ago" invented from `connected_at` would discredit
    # every other number on the Trust page, which is the one page whose entire
    # claim is that its figures are read from the workspace.

    #: What the provider actually granted. A missing capability is then
    #: diagnosable as "we were never given this" rather than as an empty feed.
    scopes: list[str] = Field(default_factory=list)

    #: Whether data is arriving, which is not the same question as whether the
    #: connection is authorised — a live installation that has failed every
    #: sync for a week is `connected` and unhealthy.
    health: str | None = None

    #: The one number a stalled-but-authorised connection cannot fake.
    last_successful_sync_at: datetime | None = None

    #: Who pressed connect. Null for connections made before CAIRN recorded it;
    #: an honest blank rather than a guessed identity.
    authorised_by: EmailStr | None = None

    #: Set when the provider withdrew access rather than the workspace choosing
    #: to disconnect. `disconnected_at` alone cannot tell those apart, and the
    #: remedy differs: one is a click, the other a fresh authorisation.
    revoked_at: datetime | None = None


class ConnectorHealthView(ApiModel):
    """One source, as far as it can be seen without reading what it carried.

    Every field is a count, an age, a flag, or a mapping keyed by a closed enum.
    There is nowhere here to put a channel name, a message, a repository or a
    person — reaching any of those needs the consent-gated support session in
    md/15 §5.2, never an operations screen.
    """

    provider: str
    credentials_configured: bool
    workspaces_connected: int
    workspaces_ever_synced: int
    workspaces_by_state: dict[str, int] = Field(default_factory=dict)
    workspaces_by_health: dict[str, int] = Field(default_factory=dict)
    errors_by_category: dict[str, int] = Field(default_factory=dict)
    oldest_unsuccessful_sync_minutes: float | None = None

    #: Null, never zero, when a provider keeps no durable inbound record —
    #: "nothing arrived" and "we cannot see what arrived" are different
    #: findings, and collapsing them is how an outage reads as a quiet week.
    deliveries_last_hour: int | None = None
    failures_last_hour: int | None = None
    deliveries_total: int | None = None
    deliveries_unobservable_reason: str | None = None

    #: Whether inbound delivery has been *observed*, not merely configured.
    inbound_verified: bool = False


class ConnectorFleetView(ApiModel):
    """Every source at one moment, and the numbers worth alerting on."""

    measured_at: datetime
    providers: list[ConnectorHealthView] = Field(default_factory=list)
    workspaces_in_error: int = 0
    workspaces_failing: int = 0

    #: The number that has to be zero before a release. Configured and never
    #: proven is exactly what the release gates refuse to call passed, so the
    #: gate and this screen cannot disagree.
    providers_configured_but_unverified: int = 0
    oldest_unsuccessful_sync_minutes: float | None = None


class PrivacySettings(ApiModel):
    """What happens to this workspace's raw activity.

    The bounds are returned with the value so the interface states the range it
    will accept before somebody is refused for typing outside it.
    """

    retention_days: int
    min_retention_days: int
    max_retention_days: int

    #: Where the data lives. Read-only here: moving a workspace between regions
    #: is a data migration under compliance pressure (md/06 §6.3), and a
    #: dropdown that silently did nothing would be worse than its absence.
    region: Region


class PrivacyUpdate(ApiModel):
    """How long to keep raw activity."""

    retention_days: int


class PersonNotification(ApiModel):
    """Whether one member has been served the worker notification.

    Named per person deliberately. Notification is an obligation the employer
    owes each individual before capture begins, and an Owner who cannot see who
    is outstanding cannot discharge it.

    Note what is **not** here: whether they opted out. That is the person's own
    decision about their own record, and a list of names beside "opted out" is a
    list of employees who declined to be recorded, handed to whoever writes their
    review — see `NotificationStatus`.
    """

    user_id: uuid.UUID
    email: EmailStr
    display_name: str | None = None

    #: When the notification's content was actually served to them. Null means
    #: it has not been, and CAIRN attributes nothing to them until it has.
    notified_at: datetime | None = None


class NotificationStatus(ApiModel):
    """Worker notification across the workspace."""

    people: list[PersonNotification] = Field(default_factory=list)

    member_count: int

    #: **A count, never a list.** md/11 §7 makes the opt-out rate the product's
    #: trust barometer and md/13 makes it a phase gate — and a rate is what a
    #: gate needs. Naming the individuals would mean a person deciding whether to
    #: opt out had to weigh how it looked to their employer, which turns a
    #: privacy control into a career calculation and produces a low number that
    #: means nothing.
    opted_out_count: int

    #: The sources a person can opt out of, so the screen can say what the count
    #: is a count of.
    sources: list[str] = Field(default_factory=list)


class TrustCommitment(ApiModel):
    """One thing CAIRN does, or refuses to do, in plain language."""

    title: str
    detail: str


class TrustCenter(ApiModel):
    """The Trust & Privacy Center (md/05 §B.6).

    **In-product and readable by every member**, not an administrator's page and
    not a PDF. Two audiences and identical content: employees deciding whether to
    trust it daily, and buyers evaluating it.

    Every number here is read from this workspace rather than written into the
    copy. A trust page that states a retention period the system does not apply
    is the most damaging sentence this product could publish, because it is read
    by the audience deciding whether the rest is true.
    """

    #: What is read, per source, with whether it is connected.
    sources: list[TrustSource] = Field(default_factory=list)

    #: What CAIRN contractually refuses to do (md/05 §B.3.4).
    refusals: list[str] = Field(default_factory=list)

    #: How the product behaves — symmetry, correction, provenance.
    commitments: list[TrustCommitment] = Field(default_factory=list)

    retention_days: int
    region: Region

    #: Members who have not yet been served the worker notification. A count,
    #: for the same reason the opt-out figure is one — and shown to everybody,
    #: because "has everyone here been told?" is a question the whole team has a
    #: stake in.
    awaiting_notification: int

    #: Third parties that process customer content, named rather than described
    #: as "trusted partners" (md/02 §5).
    subprocessors: list[TrustCommitment] = Field(default_factory=list)


class TrustSource(ApiModel):
    """One source, what it reads, and whether it is switched on here."""

    source: str
    label: str
    reads: str
    connected: bool


# Resolves the forward reference in TrustCenter.
TrustCenter.model_rebuild()


class FacetPerson(ApiModel):
    """Somebody at least one current fact is about."""

    id: uuid.UUID
    name: str


class FacetsResponse(ApiModel):
    """What this workspace can actually be filtered by.

    Every value here is one that at least one currently-valid fact would match,
    read from the facts rather than from a list of what CAIRN could hold. A menu
    offering "Meetings" to a workspace that never connected one produces an empty
    result the reader blames on the product.

    **No counts anywhere.** A number beside a person's name is a productivity
    metric wearing a filter's clothes (md/05 §B.1), and it would be the first
    thing on this screen anyone screenshotted.
    """

    people: list[FacetPerson] = Field(default_factory=list)

    #: Repository full names today; channels and document spaces later.
    projects: list[str] = Field(default_factory=list)

    sources: list[str] = Field(default_factory=list)


class SearchHit(ApiModel):
    """One search result: a stored fact, and how it was found."""

    fact: FactResponse

    #: `words` — the statement contains what was typed. `meaning` — it was found
    #: by similarity and may contain none of those words.
    #:
    #: Shown to the reader rather than kept internal. The two kinds of match fail
    #: differently, and a semantic near-miss presented as an exact hit is how a
    #: search result gets believed more than it has earned.
    matched_on: Literal["words", "meaning"]


class SearchResults(ApiModel):
    """What a search found.

    **No cursor, deliberately.** Keyset pagination needs a stable total order,
    and relevance is not one — it is recomputed per query and would reorder under
    a cursor. A ranked list is an answer rather than a stream, so this returns
    the best `limit` results and says when it stopped short of everything.

    **Results are stored facts.** Nothing on this path calls a model to compose a
    reply, which is what "grounded" is being used to mean: the reader is looking
    at what CAIRN recorded, with the evidence attached, not at prose about it.
    """

    items: list[SearchHit] = Field(default_factory=list)

    #: True when the ranking was cut at `limit`. A search that quietly returned
    #: its first fifty of two hundred looks identical to one that found fifty.
    truncated: bool = False

    #: False when the configured embedder is the offline hash, whose vectors are
    #: real and semantically meaningless. Reported rather than hidden: a reader
    #: comparing results across environments should be able to see that one of
    #: the two ways of matching was not running.
    semantic: bool = True


class FactPage(ApiModel):
    """One page of facts, and how to ask for the next.

    No total count. Counting rows a reader has not asked for costs a second
    query on every page, and the number would be read as "how much did this team
    do" — a measurement this product does not make (md/09 §10).
    """

    items: list[FactResponse] = Field(default_factory=list)

    #: Opaque. Pass it back as `cursor` to continue. Null means this was the
    #: last page — a client must branch on that rather than on a short page,
    #: because a filtered page can be short and still have more behind it.
    next_cursor: str | None = None


class CitationResponse(ApiModel):
    """Where a claim came from, resolvable in one click.

    **The URL is the whole point of this type.** Citations used to be bare
    evidence identifiers — `ev-pr-482` — which satisfies "every claim carries a
    citation" and fails the thing the citation is *for*: a reader cannot check
    `ev-pr-482`. Step 21's criterion is that every claim links to its source in
    one click, and a string that only means something inside this database is
    not a link.

    `url` is optional because some evidence genuinely has no permalink — a
    meeting transcript, most obviously. The interface names the source rather
    than hiding the citation: an unlinked citation is still provenance a person
    can go and check, whereas a hidden one silently breaks the promise.
    """

    evidence_id: str
    #: `github`, `chat`, `meeting`, `document`.
    source: str
    url: str | None = None

    #: The exact span the claim rests on, where the extractor kept one.
    quote: str | None = None


class BriefClaimResponse(ApiModel):
    """One sentence of a brief, with everything needed to check it."""

    text: str
    certainty: Certainty

    #: The facts this rests on, and the evidence those facts cite. Both, because
    #: they answer different questions: which belief produced this sentence, and
    #: what in the source material supports that belief.
    fact_ids: list[uuid.UUID] = Field(default_factory=list)
    citations: list[CitationResponse] = Field(default_factory=list)

    #: People the underlying facts concern.
    credits: list[str] = Field(default_factory=list)

    #: Whether synthesis had to add the hedge the model omitted. Surfaced
    #: because a model that never hedges unprompted is a prompt problem, and a
    #: prompt problem is invisible once the fallback silently corrects it.
    hedged_by_system: bool = False


class BriefResponse(ApiModel):
    """A period's brief: prose, and the claims behind it."""

    #: Present for a stored brief, absent for one generated on the spot.
    #: The archive links by this; the live brief has nothing to link to yet.
    id: uuid.UUID | None = None

    period_start: datetime
    period_end: datetime

    #: When this brief was written. For a stored brief that is when synthesis
    #: ran, which is not the same as the end of the period it covers — and the
    #: difference is what tells a reader whether they are looking at a record or
    #: at something composed just now.
    generated_at: datetime | None = None

    #: Whether this came from the archive rather than being generated for this
    #: request. Surfaced because "this is what we said on Tuesday" and "this is
    #: what we would say about Tuesday now" are different claims, and only the
    #: first is a record.
    stored: bool = False

    narrative: str
    claims: list[BriefClaimResponse] = Field(default_factory=list)

    #: Explicit rather than inferred from an empty claim list. "Nothing to
    #: report" and "everything was suppressed" are different answers and only
    #: one of them is fine (md/09 §8).
    abstained: bool = False

    #: How many claims did not survive verification or the guardrails.
    #:
    #: **A count, never the text.** A suppressed claim is model output that
    #: failed a check — an unsupported assertion, a boundary violation, an echoed
    #: injection — and returning it to a browser would publish exactly the
    #: content the gate rejected. The count is what makes "why is this brief
    #: short" answerable; the text belongs in the operator's log.
    suppressed_count: int = 0

    #: Whether retrieval stopped at its budget rather than running out of graph.
    #: A silently truncated brief reads exactly like a complete one.
    truncated: bool = False


class RepositoryProgress(ApiModel):
    """One repository's import, as the onboarding screen shows it."""

    repository: str
    #: `pending`, `running`, `throttled`, `completed`, `failed`.
    state: str
    commits_imported: int
    finished: bool


class OnboardingResponse(ApiModel):
    """How far a workspace has got through its first ten minutes.

    Counters rather than a percentage. GitHub does not say how many commits a
    repository holds before it is walked, so a percentage would be invented —
    and an invented one always stalls near the end, which reads as broken rather
    than as unknown. A number that climbs is honest and, on the screen where
    abandonment costs most, more reassuring.
    """

    #: `not_connected`, `importing`, `understanding`, `ready`.
    stage: str
    connected: bool
    account_login: str | None = None
    repositories: list[RepositoryProgress] = Field(default_factory=list)
    commits_imported: int = 0
    facts_available: int = 0

    #: Whether a backfill is still running, so the screen knows to keep polling.
    #: Distinct from `stage`: a workspace can have readable facts *and* an
    #: import still in flight, which is the normal case after about a minute.
    importing: bool = False


class BriefSummary(ApiModel):
    """One entry in the archive.

    Deliberately not the whole brief. An archive is a list to scan, and sending
    every claim of every period to render a list of dates is the request that
    makes the screen slow exactly as a workspace accumulates history.
    """

    id: uuid.UUID
    period_start: datetime
    period_end: datetime
    generated_at: datetime

    #: The first sentence, for a list that is scannable. Truncated server-side
    #: rather than in CSS: a clipped line still ships the whole paragraph to the
    #: browser, and an archive of five hundred briefs would ship all of it.
    excerpt: str
    claim_count: int
    abstained: bool


class BriefArchive(ApiModel):
    """A page of past briefs, newest first."""

    items: list[BriefSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class CorrectionRequest(ApiModel):
    """A person saying what CAIRN got wrong about them.

    A closed set of kinds rather than a free-text box, because free text is the
    worse input on both sides: it asks somebody to explain a defect in a product
    they did not build, and it hands evaluation an unlabelled string instead of
    a failure mode. `note` exists for the detail a kind cannot carry, and
    nothing depends on it being filled in.
    """

    #: `reworded`, `did_not_happen`, `wrong_person`, `no_longer_true`.
    kind: str

    #: The corrected sentence. Required for `reworded` and ignored otherwise —
    #: demanding one for "this did not happen" would make the fastest and most
    #: common correction the most laborious.
    statement: str | None = Field(default=None, max_length=1000)

    #: Optional context, for the audit trail and for whoever reviews the
    #: correction before it becomes an evaluation case.
    note: str | None = Field(default=None, max_length=500)


class CorrectionResponse(ApiModel):
    """What the correction did."""

    corrected_fact_id: uuid.UUID

    #: The fact that replaced it, when the correction supplied one. Absent for a
    #: denial: nothing replaced it, and returning an empty object would suggest
    #: something did.
    replacement: FactResponse | None = None


class SourceConsent(ApiModel):
    """One source, and whether this person has opted out of it."""

    source: str
    #: Plain English, so the notification does not have to carry a glossary.
    label: str
    #: What CAIRN reads from it — stated per source, because "we read your
    #: activity" is the sentence that makes people opt out (md/11 §4.1).
    reads: str
    opted_out: bool


class ConsentResponse(ApiModel):
    """What CAIRN may attribute to the caller, and what it never does.

    The refusals travel with the choices deliberately. md/05 §B.3.4 requires the
    contractual refusals to be stated in-product, and the moment a person is
    deciding whether to opt out is the moment they are most entitled to read
    them — not a policy page they would have to go looking for.
    """

    sources: list[SourceConsent] = Field(default_factory=list)

    #: What CAIRN will never do, in the person's own words rather than legal
    #: ones. Served from the API rather than hardcoded in the interface so that
    #: every surface — web, email, a future mobile client — states the same
    #: promise, and changing it is one edit rather than a search.
    refusals: list[str] = Field(default_factory=list)


class ConsentUpdate(ApiModel):
    """A person changing what CAIRN may attribute to them."""

    source: str
    opted_out: bool


class ConsentUpdateResponse(ApiModel):
    """The result of one choice."""

    source: str
    opted_out: bool

    #: How many existing attributions were removed.
    #:
    #: Reported because a control that visibly did something is a control a
    #: person believes. A silent toggle asks them to take it on faith at exactly
    #: the moment they have decided not to.
    unlinked: int = 0


# -- Slack ------------------------------------------------------------------
#
# Nothing here is a request body carrying a token. The install flow deliberately
# has no "paste your bot token" endpoint: a customer who can hand us a token can
# hand us somebody else's, and the token would then exist in a request body, a
# proxy log and a browser's memory before it ever reached the encrypting path.
# The only way a Slack credential enters CAIRN is the server-to-server exchange
# in `slack/oauth.py`.


class SlackInstallResponse(ApiModel):
    """Where to send the customer, and what they are about to be asked."""

    #: The Slack authorise URL, state parameter included. Built server-side from
    #: settings, never from the request — a redirect URI assembled from a `Host`
    #: header sends the install code to whoever set the header.
    authorize_url: str

    #: When the install link stops working. Returned so an interface can say
    #: "this link expires in ten minutes" rather than presenting a stale button.
    expires_at: datetime

    #: Exactly what CAIRN asks Slack for, shown before the customer authorises
    #: rather than only on Slack's own screen. A permission list a product is
    #: willing to state up front is one it is willing to be held to.
    requested_scopes: list[str] = Field(default_factory=list)

    #: The `/invite` requirement, in the copy `slack.channels` owns. Present on
    #: this response as well as the channel list because it changes what the
    #: customer expects *before* they start, not after they wonder why the feed
    #: is empty.
    notice: str


class SlackChannelResponse(ApiModel):
    """One public channel the workspace could select."""

    id: str

    #: The display name, fetched live and never stored.
    #:
    #: The one place a Slack channel name crosses this API, and it is bounded to
    #: it: this endpoint is Owner/Admin-only, returns the caller's own workspace's
    #: channels, and is read by somebody already looking at the same list in
    #: Slack. Nothing persists it, no log line carries it, and the selection
    #: endpoints below answer in IDs alone.
    name: str

    #: Whether the CAIRN app is currently in the channel. A channel selected
    #: without this being true delivers nothing at all, silently, so the picker
    #: has to show it.
    bot_is_member: bool

    #: Whether it is currently selected.
    selected: bool


class SlackChannelListResponse(ApiModel):
    """The picker's contents."""

    channels: list[SlackChannelResponse] = Field(default_factory=list)

    #: The `/invite` requirement. Travels with the list because this is the
    #: screen where the misunderstanding happens.
    notice: str


class SlackChannelSelectionRequest(ApiModel):
    """The full state of the picker, not a delta.

    A replace rather than a merge: unchecking a box has to mean something, and
    the something it means is withdrawing permission to read a channel.
    """

    #: Slack channel IDs (`C0123ABCD`). Names are refused — they change, and a
    #: permission keyed on a name is one a rename silently grants or revokes.
    channel_ids: list[str] = Field(default_factory=list)


class SlackChannelSelectionResponse(ApiModel):
    """What CAIRN may now process. IDs only — deliberately no names."""

    channel_ids: list[str] = Field(default_factory=list)

    #: Repeated here so the confirmation screen states it too. A selection saved
    #: without the invite is a selection that does nothing.
    notice: str


class SlackDisconnectResponse(ApiModel):
    """What disconnecting did, stated precisely enough to be trusted."""

    state: str
    disconnected_at: datetime

    #: Whether the stored bot token was destroyed. Reported rather than assumed:
    #: a disconnect that leaves the credential in place keeps a live grant to
    #: read a customer's conversations after they asked us to stop, and a
    #: customer has no way to check from outside.
    credential_cleared: bool

    #: What disconnecting does *not* do. Stated in the response because the
    #: honest sentence is the less flattering one, and a product that only says
    #: the flattering half is one whose deletion claims cannot be relied on.
    retention_notice: str


# -- Google Chat ------------------------------------------------------------
#
# Shaped like the Slack models above, with two deliberate differences.
#
# There is no `requested_scopes` on the install response. Google's two Chat
# scopes are not a list a customer can act on — they are shown on Google's own
# consent screen in Google's own words, and repeating our paraphrase of them
# invites the two to disagree.
#
# A space's **display name** appears on exactly one model here,
# `GoogleChatSpaceResponse`, served by one Owner/Admin endpoint. Every other
# model answers in resource names. A Chat space name is frequently the most
# sensitive string a customer holds — "Acme / Northwind diligence", "redundancy
# planning" — so it is fetched live, never stored, never logged, and never
# echoed back by the selection endpoints.


class GoogleChatInstallResponse(ApiModel):
    """Where to send the customer, and what they need to know first."""

    #: The Google authorise URL, state parameter and PKCE challenge included.
    #: Built server-side from settings, never from the request — a redirect URI
    #: assembled from a `Host` header sends the authorisation code, and
    #: therefore the account's refresh token, to whoever set the header.
    authorize_url: str

    #: When the install link stops working. Returned so an interface can say
    #: "this link expires in ten minutes" rather than presenting a stale button.
    expires_at: datetime

    #: The "add the app to the space" requirement, in the copy `gchat.spaces`
    #: owns. Present here as well as on the space list because it changes what
    #: the customer expects *before* they start, not after they wonder why the
    #: feed is empty.
    notice: str


class GoogleChatSpaceResponse(ApiModel):
    """One space the workspace could select, and the state of its feed."""

    #: The resource name, `spaces/AAAA1111`. The key every permission is stored
    #: under, and the only identifier a Chat event carries.
    name: str

    #: The display name, fetched live and never stored. The one place a Google
    #: Chat space name crosses this API — see the section comment above.
    display_name: str

    #: Whether CAIRN will read this kind of space at all. Direct messages, app
    #: DMs and unnamed spaces are excluded before this model is built, so this
    #: is `True` on everything currently returned; it is on the model because
    #: the reason a space is missing from a picker has to be answerable.
    eligible: bool

    #: Whether it is currently selected.
    selected: bool

    #: The Workspace Events subscription's state — `pending`, `active`,
    #: `suspended`, `expired`, `deleted` or `error` — or `None` when there is no
    #: lease at all, which is every unselected space.
    #:
    #: Shown because "selected" and "delivering" are different facts, and a
    #: screen that conflates them tells a customer their feed is fine while it
    #: has a hole in it.
    subscription_state: str | None = None

    #: When the lease lapses without renewal. `None` before Google has
    #: acknowledged one.
    expire_time: datetime | None = None

    #: Why the feed is broken, as a `ConnectorErrorCategory` and never as
    #: Google's words. Google's messages quote the space and frequently the
    #: person who authorised.
    error_category: str | None = None


class GoogleChatSpaceListResponse(ApiModel):
    """The picker's contents. Eligible spaces only."""

    spaces: list[GoogleChatSpaceResponse] = Field(default_factory=list)

    #: The "add the app to the space" requirement. Travels with the list because
    #: this is the screen where the misunderstanding happens.
    notice: str


class GoogleChatSpaceSelectionRequest(ApiModel):
    """The full state of the picker, not a delta.

    A replace rather than a merge: unchecking a box has to mean something, and
    the something it means is withdrawing permission to read a conversation.
    """

    #: Space resource names (`spaces/AAAA1111`). Display names are refused —
    #: they change, and a permission keyed on one is silently granted or revoked
    #: by a rename.
    space_names: list[str] = Field(default_factory=list)


class GoogleChatSpaceSelectionResponse(ApiModel):
    """What CAIRN may now process. Resource names only — deliberately no names."""

    space_names: list[str] = Field(default_factory=list)

    #: Repeated here so the confirmation screen states it too. A selection saved
    #: without the app being added to the space is a selection that does nothing.
    notice: str


class GoogleChatDisconnectResponse(ApiModel):
    """What disconnecting did, stated precisely enough to be trusted."""

    state: str
    disconnected_at: datetime

    #: Whether the stored refresh token was destroyed. Reported rather than
    #: assumed: a disconnect that leaves the credential in place keeps a standing
    #: grant to read a customer's conversations after they asked us to stop, and
    #: a customer has no way to check from outside.
    credential_cleared: bool

    #: What disconnecting does *not* do. Stated in the response because the
    #: honest sentence is the less flattering one.
    retention_notice: str
