"""The audit mirror: two trust domains, and the tests that keep them two.

Runs against a real second PostgreSQL instance (`docker compose up -d
audit-sink` locally; a docker step in CI). Skipped only where that instance is
absent AND we are not in CI — the same honesty rule as the Pub/Sub emulator:
skipping locally is a convenience, skipping in CI would be a silent gap in the
one control that guards the audit record.
"""

from __future__ import annotations

import os
import socket
import uuid
from typing import Any

import pytest
from cairn_api.config import Settings
from cairn_api.db.models import User
from cairn_api.internal import audit, audit_sink
from pydantic import PostgresDsn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

pytestmark = [pytest.mark.integration]

SINK_HOST = os.environ.get("CAIRN_TEST_AUDIT_SINK_HOST", "localhost")
SINK_PORT = int(os.environ.get("CAIRN_TEST_AUDIT_SINK_PORT", "5433"))

#: The application's credential at the sink: INSERT and SELECT, nothing else.
SINK_URL = f"postgresql+asyncpg://audit_mirror:audit_local_dev@{SINK_HOST}:{SINK_PORT}/cairn_audit"

#: The sink instance's owner — used only to *tamper* in the divergence tests,
#: because the attacker the mirror defends against is an owner.
SINK_OWNER_URL = (
    f"postgresql+asyncpg://audit_owner:audit_owner_local_dev@{SINK_HOST}:{SINK_PORT}/cairn_audit"
)


def _sink_reachable() -> bool:
    try:
        with socket.create_connection((SINK_HOST, SINK_PORT), timeout=1):
            return True
    except OSError:
        return False


if not _sink_reachable():
    if os.environ.get("CI"):
        pytest.fail(
            "CI must never skip the audit-sink suite: the sink container is "
            "missing from the workflow. See the 'Start the audit sink' step."
        )
    pytestmark.append(
        pytest.mark.skip(reason="audit sink not reachable; docker compose up -d audit-sink")
    )


def sink_settings() -> Settings:
    return Settings(environment="local", audit_sink_url=PostgresDsn(SINK_URL))


@pytest.fixture(autouse=True)
async def clean_sink() -> Any:
    """Empty the mirror before each test, as the owner — the role the
    application holds cannot do this, which is the point of it."""
    if not _sink_reachable():
        yield
        return
    owner = create_async_engine(SINK_OWNER_URL)
    async with owner.begin() as conn:
        await conn.execute(text("TRUNCATE internal_audit_mirror"))
    await owner.dispose()
    # A fresh engine per test: the module caches one per DSN and tests share it.
    yield


@pytest.fixture
async def actor(platform: AsyncSession) -> uuid.UUID:
    user = User(email=f"auditor-{uuid.uuid4().hex[:10]}@example.com")
    platform.add(user)
    await platform.commit()
    return user.id


async def record_actions(platform: AsyncSession, actor: uuid.UUID, count: int) -> list[int]:
    sequences = []
    for index in range(count):
        entry = await audit.record(
            platform,
            actor_user_id=actor,
            action="support.session_opened",
            reason=f"proof action {index}",
        )
        sequences.append(entry.sequence)
    await platform.commit()
    return sequences


class TestTheTrustBoundary:
    async def test_the_sink_role_grants_are_an_explicit_allow_list(self) -> None:
        """Same idiom as the application-role grant test, same reason: a grant
        nobody wrote down is the one an injection uses first. INSERT and
        SELECT, nothing else — SELECT deliberately, because verification is a
        read and the threat model here is writes."""
        engine = create_async_engine(SINK_URL)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = 'audit_mirror' AND table_name = 'internal_audit_mirror'"
                )
            )
            granted = {row.privilege_type for row in rows}
        await engine.dispose()

        assert granted == {"INSERT", "SELECT"}, (
            f"the sink role's grants drifted from the allow-list: {sorted(granted)}"
        )

    async def test_the_sink_role_cannot_update_or_delete(self) -> None:
        """The grants table says so; this proves the database enforces it."""
        engine = create_async_engine(SINK_URL)
        for statement in (
            "UPDATE internal_audit_mirror SET reason = 'rewritten'",
            "DELETE FROM internal_audit_mirror",
        ):
            with pytest.raises(Exception, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
        await engine.dispose()

    def test_a_sink_on_the_primary_instance_is_refused_at_boot(self) -> None:
        """A mirror the same owner can delete is configuration that looks like
        the control while providing none of it."""
        with pytest.raises(Exception, match="same PostgreSQL instance"):
            Settings(
                environment="local",
                audit_sink_url=PostgresDsn(
                    "postgresql+asyncpg://audit_mirror:x@localhost:5432/cairn_audit"
                ),
            )


class TestShippingAndVerification:
    async def test_ship_then_verify_is_green(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        await record_actions(platform, actor, 3)
        settings = sink_settings()

        outcome = await audit_sink.ship_pending(platform, settings=settings)
        assert outcome.failed is False
        assert outcome.shipped >= 3
        assert outcome.lag == 0

        verification = await audit_sink.verify_against_sink(platform, settings=settings)
        assert verification.intact is True
        assert verification.primary_intact is True
        assert verification.sink_entries == verification.primary_entries

    async def test_a_second_pass_ships_nothing_and_stays_green(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        await record_actions(platform, actor, 2)
        settings = sink_settings()
        await audit_sink.ship_pending(platform, settings=settings)

        again = await audit_sink.ship_pending(platform, settings=settings)

        assert again.shipped == 0
        assert again.lag == 0

    async def test_the_cursor_never_skips_an_unshipped_row(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        """A failed pass moves nothing: the cursor is the sink's own
        MAX(sequence), so it cannot run ahead of what landed, and the next
        healthy pass ships everything the failed one did not."""
        await record_actions(platform, actor, 2)
        settings = sink_settings()
        down = Settings(
            environment="local",
            audit_sink_url=PostgresDsn(
                f"postgresql+asyncpg://audit_mirror:audit_local_dev@{SINK_HOST}:1/cairn_audit"
            ),
        )

        failed = await audit_sink.ship_pending(platform, settings=down)
        assert failed.failed is True
        assert failed.shipped == 0

        recovered = await audit_sink.ship_pending(platform, settings=settings)
        assert recovered.failed is False
        assert recovered.lag == 0
        verification = await audit_sink.verify_against_sink(platform, settings=settings)
        assert verification.intact is True


class TestFailureHonesty:
    async def test_the_audited_action_succeeds_with_the_sink_down(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        """The primary write never waits. The mirror is behind the action, not
        in front of it, and a down sink delays mirroring only."""
        entry = await audit.record(
            platform,
            actor_user_id=actor,
            action="support.session_opened",
            reason="recorded while the sink is unreachable",
        )
        await platform.commit()

        assert entry.sequence > 0
        internal = await audit.verify(platform)
        assert internal.intact is True

    async def test_unconfigured_is_exactly_todays_behaviour(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        """No sink URL: recording works, shipping is a counted no-op, and the
        release gate — not a per-pass warning — is what says so."""
        await record_actions(platform, actor, 1)
        unconfigured = Settings(environment="local")

        outcome = await audit_sink.ship_pending(platform, settings=unconfigured)

        assert outcome.shipped == 0
        assert outcome.failed is False
        assert outcome.highest_primary > 0


class TestDivergenceIsASecurityFinding:
    async def test_a_deleted_sink_row_is_named_as_a_gap(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        sequences = await record_actions(platform, actor, 3)
        settings = sink_settings()
        await audit_sink.ship_pending(platform, settings=settings)

        owner = create_async_engine(SINK_OWNER_URL)
        async with owner.begin() as conn:
            await conn.execute(
                text("DELETE FROM internal_audit_mirror WHERE sequence = :seq"),
                {"seq": sequences[1]},
            )
        await owner.dispose()

        verification = await audit_sink.verify_against_sink(platform, settings=settings)

        assert verification.intact is False
        assert verification.broken_at == sequences[1]
        assert verification.reason is not None and "sink_gap" in verification.reason

    async def test_an_altered_sink_row_is_named_as_a_mismatch(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        sequences = await record_actions(platform, actor, 2)
        settings = sink_settings()
        await audit_sink.ship_pending(platform, settings=settings)

        owner = create_async_engine(SINK_OWNER_URL)
        async with owner.begin() as conn:
            await conn.execute(
                text("UPDATE internal_audit_mirror SET entry_hash = :h WHERE sequence = :seq"),
                {"h": "f" * 64, "seq": sequences[0]},
            )
        await owner.dispose()

        verification = await audit_sink.verify_against_sink(platform, settings=settings)

        assert verification.intact is False
        assert verification.broken_at == sequences[0]
        assert verification.reason is not None and "mismatch" in verification.reason

    async def test_content_tampering_that_spares_the_hash_column_is_still_caught(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        """**Found by the live proof, not by design.** The first version
        compared stored hash columns, so an owner who edited the mirror's
        *content* while leaving `entry_hash` untouched verified clean.
        Verification now recomputes the hash over the sink's own bytes - the
        hash column is a claim, and claims get checked."""
        sequences = await record_actions(platform, actor, 2)
        settings = sink_settings()
        await audit_sink.ship_pending(platform, settings=settings)

        owner = create_async_engine(SINK_OWNER_URL)
        async with owner.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE internal_audit_mirror SET reason = 'this never happened' "
                    "WHERE sequence = :seq"
                ),
                {"seq": sequences[0]},
            )
        await owner.dispose()

        verification = await audit_sink.verify_against_sink(platform, settings=settings)

        assert verification.intact is False
        assert verification.broken_at == sequences[0]
        assert verification.reason is not None and "mismatch" in verification.reason

    async def test_a_truncated_primary_is_survived_and_named(
        self, platform: AsyncSession, actor: uuid.UUID
    ) -> None:
        """**The gravest shape, and the one the sink exists for.** The
        primary's owner erases history; the sink still names every sequence."""
        sequences = await record_actions(platform, actor, 2)
        settings = sink_settings()
        await audit_sink.ship_pending(platform, settings=settings)

        await platform.execute(
            text("DELETE FROM internal_audit_log WHERE sequence = :seq"),
            {"seq": sequences[-1]},
        )
        await platform.commit()

        verification = await audit_sink.verify_against_sink(platform, settings=settings)

        assert verification.intact is False
        assert verification.broken_at == sequences[-1]
        assert verification.reason is not None and "primary_missing" in verification.reason
        assert "surviving witness" in verification.reason


class TestTheOperatorCommand:
    """`python -m cairn_api.internal.audit_sink` - the round trip the gate
    closes with, executed rather than trusted (the operator-command rule)."""

    async def test_unconfigured_refuses_with_exit_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cairn_api.config import Settings

        monkeypatch.setattr(
            "cairn_api.internal.audit_sink.get_settings",
            lambda: Settings(environment="local"),
        )
        assert await audit_sink._main() == 2

    async def test_the_green_round_trip_exits_0(
        self,
        platform: AsyncSession,
        actor: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        await record_actions(platform, actor, 1)
        monkeypatch.setattr("cairn_api.internal.audit_sink.get_settings", lambda: sink_settings())

        code = await audit_sink._main()

        assert code == 0
        out = capsys.readouterr().out
        assert "INTACT: both chains agree" in out

    async def test_a_diverged_pair_exits_1_and_names_the_sequence(
        self,
        platform: AsyncSession,
        actor: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sequences = await record_actions(platform, actor, 1)
        settings = sink_settings()
        await audit_sink.ship_pending(platform, settings=settings)
        owner = create_async_engine(SINK_OWNER_URL)
        async with owner.begin() as conn:
            await conn.execute(
                text("UPDATE internal_audit_mirror SET reason = 'edited' WHERE sequence = :s"),
                {"s": sequences[0]},
            )
        await owner.dispose()
        monkeypatch.setattr("cairn_api.internal.audit_sink.get_settings", lambda: settings)

        code = await audit_sink._main()

        assert code == 1
        err = capsys.readouterr().err
        assert f"DIVERGED at sequence {sequences[0]}" in err
