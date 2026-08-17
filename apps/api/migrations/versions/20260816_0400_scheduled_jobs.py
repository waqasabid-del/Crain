"""Durable scheduling: priority, per-tenant fairness, and leases.

Pub/Sub delivers fast and fairly to *subscribers*; it has no notion of one
customer's backfill crowding out another customer's live push. That ordering
decision needs somewhere durable to hold it, and PostgreSQL is already here.

This table is the queue's state, not a copy of it. A job is `queued` until a
worker leases it, `leased` until the worker finishes or the lease expires, and
`dead` if it exhausted its retries. Nothing is deleted on failure: a job that
disappeared is indistinguishable from one that was never sent.

Not tenant-scoped and not under row-level security, deliberately. A worker
claims work *before* it knows whose work it is — the tenant is what the envelope
carries — so a policy keyed on the current tenant would make the queue
unreadable to the process whose whole job is to drain it. Isolation is enforced
where the job runs: `run_job` opens a tenant-scoped session from the envelope,
and `test_scheduling.py` asserts a job cannot execute without one.

Revision ID: a4c72e19d8f5
Revises: c8f3e07d61b4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4c72e19d8f5"
down_revision: str | None = "c8f3e07d61b4"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_jobs",
        # The envelope's own job id. Publishing the same job twice is a
        # redelivery, not a second unit of work.
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("traceparent", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column(
            "enqueued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # When this job may next be claimed. Moved forward by a retry backoff,
        # and by the overload deferral that throttles a flooding tenant without
        # dropping anything.
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("leased_by", sa.String(length=64), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_reason", sa.String(length=500), nullable=True),
        sa.CheckConstraint("state IN ('queued', 'leased', 'dead')", name="ck_scheduled_jobs_state"),
        sa.CheckConstraint("attempt > 0", name="ck_scheduled_jobs_attempt"),
    )

    # The claim query's index: queued work, oldest first, within a priority.
    op.create_index(
        "ix_scheduled_jobs_claimable",
        "scheduled_jobs",
        ["state", "priority", "available_at"],
    )
    # The fairness sub-query counts a tenant's live leases.
    op.create_index("ix_scheduled_jobs_tenant_state", "scheduled_jobs", ["tenant_id", "state"])
    op.create_index("ix_scheduled_jobs_leased_until", "scheduled_jobs", ["leased_until"])

    # Full DML: the worker claims, releases, defers and dead-letters through the
    # application role. No DELETE — a completed job is removed by `ack`, which
    # is the one place deletion is correct, so it is granted deliberately rather
    # than as part of a blanket grant.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON scheduled_jobs TO cairn_app")


def downgrade() -> None:
    op.drop_table("scheduled_jobs")
