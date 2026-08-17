"""The three tables the Google Chat connector adds, and nothing else.

Shaped deliberately like ``db/slack_models.py``. There is no Google Chat
*connection* table: ``SourceConnection`` already answers "which workspace is
connected to which external account, with what granted, authorised by whom" for
every provider, and a second answer to that question is a second place to get
row-level security right.

:class:`GoogleChatOAuthState` — the server side of the OAuth ``state``
parameter, plus the PKCE verifier that belongs to the same in-flight install.

:class:`GoogleChatSpaceSelection` — which spaces a workspace has chosen to let
CAIRN read. **Selection is the whole permission model**, exactly as it is for
Slack: a connected Google Chat account with no row here is an account CAIRN
processes nothing from, and there is no "all spaces" flag.

:class:`GoogleChatSubscription` — one Google Workspace Events subscription per
selected space. Owned by the subscription engineer; the table lives here because
one migration per step is what keeps the schema history readable.

Nothing here stores a credential (``connectors/credentials.py`` owns that), a
space *display name*, or an email address. See the comment on ``space_name``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from cairn_api.db.connector_models import ConnectorErrorCategory

#: A Google Chat space resource name: ``spaces/{space}``.
#:
#: Kept as a string here and as a CHECK constraint in the migration, so the two
#: cannot drift and neither can be bypassed by a caller that skips the ORM. The
#: leading ``spaces/`` is part of the pattern on purpose — a bare id is what
#: arrives when somebody strips the prefix "for tidiness", and a permission keyed
#: on a bare id would not match the resource name every Chat event carries.
SPACE_NAME_PATTERN = r"^spaces/[A-Za-z0-9_-]{1,120}$"

#: A Workspace Events subscription resource name: ``subscriptions/{id}``.
SUBSCRIPTION_NAME_PATTERN = r"^subscriptions/[A-Za-z0-9_-]{1,120}$"


def _values(enum_class: type[enum.Enum]) -> list[str]:
    """Store the enum's values, not its member names."""
    return [member.value for member in enum_class]


class GoogleChatSubscriptionState(enum.StrEnum):
    """Where one space's event subscription is in its lifecycle.

    Mirrors the states Google's Workspace Events API reports, plus ``PENDING``
    for the window between "a space was selected" and "Google acknowledged a
    subscription". That window is real and it is where a customer sits looking at
    a selected space with nothing arriving, so it has a name rather than being
    represented by the absence of a row.

    ``SUSPENDED`` is Google's own state and is deliberately distinct from
    ``ERROR``: Google suspends a subscription it will still let us reactivate,
    while ``ERROR`` is our side failing to create or renew one at all.
    """

    #: Selected, not yet created at Google.
    PENDING = "pending"

    ACTIVE = "active"

    #: Google stopped delivering but the subscription still exists. Reactivatable
    #: until it lapses; ``suspension_category`` says what an operator can do.
    SUSPENDED = "suspended"

    #: Past ``expire_time`` with no renewal. Google deletes these; the row is
    #: kept so "why did this space go quiet" has an answer.
    EXPIRED = "expired"

    #: Deleted at Google — by us on deselection, or by Google after expiry.
    DELETED = "deleted"

    #: We could not create or renew it. ``suspension_category`` says why, in the
    #: bounded vocabulary.
    ERROR = "error"


class GoogleChatOAuthState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One in-flight Google Chat install, identified by an unguessable nonce.

    **Server-side, not a signed cookie**, for the reason `SlackOAuthState` gives:
    a signed value the client holds cannot be single-use without server state
    anyway, and single-use is the property that stops a captured callback URL
    being replayed to bind a second, attacker-chosen Google account to somebody
    else's workspace.
    """

    __tablename__ = "google_chat_oauth_states"

    #: Which workspace the install was started from. Carried here rather than
    #: recovered from the callback: the redirect URI is registered with Google
    #: once and therefore cannot name a workspace, so the state is the only link
    #: between the browser coming back and the workspace that asked.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: Who pressed Connect. Checked again on the callback, so a state handed to
    #: (or stolen by) a different person cannot be redeemed — being a member of
    #: the same workspace is not enough.
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    #: SHA-256 of the nonce, never the nonce itself. A stored plaintext would let
    #: anyone who can read this table finish an install an admin started.
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: The PKCE ``code_verifier``, stored as issued.
    #:
    #: Not hashed, and the difference from ``state_hash`` is the whole reason
    #: this comment exists. The nonce is a value *the browser presents back to
    #: us*, so we only ever need to recognise it — hashing costs nothing and
    #: makes a database dump useless for completing an install. The verifier is a
    #: value *we present to Google*, so it has to be recoverable in full; there
    #: is no version of this column that is both hashed and usable.
    #:
    #: What limits the exposure instead is lifetime and reach: the row is deleted
    #: or consumed within `oauth.STATE_TTL`, the table is unreachable from the
    #: application role, and the verifier is worthless without the matching
    #: authorisation code *and* the client secret, which is never in the
    #: database at all. It is deliberately absent from ``__repr__``.
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)

    #: Short — see `gchat/oauth.STATE_TTL`. An install is one browser round trip
    #: through one consent screen; anything measured in hours is a CSRF window
    #: held open for nobody's benefit.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Stamped the moment the callback claims it, *before* the code is exchanged.
    #: Consuming on success instead would leave a live state behind after a failed
    #: exchange, and "retry the callback until it works" is indistinguishable from
    #: an attacker replaying one.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_google_chat_oauth_states_tenant_id", "tenant_id"),
        # Supports the expiry sweep. Without it, deleting lapsed states is a
        # sequential scan over a table that grows by one row per abandoned
        # install — the shape a scanner can inflate for free.
        Index("ix_google_chat_oauth_states_expires_at", "expires_at"),
    )

    def is_usable(self, *, now: datetime | None = None) -> bool:
        """Whether this state may still be redeemed.

        Computed rather than stored: a ``used`` boolean is only correct until
        something forgets to set it, and a stale "unused" reads as a live
        authorisation.
        """
        moment = now or datetime.now(UTC)
        return self.consumed_at is None and self.expires_at > moment

    def __repr__(self) -> str:
        """Identity and lifecycle only — never the hash, never the verifier."""
        return (
            f"GoogleChatOAuthState(id={self.id!r}, tenant_id={self.tenant_id!r}, "
            f"consumed={self.consumed_at is not None!r})"
        )

    __str__ = __repr__


class GoogleChatSpaceSelection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One space a workspace has permitted CAIRN to read.

    The presence of the row is the permission. There is no ``enabled`` column,
    for the reason ``source_opt_outs`` has none: a boolean adds a second state
    that has to agree with the first, and the disagreement is always resolved in
    the direction of reading more.
    """

    __tablename__ = "google_chat_space_selections"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: CASCADE, because a selection outliving its connection is a permission
    #: attached to nothing — and the next connection would silently inherit it.
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_connections.id", ondelete="CASCADE"), nullable=False
    )

    #: The space **resource name** (``spaces/AAAA1111``), and never the display
    #: name.
    #:
    #: Two reasons, both load-bearing. **Display names change** — renaming a
    #: space would silently revoke a permission if the name were the key, or
    #: silently grant one if another space took the old name. **A display name is
    #: customer data**: "Acme / Northwind M&A" in a log line, an error message or
    #: a staff diagnostics screen is a disclosure on its own, which is why
    #: `ConnectorErrorCategory` exists and why there is no name column here to
    #: leak. Unlike the Slack picker, the Chat picker does not render display
    #: names at all — see `gchat/spaces.py`.
    space_name: Mapped[str] = mapped_column(String(160), nullable=False)

    #: Consent, recorded the way `source_connections` records it: who decided,
    #: with ``created_at`` answering when. An audit asking "who let CAIRN into
    #: this space" has to have an answer that is not a shrug.
    selected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        # **Global, not per connection**, and this is the one place the Google
        # design departs from the Slack one.
        #
        # Slack can rely on `source_connections`' unique `(provider,
        # installation_id)` to stop two CAIRN workspaces claiming one Slack team,
        # because a Slack install has a team id. The two Chat scopes CAIRN
        # requests carry no account identity at all — no customer id, no domain,
        # no email — so there is nothing equivalent to key a connection on, and
        # pretending otherwise would be a constraint that looks like it prevents
        # something and does not.
        #
        # A Chat space resource name *is* globally unique, so the property that
        # actually matters can be enforced exactly here: one space feeds at most
        # one CAIRN workspace. It also makes the Pub/Sub side's job unambiguous —
        # a space name resolves to one tenant or to none.
        UniqueConstraint("space_name", name="uq_google_chat_space_selections_space_name"),
        # Rejects a display name at the database, not only in the request model.
        # A bare id (prefix stripped) is refused too: it would never match the
        # resource name a Chat event carries, so it is a permission that looks
        # granted and delivers nothing.
        CheckConstraint(
            f"space_name ~ '{SPACE_NAME_PATTERN}'",
            name="ck_google_chat_space_selections_space_name_is_a_resource_name",
        ),
        Index("ix_google_chat_space_selections_tenant_id", "tenant_id"),
        Index("ix_google_chat_space_selections_connection_id", "connection_id"),
        # The ingestion lookup: "may this tenant process this space". Every
        # inbound Chat event runs it, so it is the one index that has to exist.
        Index("ix_google_chat_space_selections_tenant_space", "tenant_id", "space_name"),
    )

    def __repr__(self) -> str:
        """Ids and resource names only. There is no display name to leak."""
        return (
            f"GoogleChatSpaceSelection(id={self.id!r}, connection_id={self.connection_id!r}, "
            f"space_name={self.space_name!r})"
        )

    __str__ = __repr__


class GoogleChatSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One Google Workspace Events subscription, for one selected space.

    Created and renewed by the subscription engineer's code; this file only
    establishes the shape. A row here is **not** a permission — the selection row
    is — so a subscription that outlives a deselection still ingests nothing,
    because `spaces.is_space_permitted` never looks at this table.

    Kept rather than deleted when a subscription ends. "Why did this space go
    quiet three weeks ago" is the question this table exists to answer, and a
    row that was deleted on failure cannot answer it.
    """

    __tablename__ = "google_chat_subscriptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_connections.id", ondelete="CASCADE"), nullable=False
    )

    #: The space this subscribes to, as ``spaces/{space}``. Same column type and
    #: same CHECK as the selection table, so the two cannot disagree about what a
    #: space name is.
    space_name: Mapped[str] = mapped_column(String(160), nullable=False)

    #: Google's own resource name for the subscription (``subscriptions/{id}``).
    #: Nullable, because a row exists from the moment a space is selected and
    #: Google has not been asked yet — that is the ``PENDING`` state, and a
    #: placeholder string here would be a lie the renewal job would then try to
    #: renew.
    subscription_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: When Google will stop delivering without a renewal. Nullable for the same
    #: reason as ``subscription_name``. The renewal job's whole input.
    expire_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    state: Mapped[GoogleChatSubscriptionState] = mapped_column(
        Enum(
            GoogleChatSubscriptionState,
            native_enum=False,
            length=16,
            values_callable=_values,
        ),
        nullable=False,
        default=GoogleChatSubscriptionState.PENDING,
    )

    #: Why it is suspended, errored or expired — as a **category**, never as
    #: Google's message.
    #:
    #: Google's suspension reasons quote the resource that failed, which for this
    #: connector means space display names and the authorising person's address.
    #: This column is read by staff diagnostics and rendered in the customer's own
    #: integrations screen, so it carries the closed set the rest of the product
    #: already reports on and nothing else (md/05 §4).
    suspension_category: Mapped[ConnectorErrorCategory | None] = mapped_column(
        Enum(ConnectorErrorCategory, native_enum=False, length=32, values_callable=_values),
        nullable=True,
    )

    #: When the state above was last set. Separate from ``updated_at``, which
    #: moves on every write including a successful renewal — so "how long has
    #: this been broken" stays answerable.
    state_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The last time an event actually arrived for this space. The number a
    #: customer means by "is it working", and the one a subscription that is
    #: ACTIVE and silent cannot fake.
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # One subscription row per space per connection. Two rows would mean two
        # renewal schedules for one space and, when they disagree, a space that
        # stops delivering while a row still says ACTIVE.
        UniqueConstraint(
            "connection_id",
            "space_name",
            name="uq_google_chat_subscriptions_connection_space",
        ),
        CheckConstraint(
            f"space_name ~ '{SPACE_NAME_PATTERN}'",
            name="ck_google_chat_subscriptions_space_name_is_a_resource_name",
        ),
        CheckConstraint(
            f"subscription_name IS NULL OR subscription_name ~ '{SUBSCRIPTION_NAME_PATTERN}'",
            name="ck_google_chat_subscriptions_subscription_name_is_a_resource_name",
        ),
        Index("ix_google_chat_subscriptions_tenant_id", "tenant_id"),
        Index("ix_google_chat_subscriptions_connection_id", "connection_id"),
        # The renewal sweep: "which subscriptions lapse soon". Ordered state
        # first because the sweep only ever looks at live ones.
        Index("ix_google_chat_subscriptions_state_expire_time", "state", "expire_time"),
        # The inbound lookup, if the Pub/Sub side chooses to resolve by
        # subscription rather than by space.
        Index("ix_google_chat_subscriptions_subscription_name", "subscription_name"),
    )

    def __repr__(self) -> str:
        """Ids, resource names and lifecycle. No category text, no Google words."""
        return (
            f"GoogleChatSubscription(id={self.id!r}, space_name={self.space_name!r}, "
            f"state={self.state!r})"
        )

    __str__ = __repr__
