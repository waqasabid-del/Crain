"""Attribution correctness — the quality moat.

Step 12's exit criterion, three claims:

1. *A squash merge with co-authors credits everyone.*
2. *Dependabot is excluded from human attribution.*
3. *One person's three identities resolve to one record.*

This is where most GitHub integrations quietly fail. If the system misattributes
work, every downstream summary and document inherits the error — and a founder
who catches one wrong attribution stops trusting the entire product. The failures
tested here are not crashes: they are plausible, silent, and noticed first by the
person whose work was erased.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.db.identity_models import (
    Identity,
    IdentityKind,
    IdentityStatus,
    Person,
    PersonKind,
)
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import tenant_session
from cairn_api.github.attribution import attribute
from cairn_api.github.bots import is_ai_agent, is_bot, is_bot_login, partition
from cairn_api.github.trailers import (
    Contributor,
    contributors_of,
    normalise_email,
    parse_coauthors,
)
from cairn_api.identity.resolution import confirm, merge, reject, resolve
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------
# 1. Squash-merge attribution
# --------------------------------------------------------------------------


class TestCoauthorParsing:
    def test_a_squash_merge_credits_every_participant(self) -> None:
        """The exit criterion's first claim.

        Reading only the author field is the naive implementation. It credits
        whoever opened the pull request and erases the pair, the colleague who
        pushed a fix, the whole mob-programming afternoon.
        """
        commit = {
            "author": {"name": "Priya Shah", "email": "priya@acme.com", "username": "priyas"},
            "message": (
                "Add rate limiting (#128)\n"
                "\n"
                "Shared token bucket in Postgres.\n"
                "\n"
                "Co-authored-by: Tom Reilly <tom@acme.com>\n"
                "Co-authored-by: Ana Gómez <ana@acme.com>\n"
            ),
        }

        credited = contributors_of(commit)

        assert [c.email for c in credited] == [
            "priya@acme.com",
            "tom@acme.com",
            "ana@acme.com",
        ]

    def test_the_author_is_credited_not_the_committer(self) -> None:
        # On a rebase, a squash or an applied patch the committer is whoever ran
        # the command. Crediting them hands one person the whole team's work.
        commit = {
            "author": {"name": "Tom", "email": "tom@acme.com"},
            "committer": {"name": "Priya", "email": "priya@acme.com"},
            "message": "Fix the thing",
        }

        credited = contributors_of(commit)

        assert [c.email for c in credited] == ["tom@acme.com"]

    @pytest.mark.parametrize(
        "trailer",
        [
            "Co-authored-by: Tom <tom@acme.com>",
            "Co-Authored-By: Tom <tom@acme.com>",
            "co-authored-by: Tom <tom@acme.com>",
            "Co-authored-by:Tom <tom@acme.com>",
            "  Co-authored-by:   Tom   <tom@acme.com>  ",
        ],
    )
    def test_real_world_capitalisation_and_spacing_are_accepted(self, trailer: str) -> None:
        # The GitHub UI writes `Co-Authored-By`, the docs show `Co-authored-by`,
        # and people type both. A parser that accepts only one silently drops
        # half of all real co-authorship.
        assert [c.email for c in parse_coauthors(f"Subject\n\n{trailer}\n")] == ["tom@acme.com"]

    def test_a_repeated_trailer_credits_once(self) -> None:
        # A rebase can duplicate trailers. Crediting twice inflates one person's
        # apparent contribution, which is a quiet way to make a record wrong.
        message = (
            "Subject\n\nCo-authored-by: Tom <tom@acme.com>\nCo-authored-by: Tom <TOM@acme.com>\n"
        )

        assert len(parse_coauthors(message)) == 1

    def test_a_trailer_quoted_mid_line_is_not_attribution(self) -> None:
        # A commit explaining how to use trailers, or a review comment pasted
        # into a message, must not credit the example address.
        message = "Docs: explain that Co-authored-by: Someone <nobody@example.com> works"

        assert parse_coauthors(message) == []

    def test_a_malformed_address_is_discarded_not_guessed(self) -> None:
        # A wrong attribution is worse than a missing one: the person it credits
        # notices, and so does the person it erased.
        message = (
            "Subject\n\n"
            "Co-authored-by: Broken <not-an-email>\n"
            "Co-authored-by: Fine <fine@acme.com>\n"
        )

        assert [c.email for c in parse_coauthors(message)] == ["fine@acme.com"]

    def test_a_github_login_is_recovered_from_a_noreply_address(self) -> None:
        # A much stronger identity signal than the address: it is the same value
        # the API returns for the account, so it links commits to a GitHub user.
        message = "Subject\n\nCo-authored-by: Ana <12345+anagomez@users.noreply.github.com>\n"

        [contributor] = parse_coauthors(message)

        assert contributor.login == "anagomez"
        assert contributor.is_noreply is True

    def test_a_commit_with_no_message_or_author_yields_nothing(self) -> None:
        # Payload shapes change. A KeyError inside an ingestion worker
        # dead-letters every delivery of that event type.
        assert contributors_of({}) == []

    @pytest.mark.parametrize(
        "raw", ["", "   ", "no-at-sign", "@nolocal.com", "local@nodot", "a@" + "x" * 300]
    )
    def test_unusable_addresses_are_rejected(self, raw: str) -> None:
        assert normalise_email(raw) is None


# --------------------------------------------------------------------------
# 2. Bot filtering
# --------------------------------------------------------------------------


class TestBotFiltering:
    def test_dependabot_is_excluded_from_human_attribution(self) -> None:
        """The exit criterion's second claim.

        Automation routinely out-commits every human on a team, so counting it
        does not merely add noise — it makes the humans look idle.
        """
        contributors = [
            Contributor(email="priya@acme.com", login="priyas"),
            Contributor(
                email="49699333+dependabot[bot]@users.noreply.github.com", login="dependabot[bot]"
            ),
        ]

        people, bots = partition(contributors)

        assert [c.login for c in people] == ["priyas"]
        assert [c.login for c in bots] == ["dependabot[bot]"]

    def test_a_bot_co_author_trailer_is_filtered(self) -> None:
        """The interaction that makes naive co-author parsing worse than none.

        GitHub's squash behaviour adds `Co-authored-by` trailers carrying the
        *bot's* identity, so co-author parsing without bot filtering does not
        just fail to exclude bots — it actively imports them into human
        attribution.
        """
        commit = {
            "author": {"name": "Priya", "email": "priya@acme.com", "username": "priyas"},
            "message": (
                "Bump lodash (#77)\n\n"
                "Co-authored-by: dependabot[bot] "
                "<49699333+dependabot[bot]@users.noreply.github.com>\n"
            ),
        }

        people, bots = partition(contributors_of(commit))

        assert [c.email for c in people] == ["priya@acme.com"]
        assert len(bots) == 1

    @pytest.mark.parametrize(
        "login",
        ["dependabot[bot]", "renovate[bot]", "github-actions[bot]", "some-custom[bot]"],
    )
    def test_the_bot_suffix_is_authoritative(self, login: str) -> None:
        # Every GitHub App actor commits under a `[bot]` login, which makes this
        # the one signal that is both reliable and universal.
        assert is_bot_login(login) is True

    @pytest.mark.parametrize("login", ["robert", "abbott", "botany-team", "elliot", "talbot"])
    def test_a_person_whose_handle_contains_bot_is_not_automation(self, login: str) -> None:
        # A "contains the word bot" heuristic silently erases real contributors.
        # Erasing a person is a worse failure than counting a bot.
        assert is_bot_login(login) is False

    def test_a_workspace_can_register_its_own_automation(self) -> None:
        # Every team has automation nobody else would recognise — a company
        # release account, an internal deploy user.
        release = Contributor(email="release@acme.com", login="acme-release")

        assert is_bot(release) is False
        assert is_bot(release, custom=["acme-release"]) is True

    def test_an_agent_is_distinguished_from_a_plain_bot(self) -> None:
        # A narrower question: Dependabot is a bot and not an agent. Used to
        # mark work as agent-assisted — context on the work, never a judgement
        # about a person.
        agent = Contributor(email="copilot@users.noreply.github.com", login="github-copilot[bot]")
        dependabot = Contributor(email="x@acme.com", login="dependabot[bot]")

        assert is_ai_agent(agent) is True
        assert is_ai_agent(dependabot) is False

    def test_there_is_no_heuristic_authorship_scoring(self) -> None:
        """The restraint is a product commitment, not an omission.

        CAIRN does not guess whether a human wrote a diff. Such a capability
        would be wrong often enough to destroy trust the first time it accused
        someone incorrectly, and it would make the product the surveillance
        instrument md/05 forbids. This test fails if someone adds one.
        """
        from cairn_api.github import bots

        suspicious = [
            name
            for name in dir(bots)
            if any(word in name.lower() for word in ("score", "probability", "likelihood"))
        ]

        assert suspicious == []


# --------------------------------------------------------------------------
# 3. Identity resolution
# --------------------------------------------------------------------------


@pytest.fixture
async def tenant_id(platform: AsyncSession) -> uuid.UUID:
    tenant = Tenant(name="Acme", slug=f"attr-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.commit()
    return tenant.id


@pytest.fixture
async def actor_id(platform: AsyncSession) -> uuid.UUID:
    """A real user to attribute confirmations to.

    `confirmed_by_user_id` is a foreign key, so an invented UUID violates it —
    correctly. "Who decided this identity is mine" must name someone real.
    """
    user = User(email=f"actor-{uuid.uuid4().hex[:10]}@example.com")
    platform.add(user)
    await platform.commit()
    return user.id


class TestIdentityResolution:
    async def test_three_identities_resolve_to_one_person(self, tenant_id: uuid.UUID) -> None:
        """The exit criterion's third claim.

        A work email, a GitHub handle, and a personal address used at weekends.
        Unresolved, this one person is three partial contributors — and the
        product reports something false about who did the work.
        """
        async with tenant_session(tenant_id) as session:
            # Monday: a commit from work, carrying both handle and address.
            work = await resolve(
                session,
                Contributor(email="priya@acme.com", name="Priya Shah", login="priyas"),
                tenant_id=tenant_id,
            )
            # Saturday: same GitHub account, personal address.
            weekend = await resolve(
                session,
                Contributor(email="priya@personal.example", login="priyas"),
                tenant_id=tenant_id,
            )
            # A co-author trailer using her noreply address.
            noreply = await resolve(
                session,
                Contributor(email="99+priyas@users.noreply.github.com", login="priyas"),
                tenant_id=tenant_id,
            )

            assert work.id == weekend.id == noreply.id

            identities = (
                await session.scalars(select(Identity).where(Identity.person_id == work.id))
            ).all()
            values = {i.value for i in identities}
            assert values == {
                "priyas",
                "priya@acme.com",
                "priya@personal.example",
                "99+priyas@users.noreply.github.com",
            }

    async def test_a_new_address_alone_creates_a_separate_person(
        self, tenant_id: uuid.UUID
    ) -> None:
        """The positive control, and the honest limit of automatic resolution.

        Without a shared handle there is nothing to link on. Two people are
        created — correctly, because the alternative is guessing. Joining them
        is `merge`, which a human performs.
        """
        async with tenant_session(tenant_id) as session:
            first = await resolve(
                session, Contributor(email="tom@acme.com", login="tomr"), tenant_id=tenant_id
            )
            second = await resolve(
                session, Contributor(email="tom@personal.example"), tenant_id=tenant_id
            )

            assert first.id != second.id

    async def test_two_people_sharing_a_name_are_not_merged(self, tenant_id: uuid.UUID) -> None:
        # Names are the worst available identity key. Matching on one is how a
        # colleague's work gets attributed to someone else — and the person who
        # notices is the one whose work was taken.
        async with tenant_session(tenant_id) as session:
            one = await resolve(
                session,
                Contributor(email="j.smith@acme.com", name="John Smith", login="jsmith1"),
                tenant_id=tenant_id,
            )
            two = await resolve(
                session,
                Contributor(email="john.smith@acme.com", name="John Smith", login="jsmith2"),
                tenant_id=tenant_id,
            )

            assert one.id != two.id

    async def test_automatic_links_are_proposed_never_confirmed(self, tenant_id: uuid.UUID) -> None:
        # The system proposes, the person confirms (md/01 §5.3). Inference does
        # not get to assert a fact about whose work this is.
        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session, Contributor(email="ana@acme.com", login="anag"), tenant_id=tenant_id
            )

            identities = (
                await session.scalars(select(Identity).where(Identity.person_id == person.id))
            ).all()

            assert {i.status for i in identities} == {IdentityStatus.PROPOSED}

    async def test_a_rejected_identity_is_not_re_proposed(
        self, tenant_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        """A correction must stick.

        Someone who says "that address is not mine" must not be asked again by
        the next commit carrying it — otherwise they correct the same mistake
        forever and eventually stop correcting it.
        """
        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session,
                Contributor(email="shared@acme.com", login="someone"),
                tenant_id=tenant_id,
            )
            identity = await session.scalar(
                select(Identity).where(
                    Identity.person_id == person.id, Identity.kind == IdentityKind.EMAIL
                )
            )
            assert identity is not None
            await reject(session, identity, rejected_by=actor_id)

        async with tenant_session(tenant_id) as session:
            # The same address arrives again on a later commit.
            again = await resolve(
                session, Contributor(email="shared@acme.com"), tenant_id=tenant_id
            )

            # A new person, not the one who rejected it — and the rejection
            # stands rather than being flipped back to proposed.
            assert again.id != person.id
            rejected = await session.scalar(
                select(Identity).where(
                    Identity.value == "shared@acme.com",
                    Identity.person_id == person.id,
                )
            )
            assert rejected is not None
            assert rejected.status is IdentityStatus.REJECTED

    async def test_confirming_records_who_decided(
        self, tenant_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        # "Who decided this identity is mine" is a question with consequences.
        # The answer should be the person themselves.
        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session, Contributor(email="tom@acme.com", login="tomr"), tenant_id=tenant_id
            )
            identity = await session.scalar(select(Identity).where(Identity.person_id == person.id))
            assert identity is not None

            await confirm(session, identity, confirmed_by=actor_id)

            assert identity.status is IdentityStatus.CONFIRMED
            assert identity.confirmed_by_user_id == actor_id
            assert identity.confirmed_at is not None

    async def test_a_display_name_is_filled_but_never_overwritten(
        self, tenant_id: uuid.UUID
    ) -> None:
        # A later commit with a different spelling must not rename someone, and
        # a person who corrected their own name must not have it reverted by the
        # next push.
        async with tenant_session(tenant_id) as session:
            # Nameless first: a commit whose author block carries no name.
            person_id = (
                await resolve(
                    session, Contributor(email="ana@acme.com", login="anag"), tenant_id=tenant_id
                )
            ).id

            async def name_now() -> str | None:
                found = await session.get(Person, person_id)
                assert found is not None
                return found.display_name

            assert await name_now() is None

            await resolve(
                session,
                Contributor(email="ana@acme.com", name="Ana Gómez", login="anag"),
                tenant_id=tenant_id,
            )
            assert await name_now() == "Ana Gómez"

            await resolve(
                session,
                Contributor(email="ana@acme.com", name="ana", login="anag"),
                tenant_id=tenant_id,
            )
            assert await name_now() == "Ana Gómez"

    async def test_a_bot_gets_a_person_record_marked_as_a_bot(self, tenant_id: uuid.UUID) -> None:
        # Retained as repository context — "dependencies were updated" belongs
        # in a project summary — while excluded from human attribution.
        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session,
                Contributor(email="x@acme.com", login="dependabot[bot]"),
                tenant_id=tenant_id,
            )

            assert person.kind is PersonKind.BOT

    async def test_merging_moves_every_identity(self, tenant_id: uuid.UUID) -> None:
        # The correction someone makes when the graph split them in two —
        # typically a personal address that never shared a commit with their
        # work identity, so no automatic rule could link them.
        async with tenant_session(tenant_id) as session:
            keep = await resolve(
                session,
                Contributor(email="tom@acme.com", name="Tom", login="tomr"),
                tenant_id=tenant_id,
            )
            absorb = await resolve(
                session, Contributor(email="tom@personal.example"), tenant_id=tenant_id
            )

            merged = await merge(session, keep=keep, absorb=absorb)

            assert merged.id == keep.id
            identities = (
                await session.scalars(select(Identity).where(Identity.person_id == keep.id))
            ).all()
            assert {i.value for i in identities} == {
                "tomr",
                "tom@acme.com",
                "tom@personal.example",
            }
            assert await session.get(Person, absorb.id) is None


class TestAPersonIsLinkedToTheirAccount:
    """The link that makes the record *theirs*.

    `me/week` and every correction endpoint resolve the caller with
    `Person.user_id == current user`. Nothing in the application ever set that
    column, so My Week was permanently empty for every real account and every
    correction returned "not your record" — md/05 §B.2.3's employee-owned record
    with no reachable path to it. A browser test caught it; no component test
    could, because each layer worked in isolation.
    """

    async def test_a_verified_address_links_the_person_to_the_account(
        self, tenant_id: uuid.UUID, platform: AsyncSession
    ) -> None:
        address = f"linked-{uuid.uuid4().hex[:10]}@example.com"
        user = User(email=address, email_verified_at=datetime.now(UTC))
        platform.add(user)
        await platform.commit()
        platform.add(Membership(tenant_id=tenant_id, user_id=user.id, role=TenantRole.MEMBER))
        await platform.commit()

        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session,
                Contributor(email=address, name="Linked Person", login="linked"),
                tenant_id=tenant_id,
            )
            await session.commit()

        assert person.user_id == user.id

    async def test_a_second_person_for_one_account_declines_the_link(
        self, tenant_id: uuid.UUID, platform: AsyncSession
    ) -> None:
        """**Found by the first real end-to-end delivery, not by a unit test.**

        `uq_people_tenant_user` arrived in Step 34 and allows one person row per
        account per workspace. This function was written before it and guards
        only against relinking *this* person — nothing checked whether the
        account was already held by another person row. A workspace that had
        ever produced a second person for the same human (a personal address on
        one commit, a work address on the next) then failed here with a unique
        violation on every delivery that named them.

        The failure mode is the expensive part. It raises inside the delivery
        job, so the job retries, fails identically five times, and dead-letters:
        one person's presence in a commit stops that workspace ingesting
        anything at all, and the symptom is a queue depth rather than anything
        naming identity.

        Declining is the honest outcome, not merging. Re-pointing an account at
        a different person row moves ownership of a record between people, which
        is the merge decision this module refuses to make by inference.
        """
        address = f"dual-{uuid.uuid4().hex[:10]}@example.com"
        user = User(email=address, email_verified_at=datetime.now(UTC))
        platform.add(user)
        await platform.commit()
        platform.add(Membership(tenant_id=tenant_id, user_id=user.id, role=TenantRole.MEMBER))
        await platform.commit()

        async with tenant_session(tenant_id) as session:
            # A person already holding the account, with no identity row for the
            # address — which is how `db/seed.py` writes one, and how any path
            # that links an account before seeing a commit leaves one.
            held = Person(tenant_id=tenant_id, display_name="Held Account", user_id=user.id)
            session.add(held)
            await session.commit()
            held_id = held.id

            # Now the same address arrives on a commit. No identity claims it,
            # so resolution creates a second person and tries to link it to the
            # account the first one already holds.
            second = await resolve(
                session,
                Contributor(email=address, name="Held Account", login="held"),
                tenant_id=tenant_id,
            )
            second_id = second.id
            linked = second.user_id
            # The commit is the assertion: before the guard this raised
            # IntegrityError here and the delivery job dead-lettered.
            await session.commit()

        assert second_id != held_id
        assert linked is None, "the account is already held; a second link violates the index"

    async def test_an_unverified_address_does_not_link(
        self, tenant_id: uuid.UUID, platform: AsyncSession
    ) -> None:
        """A commit's author email is whatever the author's git config says.

        Linking on an unverified address would let anyone who can push a commit
        claim a colleague's record — including the right to rewrite it.
        """
        address = f"unverified-{uuid.uuid4().hex[:10]}@example.com"
        user = User(email=address)
        platform.add(user)
        await platform.commit()
        platform.add(Membership(tenant_id=tenant_id, user_id=user.id, role=TenantRole.MEMBER))
        await platform.commit()

        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session,
                Contributor(email=address, name="Unverified", login="unverified"),
                tenant_id=tenant_id,
            )
            await session.commit()

        assert person.user_id is None

    async def test_an_existing_link_is_never_repointed(
        self, tenant_id: uuid.UUID, platform: AsyncSession
    ) -> None:
        """Moving ownership of a record between people is a merge decision, not
        something a later commit gets to infer."""
        first = f"first-{uuid.uuid4().hex[:10]}@example.com"
        second = f"second-{uuid.uuid4().hex[:10]}@example.com"
        users = [
            User(email=first, email_verified_at=datetime.now(UTC)),
            User(email=second, email_verified_at=datetime.now(UTC)),
        ]
        platform.add_all(users)
        await platform.commit()
        for user in users:
            platform.add(Membership(tenant_id=tenant_id, user_id=user.id, role=TenantRole.MEMBER))
        await platform.commit()

        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session,
                Contributor(email=first, login="shared"),
                tenant_id=tenant_id,
            )
            await resolve(
                session,
                Contributor(email=second, login="shared"),
                tenant_id=tenant_id,
            )
            await session.commit()

        assert person.user_id == users[0].id

    async def test_a_contributor_with_no_account_is_left_unlinked(
        self, tenant_id: uuid.UUID
    ) -> None:
        """The normal case. Most contributors to a workspace never sign up, and
        an unlinked person is a complete record of their work — just not one they
        can log in and correct."""
        async with tenant_session(tenant_id) as session:
            person = await resolve(
                session,
                Contributor(email=f"stranger-{uuid.uuid4().hex[:8]}@example.com", login="stranger"),
                tenant_id=tenant_id,
            )
            await session.commit()

        assert person.user_id is None


class TestIdentityIsolation:
    async def test_the_same_contractor_is_a_separate_record_per_workspace(
        self, platform: AsyncSession
    ) -> None:
        """Identity is per workspace, not global.

        The same contractor may legitimately appear in two customers'
        workspaces. They are different records with different corrections, and
        one customer's merge must not alter the other's view.
        """
        a = Tenant(name="A", slug=f"a-{uuid.uuid4().hex[:8]}")
        b = Tenant(name="B", slug=f"b-{uuid.uuid4().hex[:8]}")
        platform.add_all([a, b])
        await platform.commit()

        contractor = Contributor(email="dev@contractor.example", login="devfreelance")

        async with tenant_session(a.id) as session:
            in_a = await resolve(session, contractor, tenant_id=a.id)
        async with tenant_session(b.id) as session:
            in_b = await resolve(session, contractor, tenant_id=b.id)

        assert in_a.id != in_b.id

    async def test_resolution_cannot_see_another_workspaces_people(
        self, platform: AsyncSession
    ) -> None:
        # Row-level security, asserted on the attribution path. A positive
        # control first: the record genuinely exists for its own workspace.
        a = Tenant(name="A", slug=f"iso-a-{uuid.uuid4().hex[:8]}")
        b = Tenant(name="B", slug=f"iso-b-{uuid.uuid4().hex[:8]}")
        platform.add_all([a, b])
        await platform.commit()

        async with tenant_session(a.id) as session:
            person = await resolve(
                session,
                Contributor(email="secret@a-corp.example", login="ateam"),
                tenant_id=a.id,
            )
            person_id = person.id

        async with tenant_session(a.id) as session:
            assert await session.get(Person, person_id) is not None

        async with tenant_session(b.id) as session:
            assert await session.get(Person, person_id) is None


# --------------------------------------------------------------------------
# End to end, through the real payload shape
# --------------------------------------------------------------------------

SQUASH_MESSAGE = (
    "Add rate limiting (#128)\n"
    "\n"
    "Shared token bucket in Postgres.\n"
    "\n"
    "Co-authored-by: Tom Reilly <tom@acme.com>\n"
    "Co-authored-by: dependabot[bot] "
    "<49699333+dependabot[bot]@users.noreply.github.com>\n"
)


class TestAttributionEndToEnd:
    async def test_a_squash_push_populates_the_identity_graph(self, tenant_id: uuid.UUID) -> None:
        """All three claims at once, on a realistic payload.

        A squash merge authored by one person, co-authored by another, with
        Dependabot's trailer attached the way GitHub attaches it — plus a second
        commit from the same person under a different address.
        """
        payload: dict[str, object] = {
            "commits": [
                {
                    "author": {
                        "name": "Priya Shah",
                        "email": "priya@acme.com",
                        "username": "priyas",
                    },
                    "message": SQUASH_MESSAGE,
                },
                {
                    # Same person, different address, same GitHub account.
                    "author": {
                        "name": "Priya",
                        "email": "priya@personal.example",
                        "username": "priyas",
                    },
                    "message": "Fix a typo",
                },
            ]
        }

        async with tenant_session(tenant_id) as session:
            result = await attribute(session, payload, tenant_id=tenant_id)

            # Two humans: Priya (credited twice, one person) and Tom.
            assert len(result.people) == 2
            # Dependabot reached the graph as context, not as a contributor.
            assert len(result.bots) == 1
            assert result.bots[0].kind is PersonKind.BOT
            assert result.commits_seen == 2
            assert result.unparseable == 0

            assert {p.display_name for p in result.people} == {"Priya Shah", "Tom Reilly"}

            # Her two addresses and her handle are one person.
            priya = next(p for p in result.people if p.display_name == "Priya Shah")
            identities = (
                await session.scalars(select(Identity).where(Identity.person_id == priya.id))
            ).all()
            assert {i.value for i in identities} == {
                "priyas",
                "priya@acme.com",
                "priya@personal.example",
            }

    async def test_reprocessing_the_same_push_does_not_duplicate_people(
        self, tenant_id: uuid.UUID
    ) -> None:
        # At-least-once delivery means this happens. Duplicating people on a
        # redelivery would split one person's record in a way nobody would think
        # to look for.
        payload: dict[str, object] = {
            "commits": [
                {
                    "author": {"name": "Ana", "email": "ana@acme.com", "username": "anag"},
                    "message": "Ship it",
                }
            ]
        }

        async with tenant_session(tenant_id) as session:
            first = await attribute(session, payload, tenant_id=tenant_id)
        async with tenant_session(tenant_id) as session:
            second = await attribute(session, payload, tenant_id=tenant_id)
            everyone = (await session.scalars(select(Person))).all()

        assert first.people[0].id == second.people[0].id
        assert len(everyone) == 1

    async def test_a_payload_with_no_commits_is_not_an_error(self, tenant_id: uuid.UUID) -> None:
        # Most events carry no commits — an opened issue, a review comment.
        # Treating that as a failure would dead-letter most of the stream.
        async with tenant_session(tenant_id) as session:
            result = await attribute(session, {"action": "opened"}, tenant_id=tenant_id)

        assert result.commits_seen == 0
        assert result.people == []

    async def test_an_unparseable_commit_is_counted_not_silently_dropped(
        self, tenant_id: uuid.UUID
    ) -> None:
        # A sudden rise means GitHub changed a payload shape. Without the
        # counter the symptom is people quietly vanishing from their own records.
        payload: dict[str, object] = {
            "commits": [{"author": {"email": "not-an-address"}, "message": "x"}]
        }

        async with tenant_session(tenant_id) as session:
            result = await attribute(session, payload, tenant_id=tenant_id)

        assert result.unparseable == 1
        assert result.people == []
