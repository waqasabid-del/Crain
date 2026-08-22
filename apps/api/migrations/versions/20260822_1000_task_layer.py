"""The task layer: tasks and their append-only event trail.

Revision ID: 3f7b9c2d5e1a
Revises: 9e2f7a1c4b6d
Create Date: 2026-08-22

Two tables. `tasks` is the board: title, workflow state, priority, an optional
assignee (a Person, following project membership's axis), an optional due
date, and the actor who created it. `task_events` is the audit: categorical
kinds only, with `from_state`/`to_state` populated for state changes — the
review-handoff rule is enforced by reading back who moved a task to
`in_review`. There is deliberately no payload column for either free text or
identifiers; see db/task_models.py for why that absence is load-bearing.

Grants are the usual deliberate allow-list:

- `tasks`: SELECT, INSERT, UPDATE and **no DELETE** — a task is archived
  (`archived_at`), never deleted, so what was worked on and reviewed stays
  answerable. A wrongly-closed task is archived and replaced, not erased.
- `task_events`: SELECT, INSERT and **no UPDATE, no DELETE** — the audit is
  append-only at the database, so history cannot be edited even by correct
  code with a bug in it. The review handoff depends on this: if an event
  could be rewritten, "a second pair of eyes" would be a suggestion.

Both tables carry FORCE row-level security with the standard tenant_isolation
policy, so a forgotten WHERE clause shows nothing rather than everything.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "3f7b9c2d5e1a"
down_revision = "9e2f7a1c4b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Every task belongs to a project — no orphan-task inbox.
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="todo"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        # The Person, not the User: a contractor who never signs in still
        # gets assigned work. Nullable — unassigned is a real state.
        sa.Column(
            "assignee_person_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_tasks_tenant_project", "tasks", ["tenant_id", "project_id"])
    op.create_index("ix_tasks_tenant_assignee", "tasks", ["tenant_id", "assignee_person_id"])

    op.create_table(
        "task_events",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Categorical only — a closed enum kind, no payload column at all.
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Populated for state_changed events only; the review-handoff rule
        # reads back who moved a task *to* in_review.
        sa.Column("from_state", sa.String(length=16), nullable=True),
        sa.Column("to_state", sa.String(length=16), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_task_events_tenant_task", "task_events", ["tenant_id", "task_id"])

    for table in ("tasks", "task_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)
        """)

    # The allow-list — see the module docstring for why each verb is or is
    # not here.
    #
    # tasks: no DELETE — archived, never deleted; a task is record.
    op.execute("GRANT SELECT, INSERT, UPDATE ON tasks TO cairn_app")
    # task_events: append-only — no UPDATE and no DELETE, so the audit the
    # review handoff depends on cannot be rewritten.
    op.execute("GRANT SELECT, INSERT ON task_events TO cairn_app")


def downgrade() -> None:
    for table in ("task_events", "tasks"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
