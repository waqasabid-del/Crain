"""Rate limiting for authentication endpoints.

Closes the second half of audit finding O2. The first half — Argon2 blocking the
event loop — was fixed by moving the hash off the loop; that made the service
survive concurrent logins, it did not stop anyone from *causing* them. Each
attempt still costs 64 MiB and ~50-100 ms of CPU, so an unthrottled login
endpoint is both a credential-stuffing target and a cheap denial-of-service.

**Two limits, because they defend different things.**

*Per identifier* (the email being tried) stops credential stuffing against one
account. On its own it is trivially evaded — an attacker spreading attempts
across a leaked list never hits it.

*Per client address* stops that spread, and stops the resource exhaustion, since
the cost is paid per request regardless of which account is named.

Neither is sufficient alone, which is why both are checked and the more
restrictive answer wins.

**The counter is deliberately not keyed on success.** Counting only failures
lets an attacker with one valid credential reset their budget at will, and does
nothing about the CPU cost, which is paid whether or not the password was right.

---

**Honest statement of the current limitation.** The backend below is in-process.
On Cloud Run with N instances the effective limit is N times the configured one,
and it resets whenever an instance is recycled — which under autoscaling is
often. That is a real weakening, not a rounding error.

It is still worth shipping. The alternative today is *no* limit, and this stops
the naive high-rate attack that constitutes the overwhelming majority of what an
unprotected login endpoint actually receives. The `RateLimiter` protocol exists
so the fix is a new class rather than a change to every call site: a Redis
backend lands with Step 10, which is when the infrastructure to run one arrives.

Saying so in the module rather than a ticket is deliberate. An in-memory limiter
that *looks* authoritative is precisely the kind of control this project's audit
kept finding — one that reads as protection and quietly is not.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimit:
    """A budget: `limit` events per `window_seconds`."""

    limit: int
    window_seconds: float

    def __post_init__(self) -> None:
        if self.limit < 1:
            msg = "limit must be at least 1"
            raise ValueError(msg)
        if self.window_seconds <= 0:
            msg = "window_seconds must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """The outcome of one check."""

    allowed: bool
    #: Seconds until the caller may retry. Zero when allowed. Rendered into the
    #: `Retry-After` header, so a well-behaved client backs off by the right
    #: amount instead of guessing or hammering.
    retry_after: float


class RateLimiter(Protocol):
    """A limiter backend.

    Deliberately narrow. Anything wider — reset, inspect, decrement — would be
    used, and would then have to be implemented in Redis with the same
    semantics.
    """

    async def check(self, key: str, limit: RateLimit) -> RateLimitResult: ...


class InMemoryRateLimiter:
    """Sliding-window limiter held in process memory.

    A sliding log, not a fixed window. A fixed window lets an attacker send a
    full budget at 0:59 and another at 1:01 — double the intended rate across
    the boundary, which is exactly when a burst is most likely to be
    deliberate. Storing timestamps costs a few hundred bytes per active key and
    removes the loophole.

    Memory is bounded by pruning on access, plus a hard cap on tracked keys. The
    cap matters: without it, an attacker cycling through addresses turns the
    defence into an unbounded allocation — a denial of service delivered through
    the thing meant to prevent one.
    """

    #: Above this many tracked keys, the oldest are discarded. Sized so that
    #: normal traffic never reaches it and an attacker cannot exhaust memory.
    MAX_TRACKED_KEYS = 10_000

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        # Checks are read-modify-write across an await boundary in the caller,
        # so concurrent requests for one key could both observe a
        # below-threshold count. The lock is uncontended in the common case and
        # far cheaper than the Argon2 hash it is protecting.
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: RateLimit) -> RateLimitResult:
        now = time.monotonic()
        cutoff = now - limit.window_seconds

        async with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._evict_if_full()
                self._hits[key] = hits

            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= limit.limit:
                # Retry-After is measured from the oldest hit still in the
                # window: that is the moment one slot frees up.
                retry_after = hits[0] + limit.window_seconds - now
                return RateLimitResult(allowed=False, retry_after=max(retry_after, 0.0))

            hits.append(now)
            return RateLimitResult(allowed=True, retry_after=0.0)

    def _evict_if_full(self) -> None:
        """Drop the least recently created keys once the cap is reached.

        `dict` preserves insertion order, so the first key is the oldest. Evicts
        a batch rather than one at a time, so a sustained attack does not pay
        eviction on every single request.
        """
        overflow = len(self._hits) - self.MAX_TRACKED_KEYS
        if overflow < 0:
            return
        for key in list(self._hits)[: overflow + 1]:
            del self._hits[key]

    def reset(self) -> None:
        """Discard all state. For tests only."""
        self._hits.clear()


# -- Policy -----------------------------------------------------------------
#
# Numbers chosen to be invisible to a real person and painful to a script.
#
# A user who has forgotten their password tries perhaps three or four times
# before resetting, so ten per fifteen minutes never fires for them. An attacker
# working a leaked credential list needs thousands of attempts per account to be
# worth running, and this makes that take months.

#: Login attempts for one email address.
LOGIN_PER_IDENTIFIER = RateLimit(limit=10, window_seconds=15 * 60)

#: Login attempts from one client address. Higher than the per-identifier limit
#: because a whole office behind one NAT gateway shares an address, and locking
#: out a customer's building is a worse outcome than the attack this bounds.
LOGIN_PER_ADDRESS = RateLimit(limit=50, window_seconds=15 * 60)

#: Signups from one client address. Tighter — signup creates rows, sends mail
#: and costs an Argon2 hash, and no legitimate person signs up repeatedly.
SIGNUP_PER_ADDRESS = RateLimit(limit=5, window_seconds=60 * 60)

#: Invitation redemptions from one address. An invitation token is unguessable,
#: so this is not brute-force defence; it bounds the cost of someone replaying
#: acceptance attempts.
INVITE_ACCEPT_PER_ADDRESS = RateLimit(limit=20, window_seconds=60 * 60)

#: Verification resends per account per hour.
#:
#: This endpoint sends mail, so an unlimited one lets an authenticated account
#: drive a relay and burn its sending reputation. Three is enough for a link
#: that went to spam and far below anything automated.
VERIFY_RESEND_PER_USER = RateLimit(limit=3, window_seconds=60 * 60)


class PostgresRateLimiter:
    """A token bucket held in PostgreSQL, shared across every instance.

    Replaces `InMemoryJobQueue`'s sibling defect: the in-process limiter was
    per-instance, so on Cloud Run the effective limit was N times the configured
    one and reset on every deploy. This one is correct regardless of how many
    instances are running, which is the entire point.

    **One statement per check.** The refill, the test and the deduction happen
    inside a single `INSERT ... ON CONFLICT DO UPDATE`, so two concurrent
    requests for the same key cannot both observe a full bucket — the row lock
    Postgres takes for the update serialises them. A read-then-write in Python
    would have exactly the race the limiter exists to prevent, and it would only
    appear under the concurrent load an attacker generates.

    **Refill is computed from elapsed time, not scheduled.** A background job
    topping up every bucket would be work proportional to the number of keys,
    most of which nobody will ever touch again. Deriving the level from
    `updated_at` costs nothing and is exact.
    """

    def __init__(
        self, session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    ) -> None:
        self._session_factory = session_factory

    async def check(self, key: str, limit: RateLimit) -> RateLimitResult:
        refill_per_second = limit.limit / limit.window_seconds

        # LEAST(...) caps the refill at the bucket's capacity: a key untouched
        # for a week must not accumulate a week's worth of allowance and permit
        # an unbounded burst.
        statement = text("""
            INSERT INTO rate_limit_buckets (key, tokens, updated_at)
            VALUES (:key, :capacity - 1, now())
            ON CONFLICT (key) DO UPDATE SET
                tokens = LEAST(
                    :capacity,
                    rate_limit_buckets.tokens
                        + EXTRACT(EPOCH FROM (now() - rate_limit_buckets.updated_at))
                          * :refill_rate
                ) - 1,
                updated_at = now()
            WHERE
                LEAST(
                    :capacity,
                    rate_limit_buckets.tokens
                        + EXTRACT(EPOCH FROM (now() - rate_limit_buckets.updated_at))
                          * :refill_rate
                ) >= 1
            RETURNING tokens
        """)

        async with self._session_factory() as session:
            result = await session.scalar(
                statement,
                {
                    "key": key,
                    "capacity": float(limit.limit),
                    "refill_rate": refill_per_second,
                },
            )

        if result is not None:
            return RateLimitResult(allowed=True, retry_after=0.0)

        # The WHERE clause suppressed the update, so the bucket was empty. One
        # token's worth of refill is the wait.
        return RateLimitResult(allowed=False, retry_after=1.0 / refill_per_second)


async def purge_expired_buckets(session: AsyncSession, *, older_than_seconds: float) -> int:
    """Delete buckets untouched for long enough to be certainly full.

    A bucket at capacity is indistinguishable from one that does not exist, so
    old rows carry no information — they are pure accumulation. Without this the
    table grows by one row per distinct address forever, which for a public
    login endpoint means one row per scanner on the internet.

    Run as a scheduled job rather than opportunistically during a check: making
    every login pay for someone else's cleanup is how a fast path acquires a
    long tail.
    """
    result = await session.execute(
        text(
            "DELETE FROM rate_limit_buckets WHERE updated_at < now() - make_interval(secs => :age)"
        ),
        {"age": older_than_seconds},
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
