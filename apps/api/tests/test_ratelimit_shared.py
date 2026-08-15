"""The shared rate-limit store, against a real database.

The in-process limiter was honest about being per-instance and was still a real
weakness: on Cloud Run the effective limit is the configured one times the
instance count, resetting on every deploy. These assert the replacement is
correct where that one was not — across instances, and under concurrency.

Against real PostgreSQL rather than a fake, because the correctness argument
rests entirely on what `INSERT ... ON CONFLICT DO UPDATE ... WHERE` does when
two transactions race for one row. A fake would assert only that the fake agrees
with itself.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from cairn_api.api.ratelimit import (
    PostgresRateLimiter,
    RateLimit,
    purge_expired_buckets,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
def limiter(platform_engine: AsyncEngine) -> PostgresRateLimiter:
    """A limiter whose sessions commit for real.

    Deliberately not the rolled-back `session` fixture. A bucket that vanishes
    on rollback would make every test pass regardless of the behaviour under
    test — the limiter's whole purpose is that its state survives the request
    that created it.
    """
    factory = async_sessionmaker(bind=platform_engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session
            await session.commit()

    return PostgresRateLimiter(session_scope)


def unique_key(prefix: str) -> str:
    """A key nobody else in the suite will touch."""
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


class TestBucketBehaviour:
    async def test_allows_up_to_the_limit_then_refuses(self, limiter: PostgresRateLimiter) -> None:
        key = unique_key("basic")
        limit = RateLimit(limit=3, window_seconds=3600)

        results = [await limiter.check(key, limit) for _ in range(4)]

        assert [r.allowed for r in results] == [True, True, True, False]

    async def test_keys_are_independent(self, limiter: PostgresRateLimiter) -> None:
        # Otherwise one noisy address would lock out everyone.
        limit = RateLimit(limit=1, window_seconds=3600)
        await limiter.check(unique_key("a"), limit)

        assert (await limiter.check(unique_key("b"), limit)).allowed is True

    async def test_refusal_reports_when_to_retry(self, limiter: PostgresRateLimiter) -> None:
        key = unique_key("retry-after")
        limit = RateLimit(limit=2, window_seconds=60)

        await limiter.check(key, limit)
        await limiter.check(key, limit)
        refused = await limiter.check(key, limit)

        assert refused.allowed is False
        # One token's worth of refill: 60s window / 2 tokens = 30s per token.
        assert refused.retry_after == pytest.approx(30.0)

    async def test_tokens_refill_over_time(self, limiter: PostgresRateLimiter) -> None:
        # Refill is derived from elapsed time rather than topped up by a
        # scheduled job, so a bucket recovers without anything having to run.
        key = unique_key("refill")
        limit = RateLimit(limit=2, window_seconds=0.4)  # 5 tokens/second

        assert (await limiter.check(key, limit)).allowed is True
        assert (await limiter.check(key, limit)).allowed is True
        assert (await limiter.check(key, limit)).allowed is False

        await asyncio.sleep(0.3)

        assert (await limiter.check(key, limit)).allowed is True

    async def test_an_idle_bucket_cannot_bank_unlimited_allowance(
        self, limiter: PostgresRateLimiter, platform_engine: AsyncEngine
    ) -> None:
        """Refill is capped at capacity.

        Without the cap, a key untouched for a week accumulates a week of
        allowance and permits a burst bounded by nothing — which is worse than
        having no limit, because it looks like one.
        """
        key = unique_key("cap")
        limit = RateLimit(limit=3, window_seconds=1)

        await limiter.check(key, limit)

        # Backdate the bucket by an hour rather than sleeping for one.
        async with async_sessionmaker(bind=platform_engine)() as session:
            await session.execute(
                text(
                    "UPDATE rate_limit_buckets "
                    "SET updated_at = now() - interval '1 hour' WHERE key = :key"
                ),
                {"key": key},
            )
            await session.commit()

        results = [await limiter.check(key, limit) for _ in range(4)]

        assert [r.allowed for r in results] == [True, True, True, False]


class TestConcurrency:
    async def test_concurrent_checks_cannot_exceed_the_limit(
        self, limiter: PostgresRateLimiter
    ) -> None:
        """The property the whole design rests on.

        Refill, test and deduction happen in one statement, so the row lock
        Postgres takes serialises concurrent callers. A read-then-write in
        Python would have exactly the race a limiter exists to prevent — and it
        would only appear under the concurrent load an attacker generates,
        which is the worst possible time to discover it.
        """
        key = unique_key("race")
        limit = RateLimit(limit=5, window_seconds=3600)

        results = await asyncio.gather(*(limiter.check(key, limit) for _ in range(25)))

        assert sum(r.allowed for r in results) == 5

    async def test_two_instances_share_one_budget(self, platform_engine: AsyncEngine) -> None:
        """The defect this replaces.

        Two limiters with separate connections stand in for two Cloud Run
        instances. With the in-process limiter each would have granted the full
        allowance, so the effective limit was the configured one times the
        instance count.
        """
        factory = async_sessionmaker(bind=platform_engine, expire_on_commit=False)

        @asynccontextmanager
        async def scope() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session
                await session.commit()

        instance_a = PostgresRateLimiter(scope)
        instance_b = PostgresRateLimiter(scope)
        key = unique_key("shared")
        limit = RateLimit(limit=4, window_seconds=3600)

        allowed = 0
        for index in range(8):
            instance = instance_a if index % 2 == 0 else instance_b
            allowed += (await instance.check(key, limit)).allowed

        assert allowed == 4


class TestMaintenance:
    async def test_stale_buckets_are_purged(
        self, limiter: PostgresRateLimiter, platform_engine: AsyncEngine
    ) -> None:
        # A bucket at capacity is indistinguishable from one that does not
        # exist, so old rows are pure accumulation. For a public login endpoint
        # that means one row per scanner on the internet, forever.
        key = unique_key("stale")
        await limiter.check(key, RateLimit(limit=5, window_seconds=60))

        async with async_sessionmaker(bind=platform_engine)() as session:
            await session.execute(
                text(
                    "UPDATE rate_limit_buckets "
                    "SET updated_at = now() - interval '2 days' WHERE key = :key"
                ),
                {"key": key},
            )
            await session.commit()

            purged = await purge_expired_buckets(session, older_than_seconds=86400)
            await session.commit()

            remaining = await session.scalar(
                text("SELECT count(*) FROM rate_limit_buckets WHERE key = :key"),
                {"key": key},
            )

        assert purged >= 1
        assert remaining == 0

    async def test_a_live_bucket_is_not_purged(
        self, limiter: PostgresRateLimiter, platform_engine: AsyncEngine
    ) -> None:
        # The positive control. Without it, a purge that deleted everything
        # would pass the test above while silently disabling rate limiting.
        key = unique_key("live")
        await limiter.check(key, RateLimit(limit=5, window_seconds=60))

        async with async_sessionmaker(bind=platform_engine)() as session:
            await purge_expired_buckets(session, older_than_seconds=86400)
            await session.commit()

            remaining = await session.scalar(
                text("SELECT count(*) FROM rate_limit_buckets WHERE key = :key"),
                {"key": key},
            )

        assert remaining == 1
