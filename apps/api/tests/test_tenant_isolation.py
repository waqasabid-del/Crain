"""Tenant isolation tests.

The most important tests in the codebase. Everything else protects against a
bug; these protect against the failure that would end the product.

They are written as **attacks**. Each one tries to reach another tenant's data
the way a real mistake would — a forgotten filter, a raw query, a leaked
session — and asserts the attempt returns nothing. A test that merely confirms
the happy path proves only that the feature works when used correctly, which is
never the case that leaks data.

Note these run against real PostgreSQL. Row-level security does not exist in
SQLite, so a suite that used it would pass while proving nothing about the
mechanism carrying the most risk.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import (
    MissingTenantContextError,
    get_tenant_context,
    set_tenant_context,
    tenant_session,
)
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


@pytest.fixture
async def two_tenants(platform: AsyncSession) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two tenants with deliberately similar data.

    Similar rather than distinct on purpose: if Acme and Globex both have a user
    called "Ali" with the same role, a leak shows up as a wrong *count* rather
    than requiring someone to notice an unfamiliar name.

    Built through the *platform* session because that is genuinely how signup
    works — creating a workspace precedes any tenant context, so it cannot be
    done from a scoped session. The data is committed so that the separate,
    RLS-subject application session can see it.
    """
    # Unique per run. Fixed slugs collide with any other module that also
    # committed an "acme", and the symptom is a unique-violation at the setup of
    # whichever test happens to run second.
    suffix = uuid.uuid4().hex[:8]
    acme = Tenant(name="Acme", slug=f"acme-{suffix}")
    globex = Tenant(name="Globex", slug=f"globex-{suffix}")
    platform.add_all([acme, globex])
    await platform.flush()

    acme_user = User(email=f"ali-{suffix}@acme.test", display_name="Ali")
    globex_user = User(email=f"ali-{suffix}@globex.test", display_name="Ali")
    platform.add_all([acme_user, globex_user])
    await platform.flush()

    platform.add_all(
        [
            Membership(tenant_id=acme.id, user_id=acme_user.id, role=TenantRole.OWNER),
            Membership(tenant_id=globex.id, user_id=globex_user.id, role=TenantRole.OWNER),
        ]
    )
    await platform.commit()

    yield acme, globex

    # The application session runs on its own connection, so this data is not
    # covered by that session's rollback and must be removed explicitly.
    ids = [acme.id, globex.id]
    user_ids = [acme_user.id, globex_user.id]
    # Scoped to what this fixture created.
    #
    # It used to be `DELETE FROM tenants` with no predicate, which removed every
    # workspace in the database — including ones another module had committed
    # and was still using. That is invisible while one file runs at a time and
    # produces "duplicate key" errors at *setup* of an unrelated test as soon as
    # two files share a session, which is the hardest kind of failure to place.
    await platform.execute(delete(Membership).where(Membership.tenant_id.in_(ids)))
    await platform.execute(delete(User).where(User.id.in_(user_ids)))
    await platform.execute(delete(Tenant).where(Tenant.id.in_(ids)))
    await platform.commit()


#: Tables that carry a `tenant_id` and are deliberately not tenant-scoped.
#:
#: `internal_audit_log` records what CAIRN staff did, across every customer. A
#: policy scoping it to one tenant would make "which workspaces did this person
#: open" unanswerable, which is the question the log exists to answer. Its
#: protection is the grant set instead: INSERT and SELECT, no UPDATE, no DELETE.
#:
#: `scheduled_jobs` is the queue. A worker claims work *before* it can know whose
#: work it is — the tenant is what the claimed envelope carries — so a policy
#: keyed on the current tenant would hide the queue from the only process whose
#: purpose is draining it. Isolation moves to where the job runs: `run_job` opens
#: a tenant-scoped session from the envelope, and every read the handler performs
#: is under RLS as normal.
NOT_TENANT_SCOPED = frozenset({"internal_audit_log", "scheduled_jobs"})


class TestRowLevelSecurity:
    """Database-level isolation. The safety net."""

    async def test_scoped_session_sees_only_its_own_memberships(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        count = await session.scalar(select(func.count()).select_from(Membership))

        assert count == 1, "A scoped session must not see another tenant's memberships"

    async def test_scoped_session_sees_only_its_own_tenant_row(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        visible = (await session.scalars(select(Tenant.id))).all()

        assert list(visible) == [acme.id]
        assert globex.id not in visible

    async def test_users_are_filtered_by_shared_membership(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """Without this, any context could enumerate every email on the platform."""
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        emails = set((await session.scalars(select(User.email))).all())

        # Asserted by shape rather than by literal, because the fixture's
        # addresses are now unique per run — a fixed literal here would be a
        # second place the suffix has to be kept in step, and the property under
        # test is "exactly one user, the one who shares a workspace".
        assert len(emails) == 1
        assert next(iter(emails)).endswith("@acme.test")

    async def test_unscoped_session_sees_nothing(
        self,
        session: AsyncSession,
        platform: AsyncSession,
        two_tenants: tuple[Tenant, Tenant],
    ) -> None:
        """A query with no tenant context returns no rows rather than everything.

        This is the case that matters most. A raw query, a forgotten filter, or a
        library opening its own session all arrive here. Returning zero rows is
        safe; returning every row is the failure this whole step exists to
        prevent.
        """
        acme, globex = two_tenants
        ids = [acme.id, globex.id]

        # Positive control first. Without it, this test passes when RLS works
        # AND when the fixture wrote nothing at all — and "sees no rows" is
        # exactly what a broken fixture and working isolation look like from
        # here. Proving the data exists is what makes the zero below meaningful.
        #
        # Counted over *this fixture's* rows rather than the whole table. The
        # global count was only ever correct because every fixture used to
        # `DELETE FROM tenants` with no predicate — and that blanket delete was
        # itself the defect, since it removed workspaces another module was
        # still using.
        assert (
            await platform.scalar(
                select(func.count()).select_from(Membership).where(Membership.tenant_id.in_(ids))
            )
            == 2
        )
        assert (
            await platform.scalar(
                select(func.count()).select_from(Tenant).where(Tenant.id.in_(ids))
            )
            == 2
        )

        assert await session.scalar(select(func.count()).select_from(Membership)) == 0
        assert await session.scalar(select(func.count()).select_from(Tenant)) == 0
        assert await session.scalar(select(func.count()).select_from(User)) == 0

    async def test_context_does_not_leak_between_transactions(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """``SET LOCAL`` must not survive its transaction.

        If context were set with plain ``SET``, a pooled connection would carry
        one tenant's scope into the next request that borrowed it — a
        cross-tenant leak caused by a single missing keyword, visible only under
        concurrency.
        """
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)
        assert await get_tenant_context(session) == acme.id

        await session.rollback()

        assert await get_tenant_context(session) is None, (
            "Tenant context survived its transaction — check SET LOCAL is used"
        )

    async def test_cannot_write_into_another_tenant(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """Membership creation is refused outright from a scoped session.

        This originally asserted an RLS rejection. Membership INSERT is now
        revoked from the application role entirely — creating a membership is a
        platform operation, and allowing it from a scoped session enabled a
        confirmed cross-tenant leak (see the grafting test below).

        The assertion changed because the protection got *stronger*: permission
        denial happens before policies are even consulted.
        """
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("INSERT INTO memberships (tenant_id, user_id) VALUES (:t, :u)"),
                {"t": str(globex.id), "u": str(uuid.uuid4())},
            )

    async def test_cannot_move_a_row_across_the_boundary(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """An UPDATE must not reassign a row to another tenant."""
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text("UPDATE memberships SET tenant_id = :other"),
                {"other": str(globex.id)},
            )

    async def test_raw_sql_is_also_filtered(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """RLS applies below the ORM.

        The ORM can be bypassed — by a raw query, a reporting script, or a
        library. Isolation that lived only in application code would not survive
        any of those.
        """
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        count = await session.scalar(text("SELECT count(*) FROM memberships"))

        assert count == 1

    async def test_every_tenant_scoped_table_has_forced_rls(self, platform: AsyncSession) -> None:
        """Derived, not hardcoded — so a future table cannot slip through.

        An earlier version listed three table names. It therefore could not see
        ``invitations``, which was added later carrying a ``tenant_id`` and no
        policy for a while. Any table with a ``tenant_id`` column holds
        tenant-scoped data by definition, so the set is discovered rather than
        maintained by hand.

        ``FORCE`` matters as much as ``ENABLE``: without it, policies do not
        apply to the table's owner while still appearing correct in psql output.
        """
        rows = (
            await platform.execute(
                text("""
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN information_schema.columns col
                      ON col.table_name = c.relname AND col.table_schema = n.nspname
                    WHERE n.nspname = 'public'
                      AND c.relkind = 'r'
                      AND col.column_name = 'tenant_id'
                """)
            )
        ).all()

        assert rows, "Found no tenant-scoped tables — the discovery query is wrong"
        for name, enabled, forced in rows:
            if name in NOT_TENANT_SCOPED:
                # Named rather than skipped by a pattern: a table opting out of
                # row-level security is a decision somebody has to make, and a
                # rule like "tables starting with internal_" would let the next
                # one opt out by being named carefully.
                assert not enabled, (
                    f"{name} is listed as deliberately unscoped but has RLS enabled. "
                    "One of the two is wrong."
                )
                continue
            assert enabled, f"RLS not enabled on tenant-scoped table {name}"
            assert forced, f"RLS not FORCED on {name} — policies are inert for the owner"

    async def test_application_role_grants_are_an_explicit_allow_list(
        self, platform: AsyncSession
    ) -> None:
        """Every grant is deliberate, and new tables start with none.

        The default-privileges rule once granted the application role full DML
        on every table created afterwards. That made "readable by every tenant"
        the default posture for anything new, while RLS remained opt-in — which
        is exactly how the auth tables ended up exposed, and how the migration
        state table quietly became writable.

        Pinning the expected grants means a new table, or a new privilege on an
        existing one, fails this test until someone states why it should exist.
        """
        rows = (
            await platform.execute(
                text("""
                    SELECT table_name, privilege_type
                    FROM information_schema.role_table_grants
                    WHERE grantee = 'cairn_app' AND table_schema = 'public'
                """)
            )
        ).all()

        actual: dict[str, set[str]] = {}
        for table, privilege in rows:
            actual.setdefault(table, set()).add(privilege)

        expected = {
            # Read and update its own row. Creation is a platform operation, and
            # so is deletion — a scoped session could otherwise destroy the whole
            # workspace with no permission check anywhere.
            "tenants": {"SELECT", "UPDATE"},
            # Same. Deletion is excluded because foreign keys cascade: deleting a
            # contractor shared with another workspace would take their
            # membership, sessions and credentials there with them.
            "users": {"SELECT", "UPDATE"},
            # Role changes and removals are in-tenant; creation is not, because
            # inserting a membership for an unseen user leaks that user.
            "memberships": {"SELECT", "UPDATE", "DELETE"},
            # Issued from a scoped session; accepted platform-side.
            "invitations": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            # Rate-limit token buckets. The one table here that is deliberately
            # *not* tenant-scoped and therefore not under row-level security:
            # rate limits apply to login, which runs before any tenant is known,
            # so there is nothing to scope to.
            #
            # Safe because it holds no customer data — a key is a client address
            # or an email, and the only values are a token count and a timestamp
            # — and because a caller who could read it learns only how much
            # allowance a key has left. DELETE is needed by the periodic sweep
            # that stops the table growing by one row per scanner on the
            # internet.
            "rate_limit_buckets": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            # Read-only. The webhook handler resolves installation to tenant
            # *before* any tenant context exists, so it writes platform-side.
            # Granting INSERT here would let a scoped session register an
            # installation and start receiving another organisation's activity.
            "github_installations": {"SELECT"},
            # SELECT so a worker can read the delivery it was given; UPDATE so it
            # can mark it processed. No INSERT: a scoped session that could
            # create a delivery could forge activity for its own workspace.
            "webhook_deliveries": {"SELECT", "UPDATE"},
            # Read-only, for exactly the reason `github_installations` is.
            # Every write is platform-side: the connect endpoint runs on the
            # platform connection, and the trigger that projects an
            # installation onto a connection runs inside that same statement.
            # INSERT would let a scoped session register a connection and start
            # receiving another organisation's activity; UPDATE would let it
            # rewrite `installation_id` and take over an existing one — the
            # same shape as the `memberships` INSERT that was revoked after it
            # was shown to leak. Nothing in production performs a scoped write
            # here, so any wider grant would be an unused privilege, and an
            # unused privilege is the one an injection gets to use first.
            "source_connections": {"SELECT"},
            # SELECT, INSERT, DELETE — the `source_opt_outs` set, and chosen for
            # the same reason. The presence of a row *is* the permission to read
            # a Slack channel, so there is no mutable state to UPDATE:
            # selecting inserts, deselecting deletes. Granting UPDATE would add
            # a privilege nothing uses, and the one operation it would enable is
            # rewriting `channel_id` on an existing row — turning a permission
            # somebody granted for one conversation into a permission for
            # another, with the consent columns still naming the person who
            # never agreed to it.
            #
            # Both writes run from inside tenant context: an admin acting on
            # their own workspace, where the policy's WITH CHECK stops a scoped
            # session writing another tenant's row. That is what makes INSERT
            # safe here where it is not on `source_connections` — those are
            # written platform-side, before any tenant is known.
            "slack_channel_selections": {"SELECT", "INSERT", "DELETE"},
            #
            # The Google Chat half of the same design, with the same grant set
            # and the same reasoning: the presence of a row *is* the permission
            # to read a space, so selecting inserts and deselecting deletes, and
            # there is nothing to UPDATE. The one privilege UPDATE would enable
            # is rewriting `space_name` on an existing row — turning a permission
            # somebody granted for one conversation into a permission for
            # another, with `selected_by_user_id` still naming the person who
            # never agreed to it.
            #
            # Both writes run from inside a workspace, where the policy's WITH
            # CHECK stops a scoped session writing another tenant's row. The
            # endpoint itself happens to run platform-side (it also writes
            # `google_chat_subscriptions`, below), so this grant is what a
            # tenant-scoped ingestion path needs to *read* — the INSERT and
            # DELETE are kept because they are safe here and because narrowing
            # them would make this table's posture differ from
            # `slack_channel_selections` for no reason a reader could recover.
            "google_chat_space_selections": {"SELECT", "INSERT", "DELETE"},
            # SELECT only, and deliberately narrower than the selection table.
            # A subscription row is **not** a permission — it is CAIRN's record
            # of a lease it holds at Google — so nothing a customer does from
            # inside tenant context should write one. Creation, renewal and
            # deletion all happen platform-side, from the selection endpoint and
            # from the maintenance loop, both of which already know the tenant.
            #
            # INSERT would let a scoped session invent a lease pointing at
            # another workspace's space name; UPDATE would let it flip a
            # `DELETED` row back to `ACTIVE`, which is precisely the state
            # `subscriptions.remove_subscription` writes *before* it calls
            # Google in order to block a deselected space immediately. A
            # privilege that can undo a withdrawal of consent is the one an
            # injection gets to use first.
            "google_chat_subscriptions": {"SELECT"},
            # -- Google Meet (Step 36A) -----------------------------------
            #
            # SELECT only, on both, and the same reasoning as Chat's
            # subscription table. A Meet subscription row is not a permission —
            # the permission lives in `meeting_consents`, where every
            # participant answered — it is CAIRN's record of having asked
            # Google to announce a transcript. Writes happen platform-side in
            # the renewal sweep, and the privilege that could quietly re-arm a
            # subscription after somebody withdrew is the one an injection
            # reaches for first.
            #
            # `google_meet_artifact_signals` records only that a transcript
            # became available. It holds no transcript, no participant and no
            # joining code, and at this step nothing writes it from a scoped
            # session.
            #
            # `google_meet_oauth_states` is deliberately absent, exactly as
            # `google_chat_oauth_states` is: the row carries a PKCE verifier,
            # which is presented to Google and therefore cannot be hashed, and
            # a redirect URI names no workspace so the table cannot be scoped
            # to one usefully.
            "google_meet_subscriptions": {"SELECT"},
            "google_meet_artifact_signals": {"SELECT"},
            #
            # `google_chat_oauth_states` is deliberately **absent** from this
            # list, exactly as `slack_oauth_states` is below and for the same
            # reasons — plus one more that is specific to Google: the row also
            # holds the PKCE `code_verifier`, which cannot be hashed because it
            # is a value we present to Google rather than one we recognise. A
            # scoped session that could read this table could complete an
            # install an admin started.
            #
            # `slack_oauth_states` is deliberately **absent** from this list: it
            # has no grant at all, and `test_the_slack_install_state_is_
            # unreachable_from_the_application_role` below asserts that rather
            # than leaving it as something a reader has to notice is missing.
            # Full DML, unlike the GitHub tables above. Attribution runs on a
            # worker that already knows which workspace it is processing, so
            # these are written from *within* tenant context — and the policy's
            # WITH CHECK clause means a scoped session cannot write a row for
            # another tenant even if it tried.
            # -- Meeting capture consent (Step 35) ------------------------
            #
            # SELECT, INSERT, UPDATE on all three, and **DELETE on none**.
            #
            # A request is cancelled rather than removed, so "was this ever
            # asked for?" stays answerable. A participant is marked removed
            # rather than deleted, so a shrinking guest list cannot look like a
            # meeting that never had one. And a consent decision is superseded
            # rather than edited: the history is how the product demonstrates
            # that withdrawal was possible and honoured, which makes DELETE
            # here precisely the privilege somebody who had just overridden a
            # refusal would reach for.
            "meeting_capture_requests": {"SELECT", "INSERT", "UPDATE"},
            "meeting_participants": {"SELECT", "INSERT", "UPDATE"},
            "meeting_consents": {"SELECT", "INSERT", "UPDATE"},
            "people": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "identities": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            # Cross-source identity, and the one grant set in this list chosen by
            # subtraction rather than by what the code happens to call.
            #
            # SELECT: the pipeline resolves a provider account to a person on
            # every event, and a member reads their own links.
            # INSERT: both ways in are written from inside tenant context — the
            # ingestion path matching two verified addresses, and a member
            # confirming their own account — so the policy's WITH CHECK is what
            # stops a scoped session writing a link into another workspace.
            # UPDATE: revoking. Ending a link sets `state`, `revoked_at` and a
            # reason on the existing row, which is the whole revocation
            # mechanism; without UPDATE a person could not withdraw a link at
            # all.
            #
            # **No DELETE, deliberately.** Revocation keeps the row and its
            # evidence (md/12 §6's rule applied to attribution): what CAIRN
            # believed, on what evidence, and when that stopped is exactly the
            # history somebody checks when they find work attributed to the
            # wrong person. A DELETE grant would also be the privilege that
            # makes an inconvenient link disappear under time pressure, and it
            # would let a compromised application role erase the trail of a
            # link it had planted — the same reasoning that keeps DELETE off
            # `facts` and `internal_audit_log`. Tenant removal still cascades,
            # because referential actions run with the table owner's rights.
            "external_identities": {"SELECT", "INSERT", "UPDATE"},
            # Same reasoning: a backfill worker runs inside tenant context, and
            # the policy's WITH CHECK stops a scoped session writing a row for
            # another workspace. DELETE so a disconnected integration's runs can
            # be cleared with the rest of its data.
            "backfill_runs": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            # No DELETE anywhere in the fact graph. Facts are superseded, never
            # deleted (md/12 §6), and a privilege that is granted is a privilege
            # something will eventually use — the first time under time
            # pressure, to make a bad fact go away. Tenant removal still
            # cascades, because referential actions run with the table owner's
            # rights rather than the caller's.
            "facts": {"SELECT", "INSERT", "UPDATE"},
            "fact_sources": {"SELECT", "INSERT", "UPDATE"},
            "fact_people": {"SELECT", "INSERT", "UPDATE"},
            # Derived data, same reasoning and the same absent DELETE. A
            # re-embed replaces a vector by UPDATE, and an edge whose facts were
            # superseded is a validity question — destroying the row that
            # explains a chain is not the answer to it.
            "fact_edges": {"SELECT", "INSERT", "UPDATE"},
            "fact_embeddings": {"SELECT", "INSERT", "UPDATE"},
            # A brief is a record of what was said to a team, so the operation
            # that makes an inconvenient one disappear is the one worth not
            # having. Same absent DELETE as the fact graph, for a reason that is
            # about the product rather than about the schema.
            "briefs": {"SELECT", "INSERT", "UPDATE"},
            "brief_claims": {"SELECT", "INSERT", "UPDATE"},
            # The one table in this list with DELETE and without UPDATE, and
            # both halves are deliberate. DELETE, because opting back in is a
            # person withdrawing a decision about their own record and a
            # tombstone of a withdrawn privacy choice is the wrong kind of
            # memory. No UPDATE, because the row has no mutable state — the
            # presence of the row is the choice.
            "source_opt_outs": {"SELECT", "INSERT", "DELETE"},
            # Staff identity. UPDATE so access can be revoked and a role
            # changed; no DELETE, because "was this person staff in March" is
            # what an audit asks and a deleted row cannot answer it.
            "staff_members": {"SELECT", "INSERT", "UPDATE"},
            # The one table in this schema that must survive a compromise of
            # the application role. Append and read: with no UPDATE and no
            # DELETE, an attacker inside the application can add to the record
            # but never rewrite it (md/15 §5.2).
            "internal_audit_log": {"SELECT", "INSERT"},
            # Staff request platform-side, so no INSERT: an application role
            # that could create a session could approve its own access from
            # inside a workspace. UPDATE because approving, rejecting and
            # revoking are the customer's own decisions. No DELETE — a support
            # session that can be deleted cannot be evidenced.
            "support_sessions": {"SELECT", "UPDATE"},
            # Read-only. Every access event is written platform-side at the
            # moment staff actually open something.
            "support_access_events": {"SELECT"},
            # The only table here with the full set, and the only one where
            # DELETE is the correct outcome: a job that succeeded has nothing
            # left to say. Failure never deletes — a dead-lettered job keeps its
            # row and its reason, because a job that vanished cannot be
            # distinguished from one that was never sent.
            "scheduled_jobs": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        }

        assert actual == expected, (
            "Application-role grants changed. Every entry here is a deliberate "
            "decision — a new table must not be granted access by default, and "
            "authentication tables must have none at all."
        )

    async def test_auth_tables_are_unreachable_from_the_application_role(
        self, session: AsyncSession
    ) -> None:
        """Authentication material must be platform-only.

        These tables cannot be tenant-scoped — a session must be resolvable
        before the tenant is known — so the application role gets no access at
        all rather than unfiltered access. Reproduced before the fix: the
        application role could insert a session row for an arbitrary user with
        no tenant context, which is account takeover from any injection.
        """
        for table in ("sessions", "password_credentials", "oauth_identities"):
            with pytest.raises(DBAPIError):
                await session.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
            await session.rollback()

    async def test_the_slack_install_state_is_unreachable_from_the_application_role(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """The OAuth nonce table is platform-only, like the auth tables.

        Stated as its own test because "no grant" is invisible in the allow-list
        above — a table with no privileges simply does not appear, which is
        indistinguishable from a table somebody forgot to add. Here the absence
        is asserted, so restoring a grant fails a test rather than passing
        review.

        Why it must stay platform-only: the Slack callback URL is registered once
        and carries no workspace, so the row is read with no tenant context to
        scope to. A scoped session that could **write** here would mint an
        install state for its own workspace; one that could **update** here could
        clear `consumed_at` and replay a callback, which is precisely the
        single-use property the whole flow rests on. Row-level security is
        enabled and forced on the table as well — the grant is the outer door,
        the policy is the inner one.
        """
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(text("SELECT count(*) FROM slack_oauth_states"))
        await session.rollback()

        await set_tenant_context(session, acme.id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text(
                    "INSERT INTO slack_oauth_states "
                    "(tenant_id, initiated_by_user_id, state_hash, expires_at) "
                    "VALUES (:t, :u, 'chosen-hash', now() + interval '10 minutes')"
                ),
                {"t": str(acme.id), "u": str(uuid.uuid4())},
            )

    async def test_cannot_plant_a_channel_selection_into_another_tenant(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """A selection row is a permission to read a conversation.

        Writing one into another workspace would let a session scoped to Tenant A
        turn on Slack ingestion for Tenant B's channel — and the consent columns
        would name whoever the attacker chose. The WITH CHECK clause is what
        makes granting INSERT on this table safe at all, so it is asserted
        directly rather than assumed from the policy's text.
        """
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text("""
                    INSERT INTO slack_channel_selections
                        (tenant_id, connection_id, channel_id, selected_by_user_id)
                    VALUES (:other, :connection, 'C0VICTIM01', :user)
                """),
                {
                    "other": str(globex.id),
                    "connection": str(uuid.uuid4()),
                    "user": str(uuid.uuid4()),
                },
            )

    async def test_cannot_graft_a_foreign_user_into_this_tenant(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """A confirmed cross-tenant data leak, closed by revoking INSERT.

        The ``users`` policy makes a person visible when they share a workspace
        with the current tenant. A scoped session could insert a membership for
        any ``user_id`` — including one it could not see, because foreign-key
        checks run as the constraint owner and are exempt from RLS.

        Reproduced: a session scoped to Tenant A grafted a Tenant B user into
        its own workspace and then read that user's email. The victim also
        silently became a member of the attacker's workspace.
        """
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        # A user that exists but belongs only to the other tenant.
        stranger_id = uuid.uuid4()

        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("INSERT INTO memberships (tenant_id, user_id) VALUES (:t, :u)"),
                {"t": str(acme.id), "u": str(stranger_id)},
            )

    async def test_cannot_create_identities_from_a_scoped_session(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """Creating a tenant or a user is a platform operation.

        Both previously carried a ``WITH CHECK (true)`` INSERT policy, which
        allowed a scoped session to create rogue rows — and handed back the
        account-enumeration oracle that ``authenticate`` works to deny: a unique
        violation proves an address exists, success proves it does not.
        """
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("INSERT INTO tenants (name, slug) VALUES ('Rogue', 'rogue-probe')")
            )
        await session.rollback()

        await set_tenant_context(session, acme.id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(text("INSERT INTO users (email) VALUES ('probe@target.test')"))

    async def test_cannot_plant_an_invitation_into_another_tenant(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """The confirmed tenant-takeover path.

        A permissive ``WITH CHECK (true)`` INSERT policy on ``invitations`` ORed
        with the isolation policy, making the effective check ``true``. A session
        scoped to Tenant A could insert an ``owner`` invitation for Tenant B,
        choose the token, and redeem it through the ordinary public flow.
        """
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text("""
                    INSERT INTO invitations
                        (tenant_id, email, role, token_hash, expires_at)
                    VALUES
                        (:other, 'attacker@evil.test', 'owner', 'chosen-hash',
                         now() + interval '7 days')
                """),
                {"other": str(globex.id)},
            )

    async def test_context_survives_a_commit_inside_the_block(
        self, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """A handler that commits mid-block must not silently lose its scope.

        `SET LOCAL` dies with its transaction, so before the `after_begin`
        listener a commit left every subsequent statement unscoped — reads
        returning nothing, writes failing their WITH CHECK, and no error naming
        the cause. The module docstring claimed this was impossible.
        """
        acme, _ = two_tenants

        async with tenant_session(acme.id) as scoped:
            assert await get_tenant_context(scoped) == acme.id

            # Simulate a long-running job checkpointing its progress.
            await scoped.commit()

            assert await get_tenant_context(scoped) == acme.id, (
                "Tenant context was lost after a commit inside the block"
            )
            assert await scoped.scalar(select(func.count()).select_from(Membership)) == 1


class TestApplicationLayer:
    """Application-level isolation. Fails loudly, so mistakes are caught early."""

    async def test_tenant_session_requires_a_tenant(self) -> None:
        with pytest.raises(MissingTenantContextError, match="requires a tenant ID"):
            async with tenant_session(None):
                pass  # pragma: no cover — the context manager must not open

    async def test_missing_context_error_is_not_a_value_error(self) -> None:
        """It must not be swallowed by generic input-validation handling.

        A broad ``except ValueError`` written for bad user input would otherwise
        hide a data-isolation defect.
        """
        assert not issubclass(MissingTenantContextError, ValueError)

    async def test_set_and_read_context_round_trip(self, session: AsyncSession) -> None:
        tenant_id = uuid.uuid4()
        await set_tenant_context(session, tenant_id)
        assert await get_tenant_context(session) == tenant_id

    async def test_context_is_empty_by_default(self, session: AsyncSession) -> None:
        assert await get_tenant_context(session) is None
