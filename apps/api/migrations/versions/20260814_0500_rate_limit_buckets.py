"""A shared store for rate limiting.

The in-process limiter added with the API layer was honest about its limitation
and still a real weakness: on Cloud Run with N instances the effective limit is
N times the configured one, and it resets whenever an instance is recycled —
which under autoscaling is often. An attacker does not need to know any of that
to benefit from it.

**Postgres rather than Redis**, which is the interesting decision.

Redis is the reflexive answer and would be faster. It is also an entire piece of
infrastructure to provision, secure, monitor, patch and pay for, whose sole
consumer would be this table. Postgres is already here, already backed up,
already inside the same failure domain as the thing being protected — if it is
down, login fails regardless, so this adds no new way for the service to break.

The cost is a write on every login attempt. At CAIRN's scale that is one indexed
upsert against a table with a few thousand rows, which is not a number worth
optimising against a dependency nobody is running yet. If authentication volume
ever makes it one, the `RateLimiter` protocol means Redis is a new class rather
than a change to every call site.

**Token bucket, not a sliding log.** A log needs a row per attempt and a periodic
sweep to stay bounded; a bucket needs one row per key and a single upsert. The
semantic difference — a bucket permits a burst up to its capacity — is
acceptable and arguably better here: someone returning after an idle period
should not be throttled for typing their password twice.

Revision ID: d8b52c04e719
Revises: c4a71b8e35d6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d8b52c04e719"
down_revision: str | None = "c4a71b8e35d6"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        # The bucket identity: "login-addr:1.2.3.4", "signup:1.2.3.4".
        #
        # Deliberately opaque to the database. Structuring it into columns would
        # mean a migration every time a new limit is added, and the only query
        # this table ever serves is an exact-match upsert on the whole key.
        sa.Column("key", sa.Text(), primary_key=True),
        # Fractional, because refill is continuous rather than stepped. An
        # integer column would round every partial refill to zero and turn a
        # slow trickle back to full into a permanent lockout.
        sa.Column("tokens", sa.Double(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Deliberately NOT tenant-scoped, and therefore NOT under row-level
        # security. Rate limiting protects the login endpoint, which runs before
        # any tenant is known — there is no tenant to scope to. The table holds
        # no customer data: a key is a hashed address or an email, and the only
        # values are a token count and a timestamp.
        comment=(
            "Token buckets for rate limiting. Not tenant-scoped: rate limits "
            "apply before authentication, so no tenant context exists yet."
        ),
    )

    # Sweeping expired buckets scans on this. Without it the periodic cleanup
    # job becomes a sequential scan that gets slower as the table grows — which
    # is exactly when it most needs to run.
    op.create_index("ix_rate_limit_buckets_updated_at", "rate_limit_buckets", ["updated_at"])

    # The application role needs full access: this is one of the few tables it
    # writes outside a tenant context.
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON rate_limit_buckets TO cairn_app"))


def downgrade() -> None:
    op.drop_index("ix_rate_limit_buckets_updated_at", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
