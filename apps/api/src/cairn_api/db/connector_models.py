"""The provider-neutral connection record.

``GitHubInstallation`` answers one question — which workspace does this App
installation belong to — and answers it only for GitHub. Slack and Google Chat
(Step 32) need the same answer plus the things GitHub never had to store: a
credential, a sync cursor, and a record of who authorised the connection. Three
near-identical tables would mean three places to get row-level security right,
three shapes for "is this connection working", and three answers to "what is
this workspace connected to" for a UI that has to show one list.

So the generalisation lands first, and GitHub adopts it: the migration installs
a trigger that projects every ``github_installations`` write into this table, so
these rows are produced by real production traffic on day one rather than
waiting for a caller that arrives in a later step.

Nothing here holds a plaintext credential. ``connectors/credentials.py`` owns
that, and the ciphertext column below is deliberately private — see the comment
on it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _values(enum_class: type[enum.Enum]) -> list[str]:
    """Store the enum's values, not its member names."""
    return [member.value for member in enum_class]


class ConnectorProvider(enum.StrEnum):
    """Which system a connection reaches.

    Closed, because a provider is not a label: each value implies a webhook
    verifier, an identity resolver and a retention rule. A free string would let
    a typo create a connection nothing on the ingestion side can service, and it
    would look connected in the UI.
    """

    GITHUB = "github"

    #: Defined, unused until Step 32. Declared now so the enum, the CHECK
    #: constraint and the UI's provider list are established by one migration
    #: rather than by a schema change on the day the connector ships.
    SLACK = "slack"
    GOOGLE_CHAT = "google_chat"


class ConnectionState(enum.StrEnum):
    """Where a connection is in its lifecycle.

    ``DISCONNECTED`` and ``REVOKED`` are separate on purpose. Disconnected is
    *our* side stopping — an admin turned it off, and reconnecting is a click.
    Revoked is *their* side stopping — the token was withdrawn at the provider,
    and reconnecting needs a fresh authorisation. Collapsing them produces the
    support ticket where a customer keeps pressing a reconnect button that
    cannot work.
    """

    #: Authorised in our UI, not yet confirmed by the provider.
    PENDING = "pending"

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REVOKED = "revoked"

    #: Still authorised, but the last attempt failed in a way we cannot resolve
    #: by retrying. ``last_error_category`` says which way.
    ERROR = "error"


class ConnectionHealth(enum.StrEnum):
    """How well a connected connection is actually working.

    Separate from ``state`` because they answer different questions. State is
    about permission; health is about whether data is arriving. A connection can
    be perfectly authorised and rate-limited into uselessness, and a customer
    looking at "connected" while nothing ingests is the situation md/05 calls
    out as worse than an honest failure.
    """

    #: Nothing has been attempted yet. Not the same as healthy, and never shown
    #: as a tick — a connection that has never synced has not proved anything.
    UNKNOWN = "unknown"

    HEALTHY = "healthy"

    #: Working, but not fully — partial results, or recovering from failures.
    DEGRADED = "degraded"

    FAILING = "failing"


class ConnectorErrorCategory(enum.StrEnum):
    """Why a connection last failed, as a category.

    Never a raw provider message. Provider errors quote the request that failed,
    which for Slack and Chat means channel names, user handles and sometimes
    message fragments — customer data, in a column that is read by staff
    diagnostics, rendered in the customer's own UI, and attached to logs. A
    closed set carries everything an operator or a customer can act on and none
    of what they must not see (md/05 §4).
    """

    #: The credential expired or was rotated. Reconnect.
    AUTHENTICATION_EXPIRED = "authentication_expired"

    #: The credential is valid but no longer carries the scopes we need —
    #: an admin removed them, or the app was reinstalled with fewer.
    PERMISSION_REVOKED = "permission_revoked"

    #: Throttled by the provider. Time fixes this one; nothing else does.
    RATE_LIMITED = "rate_limited"

    #: The provider is down or returning 5xx. Not our configuration.
    PROVIDER_UNAVAILABLE = "provider_unavailable"

    #: Something about the connection itself is wrong — a workspace that no
    #: longer exists, a space we were removed from.
    CONFIGURATION_INVALID = "configuration_invalid"

    #: Deliberately last and deliberately vague. A category that has to be
    #: guessed at is still better than a message that quotes a customer's data.
    UNKNOWN = "unknown"


class SourceConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One workspace's connection to one external account."""

    __tablename__ = "source_connections"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # `native_enum=False` keeps the column VARCHAR with a CHECK, matching the
    # migration, while round-tripping as the enum. A plain String returns `str`,
    # and every `is` comparison against a member is then quietly False.
    provider: Mapped[ConnectorProvider] = mapped_column(
        Enum(ConnectorProvider, native_enum=False, length=32, values_callable=_values),
        nullable=False,
    )

    #: The provider's identifier for the *account* — a GitHub org, a Slack team,
    #: a Chat customer. Text rather than an integer because only GitHub uses
    #: numeric ids; Slack's are `T0123ABCD`.
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)

    #: What to call it in the UI. Stored rather than fetched, so a workspace
    #: list renders without N provider calls, and nullable because a rename we
    #: have not observed yet is better shown as the id than as a stale name.
    external_account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: The provider's identifier for *this authorisation* — GitHub's
    #: installation id, Slack's app-installation id. Distinct from the account:
    #: an account can be uninstalled and reinstalled, which keeps the account id
    #: and issues a new installation id, and treating the two as one makes a
    #: reinstall look like a different customer.
    installation_id: Mapped[str] = mapped_column(String(255), nullable=False)

    #: What the provider actually granted, which is frequently less than what
    #: was asked for. Stored so a missing capability is diagnosable as "we were
    #: never given `channels:history`" rather than as an empty feed.
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    state: Mapped[ConnectionState] = mapped_column(
        Enum(ConnectionState, native_enum=False, length=16, values_callable=_values),
        nullable=False,
        default=ConnectionState.PENDING,
    )

    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Opaque, provider-defined: a GitHub delivery cursor, a Slack `oldest` ts,
    #: a Chat page token. Deliberately not parsed here — a shared schema for
    #: three unrelated pagination models would be a fiction that breaks the
    #: first time a provider changes its token format.
    sync_cursor: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    #: The last time data actually arrived. The number a customer means by "is
    #: it working", and the only one a stalled-but-authorised connection cannot
    #: fake.
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    health: Mapped[ConnectionHealth] = mapped_column(
        Enum(ConnectionHealth, native_enum=False, length=16, values_callable=_values),
        nullable=False,
        default=ConnectionHealth.UNKNOWN,
    )

    last_error_category: Mapped[ConnectorErrorCategory | None] = mapped_column(
        Enum(ConnectorErrorCategory, native_enum=False, length=32, values_callable=_values),
        nullable=True,
    )
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Consent: who in this workspace authorised the connection, and when.
    #:
    #: Nullable only because the rows projected from `github_installations`
    #: predate anyone recording it — that table never stored who pressed
    #: connect. Every connection created through the connector framework sets
    #: both, and "authorised by nobody" is exactly the shape a migrated row
    #: should have rather than a name invented to fill the column.
    authorised_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    authorised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: The encrypted credential. Private by name, and there is no property that
    #: returns it.
    #:
    #: An attribute is read by everything that walks an object: `repr`, a
    #: debugger, `structlog`'s dict rendering, a serialiser someone points at
    #: the model. Naming it with a leading underscore does not stop a
    #: determined caller — nothing in Python does — but it does stop the
    #: accidental ones, which are the ones that actually leak secrets. Reading
    #: the plaintext is `connectors.credentials.read_secret(connection)`: an
    #: import, a call, and a line in a diff someone can review.
    _secret_ciphertext: Mapped[str | None] = mapped_column(
        "secret_ciphertext", String(2048), nullable=True
    )

    tenant = relationship("Tenant")

    __table_args__ = (
        # Global, not per-tenant. This is what makes "the same external account
        # connected twice to different workspaces" unrepresentable, exactly as
        # `github_installations.installation_id` does today: two workspaces
        # claiming one installation would each receive the other's activity,
        # and the row that arrived second would silently start the leak.
        UniqueConstraint(
            "provider", "installation_id", name="uq_source_connections_provider_installation"
        ),
        Index("ix_source_connections_tenant_id", "tenant_id"),
        Index("ix_source_connections_provider_account", "provider", "external_account_id"),
    )

    @property
    def is_active(self) -> bool:
        """Whether this connection is authorised right now.

        Computed rather than stored, for the reason `SupportSession.is_active`
        gives: a boolean column is only true until the moment nobody updates
        it, and a stale `active = true` reads as live consent.
        """
        return (
            self.state is ConnectionState.CONNECTED
            and self.disconnected_at is None
            and self.revoked_at is None
        )

    @property
    def is_collecting(self) -> bool:
        """Whether data is expected to be arriving.

        Narrower than :attr:`is_active` on purpose. An authorised connection
        whose last attempts all failed is not collecting, and showing it as
        healthy is how a customer discovers a week-long gap in their briefs
        from the brief rather than from us.
        """
        return self.is_active and self.health is not ConnectionHealth.FAILING

    def __repr__(self) -> str:
        """Identity only — never the credential.

        Written out rather than left to SQLAlchemy's default. The default is
        safe today (it renders the class and an address), but it is safe by
        accident: anyone adding `__repr__` for debugging would reach for the
        obvious `self.__dict__` version and put a token into every log line
        that touched a connection. This is the version they will find instead.
        """
        return (
            f"SourceConnection(id={self.id!r}, provider={self.provider!r}, "
            f"installation_id={self.installation_id!r}, state={self.state!r})"
        )

    __str__ = __repr__
