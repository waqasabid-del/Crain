"""The provider-neutral connection record, adopted by GitHub in the same change.

``source_connections`` generalises ``github_installations``: which workspace
owns a connection, who authorised it, what was granted, where the sync got to,
and whether it is actually working. Slack and Google Chat (Step 32) need all of
that; GitHub needed only the first of it, which is why the existing table has
none of the rest.

**Adoption, not scaffolding.** A schema nothing writes is a schema nobody has
tested, and it stays wrong until the first connector discovers it — at which
point changing it is a migration on live data. So this migration also installs a
trigger projecting every ``github_installations`` write into ``source_connections``,
and backfills the rows already there. The connect endpoint, the webhook's
suspend and uninstall handling, and the seed script all feed it today without a
line of their code changing.

A trigger rather than a call site because the projection must hold for *every*
writer, including the raw SQL in a backfill script and whatever Step 32 adds
before it is finished. The direction reverses later: once the connectors read
from this table, ``github_installations`` becomes the derived side and the
trigger is dropped. Until then this table is a read-model, which is why the
application role gets SELECT and nothing else — see the grant below.

Consent columns (``authorised_by_user_id``, ``authorised_at``) are nullable, and
projected rows leave them null. ``github_installations`` never recorded who
pressed connect, and inventing a plausible user id would be worse than an
honest blank in the one column an audit reads.

Revision ID: d3f81b6c052a
Revises: b1e6c4a92f37
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3f81b6c052a"
down_revision: str | None = "b1e6c4a92f37"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"

PROVIDERS = "('github', 'slack', 'google_chat')"
STATES = "('pending', 'connected', 'disconnected', 'revoked', 'error')"
HEALTH = "('unknown', 'healthy', 'degraded', 'failing')"
ERROR_CATEGORIES = (
    "('authentication_expired', 'permission_revoked', 'rate_limited', "
    "'provider_unavailable', 'configuration_invalid', 'unknown')"
)

#: Projects one ``github_installations`` row onto its connection.
#:
#: Runs as the invoker rather than SECURITY DEFINER, deliberately. Every writer
#: of ``github_installations`` is the platform role — the application role holds
#: SELECT only, and this migration does not change that — so the invoker always
#: has the privileges this needs. SECURITY DEFINER would work too, and would
#: also quietly grant those privileges to any future writer, which is the
#: opposite of what the SELECT-only grant is for.
MIRROR_FUNCTION = """
CREATE OR REPLACE FUNCTION mirror_github_installation()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO source_connections (
        tenant_id, provider, external_account_id, external_account_label,
        installation_id, scopes, state, connected_at, disconnected_at,
        revoked_at, health, created_at, updated_at
    )
    VALUES (
        NEW.tenant_id,
        'github',
        -- GitHub's numeric account id is not stored on the legacy table, so the
        -- login is the only account identity available. It is stable enough to
        -- display and is never the uniqueness key — that is the installation id
        -- below.
        NEW.account_login,
        NEW.account_login,
        NEW.installation_id::text,
        '[]'::jsonb,
        CASE
            -- Uninstalled is the customer withdrawing at GitHub: reconnecting
            -- needs a fresh authorisation, which is what 'revoked' means.
            WHEN NEW.uninstalled_at IS NOT NULL THEN 'revoked'
            -- Suspension is reversible without re-authorising, so it maps to
            -- the milder state rather than to revoked.
            WHEN NEW.suspended_at IS NOT NULL THEN 'disconnected'
            ELSE 'connected'
        END,
        NEW.created_at,
        NEW.suspended_at,
        NEW.uninstalled_at,
        -- Not 'healthy'. Nothing measures GitHub ingestion health yet, and a
        -- connection reporting health it never checked is the failure this
        -- column exists to prevent.
        'unknown',
        NEW.created_at,
        now()
    )
    ON CONFLICT (provider, installation_id) DO UPDATE SET
        tenant_id = EXCLUDED.tenant_id,
        external_account_id = EXCLUDED.external_account_id,
        external_account_label = EXCLUDED.external_account_label,
        state = EXCLUDED.state,
        connected_at = EXCLUDED.connected_at,
        disconnected_at = EXCLUDED.disconnected_at,
        revoked_at = EXCLUDED.revoked_at,
        updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

#: A deleted installation must not leave a connection claiming to be live.
#: Reached on a direct delete; tenant removal cascades both sides anyway, and
#: this then deletes nothing, which is correct rather than an error.
FORGET_FUNCTION = """
CREATE OR REPLACE FUNCTION forget_github_installation()
RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM source_connections
    WHERE provider = 'github' AND installation_id = OLD.installation_id::text;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "source_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        # The provider's account identity (org, team, customer) and what to call
        # it in a UI. The label is nullable: a rename we have not observed is
        # better shown as the id than as a stale name.
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("external_account_label", sa.String(length=255), nullable=True),
        # The provider's identity for *this authorisation*. Text, because only
        # GitHub's is numeric.
        sa.Column("installation_id", sa.String(length=255), nullable=False),
        # What was actually granted, which is regularly less than what was asked
        # for. Makes a missing capability diagnosable as a missing scope rather
        # than as an empty feed.
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        # Opaque and provider-defined: a delivery cursor, a Slack `oldest` ts, a
        # Chat page token. Not parsed here — one schema for three unrelated
        # pagination models would be a fiction.
        sa.Column("sync_cursor", sa.String(length=1024), nullable=True),
        # The number a customer means by "is it working", and the one a
        # stalled-but-authorised connection cannot fake.
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health", sa.String(length=16), nullable=False, server_default="unknown"),
        # A category, never a provider message: provider errors quote the failed
        # request, which for a chat connector means channel names and message
        # fragments in a column staff and customers both read.
        sa.Column("last_error_category", sa.String(length=32), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        # Consent. RESTRICT rather than CASCADE: losing the record of who
        # authorised an integration because they left the company is exactly
        # backwards.
        sa.Column(
            "authorised_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("authorised_at", sa.DateTime(timezone=True), nullable=True),
        # Fernet ciphertext. Never returned by a model property — reading it is
        # an explicit `connectors.credentials.read_secret` call.
        sa.Column("secret_ciphertext", sa.String(length=2048), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"provider IN {PROVIDERS}", name="ck_source_connections_provider"),
        sa.CheckConstraint(f"state IN {STATES}", name="ck_source_connections_state"),
        sa.CheckConstraint(f"health IN {HEALTH}", name="ck_source_connections_health"),
        sa.CheckConstraint(
            f"last_error_category IS NULL OR last_error_category IN {ERROR_CATEGORIES}",
            name="ck_source_connections_error_category",
        ),
        # An error state with no category is a failure nobody can act on, and
        # the support ticket it produces starts with "it says error".
        sa.CheckConstraint(
            "state <> 'error' OR last_error_category IS NOT NULL",
            name="ck_source_connections_error_has_category",
        ),
        # Consent is recorded whole or not at all. Half of it — a user with no
        # timestamp, or a timestamp with no user — is the shape that makes an
        # audit unanswerable while looking populated.
        sa.CheckConstraint(
            "(authorised_by_user_id IS NULL) = (authorised_at IS NULL)",
            name="ck_source_connections_consent_is_whole",
        ),
        # Global, not per-tenant. This is what makes "the same external account
        # connected twice to different workspaces" unrepresentable, exactly as
        # `github_installations.installation_id` does today: two workspaces
        # claiming one installation would each receive the other's activity.
        sa.UniqueConstraint(
            "provider", "installation_id", name="uq_source_connections_provider_installation"
        ),
    )
    op.create_index("ix_source_connections_tenant_id", "source_connections", ["tenant_id"])
    op.create_index(
        "ix_source_connections_provider_account",
        "source_connections",
        ["provider", "external_account_id"],
    )

    op.execute("ALTER TABLE source_connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE source_connections FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON source_connections
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # Read-only, matching `github_installations` and for the same reason. Every
    # write happens platform-side: the connect endpoint runs on the platform
    # connection because the webhook path resolves installations before any
    # tenant context exists, and the trigger below writes as part of that same
    # statement. Granting INSERT would let a scoped session register a
    # connection and start receiving another organisation's activity; granting
    # UPDATE would let it rewrite `installation_id` and take over someone
    # else's — the same class of defect the `memberships` INSERT revocation
    # closed. Nothing in production performs a scoped write here, so a wider
    # grant would be an unused privilege, and an unused privilege is one an
    # injection gets to use first.
    op.execute("GRANT SELECT ON source_connections TO cairn_app")

    op.execute(MIRROR_FUNCTION)
    op.execute(FORGET_FUNCTION)
    op.execute("""
        CREATE TRIGGER mirror_github_installation
        AFTER INSERT OR UPDATE ON github_installations
        FOR EACH ROW EXECUTE FUNCTION mirror_github_installation()
    """)
    op.execute("""
        CREATE TRIGGER forget_github_installation
        AFTER DELETE ON github_installations
        FOR EACH ROW EXECUTE FUNCTION forget_github_installation()
    """)

    # Existing installations. Without this the table is empty on deploy and the
    # first connection anyone sees is whichever one happened to be touched next
    # — so a workspace's integrations page would show fewer connections than it
    # has, which is the one direction of wrong a trust surface must not be.
    op.execute("""
        INSERT INTO source_connections (
            tenant_id, provider, external_account_id, external_account_label,
            installation_id, scopes, state, connected_at, disconnected_at,
            revoked_at, health, created_at, updated_at
        )
        SELECT
            tenant_id,
            'github',
            account_login,
            account_login,
            installation_id::text,
            '[]'::jsonb,
            CASE
                WHEN uninstalled_at IS NOT NULL THEN 'revoked'
                WHEN suspended_at IS NOT NULL THEN 'disconnected'
                ELSE 'connected'
            END,
            created_at,
            suspended_at,
            uninstalled_at,
            'unknown',
            created_at,
            now()
        FROM github_installations
        ON CONFLICT (provider, installation_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS forget_github_installation ON github_installations")
    op.execute("DROP TRIGGER IF EXISTS mirror_github_installation ON github_installations")
    op.execute("DROP FUNCTION IF EXISTS forget_github_installation()")
    op.execute("DROP FUNCTION IF EXISTS mirror_github_installation()")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON source_connections")
    op.drop_table("source_connections")
