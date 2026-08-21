"""Demo team data for the Acme Corp development workspace.

`cairn_api.db.seed` builds the *minimum* workspace two tenants need to prove
isolation. This script builds the workspace a person is shown: ten colleagues,
four projects with real membership, and three weeks of facts spread across
them, so the dashboard, the Team page and a person page each have something
honest to render instead of an empty state.

Deliberate contrasts, because each one is a screen that has to work:

* **People without accounts.** Six of the ten have no ``User`` row at all —
  contractors and colleagues who appear in sources and have never signed in.
  A workspace where every contributor has an account is not the normal case,
  and `Person.user_id` being null is the ordinary state, not a defect.
* **Unstated capacity.** Four people have never declared availability, so
  their ``capacity_stated_at`` is null. Capacity is self-declared (see
  `PersonCapacity`); a demo that states it for everybody hides the default.
* **One person on no project**, so the empty membership state is reachable.
* **One unlinked citation per meeting fact**: a meeting has an
  ``evidence_id`` and no ``url``. Citations that cannot be clicked through are
  real, and the fact card must survive one.

Idempotent: every insert is guarded on a lookup by natural key — display name
within the tenant, email, (project, person), fact statement. Running it twice
creates nothing the second time and says so.

Synthetic data only, and local-only by construction: it writes to whatever
`platform_session` connects to, which `config.py` refuses to point at a
deployed environment on these defaults (md/17 §9.1).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from cairn_api.auth.tokens import hash_password
from cairn_api.db.auth_models import PasswordCredential
from cairn_api.db.fact_models import Fact, FactPerson, FactSource
from cairn_api.db.identity_models import Identity, IdentityKind, Person, PersonCapacity
from cairn_api.db.models import Membership, TenantRole, User, WorkRole
from cairn_api.db.project_models import Project, ProjectMember
from cairn_api.db.seed import SEED_PASSWORD
from cairn_api.db.session import dispose_engines, platform_session
from cairn_api.db.tenancy import tenant_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: The development workspace this script populates ("Acme Corp").
TENANT_ID = uuid.UUID("45979456-e008-463d-9963-e433e24da9ed")

#: The owner of record. Every membership and project membership this script
#: writes records them as the actor, because an unattributed row is exactly
#: the "silent membership" `project_models.py` refuses to allow.
OWNER_EMAIL = "ali@acme.example.com"

EMAIL_DOMAIN = "acme.example.com"

GATEWAY = "acme-inc/gateway"
PAYMENTS = "acme-inc/payments"
PROOF = "acme-inc/cairn-proof"
CRAIN = "waqasabid-del/Crain"


@dataclass(frozen=True)
class Colleague:
    """One person to seed, and whether they can sign in."""

    display_name: str
    github_login: str
    capacity: PersonCapacity

    #: Local part of an `@acme.example.com` address. ``None`` means no account:
    #: a `Person` with no `User`, which is most of this roster on purpose.
    account: str | None = None

    role: TenantRole | None = None
    work_role: WorkRole | None = None


@dataclass(frozen=True)
class Assignment:
    """A person's place in one project's context."""

    project_name: str
    display_name: str
    project_role: str


@dataclass(frozen=True)
class Citation:
    """Where a seeded fact came from."""

    source: str
    evidence_id: str
    project: str
    url: str | None = None


@dataclass(frozen=True)
class Statement:
    """One seeded fact: what happened to the work, and who it concerns.

    Never who did it *better*. Statements here describe the work — a rollout,
    a decision, a missing credential — because a fact that scores, ranks or
    compares a person is the surface md/05 §B.3.3 forbids, and a seed that
    demonstrates one teaches the product to grow it.
    """

    kind: str
    statement: str
    certainty: str
    citation: Citation
    people: tuple[str, ...]

    #: How long ago it happened, in days back from now.
    days_ago: int

    #: Hour of that day, so a feed does not stack every entry at the same time.
    hour: int = 10


ROSTER: tuple[Colleague, ...] = (
    Colleague(
        display_name="Priya Nair",
        github_login="priya",
        capacity=PersonCapacity.AT_CAPACITY,
    ),
    Colleague(
        display_name="Tom Reilly",
        github_login="treilly",
        capacity=PersonCapacity.OPEN_TO_WORK,
    ),
    Colleague(
        display_name="Ana Gómez",
        github_login="agomez",
        capacity=PersonCapacity.AT_CAPACITY,
        account="ana",
        role=TenantRole.ADMIN,
        work_role=WorkRole.PRODUCT,
    ),
    Colleague(
        display_name="Yusuf Demir",
        github_login="ydemir",
        capacity=PersonCapacity.NOT_STATED,
        account="yusuf",
        role=TenantRole.MEMBER,
        work_role=WorkRole.OPERATIONS,
    ),
    Colleague(
        display_name="Mei Lin Chen",
        github_login="meilin",
        capacity=PersonCapacity.OPEN_TO_WORK,
        account="meilin",
        role=TenantRole.MEMBER,
        work_role=WorkRole.DEVELOPER,
    ),
    Colleague(
        display_name="Daniel Okonkwo",
        github_login="dokonkwo",
        capacity=PersonCapacity.NOT_STATED,
        account="daniel",
        role=TenantRole.VIEWER,
    ),
    Colleague(
        display_name="Sofia Rossi",
        github_login="srossi",
        capacity=PersonCapacity.AT_CAPACITY,
    ),
    Colleague(
        display_name="Jonas Weber",
        github_login="jweber",
        capacity=PersonCapacity.NOT_STATED,
    ),
    Colleague(
        display_name="Aisha Rahman",
        github_login="aisha",
        capacity=PersonCapacity.OPEN_TO_WORK,
    ),
    Colleague(
        display_name="Lucas Fernandes",
        github_login="lfernandes",
        capacity=PersonCapacity.NOT_STATED,
    ),
)


#: Lucas Fernandes is deliberately absent: a person on no project is a state
#: the Team page has to render, and it cannot be reviewed if no seed produces
#: one.
ASSIGNMENTS: tuple[Assignment, ...] = (
    Assignment(GATEWAY, "Priya Nair", "Backend"),
    Assignment(GATEWAY, "Yusuf Demir", "Infrastructure"),
    Assignment(GATEWAY, "Ana Gómez", "Product"),
    Assignment(GATEWAY, "Sofia Rossi", "QA"),
    Assignment(PAYMENTS, "Priya Nair", "Backend"),
    Assignment(PAYMENTS, "Daniel Okonkwo", "Backend"),
    Assignment(PAYMENTS, "Mei Lin Chen", "Data"),
    Assignment(PAYMENTS, "Sofia Rossi", "QA"),
    Assignment(PROOF, "Tom Reilly", "Frontend"),
    Assignment(PROOF, "Aisha Rahman", "Design"),
    Assignment(PROOF, "Ana Gómez", "Product"),
    Assignment(CRAIN, "Jonas Weber", "Infrastructure"),
    Assignment(CRAIN, "Mei Lin Chen", "Data"),
)


def _github(repo: str, number: int) -> Citation:
    return Citation(
        source="github",
        evidence_id=f"github:pull_request:{repo}#{number}",
        url=f"https://github.com/{repo}/pull/{number}",
        project=repo,
    )


def _chat(channel: str, ts: str, project: str) -> Citation:
    return Citation(
        source="chat",
        evidence_id=f"chat:slack:{channel}:{ts}",
        url=f"https://acme.slack.com/archives/{channel}/p{ts}",
        project=project,
    )


def _meeting(slug: str, project: str) -> Citation:
    # No url, on purpose. A standup has minutes and no permalink, and the fact
    # card must render a citation nobody can click through to.
    return Citation(source="meeting", evidence_id=f"meeting:{slug}", project=project)


STATEMENTS: tuple[Statement, ...] = (
    # ---- gateway -------------------------------------------------------
    Statement(
        kind="delivery",
        statement="Rate limiting was rolled out to the public gateway behind a feature flag.",
        certainty="verified",
        citation=_github(GATEWAY, 214),
        people=("Priya Nair",),
        days_ago=20,
        hour=9,
    ),
    Statement(
        kind="decision",
        statement=(
            "The gateway will enforce per-tenant quotas at the edge rather than in each "
            "downstream service."
        ),
        certainty="verified",
        citation=_meeting("2026-08-03-architecture-review", GATEWAY),
        people=("Ana Gómez", "Priya Nair"),
        days_ago=19,
        hour=14,
    ),
    Statement(
        kind="delivery",
        statement="The gateway now returns Retry-After on every throttled response.",
        certainty="verified",
        citation=_github(GATEWAY, 221),
        people=("Priya Nair",),
        days_ago=17,
        hour=11,
    ),
    Statement(
        kind="blocker",
        statement=(
            "The gateway load test cannot run because the staging cluster has no spare "
            "node capacity."
        ),
        certainty="observed",
        citation=_chat("C08GATEWAY", "1755000000", GATEWAY),
        people=("Yusuf Demir",),
        days_ago=16,
        hour=16,
    ),
    Statement(
        kind="in_progress",
        statement="Structured request logging is being added to the gateway's admin routes.",
        certainty="observed",
        citation=_github(GATEWAY, 229),
        people=("Yusuf Demir", "Priya Nair"),
        days_ago=14,
        hour=10,
    ),
    Statement(
        kind="open_question",
        statement="Whether internal service-to-service calls are exempt from the new quotas is undecided.",
        certainty="suggested",
        citation=_chat("C08GATEWAY", "1755300000", GATEWAY),
        people=("Ana Gómez",),
        days_ago=13,
        hour=15,
    ),
    Statement(
        kind="delivery",
        statement="Quota headers were documented in the public API reference.",
        certainty="verified",
        citation=_github(GATEWAY, 236),
        people=("Ana Gómez",),
        days_ago=9,
        hour=13,
    ),
    Statement(
        kind="decision",
        statement=(
            "Throttled requests will be sampled into the audit log at one percent rather "
            "than logged in full."
        ),
        certainty="observed",
        citation=_meeting("2026-08-14-standup", GATEWAY),
        people=("Yusuf Demir", "Ana Gómez"),
        days_ago=8,
        hour=9,
    ),
    Statement(
        kind="delivery",
        statement="The gateway feature flag was removed and rate limiting is now on by default.",
        certainty="verified",
        citation=_github(GATEWAY, 244),
        people=("Priya Nair",),
        days_ago=4,
        hour=12,
    ),
    Statement(
        kind="in_progress",
        statement="A regression suite for quota behaviour under burst traffic is being written.",
        certainty="observed",
        citation=_chat("C08GATEWAY", "1755900000", GATEWAY),
        people=("Sofia Rossi",),
        days_ago=2,
        hour=11,
    ),
    # ---- payments ------------------------------------------------------
    Statement(
        kind="blocker",
        statement=(
            "Sandbox credentials for the payment provider are still missing, which is "
            "blocking end-to-end tests."
        ),
        certainty="verified",
        citation=_chat("C08PAYMENTS", "1754800000", PAYMENTS),
        people=("Sofia Rossi", "Daniel Okonkwo"),
        days_ago=21,
        hour=10,
    ),
    Statement(
        kind="decision",
        statement="The team decided to stage the payments cutover across two weekends.",
        certainty="verified",
        citation=_meeting("2026-08-05-payments-planning", PAYMENTS),
        people=("Ana Gómez", "Mei Lin Chen"),
        days_ago=17,
        hour=15,
    ),
    Statement(
        kind="delivery",
        statement="Idempotency keys were added to the charge endpoint to stop duplicate captures.",
        certainty="verified",
        citation=_github(PAYMENTS, 501),
        people=("Priya Nair",),
        days_ago=16,
        hour=9,
    ),
    Statement(
        kind="delivery",
        statement="Settlement reports are now reconciled against the provider's daily payout file.",
        certainty="verified",
        citation=_github(PAYMENTS, 507),
        people=("Mei Lin Chen",),
        days_ago=15,
        hour=14,
    ),
    Statement(
        kind="open_question",
        statement=(
            "It is unclear whether refunds issued during the cutover window should route "
            "to the old processor."
        ),
        certainty="suggested",
        citation=_chat("C08PAYMENTS", "1755100000", PAYMENTS),
        people=("Daniel Okonkwo", "Ana Gómez"),
        days_ago=12,
        hour=16,
    ),
    Statement(
        kind="blocker",
        statement="The payments release is held while the provider investigates delayed webhook delivery.",
        certainty="verified",
        citation=_chat("C08PAYMENTS", "1755400000", PAYMENTS),
        people=("Priya Nair", "Sofia Rossi"),
        days_ago=11,
        hour=13,
    ),
    Statement(
        kind="in_progress",
        statement="Reconciliation of the August ledger against provider statements is underway.",
        certainty="observed",
        citation=_github(PAYMENTS, 515),
        people=("Mei Lin Chen",),
        days_ago=10,
        hour=11,
    ),
    Statement(
        kind="delivery",
        statement="Failed captures are now retried with exponential backoff and a dead-letter queue.",
        certainty="verified",
        citation=_github(PAYMENTS, 519),
        people=("Daniel Okonkwo",),
        days_ago=7,
        hour=10,
    ),
    Statement(
        kind="decision",
        statement="Refund latency will be reported to customers as a range rather than a fixed estimate.",
        certainty="observed",
        citation=_meeting("2026-08-17-standup", PAYMENTS),
        people=("Ana Gómez",),
        days_ago=5,
        hour=9,
    ),
    Statement(
        kind="open_question",
        statement="Nobody has confirmed which currencies the second cutover weekend covers.",
        certainty="suggested",
        citation=_meeting("2026-08-19-payments-sync", PAYMENTS),
        people=("Mei Lin Chen", "Daniel Okonkwo"),
        days_ago=3,
        hour=15,
    ),
    Statement(
        kind="delivery",
        statement="A soak test ran the charge endpoint for six hours without a duplicate capture.",
        certainty="verified",
        citation=_github(PAYMENTS, 528),
        people=("Sofia Rossi",),
        days_ago=1,
        hour=12,
    ),
    # ---- cairn-proof ---------------------------------------------------
    Statement(
        kind="decision",
        statement="Fact cards will show their citation inline rather than behind a hover.",
        certainty="verified",
        citation=_meeting("2026-08-04-design-review", PROOF),
        people=("Aisha Rahman", "Tom Reilly"),
        days_ago=18,
        hour=14,
    ),
    Statement(
        kind="delivery",
        statement="The dashboard brief was rebuilt to read as one column on narrow screens.",
        certainty="verified",
        citation=_github(PROOF, 88),
        people=("Tom Reilly",),
        days_ago=15,
        hour=10,
    ),
    Statement(
        kind="delivery",
        statement="An empty state was added for people who belong to no project yet.",
        certainty="verified",
        citation=_github(PROOF, 91),
        people=("Tom Reilly", "Aisha Rahman"),
        days_ago=12,
        hour=11,
    ),
    Statement(
        kind="open_question",
        statement="How an unlinked meeting citation should be presented has not been settled.",
        certainty="suggested",
        citation=_meeting("2026-08-11-design-review", PROOF),
        people=("Aisha Rahman",),
        days_ago=11,
        hour=15,
    ),
    Statement(
        kind="in_progress",
        statement="The Team page is being reworked so capacity reads as self-declared, not assigned.",
        certainty="observed",
        citation=_github(PROOF, 96),
        people=("Aisha Rahman",),
        days_ago=8,
        hour=13,
    ),
    Statement(
        kind="blocker",
        statement="The proof build cannot ship until the generated theme file stops drifting on install.",
        certainty="observed",
        citation=_chat("C08PROOF", "1755600000", PROOF),
        people=("Tom Reilly",),
        days_ago=6,
        hour=16,
    ),
    Statement(
        kind="decision",
        statement="Project state stays a declared value and will not be inferred from recent activity.",
        certainty="verified",
        citation=_meeting("2026-08-18-standup", PROOF),
        people=("Ana Gómez", "Aisha Rahman"),
        days_ago=4,
        hour=9,
    ),
    Statement(
        kind="delivery",
        statement="Keyboard focus order was fixed across the workspace navigation.",
        certainty="verified",
        citation=_github(PROOF, 103),
        people=("Tom Reilly",),
        days_ago=2,
        hour=10,
    ),
    # ---- Crain ---------------------------------------------------------
    Statement(
        kind="delivery",
        statement="Nightly database backups were moved to a separate storage account.",
        certainty="verified",
        citation=_github(CRAIN, 34),
        people=("Jonas Weber",),
        days_ago=19,
        hour=8,
    ),
    Statement(
        kind="blocker",
        statement="A restore rehearsal failed because the disposable copy ran out of disk.",
        certainty="observed",
        citation=_chat("C08CRAIN", "1755200000", CRAIN),
        people=("Jonas Weber",),
        days_ago=13,
        hour=17,
    ),
    Statement(
        kind="decision",
        statement="Retention for ingested webhook payloads was set to thirty days.",
        certainty="verified",
        citation=_meeting("2026-08-12-infra-sync", CRAIN),
        people=("Jonas Weber", "Mei Lin Chen"),
        days_ago=10,
        hour=14,
    ),
    Statement(
        kind="delivery",
        statement="The worker queue was migrated from the emulator to the managed topic.",
        certainty="verified",
        citation=_github(CRAIN, 41),
        people=("Jonas Weber",),
        days_ago=6,
        hour=11,
    ),
    Statement(
        kind="in_progress",
        statement="An index on the fact table's occurrence timestamp is being trialled on a replica.",
        certainty="observed",
        citation=_github(CRAIN, 45),
        people=("Mei Lin Chen",),
        days_ago=3,
        hour=12,
    ),
    Statement(
        kind="open_question",
        statement="Whether the audit mirror needs its own retention policy is still open.",
        certainty="suggested",
        citation=_chat("C08CRAIN", "1755800000", CRAIN),
        people=("Jonas Weber",),
        days_ago=1,
        hour=9,
    ),
)


@dataclass
class Counts:
    """What the run created, and what it found already there."""

    created: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def add(self, label: str, *, created: bool) -> None:
        bucket = self.created if created else self.skipped
        bucket[label] = bucket.get(label, 0) + 1

    def total(self, label: str, *, created: bool) -> int:
        bucket = self.created if created else self.skipped
        return bucket.get(label, 0)


async def _seed_accounts(counts: Counts) -> uuid.UUID:
    """Create the `User`, credential and `Membership` rows, and return the owner.

    Platform-scoped: users are global and not subject to RLS, and a membership
    is how a user first reaches a tenant, so neither can be written from
    inside a tenant session.
    """
    async with platform_session() as session:
        owner_id = await session.scalar(select(User.id).where(User.email == OWNER_EMAIL))
        if owner_id is None:
            msg = (
                f"No user {OWNER_EMAIL!r}. Run `make seed` first — this script adds "
                "colleagues to a workspace the base seed creates."
            )
            raise RuntimeError(msg)

        # Argon2 is deliberately slow; one hash, reused, as in db/seed.py.
        password_hash: str | None = None
        verified = datetime.now(UTC)

        for colleague in ROSTER:
            if colleague.account is None or colleague.role is None:
                continue

            email = f"{colleague.account}@{EMAIL_DOMAIN}"
            user = await session.scalar(select(User).where(User.email == email))
            if user is None:
                if password_hash is None:
                    password_hash = hash_password(SEED_PASSWORD)
                user = User(
                    email=email,
                    display_name=colleague.display_name,
                    email_verified_at=verified,
                )
                session.add(user)
                await session.flush()
                session.add(PasswordCredential(user_id=user.id, password_hash=password_hash))
                counts.add("users", created=True)
            else:
                counts.add("users", created=False)

            membership = await session.scalar(
                select(Membership).where(
                    Membership.tenant_id == TENANT_ID,
                    Membership.user_id == user.id,
                )
            )
            if membership is None:
                session.add(
                    Membership(
                        tenant_id=TENANT_ID,
                        user_id=user.id,
                        role=colleague.role,
                        work_role=colleague.work_role,
                        notified_at=verified,
                    )
                )
                counts.add("memberships", created=True)
            else:
                counts.add("memberships", created=False)

        await session.commit()
        return owner_id


async def _seed_people(counts: Counts) -> dict[str, uuid.UUID]:
    """Create the `Person` rows and their identities. Returns name -> person id."""
    people: dict[str, uuid.UUID] = {}

    async with tenant_session(TENANT_ID) as session:
        for colleague in ROSTER:
            person = await session.scalar(
                select(Person)
                .where(
                    Person.tenant_id == TENANT_ID,
                    Person.display_name == colleague.display_name,
                )
                .order_by(Person.created_at)
                .limit(1)
            )

            if person is None:
                stated = (
                    None
                    if colleague.capacity is PersonCapacity.NOT_STATED
                    else datetime.now(UTC) - timedelta(days=5)
                )
                person = Person(
                    tenant_id=TENANT_ID,
                    display_name=colleague.display_name,
                    capacity=colleague.capacity,
                    capacity_stated_at=stated,
                )
                session.add(person)
                await session.flush()
                counts.add("people", created=True)
            else:
                counts.add("people", created=False)
                # The base seed's Priya has never stated capacity. Filling in a
                # value the roster declares is idempotent: the second run finds
                # it already set and changes nothing.
                if (
                    person.capacity is PersonCapacity.NOT_STATED
                    and colleague.capacity is not PersonCapacity.NOT_STATED
                ):
                    person.capacity = colleague.capacity
                    person.capacity_stated_at = datetime.now(UTC) - timedelta(days=5)

            people[colleague.display_name] = person.id

            if colleague.account is not None:
                email = f"{colleague.account}@{EMAIL_DOMAIN}"
                if person.user_id is None:
                    person.user_id = await session.scalar(
                        select(User.id).where(User.email == email)
                    )
                await _claim_identity(session, person.id, IdentityKind.EMAIL, email, counts)

            await _claim_identity(
                session,
                person.id,
                IdentityKind.GITHUB_LOGIN,
                colleague.github_login,
                counts,
            )

        await session.commit()

    return people


async def _claim_identity(
    session: AsyncSession,
    person_id: uuid.UUID,
    kind: IdentityKind,
    value: str,
    counts: Counts,
) -> None:
    """Add one `Identity` unless the (tenant, kind, value) claim already exists."""
    existing = await session.scalar(
        select(Identity.id).where(
            Identity.tenant_id == TENANT_ID,
            Identity.kind == kind,
            Identity.value == value,
        )
    )
    if existing is not None:
        counts.add("identities", created=False)
        return

    session.add(Identity(tenant_id=TENANT_ID, person_id=person_id, kind=kind, value=value))
    counts.add("identities", created=True)


async def _seed_project_members(
    people: dict[str, uuid.UUID],
    owner_id: uuid.UUID,
    counts: Counts,
) -> None:
    """Attach people to the four existing projects."""
    async with tenant_session(TENANT_ID) as session:
        projects = {
            project.name: project.id
            for project in await session.scalars(
                select(Project).where(Project.tenant_id == TENANT_ID)
            )
        }

        for assignment in ASSIGNMENTS:
            project_id = projects.get(assignment.project_name)
            if project_id is None:
                print(f"  ! no project named {assignment.project_name!r}; skipped")
                counts.add("project_members", created=False)
                continue

            person_id = people[assignment.display_name]
            existing = await session.scalar(
                select(ProjectMember.id).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.person_id == person_id,
                    ProjectMember.removed_at.is_(None),
                )
            )
            if existing is not None:
                counts.add("project_members", created=False)
                continue

            session.add(
                ProjectMember(
                    tenant_id=TENANT_ID,
                    project_id=project_id,
                    person_id=person_id,
                    project_role=assignment.project_role,
                    added_by_user_id=owner_id,
                )
            )
            counts.add("project_members", created=True)

        await session.commit()


async def _seed_facts(people: dict[str, uuid.UUID], counts: Counts) -> None:
    """Write the facts, their citations and their mentions.

    Guarded on the statement text within the tenant: a statement is the
    natural key here, and re-running must not double every card in the feed.
    """
    now = datetime.now(UTC)

    async with tenant_session(TENANT_ID) as session:
        for item in STATEMENTS:
            existing = await session.scalar(
                select(Fact.id).where(
                    Fact.tenant_id == TENANT_ID,
                    Fact.statement == item.statement,
                )
            )
            if existing is not None:
                counts.add("facts", created=False)
                continue

            occurred = (now - timedelta(days=item.days_ago)).replace(
                hour=item.hour, minute=0, second=0, microsecond=0
            )
            fact = Fact(
                tenant_id=TENANT_ID,
                kind=item.kind,
                statement=item.statement,
                certainty=item.certainty,
                occurred_at=occurred,
                valid_from=occurred,
            )
            session.add(fact)
            await session.flush()

            session.add(
                FactSource(
                    tenant_id=TENANT_ID,
                    fact_id=fact.id,
                    source=item.citation.source,
                    evidence_id=item.citation.evidence_id,
                    url=item.citation.url,
                    project=item.citation.project,
                )
            )
            for name in item.people:
                session.add(
                    FactPerson(
                        tenant_id=TENANT_ID,
                        fact_id=fact.id,
                        person_id=people[name],
                        mention=name,
                    )
                )
            counts.add("facts", created=True)

        await session.commit()


def _report(counts: Counts) -> None:
    # ASCII only: this runs in a Windows console under cp1252, where an em dash
    # is a UnicodeEncodeError rather than a character.
    print("Demo team seed for Acme Corp:")
    for label in ("users", "memberships", "people", "identities", "project_members", "facts"):
        created = counts.total(label, created=True)
        skipped = counts.total(label, created=False)
        print(f"  {label:<16} created {created:>3}   already present {skipped:>3}")

    if not any(counts.created.values()):
        print("  Nothing new - the demo data is already present.")
    else:
        print(f"  New accounts sign in with the password: {SEED_PASSWORD}")


async def seed_demo_team() -> None:
    """Populate the Acme workspace with a realistic team. Idempotent."""
    counts = Counts()
    owner_id = await _seed_accounts(counts)
    people = await _seed_people(counts)
    await _seed_project_members(people, owner_id, counts)
    await _seed_facts(people, counts)
    _report(counts)


async def main() -> None:
    try:
        await seed_demo_team()
    finally:
        await dispose_engines()


if __name__ == "__main__":
    asyncio.run(main())
