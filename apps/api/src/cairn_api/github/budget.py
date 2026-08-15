"""GitHub rate budget accounting.

Corrects md/01 §4.2: GitHub's rate limits apply *per installation*, not as a
shared pool, so they are enforced per installation here. A separate global
limit caps concurrent backfills, protecting our own database/worker pool and
the live event stream — not GitHub's quota.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

#: GraphQL points per hour, per installation.
GRAPHQL_POINTS_PER_HOUR = 5_000

#: Secondary ceiling on simultaneous requests, per installation.
MAX_CONCURRENT_REQUESTS = 100

#: Deliberately far below the ceiling: shares budget with live webhook follow-up.
BACKFILL_CONCURRENCY = 8

#: Not a GitHub limit — bounds our own database/worker load.
MAX_CONCURRENT_BACKFILLS = 4

#: Stop when this much of the hourly budget remains, reserved for live traffic.
RESERVED_POINT_FRACTION = 0.2


@dataclass(slots=True)
class RateBudget:
    """What one installation has left, from GitHub's own `rateLimit` block."""

    limit: int = GRAPHQL_POINTS_PER_HOUR
    remaining: int = GRAPHQL_POINTS_PER_HOUR
    reset_at: float = 0.0

    #: Diverging from `remaining` means another process shares this budget.
    spent: int = 0

    recent_costs: list[int] = field(default_factory=list)

    @property
    def reserve(self) -> int:
        return int(self.limit * RESERVED_POINT_FRACTION)

    @property
    def usable(self) -> int:
        return max(0, self.remaining - self.reserve)

    @property
    def seconds_until_reset(self) -> float:
        return max(0.0, self.reset_at - time.time())

    def observe(self, *, limit: int, remaining: int, reset_at: float, cost: int) -> None:
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at
        self.spent += cost
        self.recent_costs.append(cost)
        del self.recent_costs[:-20]  # bounded: prediction, not history

    def can_afford_next(self) -> bool:
        """Priced at the most expensive query seen, not the average."""
        if not self.recent_costs:
            return self.usable > 0
        return self.usable >= max(self.recent_costs)


class BudgetExhaustedError(RuntimeError):
    """No usable budget left. Carries when to resume so a run is parked, not retried."""

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(f"GitHub rate budget exhausted; resumes in {retry_after_seconds:.0f}s")
        self.retry_after_seconds = retry_after_seconds


def parse_rate_limit(block: dict[str, object]) -> tuple[int, int, float, int]:
    """Read a GraphQL `rateLimit` block into `(limit, remaining, reset_at, cost)`."""
    from datetime import datetime

    def _int(key: str, default: int) -> int:
        value = block.get(key)
        return value if isinstance(value, int) else default

    reset_at = 0.0
    raw_reset = block.get("resetAt")
    if isinstance(raw_reset, str):
        try:
            reset_at = datetime.fromisoformat(raw_reset.replace("Z", "+00:00")).timestamp()
        except ValueError:
            reset_at = time.time() + 3600

    return (
        _int("limit", GRAPHQL_POINTS_PER_HOUR),
        _int("remaining", 0),
        reset_at,
        _int("cost", 1),
    )
