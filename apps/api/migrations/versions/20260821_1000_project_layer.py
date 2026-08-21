"""The project layer: projects, auditable membership, and source-string claims.

Revision ID: 9e2f7a1c4b6d
Revises: 1631eea85edf
Create Date: 2026-08-21

Until now a project was `fact_sources.project` — a nullable string on a
citation. These three tables make it an entity: `projects` (name, purpose, a
*declared* state), `project_members` (person-scoped, history-preserving,
no activity columns — see db/project_models.py for why that is load-bearing),
and `project_sources` (a project's explicit claim over the raw strings that
link evidence to it; the strings themselves stay on the citations as
provenance).

Grants are the usual deliberate allow-list:

- `projects`: SELECT, INSERT, UPDATE and **no DELETE** — a project is archived
  (`archived_at`), never deleted, so its history and citations stay answerable.
- `project_members`: SELECT, INSERT, UPDATE and **no DELETE** — removal sets
  `removed_at`; a deletable membership row is a silent membership, which the
  spec forbids by name.
- `project_sources`: SELECT, INSERT, **DELETE**, no UPDATE — a claim is
  configuration, not evidence: releasing one deletes the mapping row while
  every citation keeps its raw string, and a claim is never edited in place
  (release and claim are two audited actions, not one quiet UPDATE).

The backfill turns every distinct existing string into an `unknown`-state
project claiming that string, so the portfolio is populated on day one and no
existing fact is unreachable through a project. `unknown` because nobody
declared anything — the state columns stay honest. `_backfill` is guarded by
NOT EXISTS on both inserts, so running it twice inserts nothing the second
time; the test imports this file and proves that.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9e2f7a1c4b6d"
down_revision = "1631eea85edf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
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
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=500), nullable=True),
        # Declared by a human, never inferred: 'unknown' is the honest default.
        sa.Column("state", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column(
            "state_declared_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("state_declared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "archived_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.create_index(
        "uq_projects_tenant_name_lower",
        "projects",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "project_members",
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
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The Person, not the User: a contractor who never signs in still does
        # the work. See db/project_models.py.
        sa.Column(
            "person_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_role", sa.String(length=100), nullable=True),
        sa.Column(
            "added_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "removed_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_project_members_tenant_id", "project_members", ["tenant_id"])
    op.create_index("ix_project_members_person_id", "project_members", ["person_id"])
    op.create_index(
        "uq_project_members_active",
        "project_members",
        ["project_id", "person_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "project_sources",
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
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column(
            "added_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("tenant_id", "value", name="uq_project_sources_tenant_value"),
    )
    op.create_index("ix_project_sources_tenant_id", "project_sources", ["tenant_id"])
    op.create_index("ix_project_sources_project_id", "project_sources", ["project_id"])

    for table in ("projects", "project_members", "project_sources"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)
        """)

    # The allow-list — see the module docstring for why each DELETE is or is
    # not here.
    op.execute("GRANT SELECT, INSERT, UPDATE ON projects TO cairn_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON project_members TO cairn_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON project_sources TO cairn_app")

    _backfill(op.get_bind())


def _backfill(bind: sa.engine.Connection) -> None:
    """Every distinct existing citation string becomes an `unknown` project
    claiming it. Idempotent by construction — both inserts are guarded by
    NOT EXISTS, so a second run inserts nothing."""
    bind.execute(
        sa.text("""
            INSERT INTO projects (tenant_id, name, state)
            SELECT DISTINCT fs.tenant_id, fs.project, 'unknown'
            FROM fact_sources fs
            WHERE fs.project IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM projects p
                  WHERE p.tenant_id = fs.tenant_id
                    AND lower(p.name) = lower(fs.project)
              )
        """)
    )
    bind.execute(
        sa.text("""
            INSERT INTO project_sources (tenant_id, project_id, value)
            SELECT DISTINCT fs.tenant_id, p.id, fs.project
            FROM fact_sources fs
            JOIN projects p
              ON p.tenant_id = fs.tenant_id
             AND lower(p.name) = lower(fs.project)
            WHERE fs.project IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM project_sources ps
                  WHERE ps.tenant_id = fs.tenant_id
                    AND ps.value = fs.project
              )
        """)
    )


def downgrade() -> None:
    for table in ("project_sources", "project_members", "projects"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
