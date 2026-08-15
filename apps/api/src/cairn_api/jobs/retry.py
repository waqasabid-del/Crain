"""Retry policy, kept as a testable value: exponential, jittered (else
failures thunder-herd at each doubling), and capped."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    #: Including the first attempt. At 5, dead-letters ~1 minute after enqueue.
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0

    #: A band, not full jitter, so the schedule stays roughly watchable.
    jitter_ratio: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        if self.base_delay_seconds <= 0:
            msg = "base_delay_seconds must be positive"
            raise ValueError(msg)
        if self.max_delay_seconds < self.base_delay_seconds:
            msg = "max_delay_seconds cannot be below base_delay_seconds"
            raise ValueError(msg)
        if not 0 <= self.jitter_ratio < 1:
            msg = "jitter_ratio must be in [0, 1)"
            raise ValueError(msg)

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay_for(self, attempt: int, *, rng: random.Random | None = None) -> float:
        """Never below zero — `asyncio.sleep` would silently coerce a negative value."""
        nominal: float = min(
            self.base_delay_seconds * (2 ** max(attempt - 1, 0)),
            self.max_delay_seconds,
        )
        if self.jitter_ratio == 0:
            return nominal

        source = rng if rng is not None else random
        spread = nominal * self.jitter_ratio
        jittered: float = nominal + source.uniform(-spread, spread)
        return max(0.0, jittered)


DEFAULT_RETRY_POLICY = RetryPolicy()

#: External APIs (GitHub, Vertex) — higher ceiling; the failure is usually a quota window.
EXTERNAL_API_RETRY_POLICY = RetryPolicy(
    max_attempts=8,
    base_delay_seconds=2.0,
    max_delay_seconds=300.0,
)
