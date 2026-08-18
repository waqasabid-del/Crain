"""Development seed data.

Two tenants, because one proves nothing about isolation: the Step 4 tests assert
that Acme's data is unreachable while operating as Globex, which needs a second
tenant with overlapping-looking data. One user belongs to both with different
roles — the contractor case, where a permission check that resolves role per user
instead of per tenant breaks.

**Sign-in works.** Every seeded account has a password and an address the login
endpoint accepts. Addresses use `example.com` rather than `.test`, which
`EmailStr` refuses as a special-use name — accounts seeded on it could be
created directly and never signed in to.

**Activity is produced by the real pipeline.** The seed writes webhook deliveries
and runs the production understanding handler over them, so facts, embeddings and
graph edges come from the code that runs in production rather than from
hand-written rows. With ``CAIRN_MODEL_BACKEND=scripted`` the model is
deterministic; without it the pipeline correctly extracts nothing and the seed
says so.

Synthetic data only. Production data never reaches a local environment
(md/17 §9.1).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from cairn_api.auth.tokens import hash_password
from cairn_api.db.auth_models import PasswordCredential
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.github_models import GitHubInstallation, WebhookDelivery
from cairn_api.db.identity_models import Identity, IdentityKind, Person
from cairn_api.db.models import Membership, Region, Tenant, TenantRole, User, WorkRole
from cairn_api.db.session import dispose_engines, platform_session
from cairn_api.db.tenancy import tenant_session
from cairn_api.domain import Certainty
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.pipeline import store
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from cairn_api.pipeline.jobs import UNDERSTAND_JOB, build_providers, make_handler
from cairn_api.pipeline.mentions import ProviderActor

#: The password every seeded account uses. Public, and local-only by
#: construction: `config.py` refuses to start a deployed environment on the
#: development database defaults these accounts live in.
SEED_PASSWORD = "correct-horse-battery"  # noqa: S105

INSTALLATION_ID = 90_210


def _push(repository: str, commits: list[tuple[str, str, str]]) -> dict[str, Any]:
    """A GitHub push payload in the shape the webhook route receives."""
    now = datetime.now(UTC)
    return {
        "installation": {"id": INSTALLATION_ID},
        "repository": {"full_name": repository, "id": 42},
        "sender": {"login": "priya", "id": 7},
        "ref": "refs/heads/main",
        "commits": [
            {
                "id": sha,
                "message": message,
                "timestamp": (now - timedelta(days=day)).isoformat(),
                "url": f"https://github.com/{repository}/commit/{sha}",
                "author": {
                    "name": author,
                    "email": f"{author.split()[0].lower()}@acme.example.com",
                },
            }
            for day, (sha, message, author) in enumerate(commits)
        ],
    }


#: Activity a small team would actually produce in a week, across two
#: repositories and five kinds of work.
DELIVERIES: list[dict[str, Any]] = [
    _push(
        "acme-inc/payments",
        [
            ("a1b2c3d4e5f6", "Add rate limiting to the public API", "Priya Nair"),
            ("b2c3d4e5f6a1", "Fix double-charge on retried webhooks", "Priya Nair"),
        ],
    ),
    _push(
        "acme-inc/gateway",
        [
            ("c3d4e5f6a1b2", "Move throttling to the gateway", "Ali Rahman"),
            ("d4e5f6a1b2c3", "Document the new limits in the runbook", "Sara Bennett"),
        ],
    ),
]


#: The Slack account the seeded workspace leaves unconnected.
#:
#: Public by construction, like `SEED_PASSWORD`: it identifies nobody, it exists
#: only in the development database, and the browser test needs a value it can
#: type into the confirm field.
SEEDED_SLACK_ACTOR: str = ProviderActor(
    provider=ConnectorProvider.SLACK, account_id="U0SEEDALI"
).mention


def _attributed_facts() -> list[Fact]:
    """Statements about named people, for the screens that are about a person.

    Written here rather than extracted, because the scripted model produces
    facts with no mentions and My Week is a screen about attribution. These go
    through `store.apply` and `attach_people` — the production storage and
    identity-resolution path — so what is bypassed is the model and nothing
    else.
    """
    now = datetime.now(UTC)
    return [
        # **One deliberately unresolved contributor.** A Slack account nobody has
        # connected, so the fact it produced carries recorded provenance and no
        # owner — which is the ordinary state of a workspace whose members have
        # not linked their accounts yet, and the state the Connected identities
        # screen exists to resolve. `store._person_row` converts this encoding
        # into the structured columns; the sentinel never reaches the database.
        Fact(
            kind=FactKind.DELIVERY,
            statement="Someone rewrote the retry logic for the webhook consumer.",
            sources=[
                SourceRef(
                    source="slack",
                    evidence_id="slack:message:9915",
                    quote="pushed the retry rewrite, should stop the duplicate deliveries",
                    project=None,
                )
            ],
            people=[SEEDED_SLACK_ACTOR],
            certainty=Certainty.OBSERVED,
            occurred_at=now - timedelta(days=2),
        ),
        Fact(
            kind=FactKind.DELIVERY,
            statement="Priya shipped rate limiting to the public API.",
            sources=[
                SourceRef(
                    source="github",
                    evidence_id="github:pull_request:acme-inc/payments#482",
                    url="https://github.com/acme-inc/payments/pull/482",
                    project="acme-inc/payments",
                )
            ],
            certainty=Certainty.VERIFIED,
            people=["@priya"],
            occurred_at=now - timedelta(days=1),
        ),
        Fact(
            kind=FactKind.BLOCKER,
            statement="The staging certificate expired, blocking the payments release.",
            sources=[
                SourceRef(
                    source="slack",
                    evidence_id="slack:message:9871",
                    quote="staging is down again, cert expired",
                    project=None,
                )
            ],
            certainty=Certainty.OBSERVED,
            people=["@ali"],
            occurred_at=now - timedelta(days=2),
        ),
        Fact(
            kind=FactKind.DECISION,
            statement="The team decided to throttle write endpoints at the gateway rather than per service.",
            sources=[
                SourceRef(
                    source="meeting",
                    evidence_id="meeting:2026-08-12#0412",
                    quote="we do it once, at the gateway",
                    project=None,
                )
            ],
            certainty=Certainty.OBSERVED,
            people=["@ali", "@sara"],
            occurred_at=now - timedelta(days=3),
        ),
        Fact(
            kind=FactKind.OPEN_QUESTION,
            statement="Nobody has decided whether the new limits apply to internal callers.",
            sources=[SourceRef(source="slack", evidence_id="slack:message:9903", project=None)],
            certainty=Certainty.SUGGESTED,
            people=["@sara"],
            occurred_at=now - timedelta(days=1),
        ),
        Fact(
            kind=FactKind.IN_PROGRESS,
            statement="Sara is redesigning the onboarding flow after the review.",
            sources=[
                SourceRef(
                    source="meeting",
                    evidence_id="meeting:2026-08-13#0119",
                    quote="taking another pass at onboarding",
                    project=None,
                )
            ],
            certainty=Certainty.OBSERVED,
            people=["@sara"],
            occurred_at=now,
        ),
    ]


async def seed() -> None:
    """Populate a development database. Idempotent."""
    async with platform_session() as session:
        if await session.scalar(select(Tenant).where(Tenant.slug == "acme")) is not None:
            print("Seed data already present — nothing to do.")
            return

        acme = Tenant(name="Acme Corp", slug="acme", region=Region.US_CENTRAL1)
        globex = Tenant(name="Globex Inc", slug="globex", region=Region.US_CENTRAL1)

        verified = datetime.now(UTC)
        ali = User(
            email="ali@acme.example.com", display_name="Ali Rahman", email_verified_at=verified
        )
        sara = User(
            email="sara@acme.example.com", display_name="Sara Bennett", email_verified_at=verified
        )
        jordan = User(
            email="jordan@globex.example.com", display_name="Jordan Lee", email_verified_at=verified
        )
        contractor = User(
            email="sam@freelance.example.com", display_name="Sam Okafor", email_verified_at=verified
        )

        session.add_all([acme, globex, ali, sara, jordan, contractor])
        await session.flush()

        # Hashed once and reused: Argon2 is deliberately slow, and four hashes
        # of the same string would add seconds to every seed run.
        password_hash = hash_password(SEED_PASSWORD)
        session.add_all(
            PasswordCredential(user_id=user.id, password_hash=password_hash)
            for user in (ali, sara, jordan, contractor)
        )

        notified = datetime.now(UTC)
        session.add_all(
            [
                Membership(
                    tenant=acme,
                    user=ali,
                    role=TenantRole.OWNER,
                    work_role=WorkRole.FOUNDER,
                    notified_at=notified,
                ),
                Membership(
                    tenant=acme,
                    user=sara,
                    role=TenantRole.MEMBER,
                    work_role=WorkRole.DESIGNER,
                    notified_at=notified,
                ),
                # Deliberately not notified: attribution must refuse to link
                # this person until they have been shown what CAIRN reads
                # (md/05 §B.3.5).
                Membership(tenant=acme, user=contractor, role=TenantRole.VIEWER),
                Membership(tenant=globex, user=jordan, role=TenantRole.OWNER, notified_at=notified),
                Membership(
                    tenant=globex, user=contractor, role=TenantRole.ADMIN, notified_at=notified
                ),
            ]
        )

        session.add(
            GitHubInstallation(
                tenant_id=acme.id,
                installation_id=INSTALLATION_ID,
                account_login="acme-inc",
                account_type="Organization",
            )
        )

        delivery_ids = []
        for payload in DELIVERIES:
            delivery_id = str(uuid.uuid4())
            session.add(
                WebhookDelivery(
                    tenant_id=acme.id,
                    delivery_id=delivery_id,
                    event_type="push",
                    payload=payload,
                )
            )
            delivery_ids.append(delivery_id)

        await session.commit()
        acme_id = acme.id

    facts = await _understand(acme_id, delivery_ids)
    attributed = await _attribute(acme_id)

    # ASCII only: this runs in a Windows console under cp1252, where an em dash
    # is a UnicodeEncodeError rather than a character.
    print("Seeded 2 tenants, 4 users, 5 memberships, 1 GitHub installation.")
    print(f"  Sign in as any of these. Password: {SEED_PASSWORD}")
    print("    ali@acme.example.com       - Acme, owner, founder")
    print("    sara@acme.example.com      - Acme, member, designer")
    print("    jordan@globex.example.com  - Globex, owner")
    print("    sam@freelance.example.com  - both workspaces, not yet notified")
    print(f"  {attributed} facts about named people, for My Week and the filters.")
    if facts:
        print(f"  The pipeline understood {facts} more from 2 GitHub pushes.")
    else:
        print(
            "  No facts: the pipeline is running without a model. Set "
            "CAIRN_MODEL_BACKEND=scripted for a working local demo, or "
            "CAIRN_GCP_PROJECT_ID for the real one."
        )


async def _understand(tenant_id: uuid.UUID, delivery_ids: list[str]) -> int:
    """Run the production handler over the seeded deliveries.

    The real code path rather than hand-written fact rows: a seed that inserts
    facts directly would keep working after the pipeline broke, which is the
    opposite of what a development environment is for.
    """
    handler = make_handler(providers=build_providers())

    async with tenant_session(tenant_id) as session:
        for delivery_id in delivery_ids:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant_id,
                    payload={"delivery_id": delivery_id},
                ),
            )
        await session.commit()

    from cairn_api.db.fact_models import Fact as FactRow

    async with tenant_session(tenant_id) as session:
        rows = list(await session.scalars(select(FactRow)))
    return len(rows)


async def _attribute(tenant_id: uuid.UUID) -> int:
    """Store the authored facts and resolve their mentions to people."""
    # The address is what ties a contributor to an account, so seeded people who
    # correspond to a seeded account carry one. Without it the seeded workspace
    # demonstrates a product where nobody owns their own record: My Week is
    # empty and every correction is refused, because both resolve the caller
    # through `Person.user_id`. Priya has no account on purpose — a workspace
    # where every contributor has signed up is not the normal case.
    people = {
        "Priya Nair": ("priya", None),
        "Ali Rahman": ("ali", "ali@acme.example.com"),
        "Sara Bennett": ("sara", "sara@acme.example.com"),
    }

    async with tenant_session(tenant_id) as session:
        for display_name, (login, email) in people.items():
            person = Person(tenant_id=tenant_id, display_name=display_name)
            session.add(person)
            await session.flush()
            session.add(
                Identity(
                    tenant_id=tenant_id,
                    person_id=person.id,
                    kind=IdentityKind.GITHUB_LOGIN,
                    value=login,
                )
            )

            if email is None:
                continue

            session.add(
                Identity(
                    tenant_id=tenant_id,
                    person_id=person.id,
                    kind=IdentityKind.EMAIL,
                    value=email,
                )
            )
            person.user_id = await session.scalar(select(User.id).where(User.email == email))

        facts = _attributed_facts()
        await store.apply(session, tenant_id=tenant_id, incoming=facts)
        await store.attach_people_bulk(
            session, tenant_id=tenant_id, fact_ids=[fact.id for fact in facts]
        )
        await session.commit()
        return len(facts)


async def main() -> None:
    try:
        await seed()
    finally:
        await dispose_engines()


if __name__ == "__main__":
    asyncio.run(main())
