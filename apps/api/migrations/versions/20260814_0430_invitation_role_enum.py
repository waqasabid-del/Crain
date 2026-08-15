"""Give ``invitations.role`` the same type as ``memberships.role``.

Both columns hold a ``TenantRole``. One was the PostgreSQL ``tenant_role`` enum,
the other a bare ``VARCHAR(16)``.

The consequence was not wasted storage. SQLAlchemy coerces an ``Enum`` column
back to ``TenantRole`` on load and leaves a ``String`` column as ``str``, so the
same logical value arrived as a different Python type depending on which model
had read it. Because ``TenantRole`` is a ``StrEnum``, comparisons, dict lookups
and every permission check kept working against the plain string — so nothing
failed until something reached for actual enum behaviour, at which point it was
an ``AttributeError`` in a request handler rather than anything the type checker
had flagged.

The database also gains a real constraint: ``VARCHAR(16)`` accepted
``'superuser'`` quite happily.

Revision ID: c4a71b8e35d6
Revises: b6e30f14a7c9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c4a71b8e35d6"
down_revision: str | None = "b6e30f14a7c9"
branch_labels: None = None
depends_on: None = None

#: Created by the initial migration for ``memberships.role``. Reused rather than
#: defined again — a second enum with the same members would be a distinct
#: PostgreSQL type, and casting between them would need an explicit conversion
#: at every join.
ROLE_ENUM = sa.Enum(
    "owner",
    "admin",
    "member",
    "viewer",
    name="tenant_role",
    create_type=False,
)


def upgrade() -> None:
    # `USING` is required: PostgreSQL will not implicitly cast varchar to an
    # enum, and without it the ALTER fails rather than silently truncating.
    # Existing rows already hold valid member names, so the cast cannot fail —
    # and if one did not, failing here is the correct outcome.
    op.alter_column(
        "invitations",
        "role",
        existing_type=sa.String(16),
        type_=ROLE_ENUM,
        existing_nullable=False,
        postgresql_using="role::tenant_role",
    )


def downgrade() -> None:
    op.alter_column(
        "invitations",
        "role",
        existing_type=ROLE_ENUM,
        type_=sa.String(16),
        existing_nullable=False,
        postgresql_using="role::text",
    )
    # The enum type itself is left in place — `memberships.role` still uses it,
    # so dropping it here would break a table this migration never touched.
